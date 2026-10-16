"""Command-line dispatcher and individual command implementations."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

from ..core import paths, helpers, ui
from ..services import ssl as ssl_svc
from ..features import backup, doctor, live_reload, tunnel, wake_lock
from . import services_ctl, menu


HELP_TEXT = """\
myserver — Termux web server manager

Usage: myserver [command]

Service control:
  start                          Start all services
  stop                           Stop all services
  restart                        Restart all services
  status                         Show status + URLs

Live Reload:
  live-start, live-enable        Enable live reload
  live-stop,  live-disable       Disable live reload
  live-restart                   Restart live reload
  live-status                    Show live reload status
  live-toggle                    Toggle live reload

Internet (Cloudflare Tunnel):
  internet-enable                Publish to a public URL
  internet-disable               Stop public URL

Backups:
  backup [name]                  Create full backup
  backup-list                    List backups
  restore <file.tar.gz>          Restore from backup

Diagnostics:
  doctor                         Full environment check
  logs <nginx|php|redis|live|tunnel>   Show recent log lines
  version                        Show version

SSL:
  ssl-info                       Show certificate details
  ssl-import <cert> <key>        Use a custom certificate
  ssl-remove                     Remove custom certificate

Maintenance:
  update                         Check GitHub for updates
  reinstall                      Reinstall (preserves DBs+htdocs)
  uninstall                      Remove EVERYTHING (confirm required)

Wake lock / boot:
  wake-lock                      Acquire wake lock
  wake-unlock                    Release wake lock
  wake-status                    Show wake-lock + boot status

Other:
  quickstart                     Framework installer
  help, -h, --help               This help
