"""Diagnostic tool — checks environment, files, permissions, services.

Supports:
    myserver doctor           → read-only check
    myserver doctor --fix     → attempt to fix common issues
"""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

from ..core import paths, helpers, ui
from ..services import ssl as ssl_svc


# ===========================================================================
def _mark(ok: bool) -> str:
    return f"{ui.C_GREEN}✓{ui.C_RESET}" if ok else f"{ui.C_RED}✗{ui.C_RESET}"


def _line(ok: bool, label: str, hint: str = ""):
    suffix = ""
    if not ok and hint:
        suffix = f"  {ui.C_YELLOW}→ {hint}{ui.C_RESET}"
    print(f"  {_mark(ok)} {label}{suffix}")


def _section(name: str):
    print(f"\n{ui.C_CYAN}[ {name} ]{ui.C_RESET}")


# ===========================================================================
def _is_android_shared_storage(path: Path) -> bool:
    """Detect /storage/emulated or ~/storage/shared — chmod is a no-op there."""
    try:
        resolved = str(path.resolve())
    except Exception:
        resolved = str(path)
    return (
        "/storage/emulated/" in resolved
        or "/storage/shared/" in resolved
        or "/sdcard/" in resolved
    )



# ===========================================================================
def _fix_php_extensions(missing: list[str]) -> int:
    """pkg install php-<ext> for each missing extension."""
    if not missing:
        return 0
    pkgs = [f"php-{e}" for e in missing]
    ui.step(f"Installing: {' '.join(pkgs)}")
    r = subprocess.run(
        ["pkg", "install", "-y"] + pkgs,
        capture_output=True, text=True)
    if r.returncode != 0:
        ui.err(f"pkg install failed: {r.stderr.strip()[:200]}")
        return 1
    ui.ok("Packages installed. Restart PHP-FPM to load them.")
    return 0


def _fix_htdocs_perms(htdocs: Path) -> int:
    """Attempt to normalize htdocs permissions. Warn on Android shared storage."""
    if not htdocs.exists():
        return 0
    android_shared = _is_android_shared_storage(htdocs)
    if android_shared:
        ui.warn("Web root is on Android shared storage.")
        ui.info("Android FUSE ignores chmod here — 0770 is normal and safe.")
        ui.info("If browsing fails, consider moving web root to Termux home.")
        return 0
    ui.step("Fixing htdocs permissions...")
    from ..services import nginx
    changed = nginx.enforce_htdocs_permissions(htdocs)
    if changed:
        ui.ok(f"Fixed {changed} entries.")
    else:
        ui.info("Nothing to fix.")
    return 0


