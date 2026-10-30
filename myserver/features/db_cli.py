"""Command-line MariaDB database helper (`myserver db`).

Provides fast database operations from the terminal without opening phpMyAdmin:
  myserver db list
  myserver db create <name>
  myserver db drop <name>
  myserver db import <name> <file.sql>
  myserver db export <name> [output.sql]
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from ..core import paths, helpers, ui
from ..services import mariadb


def _ensure_running() -> bool:
    if helpers.mariadb_is_running():
        return True
    ui.step("Starting MariaDB...")
    if not mariadb.start_mariadb_background():
        ui.err("MariaDB is not running and could not be started.")
        return False
    return True


def list_dbs() -> int:
    if not _ensure_running():
        return 1
    mariadb.list_user_databases(quiet=False)
    return 0


def create_db(name: str) -> int:
    if not helpers.is_safe_identifier(name):
        ui.err("Invalid database name. Use only letters, numbers, '-' or '_'.")
        return 1
    if not _ensure_running():
        return 1
    sql = (
        f"CREATE DATABASE IF NOT EXISTS `{name}` "
        "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    )
    r = helpers.run_mysql_query(sql)
    if r.returncode == 0:
        ui.ok(f"Database '{name}' is ready (utf8mb4).")
        return 0
    ui.err(f"Failed to create database '{name}': {(r.stderr or '').strip()[:200]}")
    return 1


def drop_db(name: str, force: bool = False) -> int:
    if not helpers.is_safe_identifier(name):
        ui.err("Invalid database name.")
        return 1
    if name.lower() in mariadb.SYSTEM_DBS:
        ui.err(f"Refusing to drop system database '{name}'.")
        return 1
    if not force and not ui.confirm(f"Permanently DROP database '{name}'?", default=False):
        ui.info("Cancelled.")
        return 0
    if not _ensure_running():
        return 1
    r = helpers.run_mysql_query(f"DROP DATABASE IF EXISTS `{name}`;")
    if r.returncode == 0:
        ui.ok(f"Database '{name}' dropped.")
        return 0
    ui.err(f"Failed to drop '{name}': {(r.stderr or '').strip()[:200]}")
    return 1


def import_sql(name: str, sql_path: str) -> int:
    if not helpers.is_safe_identifier(name):
        ui.err("Invalid database name.")
        return 1
    src = Path(sql_path).expanduser()
    if not src.exists() or not src.is_file():
        ui.err(f"SQL file not found: {src}")
        return 1
    if create_db(name) != 0:
        return 1

    ui.step(f"Importing {src.name} into '{name}'...")
    cli = helpers.mysql_client()
    with open(src, "rb") as f:
        r = subprocess.run(
            [cli, "-u", "root", f"--socket={paths.MARIADB_SOCKET}", name],
            stdin=f,
            stderr=subprocess.PIPE,
        )
    if r.returncode == 0:
        ui.ok(f"Imported '{src.name}' into database '{name}'.")
        return 0
    err = (r.stderr or b"").decode(errors="ignore").strip()[:250]
    ui.err(f"Import failed: {err}")
    return 1


def export_sql(name: str, out_path: str | None = None) -> int:
    if not helpers.is_safe_identifier(name):
        ui.err("Invalid database name.")
        return 1
    if not _ensure_running():
        return 1
    dst = Path(out_path).expanduser() if out_path else Path(f"{name}.sql").resolve()
    dump_bin = helpers.mysql_dump()
    cmd = [
        dump_bin,
        "-u", "root",
        f"--socket={paths.MARIADB_SOCKET}",
        "--single-transaction",
        "--routines",
        "--triggers",
        name,
    ]
    ui.step(f"Exporting '{name}' to {dst}...")
    with open(dst, "wb") as f:
        r = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE)
    if r.returncode == 0 and dst.exists() and dst.stat().st_size > 0:
        size_kb = dst.stat().st_size / 1024.0
        ui.ok(f"Database '{name}' exported to {dst} ({size_kb:.1f} KB).")
        return 0
    err = (r.stderr or b"").decode(errors="ignore").strip()[:250]
    ui.err(f"Export failed: {err}")
    return 1