"""


# ---------------------------------------------------------------------------
def _resolve_runtime_paths():
    paths.resolve_runtime_paths()


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------
def cmd_status():
    from ..core import helpers as h
    version = h.read_version()
    menu._render_banner(version)
    menu._render_status()
    return 0


# ---------------------------------------------------------------------------
# update
# ---------------------------------------------------------------------------
def _fetch(url: str, timeout: int = 15) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "myserver"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return None


def _print_remote_changelog(changelog: str, version: str):
    lines = changelog.splitlines()
    in_section = False
    printed = []
    for ln in lines:
        if ln.startswith(f"## [{version}]"):
            in_section = True
            printed.append(ln)
            continue
        if in_section:
            if ln.startswith("## ["):
                break
            printed.append(ln)
    if not printed:
        # fall back to first section
        for ln in lines:
            if ln.startswith("## ["):
                if printed:
                    break
                printed.append(ln)
                continue
            if printed:
                printed.append(ln)
    for ln in printed:
        print(f"  {ln}")


def _download_and_install_tarball() -> int:
    ui.step("Downloading new version...")
    tmp = Path(tempfile.mkdtemp(prefix="myserver-update-"))
    tarball = tmp / "src.tar.gz"
    try:
        req = urllib.request.Request(
            paths.GITHUB_TARBALL_URL, headers={"User-Agent": "myserver"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tarball, "wb") as f:
            shutil.copyfileobj(r, f)
        ui.ok(f"Downloaded {tarball.stat().st_size / 1024:.0f} KB")

        ui.step("Extracting...")
        with tarfile.open(tarball, "r:gz") as tar:
            # Python 3.12+ supports filter="data" for safe extraction
            try:
                tar.extractall(tmp, filter="data")
            except TypeError:
                tar.extractall(tmp)

        # find the top directory
        src_root = None
        for child in tmp.iterdir():
            if child.is_dir() and (child / "install.py").exists():
                src_root = child
                break
        if not src_root:
            ui.err("Could not find install.py in downloaded archive.")
            return 1

        ui.step("Running installer (DBs+htdocs preserved)...")
        env = os.environ.copy()
        env["MYSERVER_REINSTALL"] = "1"
        env["MYSERVER_SKIP_AUTOUPDATE"] = "1"
        py = sys.executable or "python3"
        rc = subprocess.call([py, str(src_root / "install.py")], env=env, cwd=str(src_root))
        return rc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_update(auto: bool = False) -> int:
    local = helpers.read_version()
    if not auto:
        ui.step(f"Checking for updates (current: {local})...")

    remote_version = _fetch(f"{paths.GITHUB_RAW_URL}/VERSION")
    if not remote_version:
        if not auto:
            ui.err("Could not reach GitHub.")
        return 1
    remote_version = remote_version.strip()

    if remote_version == local:
        if not auto:
            ui.ok(f"Already on latest ({local}).")
        return 0

    ui.warn(f"Update available: {local} -> {remote_version}")
    changelog = _fetch(f"{paths.GITHUB_RAW_URL}/CHANGELOG.md") or ""
    if changelog:
        print(f"\n{ui.C_CYAN}Changelog:{ui.C_RESET}")
        _print_remote_changelog(changelog, remote_version)
        print()

    if auto:
        # silent auto-update is disabled by default — do not auto-install
        return 0

    if not ui.confirm("Download and install now?", default=True):
        ui.info("Cancelled.")
        return 0

    ui.step("Stopping services...")
    services_ctl.stop_all(quiet=True)

    rc = _download_and_install_tarball()
    if rc != 0:
        ui.err(f"Update failed (rc={rc}).")
        return rc

    ui.ok(f"Updated to {remote_version}.")
    ui.info("Launching new version...")
    os.execvp(str(paths.BIN_MYSERVER), [str(paths.BIN_MYSERVER), "status"])
    return 0


# ---------------------------------------------------------------------------
# reinstall
# ---------------------------------------------------------------------------
def cmd_reinstall() -> int:
    ui.warn("Reinstall: DBs + htdocs will be preserved.")
    if not ui.confirm("Continue?", default=True):
        return 0
    services_ctl.stop_all(quiet=True)
    return _download_and_install_tarball()


# ---------------------------------------------------------------------------
# uninstall
# ---------------------------------------------------------------------------
def cmd_uninstall() -> bool:
    print(f"{ui.C_RED}============================================{ui.C_RESET}")
    print(f"{ui.C_RED}   WARNING: UNINSTALL MYSERVER STACK        {ui.C_RESET}")
    print(f"{ui.C_RED}============================================{ui.C_RESET}")
    print(" This will PERMANENTLY DELETE:")
    print("   ✗ All server configuration files")
    print("   ✗ ALL user databases (WordPress, Nextcloud, ...)")
    print("   ✗ MariaDB data directory")
    print(f"   ✗ Web root: {paths.HTDOCS_DIR}")
    print("   ✗ ~/.my.cnf, myserver CLI, Live Reload helper")
    print(f"\n{ui.C_YELLOW} Backups in {paths.BACKUP_DIR} are NOT touched.{ui.C_RESET}\n")
    try:
        answer = input(f"{ui.C_RED}Type 'yes' to confirm: {ui.C_RESET}").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    if answer != "yes":
        ui.info("Cancelled.")
        return False

    services_ctl.stop_all(quiet=True)

    # drop user databases
    ui.step("Dropping user databases...")
    from ..services import mariadb
    if mariadb.start_mariadb_background():
        cli = helpers.mysql_client()
        r = helpers.run_cmd_capture(
            f"{cli} -u root --socket='{paths.MARIADB_SOCKET}' -N -B -e "
            f"\"SHOW DATABASES WHERE `Database` NOT IN "
            f"('mysql','information_schema','performance_schema','sys');\"")
        for db in (r.stdout or "").splitlines():
            db = db.strip()
            if not db:
                continue
            ui.info(f"Dropping: {db}")
            helpers.run_cmd_capture(
                f"{cli} -u root --socket='{paths.MARIADB_SOCKET}' -e "
                f"\"DROP DATABASE IF EXISTS `{db}`;\"")
        mariadb.stop_mariadb_cleanly()

    ui.step("Removing configuration and data...")
    for p in (
        paths.LIVE_CONF_FILE,
        paths.NGINX_CONF,
        paths.PHP_FPM_CONF,
        paths.VERSION_FILE,
        paths.HTDOCS_PATH_FILE,
        paths.MY_CNF_FILE,
        paths.PID_NGINX, paths.PID_PHP, paths.PID_REDIS, paths.PID_MARIADB,
        paths.PID_TUNNEL, paths.PID_LIVE,
        paths.TUNNEL_URL_FILE, paths.TUNNEL_LOG,
        paths.LIVE_LOG_FILE,
    ):
        try:
            if p.exists():
                p.unlink()
        except Exception:
            pass

    for d in (paths.SSL_DIR, paths.MYSQL_DATA_DIR, paths.MYSQL_RUN_DIR):
        try:
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass

    # php extensions we added
    try:
        if paths.PHP_CONFD_DIR.exists():
            for f in paths.PHP_CONFD_DIR.glob("*.ini"):
                try:
                    f.unlink()
                except Exception:
                    pass
    except Exception:
        pass

    # htdocs
    ui.step("Removing web root...")
    try:
        if paths.HTDOCS_DIR.exists():
            shutil.rmtree(paths.HTDOCS_DIR, ignore_errors=True)
    except Exception:
        pass

    # boot script
    boot = paths.HOME / ".termux/boot/start-myserver.sh"
    try:
        if boot.exists():
            boot.unlink()
    except Exception:
        pass

    # package + binaries
    for d in (paths.LIB_DIR,):
        try:
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass
    for b in (paths.BIN_MYSERVER, paths.BIN_MYSERVER_LIVE):
        try:
            if b.exists():
                b.unlink()
        except Exception:
            pass

    ui.ok("Uninstalled completely.")
    return True


# ---------------------------------------------------------------------------
# logs
# ---------------------------------------------------------------------------
def cmd_logs(which: str = "nginx", lines: int = 50) -> int:
    return services_ctl.tail_service_logs(which, lines)


# ---------------------------------------------------------------------------
# ssl-import / ssl-remove
# ---------------------------------------------------------------------------
def cmd_ssl_import(cert: str, key: str) -> int:
    ok = ssl_svc.import_custom(cert, key)
    if ok:
        from ..services import nginx
        nginx.setup(paths.HTDOCS_DIR)
        nginx.reload()
    return 0 if ok else 1


def cmd_ssl_remove() -> int:
    if ssl_svc.remove_custom():
        from ..services import nginx
        nginx.setup(paths.HTDOCS_DIR)
        nginx.reload()
    return 0


# ---------------------------------------------------------------------------
# dispatcher
# ---------------------------------------------------------------------------
def main() -> int:
    # make sure HTDOCS_DIR reflects what the user chose at install time
    _resolve_runtime_paths()

    args = sys.argv[1:]

    # no args -> interactive menu
    if not args:
        # skip auto-update unless explicitly opted in
        if os.environ.get("MYSERVER_SKIP_AUTOUPDATE") != "1" \
                and os.environ.get("MYSERVER_AUTO_UPDATE") == "1":
            cmd_update(auto=True)
        version = helpers.read_version()
        menu.menu(version)
        return 0

    cmd = args[0].lower()
    rest = args[1:]

    # ---- help ----
    if cmd in ("help", "-h", "--help"):
        print(HELP_TEXT)
        return 0

    # ---- version ----
    if cmd in ("version", "-v", "--version"):
        print(f"myserver {helpers.read_version()}")
        return 0

    # ---- service control ----
    if cmd == "start":
        return 0 if services_ctl.start_all() else 1
    if cmd == "stop":
        return 0 if services_ctl.stop_all() else 1
    if cmd == "restart":
        return 0 if services_ctl.restart_all() else 1
    if cmd == "status":
        return cmd_status()

    # ---- live reload ----
    if cmd in ("live-start", "live-enable"):
        return 0 if live_reload.start() else 1
    if cmd in ("live-stop", "live-disable"):
        return 0 if live_reload.stop() else 1
    if cmd == "live-restart":
        return 0 if live_reload.restart() else 1
    if cmd == "live-status":
        live_reload.status(); return 0
    if cmd == "live-toggle":
        live_reload.toggle(); return 0

    # ---- internet ----
    if cmd in ("internet-enable", "enable-internet"):
        return 0 if tunnel.enable() else 1
    if cmd in ("internet-disable", "disable-internet"):
        return 0 if tunnel.disable() else 1

    # ---- backups ----
    if cmd == "backup":
        name = rest[0] if rest else None
        return 0 if backup.create(name) else 1
    if cmd == "backup-list":
        backup.list_cmd(); return 0
    if cmd == "restore":
        if not rest:
            ui.err("Usage: myserver restore <file.tar.gz>")
            return 2
        return 0 if backup.restore(rest[0]) else 1

    # ---- diagnostics ----
    # ---- diagnostics ----
    if cmd == "doctor":
        do_fix = any(a in ("--fix", "-f") for a in rest)
        return doctor.run(fix=do_fix)
    if cmd == "logs":
        which = rest[0] if rest else "nginx"
        return cmd_logs(which)

    # ---- ssl ----
    if cmd == "ssl-info":
        ssl_svc.print_info(); return 0
    if cmd == "ssl-import":
        if len(rest) < 2:
            ui.err("Usage: myserver ssl-import <cert.pem> <key.pem>")
            return 2
        return cmd_ssl_import(rest[0], rest[1])
    if cmd == "ssl-remove":
        return cmd_ssl_remove()

    # ---- maintenance ----
    if cmd == "update":
        return cmd_update(auto=False)
    if cmd == "reinstall":
        return cmd_reinstall()
    if cmd in ("uninstall", "delete"):
        return 0 if cmd_uninstall() else 1

    # ---- wake lock ----
    if cmd == "wake-lock":
        wake_lock.acquire(); return 0
    if cmd == "wake-unlock":
        wake_lock.release(); return 0
    if cmd == "wake-status":
        wake_lock.status(); return 0

    # ---- quickstart ----
    if cmd == "quickstart":
        from ..features import quickstart
        from ..services import mariadb
        quickstart.menu(paths.HTDOCS_DIR, mariadb.read_password_from_my_cnf())
        return 0

    # ---- unknown ----
    ui.err(f"Unknown command: {cmd}")
    print()
    print(HELP_TEXT)
    return 2