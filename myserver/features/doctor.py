"""Diagnostic tool — checks environment, files, permissions, services."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..core import paths, helpers, ui
from ..services import ssl as ssl_svc


class Result:
    def __init__(self):
        self.items: list[tuple[bool, str, str]] = []   # (ok, label, hint)

    def add(self, ok: bool, label: str, hint: str = ""):
        self.items.append((ok, label, hint))

    def render(self):
        for ok, label, hint in self.items:
            mark = f"{ui.C_GREEN}✓{ui.C_RESET}" if ok else f"{ui.C_RED}✗{ui.C_RESET}"
            line = f"  {mark} {label}"
            if not ok and hint:
                line += f"  {ui.C_YELLOW}→ {hint}{ui.C_RESET}"
            print(line)

    def summary(self) -> int:
        fails = sum(1 for ok, _, _ in self.items if not ok)
        print()
        if fails == 0:
            ui.ok(f"All checks passed ({len(self.items)} items).")
        else:
            ui.warn(f"{fails} issue(s) found out of {len(self.items)}.")
            print()
            ui.info("Suggestions:")
            for ok, label, hint in self.items:
                if not ok and hint:
                    print(f"  • {label}: {hint}")
        return 0 if fails == 0 else 1


# ---------------------------------------------------------------------------
def run() -> int:
    r = Result()

    # ---------- packages ----------
    print(f"{ui.C_CYAN}[ Packages ]{ui.C_RESET}")
    for cmd in ("nginx", "php", "php-fpm", "mariadb", "redis-server",
                "curl", "openssl", "tar", "unzip", "cloudflared"):
        r.add(helpers.command_exists(cmd),
              f"{cmd} installed",
              f"pkg install {cmd if cmd != 'php-fpm' else 'php'}")
    r.add(helpers.command_exists("inotifywait"),
          "inotifywait installed (fast Live Reload)",
          "pkg install inotify-tools")

    # ---------- PHP extensions ----------
    print(f"\n{ui.C_CYAN}[ PHP extensions ]{ui.C_RESET}")
    loaded = helpers.php_loaded_extensions()
    for ext in ("mysqli", "pdo_mysql", "mbstring", "openssl", "curl",
                "zip", "xml", "intl", "bcmath", "gd", "sodium",
                "redis", "apcu"):
        r.add(ext in loaded, f"php-{ext} loaded",
              f"pkg install php-{ext}")

    # ---------- files ----------
    print(f"\n{ui.C_CYAN}[ Files ]{ui.C_RESET}")
    for p, label in (
        (paths.NGINX_CONF,   "nginx.conf"),
        (paths.PHP_FPM_CONF, "php-fpm www.conf"),
        (paths.MY_CNF_FILE,  "~/.my.cnf"),
        (paths.HTDOCS_PATH_FILE, "htdocs path file"),
        (paths.BIN_MYSERVER, "myserver CLI"),
        (paths.BIN_MYSERVER_LIVE, "myserver-live binary"),
        (paths.DEFAULT_CERT, "SSL certificate"),
        (paths.DEFAULT_KEY,  "SSL key"),
    ):
        r.add(p.exists(), f"{label} exists", "reinstall: myserver reinstall")
    r.add(paths.HTDOCS_DIR.exists(), f"htdocs exists ({paths.HTDOCS_DIR})",
          "create web root or run install again")

    # ---------- permissions ----------
    print(f"\n{ui.C_CYAN}[ Permissions ]{ui.C_RESET}")
    if paths.HTDOCS_DIR.exists():
        mode = paths.HTDOCS_DIR.stat().st_mode & 0o777
        r.add(mode == 0o755, f"htdocs perms = {oct(mode)} (want 0755)",
              "myserver doctor --fix  (or reinstall)")
        idx = paths.HTDOCS_DIR / "index.php"
        if idx.exists():
            r.add(os.access(idx, os.R_OK), "index.php readable",
                  "chmod 644 index.php")
    if paths.DEFAULT_KEY.exists():
        mode = paths.DEFAULT_KEY.stat().st_mode & 0o777
        r.add(mode == 0o600, f"SSL key perms = {oct(mode)} (want 0600)",
              "chmod 600 ssl/server.key")

    # ---------- ports ----------
    print(f"\n{ui.C_CYAN}[ Ports ]{ui.C_RESET}")
    for port, name, ours in (
        (8080, "HTTP",   helpers.is_process_running("nginx")),
        (8443, "HTTPS",  helpers.is_process_running("nginx")),
        (9000, "PHP-FPM", helpers.is_process_running("php-fpm")),
        (6379, "Redis",  helpers.is_process_running("redis-server")),
    ):
        in_use = helpers.port_in_use(port)
        if ours and in_use:
            r.add(True, f"port {port} ({name}) in use by us")
        elif not ours and not in_use:
            r.add(True, f"port {port} ({name}) free")
        elif ours and not in_use:
            r.add(False, f"port {port} ({name}) — service running but port closed",
                  "check service logs")
        else:
            r.add(False, f"port {port} ({name}) used by another process",
                  f"lsof -i :{port}")

    # ---------- MariaDB ----------
    print(f"\n{ui.C_CYAN}[ MariaDB ]{ui.C_RESET}")
    if helpers.mariadb_is_running():
        r.add(True, "MariaDB process running")
        cli = helpers.mysql_client()
        res = helpers.run_cmd_capture(
            f"{cli} -u root --socket='{paths.MARIADB_SOCKET}' -e 'SELECT 1;'",
            timeout=8)
        r.add(res.returncode == 0, "MariaDB root login via socket works",
              "myserver reinstall  (or check ~/.my.cnf)")
    else:
        r.add(False, "MariaDB not running",
              "myserver start")

    # ---------- SSL ----------
    print(f"\n{ui.C_CYAN}[ SSL ]{ui.C_RESET}")
    info = ssl_svc.cert_info()
    if info["exists"]:
        r.add(True, f"certificate present ({'self-signed' if info['self_signed'] else 'custom'})")
        if info["days_left"] is not None:
            r.add(not info["expired"],
                  f"certificate valid ({info['days_left']} days left)",
                  "regenerate certificate: rm ssl/server.* && myserver reinstall")
    else:
        r.add(False, "certificate missing", "myserver reinstall")

    # ---------- internet ----------
    print(f"\n{ui.C_CYAN}[ Internet ]{ui.C_RESET}")
    res = helpers.run_cmd_capture(
        'curl -s --max-time 5 -o /dev/null -w "%{http_code}" https://1.1.1.1',
        timeout=10)
    online = res.returncode == 0 and res.stdout.strip()[:1] in ("2", "3")
    r.add(online, "internet reachable", "check connection / DNS")

    # ---------- services ----------
    print(f"\n{ui.C_CYAN}[ Services ]{ui.C_RESET}")
    for pat, name in (("nginx", "nginx"),
                      ("php-fpm", "php-fpm"),
                      ("redis-server", "redis"),
                      ("mariadb|mysqld", "mariadb")):
        running = helpers.is_process_running(pat)
        r.add(running, f"{name} " + ("running" if running else "stopped"),
              "myserver start")

    print()
    return r.render() or r.summary()