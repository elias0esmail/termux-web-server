"""MariaDB lifecycle: install, start, stop, password mgmt, safe repair."""
from __future__ import annotations

import getpass
import os
import subprocess
import time
from pathlib import Path

from ..core import paths, helpers, ui

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

    if helpers.command_exists("mariadbd-safe"):
        cmd = (f"mariadbd-safe --datadir='{paths.MYSQL_DATA_DIR}' "
               f"--socket='{paths.MARIADB_SOCKET}'")
    else:
        cmd = (f"mariadbd --datadir='{paths.MYSQL_DATA_DIR}' "
               f"--socket='{paths.MARIADB_SOCKET}'")

    proc = subprocess.Popen(cmd, shell=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    helpers.write_pid_file(paths.PID_MARIADB, proc.pid)

    for _ in range(15):
        if paths.MARIADB_SOCKET.exists():
            return True
        time.sleep(1)
    return paths.MARIADB_SOCKET.exists()


def stop_mariadb_cleanly():
    # graceful shutdown via admin
    if paths.MARIADB_SOCKET.exists() and helpers.command_exists(helpers.mysql_admin()):
        helpers.run_cmd(
            f"{helpers.mysql_admin()} --socket='{paths.MARIADB_SOCKET}' shutdown")
        time.sleep(1.5)
    helpers.safe_stop(paths.PID_MARIADB,
                      ("mariadbd-safe", "mysqld_safe", "mariadbd", "mysqld"))


# ---------------------------------------------------------------------------
# safe repair of broken unix_socket auth
# ---------------------------------------------------------------------------
def _port_3306_is_listening() -> bool:
    return helpers.port_in_use(3306)


def repair_root_if_unix_socket():
    """Fix root@localhost that was left on unix_socket auth.
       The repair always runs with --skip-networking to avoid exposing
       a no-auth MySQL on the network."""
    if not paths.MARIADB_SOCKET.exists():
        return
    cli = helpers.mysql_client()
    r = helpers.run_cmd_capture(
        f"{cli} -u root --socket='{paths.MARIADB_SOCKET}' -e 'SELECT 1;'",
        timeout=10)
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

    # IMPORTANT: --skip-networking AND --skip-bind-address for safety
    if helpers.command_exists("mariadbd-safe"):
        cmd = (f"mariadbd-safe --skip-grant-tables --skip-networking "
               f"--skip-bind-address "
               f"--datadir='{paths.MYSQL_DATA_DIR}' --socket='{paths.MARIADB_SOCKET}'")
    else:
        cmd = (f"mariadbd --skip-grant-tables --skip-networking "
               f"--skip-bind-address "
               f"--datadir='{paths.MYSQL_DATA_DIR}' --socket='{paths.MARIADB_SOCKET}'")

    proc = subprocess.Popen(cmd, shell=True,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        "WHERE User='root' AND Host='localhost';"
        "UPDATE mysql.user SET Password='' "
        "WHERE User='root' AND Host='localhost';"
        "UPDATE mysql.user SET authentication_string='' "
        "WHERE User='root' AND Host='localhost';"
        "FLUSH PRIVILEGES;"
    )
    helpers.run_cmd_capture(
        f"{cli} -u root --socket='{paths.MARIADB_SOCKET}' -e \"{fix_sql}\"")

    stop_mariadb_cleanly()
    time.sleep(2)

    if start_mariadb_background():
        r = helpers.run_cmd_capture(
            f"{cli} -u root --socket='{paths.MARIADB_SOCKET}' -e 'SELECT 1;'",
            timeout=10)
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
            helpers.run_cmd(
                f"mariadb-install-db --auth-root-authentication-method=normal "
                f"--datadir='{paths.MYSQL_DATA_DIR}'")
            ui.ok("MariaDB database initialized (normal auth).")
        else:
            ui.info("Existing MariaDB data detected — preserving databases.")

        if not start_mariadb_background():
            ui.err("Failed to start MariaDB.")
            return False

        repair_root_if_unix_socket()
        cli = helpers.mysql_client()

        if paths.MARIADB_SOCKET.exists():
            sec_sql = (
                "DROP USER IF EXISTS ''@'localhost';"
                "DROP USER IF EXISTS ''@'%';"
                "DROP USER IF EXISTS 'root'@'%';"
                "DROP DATABASE IF EXISTS test;"
                "FLUSH PRIVILEGES;"
            )
            r = helpers.run_cmd_capture(
                f"{cli} -u root --socket='{paths.MARIADB_SOCKET}' -e \"{sec_sql}\"")
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
            tmp = paths.TMP_DIR / "myserver_setpw.sql"
            paths.TMP_DIR.mkdir(parents=True, exist_ok=True)
            escaped = helpers.sql_escape(db_password)
            tmp.write_text(
                f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{escaped}';\n"
                "FLUSH PRIVILEGES;\n")
            r = helpers.run_cmd_capture(
                f"{cli} -u root --socket='{paths.MARIADB_SOCKET}' < '{tmp}'")
            try:
                tmp.unlink()
            except Exception:
                pass
            if r.returncode == 0:
                write_my_cnf(db_password, paths.MARIADB_SOCKET)
                ui.ok("MariaDB root password set.")
            else:
                ui.warn("Password note: " +
                        ((r.stderr or "unknown").strip().splitlines() or ["?"])[0][:200])
        else:
            r = helpers.run_cmd_capture(
                f"{cli} -u root --socket='{paths.MARIADB_SOCKET}' -e "
                f"\"ALTER USER 'root'@'localhost' IDENTIFIED BY ''; FLUSH PRIVILEGES;\"")
            if r.returncode == 0:
                ui.info("MariaDB root has no password.")
            else:
                ui.warn("Note: " +
                        ((r.stderr or "unknown").strip().splitlines() or ["?"])[0][:200])

        return True
    except Exception as e:
        ui.err(f"MariaDB init error: {e}")
        return False