# ===========================================================================
def run(fix: bool = False) -> int:
    fails: list[tuple[str, str]] = []          # (label, hint) — only failures
    missing_php: list[str] = []

    # ---------- packages ----------
    _section("Packages")
    for cmd in ("nginx", "php", "php-fpm", "mariadb", "redis-server",
                "curl", "openssl", "tar", "unzip", "cloudflared"):
        ok = helpers.command_exists(cmd)
        _line(ok, f"{cmd} installed",
              f"pkg install {cmd if cmd != 'php-fpm' else 'php'}")
        if not ok:
            fails.append((f"{cmd} installed",
                          f"pkg install {cmd if cmd != 'php-fpm' else 'php'}"))

    ok = helpers.command_exists("inotifywait")
    _line(ok, "inotifywait installed (fast Live Reload)",
          "pkg install inotify-tools")
    if not ok:
        fails.append(("inotifywait installed", "pkg install inotify-tools"))

    # ---------- PHP extensions ----------
    _section("PHP extensions")
    loaded = helpers.php_loaded_extensions()
    for ext in ("mysqli", "pdo_mysql", "mbstring", "openssl", "curl",
                "zip", "xml", "intl", "bcmath", "gd", "sodium",
                "redis", "apcu"):
        ok = ext in loaded
        _line(ok, f"php-{ext} loaded", f"pkg install php-{ext}")
        if not ok:
            fails.append((f"php-{ext} loaded", f"pkg install php-{ext}"))
            missing_php.append(ext)

    # ---------- Files ----------
    _section("Files")
    for p, label in (
        (paths.NGINX_CONF,        "nginx.conf"),
        (paths.PHP_FPM_CONF,      "php-fpm www.conf"),
        (paths.MY_CNF_FILE,       "~/.my.cnf"),
        (paths.HTDOCS_PATH_FILE,  "htdocs path file"),
        (paths.BIN_MYSERVER,      "myserver CLI"),
        (paths.BIN_MYSERVER_LIVE, "myserver-live binary"),
        (paths.DEFAULT_CERT,      "SSL certificate"),
        (paths.DEFAULT_KEY,       "SSL key"),
    ):
        ok = p.exists()
        _line(ok, f"{label} exists", "myserver reinstall")
        if not ok:
            fails.append((f"{label} exists", "myserver reinstall"))

    ok = paths.HTDOCS_DIR.exists()
    _line(ok, f"htdocs exists ({paths.HTDOCS_DIR})",
          "create web root or run install again")
    if not ok:
        fails.append(("htdocs exists", "run: myserver reinstall"))

    # ---------- Permissions ----------
    _section("Permissions")
    if paths.HTDOCS_DIR.exists():
        mode = paths.HTDOCS_DIR.stat().st_mode & 0o777
        android_shared = _is_android_shared_storage(paths.HTDOCS_DIR)
        want = 0o755
        ok = (mode == want)
        if not ok and android_shared:
            # Android shared storage is a known exception.
            _line(True, f"htdocs perms = {oct(mode)} "
                        f"(Android shared storage — 0770 accepted)")
        else:
            _line(ok, f"htdocs perms = {oct(mode)} (want 0{oct(want)[2:]})",
                  "myserver doctor --fix")
            if not ok:
                fails.append((f"htdocs perms = {oct(mode)}",
                              "myserver doctor --fix"))

        idx = paths.HTDOCS_DIR / "index.php"
        if idx.exists():
            ok = os.access(idx, os.R_OK)
            _line(ok, "index.php readable", "chmod 644 index.php")
            if not ok:
                fails.append(("index.php readable", "chmod 644 index.php"))

    if paths.DEFAULT_KEY.exists():
        mode = paths.DEFAULT_KEY.stat().st_mode & 0o777
        ok = (mode == 0o600)
        _line(ok, f"SSL key perms = {oct(mode)} (want 0600)",
              "chmod 600 ssl/server.key")
        if not ok:
            fails.append((f"SSL key perms = {oct(mode)}",
                          "chmod 600 ssl/server.key"))

    # ---------- Ports ----------
    _section("Ports")
    for port, name, ours in (
        (8080, "HTTP",    helpers.is_process_running("nginx")),
        (8443, "HTTPS",   helpers.is_process_running("nginx")),
        (9000, "PHP-FPM", helpers.is_process_running("php-fpm")),
        (6379, "Redis",   helpers.is_process_running("redis-server")),
    ):
        in_use = helpers.port_in_use(port)
        if ours and in_use:
            _line(True, f"port {port} ({name}) in use by us")
        elif not ours and not in_use:
            _line(True, f"port {port} ({name}) free")
        elif ours and not in_use:
            _line(False, f"port {port} ({name}) — service running but port closed",
                  "check service logs")
            fails.append((f"port {port} closed unexpectedly", "myserver logs nginx"))
        else:
            _line(False, f"port {port} ({name}) used by another process",
                  f"lsof -i :{port}")
            fails.append((f"port {port} busy", f"lsof -i :{port}"))

    # ---------- MariaDB ----------
    _section("MariaDB")
    if helpers.mariadb_is_running():
        _line(True, "MariaDB process running")
        cli = helpers.mysql_client()
        res = helpers.run_cmd_capture(
            f"{cli} -u root --socket='{paths.MARIADB_SOCKET}' -e 'SELECT 1;'",
            timeout=8)
        ok = res.returncode == 0
        _line(ok, "MariaDB root login via socket works",
              "myserver reinstall  (or check ~/.my.cnf)")
        if not ok:
            fails.append(("MariaDB root login failed", "myserver reinstall"))
    else:
        _line(False, "MariaDB not running", "myserver start")
        fails.append(("MariaDB not running", "myserver start"))

    # ---------- SSL ----------
    _section("SSL")
    info = ssl_svc.cert_info()
    if info["exists"]:
        _line(True, "certificate present "
                    f"({'self-signed' if info['self_signed'] else 'custom'})")
        if info["days_left"] is not None:
            ok = not info["expired"]
            _line(ok, f"certificate valid ({info['days_left']} days left)",
                  "rm ssl/server.* && myserver reinstall")
            if not ok:
                fails.append(("certificate expired",
                              "rm ssl/server.* && myserver reinstall"))
    else:
        _line(False, "certificate missing", "myserver reinstall")
        fails.append(("certificate missing", "myserver reinstall"))

    # ---------- Internet ----------
    _section("Internet")
    online, diag = helpers.check_internet()
    _line(online, f"internet reachable ({diag})",
          "check Wi-Fi / mobile data / DNS")
    if not online:
        fails.append(("internet unreachable", diag))

    # ---------- Services ----------
    _section("Services")
    for pat, name in (("nginx", "nginx"),
                      ("php-fpm", "php-fpm"),
                      ("redis-server", "redis"),
                      ("mariadb|mysqld", "mariadb")):
        running = helpers.is_process_running(pat)
        _line(running, f"{name} " + ("running" if running else "stopped"),
              "myserver start")
        if not running:
            fails.append((f"{name} stopped", "myserver start"))

    # ---------- Summary ----------
    print()
    total = 0
    for _ in range(1):
        pass
    # count visible items
    total = (len(("nginx", "php", "php-fpm", "mariadb", "redis-server",
                  "curl", "openssl", "tar", "unzip", "cloudflared"))
             + 1  # inotifywait
             + 13 # php extensions
             + 8  # files
             + 1  # htdocs exists
             + 2  # htdocs perms + index readable
             + 1  # ssl key
             + 4  # ports
             + (2 if helpers.mariadb_is_running() else 1)  # mariadb
             + (2 if info["exists"] and info["days_left"] is not None
                   else (1 if info["exists"] else 1))
             + 1  # internet
             + 4) # services

    if not fails:
        ui.ok(f"All checks passed ({total} items).")
    else:
        ui.warn(f"{len(fails)} issue(s) found out of {total}.")

    # ---------- Suggestions or fixes ----------
    if not fails:
        return 0

    if not fix:
        print()
        ui.info("Suggestions:")
        seen = set()
        for label, hint in fails:
            key = (label, hint)
            if key in seen:
                continue
            seen.add(key)
            print(f"  • {label}: {hint}")
        print()
        ui.info("Tip: 'myserver doctor --fix' attempts to repair common issues.")
        return 1

    # ---------- Auto-fix ----------
    print()
    ui.step("Running auto-fix...")
    rc = 0

    # 1) PHP extensions
    real_missing = [e for e in missing_php if e in
                    ("gd", "sodium", "redis", "apcu", "imagick")]
    if real_missing:
        rc |= _fix_php_extensions(real_missing)

    # 2) htdocs perms
    if any("htdocs perms" in label for label, _ in fails):
        rc |= _fix_htdocs_perms(paths.HTDOCS_DIR)

    # 3) services (only if not running)
    not_running = any("stopped" in label for label, _ in fails)
    if not_running:
        from ..cli import services_ctl
        ui.step("Starting services...")
        services_ctl.start_all(open_browser=False)

    print()
    if rc == 0:
        ui.ok("Auto-fix complete. Re-run 'myserver doctor' to verify.")
    else:
        ui.warn("Auto-fix finished with warnings. Re-run 'myserver doctor'.")
    return rc