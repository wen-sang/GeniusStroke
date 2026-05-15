from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path


REQUIRED_TABLES = (
    "alembic_version",
    "sys_account_fund",
    "trade_order",
    "account_cash_flow",
    "dat_position",
    "dat_account_history",
)


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_runtime_path(index_data: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return (index_data / path).resolve()


def run_alembic(index_data: Path, env: dict[str, str]) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=index_data,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit("alembic upgrade head failed")


def assert_database_ready(db_path: Path) -> None:
    if not db_path.exists():
        raise SystemExit(f"database was not created: {db_path}")

    with sqlite3.connect(db_path) as conn:
        for table in REQUIRED_TABLES:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if row is None:
                raise SystemExit(f"required table is missing: {table}")

        version_row = conn.execute(
            "SELECT version_num FROM alembic_version LIMIT 1"
        ).fetchone()
        if version_row is None:
            raise SystemExit("alembic_version is empty")


def ensure_default_account(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO sys_account_fund (
                account_id,
                account_no,
                account_name,
                cash_balance,
                total_deposit,
                total_withdraw,
                total_shares,
                acc_profit
            )
            VALUES (1, 'ACC0001', 'Default', 0, 0, 0, 0, 0)
            """
        )
        conn.execute(
            """
            UPDATE sys_account_fund
            SET account_no = 'ACC0001',
                account_name = COALESCE(NULLIF(account_name, ''), 'Default'),
                cash_balance = COALESCE(cash_balance, 0),
                total_deposit = COALESCE(total_deposit, 0),
                total_withdraw = COALESCE(total_withdraw, 0),
                total_shares = COALESCE(total_shares, 0),
                acc_profit = COALESCE(acc_profit, 0)
            WHERE account_id = 1
            """
        )
        row = conn.execute(
            """
            SELECT account_no, cash_balance, total_deposit, total_withdraw,
                   total_shares, acc_profit
            FROM sys_account_fund
            WHERE account_id = 1
            """
        ).fetchone()
        if row is None or row[0] != "ACC0001":
            raise SystemExit("default account ACC0001 was not created")
        if any(float(value or 0) != 0 for value in row[1:]):
            raise SystemExit("default account is not zero-balance")
        conn.commit()


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    index_data = repo_root / "index_data"
    env_example = repo_root / ".env.example"
    env_file = repo_root / ".env"

    if not index_data.exists():
        raise SystemExit(f"index_data not found: {index_data}")
    if not env_example.exists():
        raise SystemExit(".env.example is missing")
    if not env_file.exists():
        shutil.copy2(env_example, env_file)

    env_values = load_env_file(env_file)
    env = os.environ.copy()
    for key, value in env_values.items():
        env.setdefault(key, value)

    env.setdefault("ENV", "public")
    env.setdefault("HOST", "127.0.0.1")
    env.setdefault("PORT", "8002")
    env.setdefault("RELOAD", "false")
    env.setdefault("DB_AUTO_SCHEMA", "false")
    env.setdefault("DATA_DIR", "../data")
    env.setdefault("LOG_DIR", "../logs")
    env.setdefault("DB_NAME", "GeniusStroke_v2.db")

    data_dir = resolve_runtime_path(index_data, env["DATA_DIR"])
    log_dir = resolve_runtime_path(index_data, env["LOG_DIR"])
    data_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / env["DB_NAME"]

    run_alembic(index_data, env)
    assert_database_ready(db_path)
    ensure_default_account(db_path)

    print(f"本地数据库已初始化：{db_path}")


if __name__ == "__main__":
    main()
