from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.retrieval_service.config import load_config
from services.retrieval_service.db import DB


def _schema_path() -> Path:
    return ROOT / "services" / "retrieval_service" / "sql" / "001_init_schema.sql"


def _split_sql(sql_text: str) -> list[str]:
    statements: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    i = 0
    while i < len(sql_text):
        ch = sql_text[i]
        nxt = sql_text[i + 1] if i + 1 < len(sql_text) else ""
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        if ch == ";" and not in_single and not in_double:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(ch)
        if ch == "\\" and nxt:
            current.append(nxt)
            i += 1
        i += 1
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def _execute_schema(cfg) -> None:
    try:
        import mysql.connector  # type: ignore
    except Exception as exc:  # pragma: no cover - environment dependent
        raise RuntimeError("mysql-connector-python is not installed.") from exc

    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", cfg.mysql.database):
        raise ValueError("MYSQL_DB must be a simple database name (letters, digits, underscores).")
    conn = mysql.connector.connect(
        host=cfg.mysql.host,
        port=cfg.mysql.port,
        user=cfg.mysql.user,
        password=cfg.mysql.password,
        autocommit=False,
    )
    try:
        cur = conn.cursor()
        cur.execute(
            f"CREATE DATABASE IF NOT EXISTS `{cfg.mysql.database}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        )
        cur.execute(f"USE `{cfg.mysql.database}`")
        sql_text = _schema_path().read_text(encoding="utf-8-sig")
        sql_text = "\n".join(line for line in sql_text.splitlines() if not line.lstrip().startswith("--"))
        for statement in _split_sql(sql_text):
            cleaned = statement.strip()
            if not cleaned or re.fullmatch(r"[-\s]+", cleaned):
                continue
            cur.execute(cleaned)
        conn.commit()
    finally:
        conn.close()


def main() -> None:
    cfg = load_config()
    _execute_schema(cfg)
    db = DB.create(cfg)
    db.ensure_runtime_tables()
    tables = [row[0] for row in db.fetchall("SHOW TABLES")]
    print(f"init_db ok database={cfg.mysql.database} tables={len(tables)}")


if __name__ == "__main__":
    main()
