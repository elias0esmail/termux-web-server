"""All filesystem paths and runtime constants used by myserver."""
from __future__ import annotations

import os
from pathlib import Path

PREFIX = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
HOME   = Path.home()

# --- installation --------------------------------------------------------
LIB_DIR           = PREFIX / "lib/myserver"
BIN_MYSERVER      = PREFIX / "bin/myserver"
BIN_MYSERVER_LIVE = PREFIX / "bin/myserver-live"
VERSION_FILE      = PREFIX / "etc/myserver_version"

# --- web root ------------------------------------------------------------
HTDOCS_PATH_FILE = PREFIX / "etc/myserver_htdocs_path"
HOME_HTDOCS      = HOME / "htdocs"
STORAGE_HTDOCS   = HOME / "storage/shared/htdocs"
HTDOCS_DIR       = HOME_HTDOCS   # overridden at runtime by resolve_runtime_paths()

# --- nginx ---------------------------------------------------------------
NGINX_DIR       = PREFIX / "etc/nginx"
NGINX_CONF      = NGINX_DIR / "nginx.conf"
NGINX_CONFD_DIR = NGINX_DIR / "conf.d"
SSL_DIR         = NGINX_DIR / "ssl"
LIVE_CONF_FILE  = NGINX_DIR / "live-reload.conf"
CUSTOM_CERT     = SSL_DIR / "custom.crt"
CUSTOM_KEY      = SSL_DIR / "custom.key"
DEFAULT_CERT    = SSL_DIR / "server.crt"
DEFAULT_KEY     = SSL_DIR / "server.key"

# --- php -----------------------------------------------------------------
PHP_FPM_DIR      = PREFIX / "etc/php-fpm.d"
PHP_FPM_CONF     = PHP_FPM_DIR / "www.conf"
PHP_CONFD_DIR    = PREFIX / "etc/php/conf.d"
PHP_MYSERVER_INI = PHP_CONFD_DIR / "99-myserver.ini"
PHP_LIB_DIR      = PREFIX / "lib/php"

# --- mariadb -------------------------------------------------------------
MYSQL_DATA_DIR = PREFIX / "var/lib/mysql"
MYSQL_RUN_DIR  = PREFIX / "var/run/mysqld"
MARIADB_SOCKET = MYSQL_RUN_DIR / "mysqld.sock"
MY_CNF_FILE    = HOME / ".my.cnf"

# --- redis ---------------------------------------------------------------
REDIS_CONF          = PREFIX / "etc/redis.conf"
REDIS_DISABLED_FILE = PREFIX / "etc/myserver_disable_redis"

# --- misc ----------------------------------------------------------------
TMP_DIR = PREFIX / "tmp"
LOG_DIR = PREFIX / "var/log"

# --- pid files (safe-kill & zero-subprocess status checks) ---------------
PID_NGINX   = TMP_DIR / "myserver-nginx.pid"
PID_PHP     = TMP_DIR / "myserver-php-fpm.pid"
PID_REDIS   = TMP_DIR / "myserver-redis.pid"
PID_MARIADB = TMP_DIR / "myserver-mariadb.pid"
PID_TUNNEL  = TMP_DIR / "myserver-tunnel.pid"
PID_LIVE    = TMP_DIR / "myserver-live.pid"

# --- live reload & Android process budget --------------------------------
LIVE_PORT             = 35730
LIVE_LOG_FILE         = TMP_DIR / "myserver-live.log"
LIVE_IGNORE_FILE      = ".myserver-ignore"
LIVE_MARKER_FILE      = ".livereload"
# Default capped at 10 (instead of 50) to respect Android's thread/process limits
LIVE_MAX_CLIENTS      = int(os.environ.get("MYSERVER_LIVE_MAX_CLIENTS", "10"))
LIVE_IDLE_TIMEOUT     = 90   # seconds
ANDROID_PHANTOM_LIMIT = 32   # Android 12+ default max_phantom_processes

# --- tunnel --------------------------------------------------------------
TUNNEL_URL_FILE = TMP_DIR / "myserver-tunnel.url"
TUNNEL_LOG      = TMP_DIR / "myserver-tunnel.log"

# --- backups -------------------------------------------------------------
HOME_BACKUP_DIR    = HOME / "myserver-backups"
STORAGE_BACKUP_DIR = HOME / "storage/shared/myserver-backups"
BACKUP_DIR         = HOME_BACKUP_DIR  # resolved safely by resolve_runtime_paths()

# --- github --------------------------------------------------------------
GITHUB_REPO        = "elias0esmail/termux-web-server"
GITHUB_RAW_URL     = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main"
GITHUB_TARBALL_URL = f"https://github.com/{GITHUB_REPO}/archive/refs/heads/main.tar.gz"


# ---------------------------------------------------------------------------
# runtime resolution — call this once at CLI startup
# ---------------------------------------------------------------------------
def resolve_runtime_paths() -> None:
    """Update HTDOCS_DIR and BACKUP_DIR safely at startup.

    1. Reads ``$PREFIX/etc/myserver_htdocs_path`` to set ``HTDOCS_DIR``.
    2. Checks whether ``~/storage/shared`` exists as a real mounted directory
       before using ``~/storage/shared/myserver-backups``. If Termux shared
       storage has NOT been set up yet, falls back to ``~/myserver-backups``
       so we never create an unlinked ``~/storage`` folder that breaks
       ``termux-setup-storage``.
    """
    global HTDOCS_DIR, BACKUP_DIR
    try:
        if HTDOCS_PATH_FILE.exists():
            saved = HTDOCS_PATH_FILE.read_text().strip()
            if saved:
                HTDOCS_DIR = Path(saved)
    except Exception:
        pass

    try:
        shared_root = HOME / "storage/shared"
        if shared_root.exists() and shared_root.is_dir():
            BACKUP_DIR = STORAGE_BACKUP_DIR
        else:
            BACKUP_DIR = HOME_BACKUP_DIR
    except Exception:
        BACKUP_DIR = HOME_BACKUP_DIR