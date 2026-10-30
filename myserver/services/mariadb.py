"""MariaDB lifecycle: install, start, stop, password mgmt, safe repair.

Android Process Optimization:
  * Launches `mariadbd` directly (`shell=False`) instead of the `mariadbd-safe`
    shell wrapper, saving 1 persistent background process against Android 12+'s
    32 phantom-process limit.
  * Disables `performance_schema` and caps connections/caches to reduce thread
    and RAM overhead on mobile devices.
  * Executes all SQL via `helpers.run_mysql_query` (`stdin` + `shell=False`),
    eliminating shell injection and `/bin/sh` wrapper processes.
"""
from __future__ import annotations

import getpass
import os
import subprocess
import time
from pathlib import Path

from ..core import paths, helpers, ui

SYSTEM_DBS = ("mysql", "information_schema", "performance_schema", "sys")


# ---------------------------------------------------------------------------
# .my.cnf
# ---------------------------------------------------------------------------
def write_my_cnf(password: str, sock_path: Path):
    lines = ["[client]", "user = root"]
    if password:
        lines.append(f'password = "{helpers.cnf_escape(password)}"')
    lines.append(f"socket = {sock_path}")
    paths.MY_CNF_FILE.write_text("\n".join(lines) + "\n")
    try:
        os.chmod(paths.MY_CNF_FILE, 0o600)
    except Exception:
        pass


def read_password_from_my_cnf() -> str:
    if not paths.MY_CNF_FILE.exists():
        return ""
    try:
        in_client = False
        for raw in paths.MY_CNF_FILE.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith(("#", ";")):
                continue
            if line.startswith("[") and line.endswith("]"):
                in_client = (line[1:-1].strip().lower() == "client")
                continue
            if not in_client or "=" not in line:
                continue
            k, _, v = line.partition("=")
            if k.strip().lower() != "password":
                continue
            v = v.strip()
            if len(v) >= 2 and v.startswith('"') and v.endswith('"'):
                v = v[1:-1].replace('\\"', '"').replace('\\\\', '\\')
            elif len(v) >= 2 and v.startswith("'") and v.endswith("'"):
                v = v[1:-1]
            return v
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Database listing (shared across backup, uninstall, and db_cli)
# ---------------------------------------------------------------------------
def list_user_databases(quiet: bool = False) -> list[str]:
    """Return user databases (excluding system schemas) via information_schema."""
    sql = (
        "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
        "WHERE SCHEMA_NAME NOT IN "
        "('mysql','information_schema','performance_schema','sys');"
    )
    r = helpers.run_mysql_query(sql, timeout=15, batch=True)
    if r.returncode != 0:
        if not quiet:
            err = (r.stderr or "").strip().splitlines()
            ui.warn(f"DB list failed: {err[0][:200] if err else 'unknown error'}")
        return []

    dbs = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    if not quiet:
        if dbs:
            ui.info(f"Found {len(dbs)} user database(s): {', '.join(dbs)}")
        else:
            ui.info("No user databases found.")
    return dbs


# ---------------------------------------------------------------------------
# interactive
# ---------------------------------------------------------------------------
def ask_db_password() -> str:
    print(f"{ui.C_CYAN}[i] MariaDB root password{ui.C_RESET}")
    print(f"{ui.C_YELLOW}    Leave empty and press Enter for NO password (default){ui.C_RESET}")
    while True:
        try:
            pw = getpass.getpass(f"{ui.C_YELLOW}  Password: {ui.C_RESET}").strip()
        except KeyboardInterrupt:
            raise
        except Exception as e:
            ui.warn(f"Cannot read password (no TTY?): {e}")
            ui.info("Falling back to NO password.")
            return ""
        if not pw:
            return ""
        try:
            confirm = getpass.getpass(f"{ui.C_YELLOW}  Confirm : {ui.C_RESET}").strip()
        except KeyboardInterrupt:
            raise
        except Exception:
            confirm = ""
        if pw == confirm:
            return pw
        ui.err("Passwords do not match. Please try again.")
        print()


# ---------------------------------------------------------------------------
# lifecycle
# ---------------------------------------------------------------------------
def _mariadb_daemon_binary() -> str:
    if helpers.command_exists("mariadbd"):
        return "mariadbd"
    if helpers.command_exists("mysqld"):
        return "mysqld"
    return "mariadbd-safe"


