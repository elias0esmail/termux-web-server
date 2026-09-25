#!/data/data/com.termux/files/usr/bin/python3

import os
import sys
import time
import shutil
import re
import subprocess
import secrets
import string
from pathlib import Path

# Current Version & Release Notes
CURRENT_VERSION = "2.15.0"
CHANGELOG = [
    "Fix: Real Termux PHP 8.5 extension model (built-in vs packaged)",
    "Fix: Use `php -m` as source of truth instead of scanning .so paths",
    "Fix: Correct package names (php-sodium, php-redis, php-apcu, php-imagick)",
    "Fix: Remove non-existent packages (php-mysqli, php-curl, php-zip, php-xml, ...)",
    "Fix: Auto-detect PHP's real extension_dir via `php -r`",
    "Improvement: Cleaner install report (loaded vs optional vs missing)",
    "Improvement: sync_php_extensions now uses php -m for accuracy",
    "Security: (carried) PHP path traversal fix + phpMyAdmin AllowNoPassword OFF",
    "Fix: (carried) MariaDB stopped cleanly after installation",
    "Fix: (carried) conf.d auto-generation with stale cleanup",
]

# System and Environment Paths
PREFIX = Path(os.environ.get('PREFIX', '/data/data/com.termux/files/usr'))
HOME = Path.home()
HTDOCS_DIR = HOME / "storage/shared/htdocs"
NGINX_DIR = PREFIX / "etc/nginx"
PHP_FPM_DIR = PREFIX / "etc/php-fpm.d"
PHP_CONFD_DIR = PREFIX / "etc/php/conf.d"
PHP_LIB_DIR = PREFIX / "lib/php"
SSL_DIR = NGINX_DIR / "ssl"
TMP_DIR = PREFIX / "tmp"
VERSION_FILE = PREFIX / "etc/myserver_version"
REPO_DIR = Path(__file__).resolve().parent

GITHUB_RAW_URL = "https://raw.githubusercontent.com/elias0esmail/termux-web-server/main"

# ---------------------------------------------------------------------------
# PHP extension inventory (verified against Termux PHP 8.5.1, Dec 2025)
# ---------------------------------------------------------------------------

# Extensions we EXPECT to be available after install.
# Built-in ones are compiled INTO the main 'php' package — no .so file,
# no separate installable package.
PHP_EXPECTED_EXTENSIONS = [
    # Built-in to the main php package:
    "mysqli",
    "pdo_mysql",
    "mbstring",
    "openssl",
    "curl",
    "zip",
    "xml",
    "intl",
    "bcmath",
    # Provided by separate Termux packages (checked at runtime):
    "gd",
    "sodium",
    "redis",
    "apcu",
]

# Extensions bundled INSIDE the main php package (no .so lookup needed).
PHP_BUILTIN_EXTENSIONS = {
    "mysqli", "pdo_mysql", "mbstring", "openssl",
    "curl", "zip", "xml", "intl", "bcmath",
}

# Termux packages that ACTUALLY EXIST and provide PHP extensions.
# Source: `pkg search php` on Termux PHP 8.5.1.
PHP_EXT_PACKAGES = {
    "gd":      "php-gd",
    "sodium":  "php-sodium",
    "redis":   "php-redis",
    "apcu":    "php-apcu",
    "imagick": "php-imagick",
}


