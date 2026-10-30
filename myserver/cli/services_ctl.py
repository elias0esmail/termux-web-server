"""Orchestrate start/stop/restart of all services in the correct order."""
from __future__ import annotations

import time

from ..core import paths, helpers, ui
from ..services import mariadb, nginx, php, redis
from ..features import live_reload, tunnel, wake_lock


# ---------------------------------------------------------------------------
def status() -> dict[str, bool]:
    return {
        "nginx":   helpers.is_process_running("nginx", pid_file=paths.PID_NGINX),
        "php-fpm": helpers.is_process_running("php-fpm", pid_file=paths.PID_PHP),
        "mariadb": helpers.mariadb_is_running(),
        "redis":   helpers.is_process_running("redis-server", pid_file=paths.PID_REDIS),
        "live":    live_reload.is_running(),
        "tunnel":  tunnel.is_running(),
    }


def any_running() -> bool:
    s = status()
    return any(s[k] for k in ("nginx", "php-fpm", "mariadb", "redis"))


# ---------------------------------------------------------------------------
def _ensure_pma_storage():
    try:
        pma_sql = paths.HTDOCS_DIR / "phpmyadmin/sql/create_tables.sql"
        if not (paths.MARIADB_SOCKET.exists() and pma_sql.exists()):
            return
        r = helpers.run_mysql_query(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema='phpmyadmin' AND table_name LIKE 'pma\\_%';"
        )
        try:
            count = int((r.stdout or "").strip() or "0")
        except ValueError:
            count = 0
        if count > 0:
            return
        ui.info("Setting up phpMyAdmin storage...")
        helpers.run_mysql_query(
            "CREATE DATABASE IF NOT EXISTS phpmyadmin "
            "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
        )
        sql_text = pma_sql.read_text(errors="ignore")
        helpers.run_mysql_query(
            sql_text,
            database="phpmyadmin",
            batch=False,
            force=True,
            timeout=30,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
def start_all(open_browser: bool = True) -> bool:
    paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
    paths.TMP_DIR.mkdir(parents=True, exist_ok=True)

    if not paths.HTDOCS_DIR.exists():
        ui.err(f"Web root missing: {paths.HTDOCS_DIR}")
        ui.info("If this is wrong, run: myserver reinstall")
        return False

    # Fast top-level permission check (<2ms, 0 subprocesses)
    nginx.enforce_htdocs_permissions(paths.HTDOCS_DIR, deep=False)
    wake_lock.acquire()

    ui.step("Starting MariaDB...")
    if not mariadb.start_mariadb_background():
        ui.err("MariaDB failed to start.")
        return False
    _ensure_pma_storage()

    if redis.is_enabled():
        ui.step("Starting Redis...")
        redis.start()
    else:
        ui.info("Redis disabled (process-saving mode).")

    ui.step("Starting PHP-FPM...")
    php.start()

    ui.step("Starting Nginx...")
    nginx.start()

    time.sleep(0.8)
    s = status()
    if not (s["nginx"] and s["php-fpm"]):
        ui.warn("Some services did not start — run 'myserver doctor'.")
        return False

    proc_count, rss_mb = helpers.count_user_processes()
    ui.ok(f"Services started ({proc_count}/{paths.ANDROID_PHANTOM_LIMIT} Android processes, ~{rss_mb:.1f} MB RAM).")
    ui.info("Live Reload:  myserver live-start")
    ui.info("Public URL:   myserver internet-enable")

    if open_browser and helpers.command_exists("termux-open-url"):
        helpers.run_cmd(["termux-open-url", "http://localhost:8080"])
    return True


def stop_all(quiet: bool = False) -> bool:
    if not quiet:
        ui.step("Stopping all services (graceful)...")

    try:
        if tunnel.is_running():
            tunnel.disable()
    except Exception:
        pass

    try:
        if live_reload.is_running():
            live_reload.stop(quiet=True)
        else:
            paths.LIVE_CONF_FILE.write_text("")
    except Exception:
        pass

    php.stop()
    nginx.stop()
    redis.stop()
    mariadb.stop_mariadb_cleanly()

    try:
        wake_lock.release()
    except Exception:
        pass

    s = status()
    left = [k for k in ("nginx", "php-fpm", "mariadb", "redis") if s[k]]
    if not quiet:
        if not left:
            ui.ok("All services stopped.")
        else:
            ui.warn(f"Still running: {', '.join(left)}")
    return not left


def restart_all() -> bool:
    stop_all(quiet=True)
    time.sleep(0.8)
    return start_all(open_browser=False)


def tail_service_logs(which: str, lines: int = 50) -> int:
    mapping = {
        "nginx":  [paths.LOG_DIR / "nginx-access.log",
                   paths.LOG_DIR / "nginx-error.log"],
        "php":    [paths.LOG_DIR / "php-fpm.log"],
        "redis":  [paths.LOG_DIR / "redis.log"],
        "live":   [paths.LIVE_LOG_FILE],
        "tunnel": [paths.TUNNEL_LOG],
    }
    files = mapping.get(which.lower())
    if not files:
        ui.err(f"Unknown log target: {which}")
        ui.info("Try: nginx | php | redis | live | tunnel")
        return 1
    printed = False
    for f in files:
        if not f.exists():
            continue
        printed = True
        print(f"\n{ui.C_CYAN}=== {f} ==={ui.C_RESET}")
        try:
            content = f.read_text(errors="ignore").splitlines()
            for ln in content[-lines:]:
                print(ln)
        except Exception as e:
            ui.err(f"Read error: {e}")
    if not printed:
        ui.warn("No log files found yet.")
    return 0