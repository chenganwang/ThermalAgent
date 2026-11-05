"""Bounded, read-only discovery of a local Windows Fluent installation.

No subprocess, solver import, license probe, registry mutation or filesystem
write is performed. ``available`` describes installation checks only; the
runner must still enforce execution gates and handle runtime/license failures.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import struct
import sys
from typing import Any


def _windows_host() -> bool:
    return sys.platform == "win32"


def _local_drive(path: Path) -> bool:
    """Reject UNC/device paths and mapped network drives before reading files."""
    if str(path).startswith(("\\\\", "//")):
        return False
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32.dll", winmode=0x00000800)
    get_drive_type = kernel.GetDriveTypeW
    get_drive_type.argtypes = [wintypes.LPCWSTR]
    get_drive_type.restype = wintypes.UINT
    return get_drive_type(str(path.absolute().anchor)) in {2, 3, 5, 6}


def _candidate_paths(path: Path) -> tuple[str, list[Path]]:
    if path.suffix.casefold() == ".exe":
        return "executable", [path] if path.name.casefold() == "fluent.exe" else []
    if not path.is_dir():
        return "missing_or_unsupported", []
    # Framework is Workbench, not the solver. Only use its enclosing version;
    # never jump to a different installed Ansys release when this one is absent.
    version_root = next((item for item in [path, *path.parents] if re.fullmatch(r"v\d{3,4}", item.name, re.I)), None)
    if any(item.casefold() == "framework" for item in path.parts):
        return "workbench_framework_directory", [version_root / "fluent/ntbin/win64/fluent.exe"] if version_root else []
    kind = "version_root" if re.fullmatch(r"v\d{3,4}", path.name, re.I) else "fluent_root" if path.name.casefold() == "fluent" else "installation_directory"
    return kind, [
        path / "fluent.exe",
        path / "ntbin/win64/fluent.exe",
        path / "fluent/ntbin/win64/fluent.exe",
        path / "v242/fluent/ntbin/win64/fluent.exe",
    ]


def _binary_format(path: Path) -> bool:
    """Check MZ + bounded PE header and an x86/x64 Windows launcher machine."""
    size = path.stat().st_size
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ" or size < 64:
            return False
        stream.seek(60)
        raw_offset = stream.read(4)
        if len(raw_offset) != 4:
            return False
        offset = struct.unpack("<I", raw_offset)[0]
        if not 64 <= offset <= min(size - 6, 1_048_576):
            return False
        stream.seek(offset)
        header = stream.read(6)
    return len(header) == 6 and header[:4] == b"PE\x00\x00" and struct.unpack("<H", header[4:])[0] in {0x14C, 0x8664}


def _read_file_version(path: Path) -> str | None:
    """Use Windows version resources; do not run ``fluent.exe -version``."""
    import ctypes
    from ctypes import wintypes

    class FixedFileInfo(ctypes.Structure):
        _fields_ = [(name, wintypes.DWORD) for name in (
            "signature", "struct_version", "file_ms", "file_ls", "product_ms", "product_ls",
            "flags_mask", "flags", "file_os", "file_type", "file_subtype", "date_ms", "date_ls",
        )]

    library = ctypes.WinDLL("version.dll", winmode=0x00000800)
    get_size = library.GetFileVersionInfoSizeW
    get_size.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    get_size.restype = wintypes.DWORD
    get_info = library.GetFileVersionInfoW
    get_info.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    get_info.restype = wintypes.BOOL
    query = library.VerQueryValueW
    query.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    query.restype = wintypes.BOOL
    unused = wintypes.DWORD()
    size = get_size(str(path), ctypes.byref(unused))
    if not 0 < size <= 16_777_216:
        return None
    buffer = ctypes.create_string_buffer(size)
    if not get_info(str(path), 0, size, buffer):
        return None
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not query(buffer, "\\", ctypes.byref(pointer), ctypes.byref(length)) or not pointer.value:
        return None
    start = ctypes.addressof(buffer)
    if length.value < ctypes.sizeof(FixedFileInfo) or not start <= pointer.value <= start + size - ctypes.sizeof(FixedFileInfo):
        return None
    info = FixedFileInfo.from_address(pointer.value)
    if info.signature != 0xFEEF04BD:
        return None
    numbers = [info.file_ms >> 16, info.file_ms & 0xFFFF, info.file_ls >> 16, info.file_ls & 0xFFFF]
    if not any(numbers):
        return None
    if numbers[-1] == 0:
        numbers.pop()
    return ".".join(str(number) for number in numbers)


def detect_environment(executable: Path | None) -> dict[str, Any]:
    """Resolve explicit configuration first; return public diagnostics safely.

    If no argument is configured, FLUENT_INSTALL_ROOT precedes AWP_ROOT242.
    A configured but invalid installation fails closed rather than silently
    switching to another release. The caller may then select its mock runner.
    """
    report: dict[str, Any] = {
        "schema_version": "1.0", "status": "unavailable", "solver_found": False,
        "version": None, "license_checked": False, "checks": [],
        "requested_path_kind": "not_inspected" if executable is not None else "unconfigured",
        "resolution_source": "explicit" if executable is not None else "none",
    }

    def check(name: str, status: str, code: str, message: str) -> None:
        report["checks"].append({"name": name, "status": status, "code": code, "message": message})

    def finish(solver: Path | None = None) -> dict[str, Any]:
        check("license", "not_checked", "FLUENT_LICENSE_NOT_CHECKED", "License availability was not checked; a detected installation does not establish execution readiness.")
        available = solver is not None
        report["status"] = "available" if available else "unavailable"
        return {"available": available, "executable": solver, "report": report}

    try:
        if not _windows_host():
            check("host", "failed", "FLUENT_HOST_UNSUPPORTED", "This adapter supports a local Windows Fluent installation.")
            return finish()
        check("host", "passed", "FLUENT_WINDOWS_HOST", "Windows host detected.")
        requested = executable
        if requested is not None:
            report["resolution_source"] = "explicit"
        else:
            for name, source in (("FLUENT_INSTALL_ROOT", "env_fluent_install_root"), ("AWP_ROOT242", "env_awp_root242")):
                value = os.getenv(name, "").strip()
                if value:
                    requested = Path(value)
                    report["resolution_source"] = source
                    break
        if requested is None:
            check("path_resolution", "failed", "FLUENT_NOT_CONFIGURED", "Configure a Fluent executable, installation root, or Ansys version root.")
            return finish()
        requested = Path(requested).absolute()
        if not _local_drive(requested):
            report["requested_path_kind"] = "nonlocal_or_unsupported"
            check("path_resolution", "failed", "FLUENT_LOCAL_PATH_REQUIRED", "A local disk installation is required; network and device paths are not probed.")
            return finish()
        requested = requested.resolve()
        if not _local_drive(requested):
            report["requested_path_kind"] = "nonlocal_or_unsupported"
            check("path_resolution", "failed", "FLUENT_LOCAL_PATH_REQUIRED", "The resolved installation must remain on a local disk.")
            return finish()
        kind, candidates = _candidate_paths(requested)
        report["requested_path_kind"] = kind
        solver = next((candidate for candidate in candidates if candidate.is_file()), None)
        if solver is None:
            check("path_resolution", "failed", "FLUENT_SOLVER_NOT_FOUND", "No Fluent solver executable was found in the configured installation layout.")
            return finish()
        solver = solver.resolve()
        if not _local_drive(solver):
            check("path_resolution", "failed", "FLUENT_LOCAL_PATH_REQUIRED", "The solver must resolve to a local disk file.")
            return finish()
        report["solver_found"] = True
        check("path_resolution", "passed", "FLUENT_SOLVER_FOUND", "A Fluent solver executable was found in the configured installation.")
        try:
            valid_binary = _binary_format(solver)
        except OSError:
            check("binary", "failed", "FLUENT_BINARY_UNREADABLE", "The solver executable could not be read.")
            return finish()
        if not valid_binary:
            check("binary", "failed", "FLUENT_BINARY_INVALID", "The candidate is not a supported readable Windows MZ/PE executable.")
            return finish()
        check("binary", "passed", "FLUENT_BINARY_VERIFIED", "Readable Windows MZ/PE executable with x86 or x64 launcher format verified.")
        try:
            version = _read_file_version(solver)
        except (OSError, ValueError):
            version = None
        if not version:
            check("version", "failed", "FLUENT_VERSION_UNAVAILABLE", "Windows file version metadata could not be verified; real execution readiness is unavailable.")
            return finish()
        report["version"] = version
        check("version", "passed", "FLUENT_VERSION_VERIFIED", "Solver file version was read from Windows version resources without starting a process.")
        return finish(solver)
    except Exception:
        check("environment", "failed", "FLUENT_ENVIRONMENT_CHECK_FAILED", "The read-only environment check could not complete; review the local installation configuration.")
        return finish()
