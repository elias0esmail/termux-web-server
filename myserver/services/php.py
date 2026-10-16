from __future__ import annotations

import re
from pathlib import Path

from ..core import paths, helpers, ui


def setup_fpm() -> bool:
    try:
        paths.PHP_FPM_DIR.mkdir(parents=True, exist_ok=True)
        paths.PHP_FPM_CONF.write_text("""\
[www]
listen = 127.0.0.1:9000
listen.allowed_clients = 127.0.0.1
pm = dynamic
pm.max_children = 10
pm.start_servers = 2
pm.min_spare_servers = 1
pm.max_spare_servers = 3
pm.max_requests = 500
""")
        ui.ok("PHP-FPM configured (Port 9000, Termux-safe).")
        return True
    except Exception as e:
        ui.err(f"PHP-FPM config error: {e}")
        return False


def _clean_php_ini_legacy(ini: Path) -> int:
    if not ini.exists():
        return 0
    try:
        content = ini.read_text()
    except Exception:
        return 0
    new_content, n = re.subn(
        r"^[ \t]*extension[ \t]*=[ \t]*[^\r\n]*[\r\n]?",
        "", content, flags=re.MULTILINE)
    if n > 0:
        ini.write_text(new_content)
    return n


def create_php_ini() -> bool:
    ini = helpers.get_php_ini_path()
    paths.PHP_CONFD_DIR.mkdir(parents=True, exist_ok=True)
    paths.TMP_DIR.mkdir(parents=True, exist_ok=True)

    removed = _clean_php_ini_legacy(ini)
    if removed:
        ui.warn(f"Removed {removed} legacy 'extension=' line(s).")

    ext_dir = helpers.php_extension_dir()
    ui.info(f"PHP extension_dir = {ext_dir}")

    available = helpers.scan_available_so(ext_dir)
    if available:
        ui.info("Available .so: " + ", ".join(sorted(available)))

    loaded_before = helpers.php_loaded_extensions()

    content = f"""\
upload_max_filesize = 512M
post_max_size = 512M
memory_limit = 512M
max_execution_time = 300
error_reporting = E_ALL & ~E_DEPRECATED
display_errors = On
date.timezone = UTC

extension_dir = "{ext_dir}"
cgi.fix_pathinfo=0

mysqli.default_socket = "{paths.MARIADB_SOCKET}"
pdo_mysql.default_socket = "{paths.MARIADB_SOCKET}"

session.save_handler = files
session.save_path = "{paths.TMP_DIR}"
session.use_cookies = 1
session.use_only_cookies = 1
session.name = PHPSESSID
session.auto_start = 0
session.cookie_lifetime = 0
session.cookie_path = /
session.gc_maxlifetime = 1440
"""
    try:
        ini.parent.mkdir(parents=True, exist_ok=True)
        ini.write_text(content)
        ui.ok(f"php.ini updated at {ini}")
        ui.ok(f"MySQLi/PDO default_socket → {paths.MARIADB_SOCKET}")
    except Exception as e:
        ui.err(f"php.ini error: {e}")
        return False

    synced = []
    for ext in helpers.PHP_EXPECTED_EXTENSIONS:
        ini_file = paths.PHP_CONFD_DIR / f"{ext}.ini"
        if ext in loaded_before:
            if ini_file.exists():
                try: ini_file.unlink()
                except Exception: pass
            continue
        if ext in available:
            desired = f"extension={ext}.so\n"
            try:
                if not ini_file.exists() or ini_file.read_text() != desired:
                    ini_file.write_text(desired)
                    synced.append(ext)
            except Exception:
                pass
            continue
        if ini_file.exists():
            try: ini_file.unlink()
            except Exception: pass

    if synced:
        ui.ok("Registered via conf.d: " + ", ".join(synced))
    preview = ", ".join(sorted(loaded_before)[:15])
    suffix = "..." if len(loaded_before) > 15 else ""
    ui.ok(f"PHP loaded {len(loaded_before)} extensions: {preview}{suffix}")
    return True


def start() -> bool:
    if helpers.is_process_running("php-fpm"):
        pid = helpers.pid_from_pgrep("php-fpm")
        if pid:
            helpers.write_pid_file(paths.PID_PHP, pid)
        return True
    helpers.run_cmd("php-fpm")
    pid = helpers.pid_from_pgrep("php-fpm")
    if pid:
        helpers.write_pid_file(paths.PID_PHP, pid)
        return True
    return False


def stop() -> bool:
    return helpers.safe_stop(paths.PID_PHP, ("php-fpm",))