def run_cmd(cmd, check=False):
    return subprocess.run(cmd, shell=True, check=check,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def command_exists(cmd):
    return shutil.which(cmd) is not None


def is_process_running(pattern: str) -> bool:
    r = subprocess.run(f"pgrep -f '{pattern}'", shell=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


def get_php_ini_path() -> Path:
    """Detect the actual php.ini path from the php binary."""
    try:
        result = subprocess.run(["php", "--ini"], capture_output=True, text=True)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.endswith("php.ini") and line.startswith("/"):
                    return Path(line)
    except Exception:
        pass
    for candidate in [
        PREFIX / "etc/php/php.ini",
        PREFIX / "lib/php.ini",
        PREFIX / "etc/php.ini",
    ]:
        if candidate.exists():
            return candidate
    return PREFIX / "etc/php/php.ini"


def get_php_confd_dir() -> Path:
    return PHP_CONFD_DIR


# ---------------------------------------------------------------------------
# PHP introspection helpers (source of truth = the php binary itself)
# ---------------------------------------------------------------------------
def php_loaded_extensions() -> set:
    """Return the set of extensions PHP reports as loaded (lowercase)."""
    try:
        r = subprocess.run(["php", "-m"], capture_output=True,
                           text=True, timeout=15)
        if r.returncode == 0:
            return {
                ln.strip().lower()
                for ln in r.stdout.splitlines()
                if ln.strip() and not ln.strip().startswith("[")
            }
    except Exception:
        pass
    return set()


def php_extension_dir() -> Path:
    """Ask PHP itself where its extension_dir is."""
    try:
        r = subprocess.run(
            ["php", "-r", 'echo ini_get("extension_dir");'],
            capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0 and r.stdout.strip():
            return Path(r.stdout.strip())
    except Exception:
        pass
    return PHP_LIB_DIR


def php_ext_loaded(name: str) -> bool:
    """True if PHP currently reports this extension as loaded."""
    return name.lower() in php_loaded_extensions()


def php_ext_so_exists(name: str) -> bool:
    """True if a physical .so exists in PHP's real extension_dir."""
    ext_dir = php_extension_dir()
    if not ext_dir.exists():
        return False
    return (ext_dir / f"{name}.so").exists()


def php_ext_installed(name: str) -> bool:
    """An extension is 'installed' if PHP reports it OR a .so exists."""
    if php_ext_loaded(name):
        return True
    if php_ext_so_exists(name):
        return True
    return False


def clean_php_ini_legacy(ini_path: Path) -> int:
    """
    Remove legacy 'extension=...' lines from php.ini that cause PHP startup
    warnings when the corresponding .so is not present.

    Returns the number of lines removed.
    """
    if not ini_path.exists():
        return 0
    try:
        content = ini_path.read_text()
    except Exception:
        return 0

    new_content, n = re.subn(
        r"^[ \t]*extension[ \t]*=[ \t]*[^\r\n]*[\r\n]?",
        "",
        content,
        flags=re.MULTILINE,
    )
    if n > 0:
        ini_path.write_text(new_content)
    return n


# ---------------------------------------------------------------------------
# MariaDB
# ---------------------------------------------------------------------------
def setup_mariadb():
    """
    Initialize MariaDB, apply security hardening, then STOP it cleanly.
    Uses `mariadbd` directly (NOT the supervisor) so shutdown is final.
    """
    try:
        data_dir = PREFIX / "var/lib/mysql"
        run_dir = PREFIX / "var/run/mysqld"
        data_dir.mkdir(parents=True, exist_ok=True)
        run_dir.mkdir(parents=True, exist_ok=True)

        sock_path = run_dir / "mysqld.sock"
        if sock_path.exists():
            try:
                sock_path.unlink()
            except Exception:
                pass

        if not (data_dir / "mysql").exists():
            run_cmd(f"mariadb-install-db --datadir='{data_dir}'")
            print("\033[1;32m [✓] MariaDB database initialized. \033[0m")

        cmd = f"mariadbd --datadir='{data_dir}' --socket='{sock_path}'"
        subprocess.Popen(cmd, shell=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        for _ in range(15):
            if sock_path.exists():
                break
            time.sleep(1)

        if sock_path.exists():
            sec_sql = (
                "DELETE FROM mysql.user WHERE User='';"
                "DELETE FROM mysql.user WHERE User='root' AND Host NOT IN "
                "('localhost', '127.0.0.1', '::1');"
                "DROP DATABASE IF EXISTS test;"
                "DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%';"
                "FLUSH PRIVILEGES;"
            )
            run_cmd(f"mysql -u root --socket='{sock_path}' -e \"{sec_sql}\"")
            print("\033[1;32m [✓] MariaDB Security Hardening applied. \033[0m")

        run_cmd(f"mysqladmin --socket='{sock_path}' shutdown")
        time.sleep(2)

        # Kill supervisors FIRST (otherwise they respawn mariadbd)
        for pattern in ("mariadbd-safe", "mysqld_safe"):
            run_cmd(f"pkill -TERM -f '{pattern}'")
        time.sleep(1)
        for pattern in ("mariadbd-safe", "mysqld_safe", "mariadbd", "mysqld"):
            run_cmd(f"pkill -TERM -f '{pattern}'")
        time.sleep(1)
        for pattern in ("mariadbd-safe", "mysqld_safe", "mariadbd", "mysqld"):
            run_cmd(f"pkill -KILL -f '{pattern}'")

        if is_process_running("mariadbd") or is_process_running("mysqld"):
            print("\033[1;33m [!] Warning: MariaDB still running after shutdown.\033[0m")
        else:
            print("\033[1;32m [✓] MariaDB stopped cleanly (no supervisors left). \033[0m")

        return True
    except Exception as e:
        print(f"\033[1;31m [!] MariaDB init error: {e}\033[0m")
        return False


# ---------------------------------------------------------------------------
# Redis
# ---------------------------------------------------------------------------
def setup_redis():
    try:
        redis_data = PREFIX / "var/lib/redis"
        log_dir = PREFIX / "var/log"
        redis_data.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)

        redis_conf = PREFIX / "etc/redis.conf"
        content = (
            f"dir {redis_data}\n"
            "port 6379\n"
            "bind 127.0.0.1\n"
            "daemonize yes\n"
            f"logfile {log_dir}/redis.log\n"
            "ignore-warnings ARM64-COW-BUG\n"
        )
        redis_conf.write_text(content)
        print("\033[1;32m [✓] Redis configured (ARM64 warning suppressed). \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] Redis init error: {e}\033[0m")
        return False


# ---------------------------------------------------------------------------
# PHP-FPM
# ---------------------------------------------------------------------------
def setup_php_fpm():
    try:
        PHP_FPM_DIR.mkdir(parents=True, exist_ok=True)
        www_conf = PHP_FPM_DIR / "www.conf"

        conf_content = """\
[www]
listen = 127.0.0.1:9000
listen.allowed_clients = 127.0.0.1
pm = dynamic
pm.max_children = 10
pm.start_servers = 2
pm.min_spare_servers = 1
pm.max_spare_servers = 3
pm.max_requests = 500
"""
        www_conf.write_text(conf_content)
        print("\033[1;32m [✓] PHP-FPM configured (Port 9000, Termux-safe). \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] PHP-FPM config error: {e}\033[0m")
        return False


# ---------------------------------------------------------------------------
# SSL
# ---------------------------------------------------------------------------
def setup_ssl():
    try:
        SSL_DIR.mkdir(parents=True, exist_ok=True)
        cert_path = SSL_DIR / "server.crt"
        key_path = SSL_DIR / "server.key"

        if cert_path.exists() and key_path.exists():
            try:
                os.chmod(key_path, 0o600)
            except Exception:
                pass
            return True

        openssl_cnf = SSL_DIR / "openssl.cnf"
        openssl_cnf.write_text("""\
[req]
distinguished_name = req_distinguished_name
x509_extensions = v3_req
prompt = no
default_bits = 2048

[req_distinguished_name]
C = US
ST = Dev
L = Local
O = TermuxServer
CN = localhost

[v3_req]
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
IP.1 = 127.0.0.1
IP.2 = ::1
""")
        run_cmd(f"openssl req -x509 -nodes -days 365 -newkey rsa:2048 "
                f"-keyout '{key_path}' -out '{cert_path}' -config '{openssl_cnf}'")

        try:
            os.chmod(key_path, 0o600)
            os.chmod(SSL_DIR, 0o700)
        except Exception:
            pass

        print("\033[1;32m [✓] Enhanced SSL Certificates generated (key chmod 600). \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] SSL generation error: {e}\033[0m")
        return False


# ---------------------------------------------------------------------------
# Nginx
# ---------------------------------------------------------------------------
def setup_nginx():
    try:
        conf_path = NGINX_DIR / "nginx.conf"
        cert_path = SSL_DIR / "server.crt"
        key_path = SSL_DIR / "server.key"

        nginx_config = f"""\
worker_processes 2;
events {{ worker_connections 1024; }}

http {{
    include mime.types;
    default_type application/octet-stream;
    sendfile on;
    keepalive_timeout 65;

    access_log {PREFIX}/var/log/nginx-access.log;
    error_log  {PREFIX}/var/log/nginx-error.log;

    gzip on;
    gzip_comp_level 5;
    gzip_min_length 256;
    gzip_vary on;
    gzip_types
        text/plain text/css text/xml text/javascript
        application/javascript application/json application/xml
        application/xml+rss application/x-font-ttf font/opentype
        image/svg+xml;

    limit_req_zone $binary_remote_addr zone=pma_zone:10m rate=10r/m;

    upstream php_fpm {{
        server 127.0.0.1:9000;
    }}

    server {{
        listen 8080;
        listen [::]:8080;
        server_name localhost;
        root {HTDOCS_DIR};
        index index.php index.html index.htm;

        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;

        location / {{
            try_files $uri $uri/ /index.php?$args;
        }}

        location ~ ^/laravel/ {{
            try_files $uri $uri/ /laravel/public/index.php?$query_string;
        }}

        location ~ ^/nextcloud/ {{
            try_files $uri $uri/ /nextcloud/index.php$request_uri;
        }}

        location ~ ^/phpmyadmin/.*\\.php$ {{
            limit_req zone=pma_zone burst=5 nodelay;
            try_files $uri =404;
            fastcgi_pass php_fpm;
            fastcgi_index index.php;
            include fastcgi_params;
            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
            fastcgi_param PATH_INFO $fastcgi_path_info;
            fastcgi_param PATH_TRANSLATED $document_root$fastcgi_path_info;
            fastcgi_read_timeout 300;
        }}

        location ~ \\.php$ {{
            try_files $uri =404;
            fastcgi_pass php_fpm;
            fastcgi_index index.php;
            include fastcgi_params;
            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
            fastcgi_param PATH_INFO $fastcgi_path_info;
            fastcgi_param PATH_TRANSLATED $document_root$fastcgi_path_info;
            fastcgi_read_timeout 300;
        }}

        location ~ /\\. {{
            deny all;
        }}
    }}

    server {{
        listen 8443 ssl;
        listen [::]:8443 ssl;
        server_name localhost;

        ssl_certificate "{cert_path}";
        ssl_certificate_key "{key_path}";
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;
        ssl_prefer_server_ciphers on;

        root {HTDOCS_DIR};
        index index.php index.html index.htm;

        add_header Strict-Transport-Security "max-age=31536000" always;
        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;

        location / {{
            try_files $uri $uri/ /index.php?$args;
        }}

        location ~ ^/laravel/ {{
            try_files $uri $uri/ /laravel/public/index.php?$query_string;
        }}

        location ~ ^/nextcloud/ {{
            try_files $uri $uri/ /nextcloud/index.php$request_uri;
        }}

        location ~ ^/phpmyadmin/.*\\.php$ {{
            limit_req zone=pma_zone burst=5 nodelay;
            try_files $uri =404;
            fastcgi_pass php_fpm;
            fastcgi_index index.php;
            include fastcgi_params;
            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
            fastcgi_param PATH_INFO $fastcgi_path_info;
            fastcgi_param PATH_TRANSLATED $document_root$fastcgi_path_info;
            fastcgi_read_timeout 300;
        }}

        location ~ \\.php$ {{
            try_files $uri =404;
            fastcgi_pass php_fpm;
            fastcgi_index index.php;
            include fastcgi_params;
            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
            fastcgi_param PATH_INFO $fastcgi_path_info;
            fastcgi_param PATH_TRANSLATED $document_root$fastcgi_path_info;
            fastcgi_read_timeout 300;
        }}

        location ~ /\\. {{
            deny all;
        }}
    }}
}}
"""
        conf_path.write_text(nginx_config)

        (PREFIX / "var/log").mkdir(parents=True, exist_ok=True)
        print("\033[1;32m [✓] Nginx configured (security headers, rate limiting, gzip). \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] Nginx config error: {e}\033[0m")
        return False


# ---------------------------------------------------------------------------
# php.ini  +  conf.d management (source of truth = `php -m`)
# ---------------------------------------------------------------------------
def create_php_ini():
    """
    Write php.ini and keep conf.d/*.ini in sync with reality.

    Uses `php -m` as the source of truth (NOT .so scanning) because many
    extensions are compiled INTO the php binary in Termux and have no .so.
    """
    php_ini_path = get_php_ini_path()
    PHP_CONFD_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    # --- 1. Clean legacy 'extension=' lines ---
    removed = clean_php_ini_legacy(php_ini_path)
    if removed:
        print(f"\033[1;33m [*] Removed {removed} legacy 'extension=' line(s) from php.ini \033[0m")

    # --- 2. Discover PHP's real extension_dir ---
    ext_dir = php_extension_dir()
    print(f"\033[1;36m [i] PHP extension_dir = {ext_dir} \033[0m")

    # --- 3. Write fresh php.ini ---
    php_ini_content = f"""\
upload_max_filesize = 512M
post_max_size = 512M
memory_limit = 512M
max_execution_time = 300
error_reporting = E_ALL & ~E_DEPRECATED
display_errors = On
date.timezone = UTC

; --- Extensions ---
extension_dir = "{ext_dir}"
; NOTE: Do NOT add `extension=` lines here. conf.d/*.ini handles them.

; Security: prevent path traversal in FPM
cgi.fix_pathinfo=0

; Session settings
session.save_handler = files
session.save_path = "{TMP_DIR}"
session.use_cookies = 1
session.use_only_cookies = 1
session.name = PHPSESSID
session.auto_start = 0
session.cookie_lifetime = 0
session.cookie_path = /
session.gc_maxlifetime = 1440
"""
    try:
        php_ini_path.parent.mkdir(parents=True, exist_ok=True)
        php_ini_path.write_text(php_ini_content)
        print(f"\033[1;32m [✓] php.ini updated at {php_ini_path}. \033[0m")
    except Exception as e:
        print(f"\033[1;31m [!] php.ini error: {e}\033[0m")
        return False

    # --- 4. Sync conf.d for external .so extensions only ---
    loaded = php_loaded_extensions()
    synced_so = []
    for ext in PHP_EXPECTED_EXTENSIONS:
        # Skip built-ins already loaded (no .so needed)
        if ext in PHP_BUILTIN_EXTENSIONS and ext in loaded:
            continue

        ini_file = PHP_CONFD_DIR / f"{ext}.ini"

        if ext in loaded:
            # Already loaded (php auto-registered it) → no conf.d needed
            if ini_file.exists():
                try:
                    ini_file.unlink()
                except Exception:
                    pass
            continue

        if php_ext_so_exists(ext):
            desired = f"extension={ext}.so\n"
            try:
                if not ini_file.exists() or ini_file.read_text() != desired:
                    ini_file.write_text(desired)
                    synced_so.append(ext)
            except Exception:
                pass
        else:
            # No .so → remove any stale conf.d
            try:
                if ini_file.exists():
                    ini_file.unlink()
            except Exception:
                pass

    if synced_so:
        print(f"\033[1;32m [✓] Registered via conf.d: {', '.join(synced_so)} \033[0m")

    # --- 5. Report loaded extensions ---
    loaded_sorted = sorted(loaded)
    preview = ", ".join(loaded_sorted[:15])
    suffix = "..." if len(loaded_sorted) > 15 else ""
    print(f"\033[1;32m [✓] PHP loaded extensions: {preview}{suffix} \033[0m")

    # --- 6. Report only REAL missing packages (that actually exist in repos) ---
    missing_pkgs = []
    for ext, pkg in sorted(PHP_EXT_PACKAGES.items()):
        if ext not in loaded and not php_ext_so_exists(ext):
            missing_pkgs.append(pkg)

    if missing_pkgs:
        print(f"\033[1;33m [!] Optional packages not installed: {', '.join(missing_pkgs)} \033[0m")
        print(f"\033[1;33m     To install: pkg install {' '.join(missing_pkgs)} \033[0m")
    else:
        print("\033[1;32m [✓] All available PHP extension packages are installed. \033[0m")

    return True


# ---------------------------------------------------------------------------
# htdocs
# ---------------------------------------------------------------------------
def setup_htdocs():
    try:
        HTDOCS_DIR.mkdir(parents=True, exist_ok=True)
        (HTDOCS_DIR / "index.php").write_text(
            "<?php echo '<h1>Nginx + PHP-FPM Server is Running!</h1>'; ?>"
        )

        info_dir = HTDOCS_DIR / "phpinfo"
        info_dir.mkdir(exist_ok=True)
        (info_dir / "index.php").write_text("<?php phpinfo(); ?>")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] htdocs error: {e}\033[0m")
        return False


# ---------------------------------------------------------------------------
# phpMyAdmin
# ---------------------------------------------------------------------------
def install_phpmyadmin():
    pma_dir = HTDOCS_DIR / "phpmyadmin"
    is_update = pma_dir.exists()

    try:
        if is_update:
            print("\033[1;34m [*] Checking and updating phpMyAdmin... \033[0m")
        else:
            print("\033[1;34m [*] Downloading and installing phpMyAdmin... \033[0m")

        TMP_DIR.mkdir(parents=True, exist_ok=True)
        tar_file = TMP_DIR / "pma.tar.gz"
        url = "https://www.phpmyadmin.net/downloads/phpMyAdmin-latest-all-languages.tar.gz"

        run_cmd(f"curl -sL '{url}' -o '{tar_file}'")
        if not tar_file.exists() or tar_file.stat().st_size == 0:
            print("\033[1;31m [!] Failed to download phpMyAdmin. \033[0m")
            return False

        config_file = pma_dir / "config.inc.php"
        saved_config = None
        if is_update and config_file.exists():
            saved_config = config_file.read_text()

        pma_dir.mkdir(parents=True, exist_ok=True)
        run_cmd(f"tar -xf '{tar_file}' -C '{pma_dir}' --strip-components=1")
        if tar_file.exists():
            tar_file.unlink()

        config_sample = pma_dir / "config.sample.inc.php"

        if saved_config:
            config_file.write_text(saved_config)
        elif config_sample.exists():
            secret = secrets.token_hex(16)
            content = config_sample.read_text()
            content = re.sub(
                r"\$cfg\['blowfish_secret'\]\s*=\s*'';|\$cfg\['blowfish_secret'\]\s*=\s*\".*\";",
                f"$cfg['blowfish_secret'] = '{secret}';",
                content,
            )
            content = re.sub(
                r"\$cfg\['Servers'\]\[\$i\]\['AllowNoPassword'\]\s*=\s*true;",
                "$cfg['Servers'][$i]['AllowNoPassword'] = false;",
                content,
            )
            if "AllowNoPassword" not in content:
                content += "\n$cfg['Servers'][$i]['AllowNoPassword'] = false;\n"

            content = re.sub(
                r"\$cfg\['Servers'\]\[\$i\]\['host'\]\s*=\s*'localhost';",
                "$cfg['Servers'][$i]['host'] = '127.0.0.1';",
                content,
            )

            pma_tmp = pma_dir / "tmp"
            pma_tmp.mkdir(exist_ok=True)
            content += f"\n$cfg['TempDir'] = '{pma_tmp}';\n"

            config_file.write_text(content)

        pma_tmp = pma_dir / "tmp"
        pma_tmp.mkdir(exist_ok=True)

        if is_update:
            print("\033[1;32m [✓] phpMyAdmin updated successfully. \033[0m")
        else:
            print("\033[1;32m [✓] phpMyAdmin installed (AllowNoPassword=OFF). \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] phpMyAdmin error: {e}\033[0m")
        return False


# ---------------------------------------------------------------------------
# myserver CLI (bash)
# ---------------------------------------------------------------------------
def create_myserver_cli():
    bin_path = PREFIX / "bin/myserver"
    VERSION_FILE.write_text(CURRENT_VERSION)

    script_content = rf"""#!/data/data/com.termux/files/usr/bin/bash

PREFIX="{PREFIX}"
HTDOCS_DIR="{HTDOCS_DIR}"
VERSION_FILE="{VERSION_FILE}"
GITHUB_RAW_URL="{GITHUB_RAW_URL}"
PHP_CONFD_DIR="{PHP_CONFD_DIR}"
PHP_LIB_DIR="{PHP_LIB_DIR}"
TUNNEL_PID_FILE="$PREFIX/tmp/cloudflared.pid"
TUNNEL_URL_FILE="$PREFIX/tmp/cloudflared.url"
TUNNEL_LOG="$PREFIX/tmp/cloudflared.log"
MARIADB_SOCKET="$PREFIX/var/run/mysqld/mysqld.sock"

is_tunnel_running() {{
    if [ -f "$TUNNEL_PID_FILE" ]; then
        TPID=$(cat "$TUNNEL_PID_FILE" 2>/dev/null)
        if [ -n "$TPID" ] && kill -0 "$TPID" 2>/dev/null; then
            return 0
        fi
    fi
    if pgrep -f "cloudflared tunnel" > /dev/null; then
        return 0
    fi
    return 1
}}

get_tunnel_url() {{
    if [ -f "$TUNNEL_URL_FILE" ]; then
        cat "$TUNNEL_URL_FILE" 2>/dev/null
    fi
}}

has_internet() {{
    if curl -s --max-time 5 -o /dev/null -w "%{{http_code}}" https://1.1.1.1 2>/dev/null | grep -qE '^[23]'; then
        return 0
    fi
    if curl -s --max-time 5 -o /dev/null https://www.google.com 2>/dev/null; then
        return 0
    fi
    return 1
}}

sync_php_extensions() {{
    # Source of truth = php -m (many extensions are built into php in Termux).
    local ext_dir
    ext_dir=$(php -r 'echo ini_get("extension_dir");' 2>/dev/null)
    [ -z "$ext_dir" ] && ext_dir="$PHP_LIB_DIR"
    mkdir -p "$ext_dir" "$PHP_CONFD_DIR" 2>/dev/null

    local loaded
    loaded=$(php -m 2>/dev/null | tr 'A-Z' 'a-z')

    for ext in gd sodium redis apcu imagick; do
        if echo "$loaded" | grep -qx "$ext"; then
            # Already loaded → clean any leftover conf.d
            rm -f "$PHP_CONFD_DIR/$ext.ini"
            continue
        fi
        if [ -f "$ext_dir/$ext.so" ]; then
            echo "extension=$ext.so" > "$PHP_CONFD_DIR/$ext.ini"
        else
            rm -f "$PHP_CONFD_DIR/$ext.ini"
        fi
    done
}}

show_banner_and_status() {{
    clear
    echo -e "\033[1;36m"
    echo "  __  __       _____                                "
    echo " |  \/  |     / ____|                               "
    echo " | \  / |0_ _| (___   ___  _ __ __   _____ _ __     "
    echo " | |\/| | | | |\___ \ / _ \| '__|\ \ / / _ \ '__|    "
    echo " | |  | | |_| |____) |  __/| |    \ V /  __/ |       "
    echo " |_|  |_|\__, |_____/ \___||_|     \_/ \___|_|       "
    echo "          __/ |                                     "
    echo "         |___/        Server Manager v{CURRENT_VERSION}  "
    echo -e "\033[0m"

    echo -e "\033[1;33m============= [ DEVELOPER INFO ] ==============\033[0m"
    echo -e " Developer : \033[1;32mElias Esmail\033[0m"
    echo -e " WhatsApp  : \033[1;32m+967771902342\033[0m"
    echo -e " GitHub    : \033[1;36mhttps://github.com/elias0esmail\033[0m"
    echo -e "\033[1;33m================================================\033[0m\n"

    echo -e "\033[1;35m============= [ SERVICES STATUS ] =============\033[0m"
    pgrep -f nginx > /dev/null && echo -e " Nginx:    \033[1;32mRunning [OK]\033[0m" || echo -e " Nginx:    \033[1;31mStopped [X]\033[0m"
    pgrep -f php-fpm > /dev/null && echo -e " PHP-FPM:  \033[1;32mRunning [OK]\033[0m" || echo -e " PHP-FPM:  \033[1;31mStopped [X]\033[0m"
    pgrep -f "mariadb|mysqld" > /dev/null && echo -e " MariaDB:  \033[1;32mRunning [OK]\033[0m" || echo -e " MariaDB:  \033[1;31mStopped [X]\033[0m"
    pgrep -f redis-server > /dev/null && echo -e " Redis:    \033[1;32mRunning [OK]\033[0m" || echo -e " Redis:    \033[1;31mStopped [X]\033[0m"
    if is_tunnel_running; then
        echo -e " Tunnel:   \033[1;32mRunning [OK]\033[0m"
    else
        echo -e " Tunnel:   \033[1;31mStopped [X]\033[0m"
    fi
    echo -e "\033[1;35m===============================================\033[0m\n"

    SVC_INFO=0
    if pgrep -f nginx > /dev/null || pgrep -f php-fpm > /dev/null || pgrep -f "mariadb|mysqld" > /dev/null || pgrep -f redis-server > /dev/null; then
        SVC_INFO=1
    fi

    TUNNEL_URL_VAL=$(get_tunnel_url)
    TUNNEL_ACTIVE=0
    if is_tunnel_running && [ -n "$TUNNEL_URL_VAL" ]; then
        TUNNEL_ACTIVE=1
    fi

    if [ "$SVC_INFO" -eq 1 ] || [ "$TUNNEL_ACTIVE" -eq 1 ]; then
        echo -e "\033[1;36m============= [ SERVER INFORMATION ] =============\033[0m"
        echo -e " Web Root Path : \033[1;33m$HTDOCS_DIR\033[0m"
        echo -e " HTTP URL      : \033[1;34mhttp://localhost:8080\033[0m"
        echo -e " HTTPS URL     : \033[1;32mhttps://localhost:8443\033[0m"
        echo -e " phpMyAdmin    : \033[1;35mhttp://localhost:8080/phpmyadmin\033[0m"
        if [ "$TUNNEL_ACTIVE" -eq 1 ]; then
            echo -e " Global URL    : \033[1;32m$TUNNEL_URL_VAL\033[0m"
        else
            echo -e " Global URL    : \033[1;31mInactive\033[0m"
        fi
        echo -e "\033[1;36m==================================================\033[0m\n"
    fi
}}

start_services() {{
    sync_php_extensions

    echo -e "\033[1;34m[+] Starting MariaDB...\033[0m"
    mkdir -p "$PREFIX/var/lib/mysql" "$PREFIX/var/run/mysqld"
    if ! pgrep -f "mariadb|mysqld" > /dev/null; then
        [ -S "$MARIADB_SOCKET" ] && rm -f "$MARIADB_SOCKET"
        if [ ! -d "$PREFIX/var/lib/mysql/mysql" ]; then
            mariadb-install-db --datadir="$PREFIX/var/lib/mysql" > /dev/null 2>&1
        fi
        if command -v mariadbd-safe &> /dev/null; then
            mariadbd-safe --datadir="$PREFIX/var/lib/mysql" --socket="$MARIADB_SOCKET" > /dev/null 2>&1 &
        elif command -v mysqld_safe &> /dev/null; then
            mysqld_safe --datadir="$PREFIX/var/lib/mysql" --socket="$MARIADB_SOCKET" > /dev/null 2>&1 &
        else
            mariadbd --datadir="$PREFIX/var/lib/mysql" --socket="$MARIADB_SOCKET" > /dev/null 2>&1 &
        fi

        echo -e "\033[1;33m[*] Waiting for MariaDB socket...\033[0m"
        i=0
        while [ $i -lt 15 ]; do
            [ -S "$MARIADB_SOCKET" ] && break
            sleep 1
            i=$((i+1))
        done
    fi

    echo -e "\033[1;34m[+] Starting Redis...\033[0m"
    mkdir -p "$PREFIX/var/lib/redis" "$PREFIX/var/log"
    if ! pgrep -f redis-server > /dev/null; then
        if [ -f "$PREFIX/etc/redis.conf" ]; then
            grep -q "ignore-warnings ARM64-COW-BUG" "$PREFIX/etc/redis.conf" || \
                echo "ignore-warnings ARM64-COW-BUG" >> "$PREFIX/etc/redis.conf"
            redis-server "$PREFIX/etc/redis.conf" > /dev/null 2>&1
        else
            redis-server --daemonize yes --ignore-warnings ARM64-COW-BUG > /dev/null 2>&1
        fi
    fi

    echo -e "\033[1;34m[+] Starting PHP-FPM...\033[0m"
    if ! pgrep -f php-fpm > /dev/null; then
        php-fpm > /dev/null 2>&1
    fi

    echo -e "\033[1;34m[+] Starting Nginx...\033[0m"
    if ! pgrep -f nginx > /dev/null; then
        nginx > /dev/null 2>&1
    fi

    sleep 1.5
    echo -e "\033[1;32m[OK] Services started successfully.\033[0m"

    echo -e "\033[1;33m[*] Launching HTTPS URL in browser...\033[0m"
    if command -v termux-open &> /dev/null; then
        termux-open https://localhost:8443
    elif command -v xdg-open &> /dev/null; then
        xdg-open https://localhost:8443
    fi
    sleep 1.5
}}

stop_services() {{
    if is_tunnel_running; then
        echo -e "\033[1;33m[*] Stopping internet tunnel...\033[0m"
        disable_internet
    fi
    echo -e "\033[1;33m[*] Stopping all services (graceful)...\033[0m"

    if [ -S "$MARIADB_SOCKET" ]; then
        mysqladmin --socket="$MARIADB_SOCKET" shutdown 2>/dev/null
        sleep 2
    fi
    # Supervisors FIRST (otherwise they restart mariadbd right away)
    pkill -TERM -f "mariadbd-safe" > /dev/null 2>&1
    pkill -TERM -f "mysqld_safe"   > /dev/null 2>&1
    sleep 1
    pkill -TERM -f "mariadbd|mysqld" > /dev/null 2>&1
    sleep 1
    pkill -KILL -f "mariadbd|mysqld" > /dev/null 2>&1

    pkill -f nginx > /dev/null 2>&1
    pkill -f php-fpm > /dev/null 2>&1
    pkill -f redis-server > /dev/null 2>&1

    echo -e "\033[1;31m[OK] All services stopped safely.\033[0m"
    sleep 1
}}

restart_services() {{
    stop_services
    sleep 1
    start_services
}}

enable_internet() {{
    if ! pgrep -f nginx > /dev/null && ! pgrep -f php-fpm > /dev/null && ! pgrep -f "mariadb|mysqld" > /dev/null && ! pgrep -f redis-server > /dev/null; then
        echo -e "\033[1;31m[!] Server is not running. Please start the server first.\033[0m"
        sleep 2
        return
    fi

    if is_tunnel_running; then
        echo -e "\033[1;33m[i] Internet tunnel is already running.\033[0m"
        sleep 1.5
        return
    fi

    if ! has_internet; then
        echo -e "\033[1;31m[!] No internet connection.\033[0m"
        sleep 2
        return
    fi

    echo -e "\033[1;34m[*] Starting Cloudflare tunnel...\033[0m"
    rm -f "$TUNNEL_PID_FILE" "$TUNNEL_URL_FILE" "$TUNNEL_LOG"
    cloudflared tunnel --url http://localhost:8080 > "$TUNNEL_LOG" 2>&1 &
    echo $! > "$TUNNEL_PID_FILE"

    echo -e "\033[1;33m[*] Waiting for the public URL...\033[0m"
    FOUND_URL=""
    i=0
    while [ $i -lt 30 ]; do
        sleep 1
        i=$((i+1))
        FOUND_URL=$(grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -n 1)
        [ -n "$FOUND_URL" ] && break
    done

    if [ -n "$FOUND_URL" ]; then
        echo "$FOUND_URL" > "$TUNNEL_URL_FILE"
        echo -e "\033[1;32m[OK] Global URL: $FOUND_URL\033[0m"
    else
        echo -e "\033[1;31m[!] Failed to obtain the tunnel URL. Stopping tunnel.\033[0m"
        disable_internet
    fi
    sleep 2
}}

disable_internet() {{
    if ! is_tunnel_running; then
        echo -e "\033[1;33m[i] Internet tunnel is already disabled.\033[0m"
        sleep 1
        return
    fi

    echo -e "\033[1;33m[*] Stopping Cloudflare tunnel...\033[0m"
    if [ -f "$TUNNEL_PID_FILE" ]; then
        TPID=$(cat "$TUNNEL_PID_FILE" 2>/dev/null)
        if [ -n "$TPID" ]; then
            kill "$TPID" 2>/dev/null
            sleep 1
            kill -9 "$TPID" 2>/dev/null
        fi
    fi
    pkill -f "cloudflared tunnel" > /dev/null 2>&1
    rm -f "$TUNNEL_PID_FILE" "$TUNNEL_URL_FILE" "$TUNNEL_LOG"
    echo -e "\033[1;31m[OK] Internet tunnel disabled.\033[0m"
    sleep 1
}}

quickstart_menu() {{
    echo -e "\033[1;35m============================================\033[0m"
    echo -e "\033[1;35m      QUICKSTART FRAMEWORK INSTALLER        \033[0m"
    echo -e "\033[1;35m============================================\033[0m"
    echo " 1) Install WordPress"
    echo " 2) Install Laravel Skeleton"
    echo " 3) Install Nextcloud"
    echo " 4) Back to main menu"
    echo ""
    read -p $'\033[1;33mSelect framework [1-4]: \033[0m' q_choice

    case "$q_choice" in
        1) install_wordpress ;;
        2) install_laravel ;;
        3) install_nextcloud ;;
        *) return ;;
    esac
}}

install_wordpress() {{
    echo -e "\033[1;34m[*] Preparing WordPress installation...\033[0m"
    WP_DIR="$HTDOCS_DIR/wordpress"
    if [ -d "$WP_DIR" ]; then
        echo -e "\033[1;31m[!] Folder $WP_DIR already exists.\033[0m"
        read -p "Press Enter to return..."
        return
    fi

    echo -e "\033[1;33m[*] Downloading latest WordPress...\033[0m"
    mkdir -p "$PREFIX/tmp"
    WP_TAR="$PREFIX/tmp/wordpress.tar.gz"
    curl -sL https://wordpress.org/latest.tar.gz -o "$WP_TAR"

    if [ ! -s "$WP_TAR" ]; then
        echo -e "\033[1;31m[!] Download failed.\033[0m"
        rm -f "$WP_TAR"
        read -p "Press Enter to return..."
        return
    fi

    tar -xf "$WP_TAR" -C "$HTDOCS_DIR"
    rm -f "$WP_TAR"

    if pgrep -f "mariadb|mysqld" > /dev/null && [ -S "$MARIADB_SOCKET" ]; then
        echo -e "\033[1;34m[*] Creating MariaDB database 'wordpress'...\033[0m"
        mysql -u root --socket="$MARIADB_SOCKET" -e "CREATE DATABASE IF NOT EXISTS wordpress DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" 2>/dev/null
    fi

    echo -e "\033[1;32m[✓] WordPress installed!\033[0m"
    echo -e " URL      : \033[1;34mhttp://localhost:8080/wordpress\033[0m"
    echo -e " Database : \033[1;33mwordpress\033[0m (User: root, Pass: [empty])"
    echo ""
    read -p "Press Enter to continue..."
}}

install_laravel() {{
    echo -e "\033[1;34m[*] Preparing Laravel...\033[0m"

    if ! command -v composer &> /dev/null; then
        echo -e "\033[1;33m[*] Installing Composer...\033[0m"
        pkg install composer -y
    fi

    read -p "Enter project folder name [default: laravel]: " PROJECT_NAME
    PROJECT_NAME=${{PROJECT_NAME:-laravel}}
    LARAVEL_DIR="$HTDOCS_DIR/$PROJECT_NAME"

    if [ -d "$LARAVEL_DIR" ]; then
        echo -e "\033[1;31m[!] Folder exists.\033[0m"
        read -p "Press Enter to return..."
        return
    fi

    composer create-project --prefer-dist laravel/laravel "$LARAVEL_DIR"

    DB_NAME=$(echo "$PROJECT_NAME" | tr '-' '_')
    if pgrep -f "mariadb|mysqld" > /dev/null && [ -S "$MARIADB_SOCKET" ]; then
        mysql -u root --socket="$MARIADB_SOCKET" -e "CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" 2>/dev/null
    fi

    echo -e "\033[1;32m[✓] Laravel installed!\033[0m"
    echo -e " URL      : \033[1;34mhttp://localhost:8080/$PROJECT_NAME/public\033[0m"
    echo -e " Database : \033[1;33m$DB_NAME\033[0m"
    echo ""
    read -p "Press Enter to continue..."
}}

install_nextcloud() {{
    echo -e "\033[1;34m[*] Preparing Nextcloud...\033[0m"
    NC_DIR="$HTDOCS_DIR/nextcloud"
    if [ -d "$NC_DIR" ]; then
        echo -e "\033[1;31m[!] Folder exists.\033[0m"
        read -p "Press Enter to return..."
        return
    fi

    echo -e "\033[1;33m[*] Downloading Nextcloud...\033[0m"
    mkdir -p "$PREFIX/tmp"
    NC_ZIP="$PREFIX/tmp/nextcloud.zip"
    curl -sL https://download.nextcloud.com/server/releases/latest.zip -o "$NC_ZIP"

    if [ ! -s "$NC_ZIP" ]; then
        echo -e "\033[1;31m[!] Download failed.\033[0m"
        rm -f "$NC_ZIP"
        read -p "Press Enter to return..."
        return
    fi

    unzip -q "$NC_ZIP" -d "$HTDOCS_DIR"
    rm -f "$NC_ZIP"

    NC_DB_PASS=$(head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 20)
    NC_DB_USER="ncuser"

    if pgrep -f "mariadb|mysqld" > /dev/null && [ -S "$MARIADB_SOCKET" ]; then
        echo -e "\033[1;34m[*] Creating dedicated MariaDB user + database...\033[0m"
        mysql -u root --socket="$MARIADB_SOCKET" <<SQL 2>/dev/null
CREATE DATABASE IF NOT EXISTS nextcloud DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$NC_DB_USER'@'127.0.0.1' IDENTIFIED BY '$NC_DB_PASS';
CREATE USER IF NOT EXISTS '$NC_DB_USER'@'localhost' IDENTIFIED BY '$NC_DB_PASS';
GRANT ALL PRIVILEGES ON nextcloud.* TO '$NC_DB_USER'@'127.0.0.1';
GRANT ALL PRIVILEGES ON nextcloud.* TO '$NC_DB_USER'@'localhost';
FLUSH PRIVILEGES;
SQL
    fi

    echo -e "\033[1;32m[✓] Nextcloud installed!\033[0m"
    echo -e " URL      : \033[1;34mhttp://localhost:8080/nextcloud\033[0m"
    echo -e " Database : \033[1;33mnextcloud\033[0m"
    echo -e " DB User  : \033[1;33m$NC_DB_USER\033[0m"
    echo -e " DB Pass  : \033[1;33m$NC_DB_PASS\033[0m  \033[1;31m(save this!)\033[0m"
    echo -e " DB Host  : \033[1;33m127.0.0.1\033[0m"
    echo ""
    read -p "Press Enter to continue..."
}}

update_server() {{
    MODE="$1"

    [ "$MODE" != "auto" ] && echo -e "\033[1;36m[*] Checking for updates...\033[0m"

    LOCAL_VER=$(cat "$VERSION_FILE" 2>/dev/null || echo "{CURRENT_VERSION}")

    mkdir -p "$PREFIX/tmp"
    TMP_UPD="$PREFIX/tmp/install_server_latest.py"
    curl -sL --max-time 15 "$GITHUB_RAW_URL/install_server.py" -o "$TMP_UPD" 2>/dev/null

    if [ ! -s "$TMP_UPD" ]; then
        rm -f "$TMP_UPD"
        if [ "$MODE" = "auto" ]; then
            echo -e "\033[1;33m[INFO] No internet or update server unreachable.\033[0m"
            sleep 1.2
            return
        fi
        echo -e "\033[1;31m[!] Connection failed.\033[0m"
        read -p "Press Enter to continue..."
        return
    fi

    REMOTE_VER=$(grep -oP 'CURRENT_VERSION\s*=\s*"\K[^"]+' "$TMP_UPD" 2>/dev/null || echo "0.0.0")

    echo -e "  - Installed : \033[1;33m$LOCAL_VER\033[0m"
    echo -e "  - Remote    : \033[1;32m$REMOTE_VER\033[0m"

    if [ "$LOCAL_VER" != "$REMOTE_VER" ]; then
        echo -e "\n\033[1;35m[!] New version ($REMOTE_VER) available!\033[0m"
        echo -e "\033[1;33m[*] Changelog:\033[0m"

        PARSER="$PREFIX/tmp/myserver_changelog_parser.py"
        cat > "$PARSER" <<'PYEOF'
import ast, re, sys
try:
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        content = f.read()
    m = re.search(r"CHANGELOG\s*=\s*(\[.*?\])", content, re.DOTALL)
    if m:
        for item in ast.literal_eval(m.group(1)):
            print("  - " + str(item))
    else:
        print("  - General fixes and improvements.")
except Exception:
    print("  - General fixes and improvements.")
PYEOF
        python3 "$PARSER" "$TMP_UPD"
        rm -f "$PARSER"

        echo ""
        read -p "Download and install update now? (y/N): " confirm
        case "$confirm" in
            [yY][eE][sS]|[yY])
                echo -e "\033[1;33m[*] Stopping services...\033[0m"
                stop_services
                echo -e "\033[1;34m[*] Installing update...\033[0m"
                MYSERVER_SKIP_AUTOUPDATE=1 python3 "$TMP_UPD"
                rm -f "$TMP_UPD"
                echo -e "\n\033[1;32m[OK] Updated to $REMOTE_VER!\033[0m"
                echo -e "\033[1;36m[*] Press Enter to restart myserver...\033[0m"
                read -r
                export MYSERVER_SKIP_AUTOUPDATE=1
                exec "$PREFIX/bin/myserver"
                ;;
            *)
                echo -e "\033[1;33m[INFO] Update cancelled.\033[0m"
                rm -f "$TMP_UPD"
                if [ "$MODE" != "auto" ]; then
                    read -p "Press Enter to continue..."
                else
                    sleep 1
                fi
                ;;
        esac
    else
        echo -e "\033[1;32m[OK] Already on latest ($LOCAL_VER).\033[0m"
        rm -f "$TMP_UPD"
        if [ "$MODE" != "auto" ]; then
            read -p "Press Enter to continue..."
        else
            sleep 1.2
        fi
    fi
}}

reinstall_server() {{
    echo -e "\033[1;35m============================================\033[0m"
    echo -e "\033[1;35m   REINSTALL MYSERVER STACK (Fix Issues)    \033[0m"
    echo -e "\033[1;35m============================================\033[0m"
    echo -e " Web root ($HTDOCS_DIR) will NOT be deleted."
    echo ""
    read -p "Reinstall myserver? (y/N): " confirm
    case "$confirm" in
        [yY][eE][sS]|[yY])
            echo -e "\033[1;36m[*] Downloading latest installer...\033[0m"
            mkdir -p "$PREFIX/tmp"
            TMP_UPD="$PREFIX/tmp/install_server_latest.py"
            curl -sL --max-time 30 "$GITHUB_RAW_URL/install_server.py" -o "$TMP_UPD" 2>/dev/null

            if [ ! -s "$TMP_UPD" ]; then
                echo -e "\033[1;31m[!] Download failed.\033[0m"
                rm -f "$TMP_UPD"
                read -p "Press Enter to continue..."
                return
            fi

            stop_services
            echo -e "\033[1;34m[*] Reinstalling...\033[0m"
            MYSERVER_SKIP_AUTOUPDATE=1 python3 "$TMP_UPD"
            rm -f "$TMP_UPD"

            echo -e "\n\033[1;32m[OK] Reinstall completed!\033[0m"
            echo -e "\033[1;36m[*] Press Enter to relaunch...\033[0m"
            read -r
            export MYSERVER_SKIP_AUTOUPDATE=1
            exec "$PREFIX/bin/myserver"
            ;;
        *)
            echo -e "\033[1;36m[INFO] Cancelled.\033[0m"
            sleep 1
            ;;
    esac
}}

uninstall_server() {{
    echo -e "\033[1;31m============================================\033[0m"
    echo -e "\033[1;31m   WARNING: UNINSTALL MYSERVER STACK        \033[0m"
    echo -e "\033[1;31m============================================\033[0m"
    read -p "Uninstall myserver? (y/N): " confirm
    case "$confirm" in
        [yY][eE][sS]|[yY])
            stop_services

            rm -rf "$PREFIX/etc/nginx/ssl"
            rm -f "$PREFIX/etc/nginx/nginx.conf"
            rm -f "$PREFIX/etc/php-fpm.d/www.conf"
            rm -f "$VERSION_FILE"
            rm -f "$TUNNEL_PID_FILE" "$TUNNEL_URL_FILE" "$TUNNEL_LOG"

            # Remove generated conf.d files (only ours)
            for ext in gd sodium redis apcu imagick mysqli pdo_mysql mbstring openssl curl zip xml intl bcmath; do
                rm -f "$PHP_CONFD_DIR/$ext.ini"
            done

            read -p "Delete web root ($HTDOCS_DIR)? (y/N): " del_web
            case "$del_web" in
                [yY][eE][sS]|[yY])
                    rm -rf "$HTDOCS_DIR"
                    echo -e "\033[1;32m[OK] Web root deleted.\033[0m"
                    ;;
                *)
                    echo -e "\033[1;36m[INFO] Web root preserved.\033[0m"
                    ;;
            esac

            rm -f "$PREFIX/bin/myserver"
            echo -e "\033[1;32m[OK] Uninstalled.\033[0m"
            exit 0
            ;;
        *)
            echo -e "\033[1;36m[INFO] Cancelled.\033[0m"
            sleep 1
            ;;
    esac
}}

if [ -n "$1" ]; then
    case "$1" in
        start) start_services ;;
        stop) stop_services ;;
        restart) restart_services ;;
        status) show_banner_and_status; read -p "Press Enter to continue..." ;;
        quickstart) quickstart_menu ;;
        update) update_server manual ;;
        reinstall) reinstall_server ;;
        internet-enable|enable-internet) enable_internet ;;
        internet-disable|disable-internet) disable_internet ;;
        delete|uninstall) uninstall_server ;;
        *) echo "Usage: myserver [start|stop|restart|status|quickstart|update|reinstall|internet-enable|internet-disable|uninstall]" ;;
    esac
    exit 0
fi

# --- Auto-update check on interactive launch (with skip guard) ---
if [ -z "$MYSERVER_SKIP_AUTOUPDATE" ]; then
    echo -e "\033[1;36m[*] Checking for updates...\033[0m"
    sleep 0.6
    update_server auto
fi
# ------------------------------------------------------------------

while true; do
    show_banner_and_status

    if pgrep -f nginx > /dev/null || pgrep -f php-fpm > /dev/null || pgrep -f "mariadb|mysqld" > /dev/null || pgrep -f redis-server > /dev/null; then
        SERVER_RUNNING=1
    else
        SERVER_RUNNING=0
    fi

    echo -e "\033[1;33mSelect an option:\033[0m"
    if [ "$SERVER_RUNNING" -eq 1 ]; then
        echo -e "\033[1;33m 1) stop             (Stop all services)\033[0m"
    else
        echo -e "\033[1;33m 1) start            (Start all services)\033[0m"
    fi
    if is_tunnel_running; then
        echo -e "\033[1;33m 2) Disable Internet (disable internet access)\033[0m"
    else
        echo -e "\033[1;33m 2) Enable Internet  (enable internet access)\033[0m"
    fi
    echo -e "\033[1;33m 3) restart          (Restart all services)\033[0m"
    echo -e "\033[1;33m 4) quickstart       (Install WP / Laravel / Nextcloud)\033[0m"
    echo -e "\033[1;33m 5) refresh status   (Re-check server status)\033[0m"
    echo -e "\033[1;33m 6) update           (Check and apply updates)\033[0m"
    echo -e "\033[1;33m 7) reinstall        (To fix issues)\033[0m"
    echo -e "\033[1;33m 8) uninstall        (Remove server stack)\033[0m"
    echo -e "\033[1;33m 9) exit             (Exit & Stop Server)\033[0m"
    echo ""
    read -p $'\033[1;33mEnter choice [1-9]: \033[0m' choice

    case "$choice" in
        1)
            if [ "$SERVER_RUNNING" -eq 1 ]; then
                stop_services
            else
                start_services
            fi
            ;;
        start) start_services ;;
        stop) stop_services ;;
        2)
            if is_tunnel_running; then
                disable_internet
            else
                enable_internet
            fi
            ;;
        3|restart) restart_services ;;
        4|quickstart) quickstart_menu ;;
        5|refresh) continue ;;
        6|update) update_server manual ;;
        7|reinstall) reinstall_server ;;
        8|uninstall|delete) uninstall_server ;;
        9|exit)
            stop_services
            echo -e "\033[1;32mServer stopped and exited successfully.\033[0m"
            exit 0
            ;;
        *) echo -e "\033[1;31mInvalid choice!\033[0m"; sleep 1 ;;
    esac
done
"""
    try:
        bin_path.write_text(script_content, encoding='utf-8')
        bin_path.chmod(0o755)
        print("\033[1;32m [✓] CLI Tool 'myserver' configured. \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] CLI creation error: {e}\033[0m")
        return False


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------
def cleanup_repository():
    try:
        cwd = Path.cwd().resolve()
        forbidden = {HOME, PREFIX, Path('/'), Path('/data'),
                     Path('/data/data'), Path('/data/data/com.termux'),
                     Path('/data/data/com.termux/files')}
        if cwd in forbidden:
            return

        install_py = cwd / "install_server.py"
        git_dir = cwd / ".git"
        if not install_py.exists() or not git_dir.exists():
            return

        try:
            result = subprocess.run(
                ["git", "-C", str(cwd), "remote", "-v"],
                capture_output=True, text=True, timeout=5
            )
            if "elias0esmail/termux-web-server" not in result.stdout:
                return
        except Exception:
            return

        print("\033[1;33m[*] Cleaning up downloaded repository folder...\033[0m")
        os.chdir(HOME)
        shutil.rmtree(cwd, ignore_errors=True)
        print("\033[1;32m[✓] Repository folder deleted.\033[0m")
    except Exception as e:
        print(f"\033[1;31m [!] Cleanup notice: {e}\033[0m")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    try:
        print(f"\033[1;33m[+] Deploying Advanced Nginx + PHP-FPM Server Stack v{CURRENT_VERSION}...\033[0m")

        # --- Pre-flight: clean any legacy extension= lines before we start ---
        ini_path = get_php_ini_path()
        if ini_path.exists():
            removed = clean_php_ini_legacy(ini_path)
            if removed:
                print(f"\033[1;33m [*] Pre-flight: removed {removed} legacy 'extension=' line(s) from php.ini \033[0m")

        # Only install packages that ACTUALLY EXIST in Termux repos.
        # Built-in extensions (mysqli, curl, zip, mbstring, ...) ship inside
        # the main php package and require no separate install.
        php_ext_pkgs = " ".join(sorted(set(PHP_EXT_PACKAGES.values())))
        core_pkgs = (
            "nginx php php-fpm mariadb redis openssl-tool "
            "curl tar unzip git wget cloudflared"
        )
        install_cmd = f"pkg install -y {core_pkgs} {php_ext_pkgs}"

        steps = [
            ("Updating Packages", "pkg update -y"),
            ("Storage Setup", None),
            ("Installing Core Software", install_cmd),
            ("MariaDB Hardened Initialization", setup_mariadb),
            ("Redis Setup", setup_redis),
            ("PHP-FPM Configuration", setup_php_fpm),
            ("SSL Certificate Setup", setup_ssl),
            ("Nginx Server Setup", setup_nginx),
            ("PHP Configuration & Sessions Fix", create_php_ini),
            ("Web Root Setup", setup_htdocs),
            ("phpMyAdmin Installation", install_phpmyadmin),
            ("CLI Configuration", create_myserver_cli),
        ]

        for i, (desc, action) in enumerate(steps, 1):
            print(f"\033[1;34m[{i}/{len(steps)}] {desc}...\033[0m")

            if desc == "Storage Setup":
                if not (HOME / "storage").exists():
                    subprocess.run("termux-setup-storage", shell=True)
                    time.sleep(3)
            elif callable(action):
                if not action():
                    raise Exception(f"Failed at step: {desc}")
            elif isinstance(action, str):
                run_cmd(action)

        # Verify critical tools
        missing = [c for c in ["nginx", "php", "php-fpm", "mysqld", "redis-server"]
                   if not command_exists(c)]
        if missing:
            print(f"\033[1;33m [!] Warning: missing binaries: {', '.join(missing)}\033[0m")

        # Final MariaDB state verification
        if is_process_running("mariadbd") or is_process_running("mysqld"):
            print("\033[1;33m [!] Notice: MariaDB left running after install — "
                  "run 'myserver stop' to halt it.\033[0m")
        else:
            print("\033[1;32m [✓] MariaDB is stopped (ready for 'myserver start').\033[0m")

        print("\n\033[1;32m[✓] Server Stack Deployed Successfully!\033[0m")
        print(f"\033[1;36mWeb Root: {HTDOCS_DIR}\033[0m")
        print("HTTP URL:  http://localhost:8080")
        print("HTTPS URL: https://localhost:8443")
        print("phpMyAdmin: http://localhost:8080/phpmyadmin")
        print("\n\033[1;35mType 'myserver' anytime to open the interactive manager.\033[0m\n")

        cleanup_repository()

    except Exception as e:
        print(f"\033[1;31m[!] Installation Error: {e}\033[0m")
        sys.exit(1)


if __name__ == "__main__":
    main()