from __future__ import annotations

import argparse
import importlib
import os
import socket
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any


APP_IMPORT = "services.retrieval_service.v11_api_server:app"
IMPLEMENTATION_IMPORT = "services.retrieval_service.api.v11_api_server:app"
CORE_ROUTE = "/agent/answer"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
MYSQL_ENV_NAMES = ("MYSQL_HOST", "MYSQL_PORT", "MYSQL_DB", "MYSQL_USER", "MYSQL_PASSWORD")
REQUIRED_INDEX_FILES = (Path("indexes/faiss.index"), Path("indexes/bm25.pkl"))
PROJECT_MARKERS = (
    Path("AGENTS.md"),
    Path("README.md"),
    Path("requirements.txt"),
    Path("services/retrieval_service"),
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    required: bool = True


def find_project_root(start: str | Path | None = None) -> Path:
    current = Path(start or __file__).resolve()
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if all((candidate / marker).exists() for marker in PROJECT_MARKERS):
            return candidate

    return Path(__file__).resolve().parents[1]


def ensure_project_context(root: Path) -> None:
    root = root.resolve()
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)
    os.environ["RAG_PROJECT_ROOT"] = root_text
    os.chdir(root)


def split_app_import(app_import: str) -> tuple[str, str]:
    if ":" not in app_import:
        raise ValueError(f"ASGI 入口必须是 'module:app' 格式：{app_import}")
    module_name, app_name = app_import.split(":", 1)
    module_name = module_name.strip()
    app_name = app_name.strip()
    if not module_name or not app_name:
        raise ValueError(f"ASGI 入口必须包含模块名和 app 变量名：{app_import}")
    return module_name, app_name


def import_app(app_import: str = APP_IMPORT) -> tuple[Any, Any]:
    module_name, app_name = split_app_import(app_import)
    module = importlib.import_module(module_name)
    app = getattr(module, app_name)
    return module, app


def registered_routes(app: Any) -> set[str]:
    return {getattr(route, "path", "") for route in getattr(app, "routes", [])}


def format_traceback_tail(exc: BaseException, max_lines: int = 8) -> str:
    lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    return "".join(lines[-max_lines:]).strip()


def read_dotenv_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    keys: set[str] = set()
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return keys
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            keys.add(key)
    return keys


def has_config_key(name: str, dotenv_keys: set[str]) -> bool:
    return bool(os.getenv(name)) or name in dotenv_keys


def check_required_path(name: str, path: Path) -> CheckResult:
    if path.exists():
        return CheckResult(name=name, ok=True, detail=str(path))
    return CheckResult(name=name, ok=False, detail=f"缺失：{path}")


def check_index_files(root: Path) -> list[CheckResult]:
    return [check_required_path(str(relative), root / relative) for relative in REQUIRED_INDEX_FILES]


def _port_probe_host(host: str) -> str:
    if host in {"0.0.0.0", "::", ""}:
        return "127.0.0.1"
    return host


def is_port_in_use(host: str, port: int) -> bool:
    probe_host = _port_probe_host(host)
    try:
        with socket.create_connection((probe_host, port), timeout=0.5):
            return True
    except OSError:
        return False


