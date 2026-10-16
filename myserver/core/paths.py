"""All filesystem paths used by myserver."""
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
NGINX_DIR      = PREFIX / "etc/nginx"
NGINX_CONF     = NGINX_DIR / "nginx.conf"
SSL_DIR        = NGINX_DIR / "ssl"
LIVE_CONF_FILE = NGINX_DIR / "live-reload.conf"
CUSTOM_CERT    = SSL_DIR / "custom.crt"
CUSTOM_KEY     = SSL_DIR / "custom.key"
DEFAULT_CERT   = SSL_DIR / "server.crt"
DEFAULT_KEY    = SSL_DIR / "server.key"

# --- php -----------------------------------------------------------------
PHP_FPM_DIR    = PREFIX / "etc/php-fpm.d"
PHP_FPM_CONF   = PHP_FPM_DIR / "www.conf"
PHP_CONFD_DIR  = PREFIX / "etc/php/conf.d"
PHP_LIB_DIR    = PREFIX / "lib/php"

# --- mariadb -------------------------------------------------------------
MYSQL_DATA_DIR = PREFIX / "var/lib/mysql"
MYSQL_RUN_DIR  = PREFIX / "var/run/mysqld"
MARIADB_SOCKET = MYSQL_RUN_DIR / "mysqld.sock"
MY_CNF_FILE    = HOME / ".my.cnf"

# --- misc ----------------------------------------------------------------
TMP_DIR = PREFIX / "tmp"
LOG_DIR = PREFIX / "var/log"

# --- pid files (safe-kill) ----------------------------------------------
PID_NGINX   = TMP_DIR / "myserver-nginx.pid"
PID_PHP     = TMP_DIR / "myserver-php-fpm.pid"
PID_REDIS   = TMP_DIR / "myserver-redis.pid"
PID_MARIADB = TMP_DIR / "myserver-mariadb.pid"
PID_TUNNEL  = TMP_DIR / "myserver-tunnel.pid"
PID_LIVE    = TMP_DIR / "myserver-live.pid"

# --- live reload ---------------------------------------------------------
LIVE_PORT         = 35730
LIVE_LOG_FILE     = TMP_DIR / "myserver-live.log"
LIVE_IGNORE_FILE  = ".myserver-ignore"
LIVE_MARKER_FILE  = ".livereload"
LIVE_MAX_CLIENTS  = int(os.environ.get("MYSERVER_LIVE_MAX_CLIENTS", "50"))
LIVE_IDLE_TIMEOUT = 90   # seconds

# --- tunnel --------------------------------------------------------------
TUNNEL_URL_FILE = TMP_DIR / "myserver-tunnel.url"
TUNNEL_LOG      = TMP_DIR / "myserver-tunnel.log"

# --- backups -------------------------------------------------------------
BACKUP_DIR = HOME / "storage/shared/myserver-backups"

# --- github --------------------------------------------------------------
GITHUB_REPO        = "elias0esmail/termux-web-server"
GITHUB_RAW_URL     = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main"
GITHUB_TARBALL_URL = f"https://github.com/{GITHUB_REPO}/archive/refs/heads/main.tar.gz"


# ---------------------------------------------------------------------------
# runtime resolution — call this once at CLI startup
# ---------------------------------------------------------------------------
def resolve_runtime_paths() -> None:
    """Update HTDOCS_DIR from the saved path file, if present.

    The installer writes the user's chosen web-root path to
    ``$PREFIX/etc/myserver_htdocs_path``. Every myserver entrypoint
    (CLI, menu, command dispatcher) must call this once at startup so that
    runtime code sees the same HTDOCS_DIR that the user selected during
    installation. Without this call, HTDOCS_DIR stays at its default
    (``$HOME/htdocs``) even when the user chose phone storage.
    """
    global HTDOCS_DIR
    try:
        if HTDOCS_PATH_FILE.exists():
            saved = HTDOCS_PATH_FILE.read_text().strip()
            if saved:
                HTDOCS_DIR = Path(saved)
    except Exception:
        # never crash on path resolution — keep the current default
        pass