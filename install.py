#!/data/data/com.termux/files/usr/bin/python3
"""myserver installer — deploys the full Termux web-server stack."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ---- make sibling package importable --------------------------------------
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from myserver.core import paths, helpers, ui          # noqa: E402
from myserver.services import mariadb, redis as redis_svc, php, ssl, nginx  # noqa: E402
from myserver.features import live_reload, quickstart  # noqa: E402

SRC_PKG = ROOT / "myserver"
DEST_PKG = paths.LIB_DIR                                # $PREFIX/lib/myserver
BIN_MYSERVER = paths.BIN_MYSERVER
BIN_LIVE = paths.BIN_MYSERVER_LIVE


# ---------------------------------------------------------------------------
def read_version() -> str:
    try:
        return (ROOT / "VERSION").read_text().strip() or "0.0.0"
    except Exception:
        return "0.0.0"


def read_changelog_head() -> str:
    try:
        txt = (ROOT / "CHANGELOG.md").read_text()
    except Exception:
        return ""
    lines = txt.splitlines()
    out, started = [], False
    for ln in lines:
        if ln.startswith("## ["):
            if started:
                break
            started = True
        if started:
            out.append(ln)
    return "\n".join(out[:40])


def ensure_packages():
    php_ext_pkgs = " ".join(sorted(set(helpers.PHP_EXT_PACKAGES.values()))) if hasattr(helpers, "PHP_EXT_PACKAGES") else \
        "php-gd php-sodium php-redis php-apcu php-imagick"
    core_pkgs = ("nginx php php-fpm mariadb redis openssl-tool "
                 "curl tar unzip git wget cloudflared fzf inotify-tools")
    ui.step("Updating package index...")
    helpers.run_cmd("pkg update -y")
    ui.step("Installing core software...")
    r = helpers.run_cmd_capture(f"pkg install -y {core_pkgs} {php_ext_pkgs}", timeout=None)
    if r.returncode != 0:
        ui.warn(f"pkg install exited with code {r.returncode} — continuing.")


def ensure_storage_if_needed(htdocs: Path):
    if "storage" in str(htdocs) and not (paths.HOME / "storage").exists():
        subprocess.run("termux-setup-storage", shell=True)
        time.sleep(3)


def install_package():
    """Copy myserver/ package to $PREFIX/lib/myserver/ and create CLI shims."""
    ui.step(f"Installing package to {DEST_PKG} ...")
    if DEST_PKG.exists():
        shutil.rmtree(DEST_PKG, ignore_errors=True)
    shutil.copytree(SRC_PKG, DEST_PKG, ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", ".git"))

    # CLI shim
    BIN_MYSERVER.write_text(
        "#!/data/data/com.termux/files/usr/bin/python3\n"
        "import sys\n"
        f"sys.path.insert(0, {str(paths.PREFIX / 'lib')!r})\n"
        "from myserver.cli import main\n"
        "sys.exit(main())\n"
    )
    BIN_MYSERVER.chmod(0o755)

    # Live server (standalone)
    live_src = DEST_PKG / "features/live_server.py"
    if live_src.exists():
        content = live_src.read_text()
        if not content.startswith("#!"):
            content = "#!/data/data/com.termux/files/usr/bin/python3\n" + content
        BIN_LIVE.write_text(content)
        BIN_LIVE.chmod(0o755)
    ui.ok("Package installed.")


def write_version_file(version: str):
    try:
        paths.VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        paths.VERSION_FILE.write_text(version + "\n")
    except Exception as e:
        ui.warn(f"Could not write version file: {e}")


def bootstrap_boot_script():
    """Install Termux:Boot entry if the boot folder exists."""
    try:
        boot = paths.HOME / ".termux/boot"
        if not boot.parent.exists():
            boot.parent.mkdir(parents=True, exist_ok=True)
        boot.mkdir(exist_ok=True)
        script = boot / "start-myserver.sh"
        script.write_text(
            "#!/data/data/com.termux/files/usr/bin/sh\n"
            "termux-wake-lock\n"
            f"{paths.PREFIX}/bin/myserver start\n"
        )
        script.chmod(0o755)
        ui.ok(f"Boot script ready: {script}")
    except Exception as e:
        ui.warn(f"Boot script setup skipped: {e}")


# ---------------------------------------------------------------------------
def main() -> int:
    reinstall = (os.environ.get("MYSERVER_REINSTALL") == "1") or \
                ((paths.MYSQL_DATA_DIR / "mysql").exists() and paths.MY_CNF_FILE.exists())
    version = read_version()

    ui.info(f"myserver installer v{version} — {'REINSTALL' if reinstall else 'fresh install'}")
    if reinstall:
        ui.ok("Databases will be preserved")
        ui.ok("htdocs will be preserved")
        ui.info("phpMyAdmin will be refreshed")

    changelog = read_changelog_head()
    if changelog:
        print()
        ui.info("Latest changes:")
        for ln in changelog.splitlines():
            print(f"    {ln}")
        print()

    ui.ensure_fzf()
    ensure_packages()

    # ---- web root --------------------------------------------------------
    htdocs = None
    if paths.HTDOCS_PATH_FILE.exists():
        try:
            saved = paths.HTDOCS_PATH_FILE.read_text().strip()
            if saved:
                htdocs = Path(saved)
                ui.info(f"Web root: {htdocs}")
        except Exception:
            htdocs = None
    if not htdocs:
        idx = ui.choose_option(
            "Where should the web root (htdocs) be created?",
            ["Termux home", "Phone storage"],
            default=0)
        htdocs = paths.HOME_HTDOCS if idx == 0 else paths.STORAGE_HTDOCS
        paths.HTDOCS_PATH_FILE.parent.mkdir(parents=True, exist_ok=True)
        paths.HTDOCS_PATH_FILE.write_text(str(htdocs))
        ui.ok(f"Web root set to: {htdocs}")

    paths.HTDOCS_DIR = htdocs  # module-level override
    ensure_storage_if_needed(htdocs)

    # ---- DB password -----------------------------------------------------
    db_password = ""
    if reinstall:
        db_password = mariadb.read_password_from_my_cnf()
        if db_password:
            ui.info("Reusing MariaDB password from ~/.my.cnf")
        else:
            ui.info("MariaDB root has no password (preserved)")
    else:
        print()
        db_password = mariadb.ask_db_password()
        if db_password:
            ui.ok("MariaDB root password will be set")
        else:
            ui.info("MariaDB root will have NO password")
        print()

    # ---- setup steps -----------------------------------------------------
    steps = [
        ("MariaDB Initialization", lambda: mariadb.setup(htdocs, db_password, reinstall)),
        ("Redis Setup",            redis_svc.setup),
        ("PHP-FPM Configuration",  php.setup_fpm),
        ("SSL Certificate Setup",  ssl.setup),
        ("Nginx Server Setup",     lambda: nginx.setup(htdocs)),
        ("PHP Configuration",      php.create_php_ini),
        ("Web Root Setup",         lambda: nginx.setup_htdocs(htdocs)),
        ("phpMyAdmin Installation", lambda: quickstart.install_phpmyadmin(htdocs, db_password)),
        ("Live Reload Server",     live_reload.install_binary),
        ("Package Installation",   install_package),
        ("Boot Script",            bootstrap_boot_script),
        ("Version File",           lambda: (write_version_file(version), True)[1]),
    ]

    total = len(steps)
    for i, (desc, fn) in enumerate(steps, 1):
        ui.step(f"[{i}/{total}] {desc}...")
        try:
            ok = fn()
        except Exception as e:
            ui.err(f"Step failed: {desc} — {e}")
            return 1
        if ok is False:
            ui.err(f"Step failed: {desc}")
            return 1

    nginx.enforce_htdocs_permissions(htdocs)
    nginx.print_htdocs_diagnostic(htdocs)

    ui.step("Stopping MariaDB (post-install)...")
    mariadb.stop_mariadb_cleanly()

    print()
    ui.ok(f"{'Reinstall' if reinstall else 'Server Stack Deployed'} Successfully!")
    print(f"  Web Root:   {htdocs}")
    print(f"  HTTP URL:   http://localhost:8080")
    print(f"  HTTPS URL:  https://localhost:8443")
    print(f"  phpMyAdmin: http://localhost:8080/phpmyadmin")
    print()
    ui.info("Run 'myserver' to open the interactive manager.")
    ui.info("Enable Live Reload: myserver live-start")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[!] Cancelled.")
        sys.exit(130)