def collect_checks(
    root: Path,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    app_import: str = APP_IMPORT,
    check_port: bool = True,
) -> tuple[list[CheckResult], BaseException | None]:
    ensure_project_context(root)
    checks: list[CheckResult] = [
        CheckResult("Python 版本", True, sys.version.split()[0], required=False),
        CheckResult("项目根目录", True, str(root)),
        check_required_path(".env", root / ".env"),
        check_required_path("requirements.txt", root / "requirements.txt"),
    ]
    checks.extend(check_index_files(root))

    dotenv_keys = read_dotenv_keys(root / ".env")
    missing_mysql = [name for name in MYSQL_ENV_NAMES if not has_config_key(name, dotenv_keys)]
    if missing_mysql:
        checks.append(
            CheckResult(
                "MySQL 环境变量",
                False,
                "缺失：" + ", ".join(missing_mysql),
                required=False,
            )
        )
    else:
        checks.append(CheckResult("MySQL 环境变量", True, "已配置必要键名", required=False))

    import_error: BaseException | None = None
    try:
        _, app = import_app(app_import)
        routes = registered_routes(app)
        checks.append(CheckResult("FastAPI app import", True, app_import))
        checks.append(CheckResult("app 变量", app is not None, "已找到 app 变量"))
        checks.append(
            CheckResult(
                f"{CORE_ROUTE} 路由",
                CORE_ROUTE in routes,
                "已注册" if CORE_ROUTE in routes else "未注册",
            )
        )
    except BaseException as exc:  # noqa: BLE001 - startup diagnostics must report import failures.
        import_error = exc
        module_name, app_name = split_app_import(app_import)
        checks.append(
            CheckResult(
                "FastAPI app import",
                False,
                f"导入 {module_name}:{app_name} 失败：{type(exc).__name__}: {exc}",
            )
        )

    if check_port:
        occupied = is_port_in_use(host, port)
        checks.append(
            CheckResult(
                "端口占用",
                not occupied,
                f"{host}:{port} 可用" if not occupied else f"{host}:{port} 已被占用",
            )
        )

    return checks, import_error


def has_required_failure(checks: list[CheckResult]) -> bool:
    return any(check.required and not check.ok for check in checks)


def print_checks(checks: list[CheckResult]) -> None:
    for item in checks:
        if item.ok:
            status = "通过"
        elif item.required:
            status = "失败"
        else:
            status = "提示"
        print(f"- [{status}] {item.name}: {item.detail}")


def print_import_error(root: Path, app_import: str, exc: BaseException) -> None:
    module_name, app_name = split_app_import(app_import)
    print()
    print("FastAPI 入口导入失败诊断：")
    print(f"- 当前项目根目录：{root}")
    print(f"- 当前 Python：{sys.executable}")
    print(f"- 尝试导入模块：{module_name}")
    print(f"- app 变量名：{app_name}")
    print("- 当前 sys.path 前几项：")
    for item in sys.path[:6]:
        print(f"  - {item}")
    print("- 原始异常最后几行：")
    print(format_traceback_tail(exc))


def print_frontend_info(host: str, port: int) -> None:
    base_url = f"http://{host}:{port}"
    print()
    print(f"后端启动地址：{base_url}")
    print(f"接口文档：{base_url}/docs")
    print("核心接口：POST /agent/answer")
    print("示例请求：")
    print('{\n  "query": "什么是傅里叶导热定律？"\n}')


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="一键检查并启动 ThermalAgent FastAPI 后端。")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"监听地址，默认 {DEFAULT_HOST}")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"监听端口，默认 {DEFAULT_PORT}")
    parser.add_argument("--no-reload", action="store_true", help="关闭 uvicorn reload")
    parser.add_argument("--check", action="store_true", help="只执行启动前检查，不启动服务")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.port < 1 or args.port > 65535:
        parser.error("--port 必须在 1 到 65535 之间")

    root = find_project_root()
    checks, import_error = collect_checks(root=root, host=args.host, port=args.port)

    print("后端启动预检查：")
    print(f"- 推荐 uvicorn 入口：{APP_IMPORT}")
    print(f"- 实际 app 定义入口：{IMPLEMENTATION_IMPORT}")
    print_checks(checks)

    if import_error is not None:
        print_import_error(root, APP_IMPORT, import_error)

    if has_required_failure(checks):
        print()
        print("预检查未通过，请按上面的失败项处理后再启动。")
        return 1

    if args.check:
        print()
        print("检查通过；--check 模式不会启动服务，也不会写数据库或重建索引。")
        return 0

    print_frontend_info(args.host, args.port)

    try:
        import uvicorn
    except Exception as exc:  # noqa: BLE001 - show a clear dependency hint.
        print()
        print("启动失败：无法导入 uvicorn。请先执行：pip install -r requirements.txt")
        print(f"原始错误：{type(exc).__name__}: {exc}")
        return 1

    reload_enabled = not args.no_reload
    reload_dirs = [str(root / "services"), str(root / "scripts")] if reload_enabled else None
    uvicorn.run(
        APP_IMPORT,
        host=args.host,
        port=args.port,
        reload=reload_enabled,
        reload_dirs=reload_dirs,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