def start_mariadb_background() -> bool:
    paths.MYSQL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    paths.MYSQL_RUN_DIR.mkdir(parents=True, exist_ok=True)

    if helpers.mariadb_is_running():
        return True

    # clean stale socket only when no server is alive
    if paths.MARIADB_SOCKET.exists():
        try:
            paths.MARIADB_SOCKET.unlink()
        except Exception:
            pass

    daemon_bin = _mariadb_daemon_binary()
    cmd = [
        daemon_bin,
        f"--datadir={paths.MYSQL_DATA_DIR}",
        f"--socket={paths.MARIADB_SOCKET}",
        f"--pid-file={paths.PID_MARIADB}",
        "--bind-address=127.0.0.1",
        "--max-connections=25",
        "--table-open-cache=128",
        "--performance-schema=OFF",
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    helpers.write_pid_file(paths.PID_MARIADB, proc.pid)

    for _ in range(15):
        if paths.MARIADB_SOCKET.exists():
            return True
        time.sleep(1)
    return paths.MARIADB_SOCKET.exists()


def stop_mariadb_cleanly():
    # graceful shutdown via admin
    admin_bin = helpers.mysql_admin()
    if paths.MARIADB_SOCKET.exists() and helpers.command_exists(admin_bin):
        helpers.run_cmd([
            admin_bin,
            f"--socket={paths.MARIADB_SOCKET}",
            "shutdown",
        ])
        time.sleep(1.5)
    helpers.safe_stop(
        paths.PID_MARIADB,
        ("mariadbd", "mysqld", "mariadbd-safe", "mysqld_safe"),
    )


# ---------------------------------------------------------------------------
# safe repair of broken unix_socket auth
# ---------------------------------------------------------------------------
def _port_3306_is_listening() -> bool:
    return helpers.port_in_use(3306)


def repair_root_if_unix_socket():
    """Fix root@localhost that was left on unix_socket auth.
       Runs with --skip-networking and --skip-bind-address to avoid exposing
       a no-auth MySQL on the network."""
    if not paths.MARIADB_SOCKET.exists():
        return
    r = helpers.run_mysql_query("SELECT 1;", timeout=10)
    if r.returncode == 0:
        return
    err = (r.stderr or "").lower()
    if "1698" not in err and "unix_socket" not in err and "access denied" not in err:
        return

    ui.warn("Detected broken root auth — repairing via skip-grant-tables...")
    stop_mariadb_cleanly()
    time.sleep(2)

    if _port_3306_is_listening():
        ui.err("Port 3306 is listening — refusing to run repair. Stop the foreign server first.")
        start_mariadb_background()
        return

    daemon_bin = _mariadb_daemon_binary()
    cmd = [
        daemon_bin,
        "--skip-grant-tables",
        "--skip-networking",
        "--skip-bind-address",
        f"--datadir={paths.MYSQL_DATA_DIR}",
        f"--socket={paths.MARIADB_SOCKET}",
    ]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    ok = False
    for _ in range(15):
        if paths.MARIADB_SOCKET.exists():
            ok = True
            break
        time.sleep(1)
    if not ok:
        ui.err("Repair failed: MariaDB did not start.")
        try:
            proc.kill()
        except Exception:
            pass
        return
    time.sleep(2)

    if _port_3306_is_listening():
        ui.err("3306 unexpectedly listening during repair — aborting.")
        stop_mariadb_cleanly()
        return

    fix_sql = (
        "UPDATE mysql.user SET plugin='mysql_native_password' "
        "WHERE User='root' AND Host='localhost';\n"
        "UPDATE mysql.user SET Password='' "
        "WHERE User='root' AND Host='localhost';\n"
        "UPDATE mysql.user SET authentication_string='' "
        "WHERE User='root' AND Host='localhost';\n"
        "FLUSH PRIVILEGES;\n"
    )
    helpers.run_mysql_query(fix_sql, batch=False)

    stop_mariadb_cleanly()
    time.sleep(2)

    if start_mariadb_background():
        r = helpers.run_mysql_query("SELECT 1;", timeout=10)
        if r.returncode == 0:
            ui.ok("Root authentication repaired successfully.")
        else:
            ui.warn("Repair attempted but root still not accessible.")


# ---------------------------------------------------------------------------
# setup
# ---------------------------------------------------------------------------
def setup(_htdocs: Path, db_password: str, reinstall: bool) -> bool:
    try:
        paths.MYSQL_DATA_DIR.mkdir(parents=True, exist_ok=True)
        paths.MYSQL_RUN_DIR.mkdir(parents=True, exist_ok=True)

        if not helpers.mariadb_is_running() and paths.MARIADB_SOCKET.exists():
            try:
                paths.MARIADB_SOCKET.unlink()
            except Exception:
                pass

        fresh = not (paths.MYSQL_DATA_DIR / "mysql").exists()
        if fresh:
            helpers.run_cmd([
                "mariadb-install-db",
                "--auth-root-authentication-method=normal",
                f"--datadir={paths.MYSQL_DATA_DIR}",
            ])
            ui.ok("MariaDB database initialized (normal auth).")
        else:
            ui.info("Existing MariaDB data detected — preserving databases.")

        if not start_mariadb_background():
            ui.err("Failed to start MariaDB.")
            return False

        repair_root_if_unix_socket()

        if paths.MARIADB_SOCKET.exists():
            sec_sql = (
                "DROP USER IF EXISTS ''@'localhost';\n"
                "DROP USER IF EXISTS ''@'%';\n"
                "DROP USER IF EXISTS 'root'@'%';\n"
                "DROP DATABASE IF EXISTS test;\n"
                "FLUSH PRIVILEGES;\n"
            )
            r = helpers.run_mysql_query(sec_sql, batch=False)
            if r.returncode == 0:
                ui.ok("MariaDB Security Hardening applied.")
            else:
                ui.warn("Hardening note: " +
                        ((r.stderr or "unknown").strip().splitlines() or ["?"])[0][:200])

        if reinstall:
            ui.info("Reinstall mode — preserving root credentials.")
            return True

        write_my_cnf("", paths.MARIADB_SOCKET)

        if db_password:
            escaped = helpers.sql_escape(db_password)
            pw_sql = (
                f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{escaped}';\n"
                "FLUSH PRIVILEGES;\n"
            )
            r = helpers.run_mysql_query(pw_sql, batch=False)
            if r.returncode == 0:
                write_my_cnf(db_password, paths.MARIADB_SOCKET)
                ui.ok("MariaDB root password set.")
            else:
                ui.warn("Password note: " +
                        ((r.stderr or "unknown").strip().splitlines() or ["?"])[0][:200])
        else:
            r = helpers.run_mysql_query(
                "ALTER USER 'root'@'localhost' IDENTIFIED BY '';\nFLUSH PRIVILEGES;\n",
                batch=False,
            )
            if r.returncode == 0:
                ui.info("MariaDB root has no password.")
            else:
                ui.warn("Note: " +
                        ((r.stderr or "unknown").strip().splitlines() or ["?"])[0][:200])

        return True
    except Exception as e:
        ui.err(f"MariaDB init error: {e}")
        return False