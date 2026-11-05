"""Run one trusted test command with cleanup of only its owned process tree."""
from __future__ import annotations

import ctypes
import json
import os
import signal
import subprocess
import sys


# The gate cannot launch the test until the parent has assigned its Job Object.
# A short-lived launcher may exit before its children; job membership survives it.
_GATE = """import json, subprocess, sys
argv = json.loads(sys.stdin.readline())
child = subprocess.Popen(argv, stdin=subprocess.DEVNULL)
raise SystemExit(child.wait())
"""


class _WindowsJob:
    def __init__(self):
        from ctypes import wintypes as w

        class BasicLimits(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                        ('flags', w.DWORD), ('minimum_working_set', ctypes.c_size_t),
                        ('maximum_working_set', ctypes.c_size_t), ('active_process_limit', w.DWORD),
                        ('affinity', ctypes.c_size_t), ('priority_class', w.DWORD), ('scheduling_class', w.DWORD)]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in
                        ('read_operations', 'write_operations', 'other_operations', 'read_bytes', 'write_bytes', 'other_bytes')]

        class ExtendedLimits(ctypes.Structure):
            _fields_ = [('basic', BasicLimits), ('io', IoCounters),
                        ('process_memory_limit', ctypes.c_size_t), ('job_memory_limit', ctypes.c_size_t),
                        ('peak_process_memory', ctypes.c_size_t), ('peak_job_memory', ctypes.c_size_t)]

        self.api = ctypes.WinDLL('kernel32', use_last_error=True)
        self.api.CreateJobObjectW.argtypes = [ctypes.c_void_p, w.LPCWSTR]
        self.api.CreateJobObjectW.restype = w.HANDLE
        self.api.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD]
        self.api.SetInformationJobObject.restype = w.BOOL
        self.api.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        self.api.AssignProcessToJobObject.restype = w.BOOL
        self.api.CloseHandle.argtypes = [w.HANDLE]
        self.api.CloseHandle.restype = w.BOOL
        self.handle = self.api.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimits()
        limits.basic.flags = 0x00002000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not self.api.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.WinError(ctypes.get_last_error())
            self.close()
            raise error

    def assign(self, process):
        # Use CPython Popen's owned Windows handle, avoiding a PID reuse lookup.
        if not self.api.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        if self.handle:
            handle, self.handle = self.handle, None
            if not self.api.CloseHandle(handle):
                raise ctypes.WinError(ctypes.get_last_error())


def run_test_process(argv, *, cwd, env, timeout):
    """Capture UTF-8 output; timeout closes this invocation's owned process tree.

    Windows requires successful Job assignment before the test can execute; an
    incompatible host raises OSError instead of silently running uncontained.
    POSIX uses a new process group for ordinary non-daemonizing test children.
    This helper is for noninteractive tests; command stdin is always closed.
    """
    argv = [os.fspath(value) for value in argv]
    job = _WindowsJob() if os.name == 'nt' else None
    process = None

    def stop_owned_tree():
        if job:
            job.close()
        elif process:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    try:
        process = subprocess.Popen(
            [sys.executable, '-c', _GATE] if job else argv,
            cwd=cwd, env=env, stdin=subprocess.PIPE if job else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace',
            creationflags=subprocess.CREATE_NO_WINDOW if job else 0,
            start_new_session=not bool(job),
        )
        if job:
            try:
                job.assign(process)
            except BaseException:
                # The gate is still waiting; no test or descendant exists yet.
                process.kill()
                process.communicate()
                raise
        try:
            stdout, stderr = process.communicate(json.dumps(argv) + '\n' if job else None, timeout=timeout)
        except subprocess.TimeoutExpired:
            stop_owned_tree()
            stdout, stderr = process.communicate(timeout=10)
            raise subprocess.TimeoutExpired(argv, timeout, output=stdout, stderr=stderr) from None
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    finally:
        stop_owned_tree()
