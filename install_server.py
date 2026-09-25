#!/data/data/com.termux/files/usr/bin/python3

import os
import sys
import time
import shutil
import re
import subprocess
import secrets
import getpass
from pathlib import Path

CURRENT_VERSION = "2.19.5"
CHANGELOG = [
    "Improvement: Password prompt retries infinitely on mismatch",
    "New: (carried) Quickstart hidden when server is stopped",
    "Fix: (carried) MariaDB normal auth (no more ERROR 1698)",
    "Fix: (carried) Auto-repair broken unix_socket root auth",
    "Fix: (carried) fzf clean menu rendering",
    "Fix: (carried) Full wipe on uninstall, preserve on reinstall",
]

PREFIX = Path(os.environ.get('PREFIX', '/data/data/com.termux/files/usr'))
HOME = Path.home()

HTDOCS_DIR = HOME / "storage/shared/htdocs"
HTDOCS_PATH_FILE = PREFIX / "etc/myserver_htdocs_path"

NGINX_DIR = PREFIX / "etc/nginx"
PHP_FPM_DIR = PREFIX / "etc/php-fpm.d"
PHP_CONFD_DIR = PREFIX / "etc/php/conf.d"
PHP_LIB_DIR = PREFIX / "lib/php"
SSL_DIR = NGINX_DIR / "ssl"
TMP_DIR = PREFIX / "tmp"
VERSION_FILE = PREFIX / "etc/myserver_version"
REPO_DIR = Path(__file__).resolve().parent
MY_CNF_FILE = HOME / ".my.cnf"
MYSQL_DATA_DIR = PREFIX / "var/lib/mysql"
MYSQL_RUN_DIR = PREFIX / "var/run/mysqld"
MARIADB_SOCKET = MYSQL_RUN_DIR / "mysqld.sock"

GITHUB_RAW_URL = "https://raw.githubusercontent.com/elias0esmail/termux-web-server/main"

DB_ROOT_PASSWORD = ""
REINSTALL_MODE = False

PHP_EXPECTED_EXTENSIONS = [
    "mysqli", "pdo_mysql", "mbstring", "openssl",
    "curl", "zip", "xml", "intl", "bcmath",
    "gd", "sodium", "redis", "apcu", "imagick",
]
PHP_BUILTIN_EXTENSIONS = {
    "mysqli", "pdo_mysql", "mbstring", "openssl",
    "curl", "zip", "xml", "intl", "bcmath",
}
PHP_EXT_PACKAGES = {
    "gd": "php-gd", "sodium": "php-sodium", "redis": "php-redis",
    "apcu": "php-apcu", "imagick": "php-imagick",
}


# ===========================================================================
# Helpers
# ===========================================================================
def run_cmd(cmd, check=False):
    return subprocess.run(cmd, shell=True, check=check,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def command_exists(cmd):
    return shutil.which(cmd) is not None


def is_process_running(pattern: str) -> bool:
    r = subprocess.run(f"pgrep -f '{pattern}'", shell=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


def mysql_client() -> str:
    return "mariadb" if command_exists("mariadb") else "mysql"


def mysql_admin() -> str:
    return "mariadb-admin" if command_exists("mariadb-admin") else "mysqladmin"


# ===========================================================================
# fzf menu
# ===========================================================================
def ensure_fzf() -> bool:
    if command_exists("fzf"):
        return True
    print("\033[1;33m[*] Installing fzf (one-time)...\033[0m")
    r = subprocess.run("pkg install -y fzf", shell=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0 and command_exists("fzf")


def choose_option(title: str, options: list, default: int = 0) -> int:
    if not options:
        return 0
    if len(options) == 1:
        return 0

    if not ensure_fzf():
        print(f"\033[1;36m{title}\033[0m")
        for i, opt in enumerate(options, 1):
            print(f"  {i}) {opt}")
        try:
            raw = input(f"\033[1;33mSelect [1-{len(options)}] (default {default+1}): \033[0m").strip()
            if not raw:
                return default
            return max(0, min(len(options) - 1, int(raw) - 1))
        except Exception:
            return default

    sys.stdout.write("\033[0m\n")
    sys.stdout.flush()

    lines = [f"{i}\t{opt}" for i, opt in enumerate(options)]
    reordered = [lines[default]] + [l for i, l in enumerate(lines) if i != default]
    input_text = "\n".join(reordered) + "\n"

    try:
        result = subprocess.run(
            [
                "fzf",
                "--height=8",
                "--min-height=5",
                "--layout=reverse",
                "--no-multi",
                "--no-mouse",
                "--no-info",
                "--no-separator",
                "--no-scrollbar",
                "--with-nth=2..",
                "--delimiter=\t",
                f"--header={title}",
                "--header-first",
                "--pointer=>",
                "--marker= ",
                "--prompt=  ",
                "--color=pointer:cyan,fg+:cyan,header:yellow,prompt:cyan",
            ],
            input=input_text,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            idx_str = result.stdout.strip().split("\t", 1)[0]
            try:
                idx = int(idx_str)
                if 0 <= idx < len(options):
                    return idx
            except ValueError:
                pass
    except Exception:
        pass
    return default


def ask_web_root_location() -> Path:
    home_path = HOME / "htdocs"
    storage_path = HOME / "storage/shared/htdocs"
    idx = choose_option(
        "Where should the web root (htdocs) be created?",
        ["Termux home", "Phone storage"],
        default=0)
    return home_path if idx == 0 else storage_path


def ask_db_password() -> str:
    """
    Prompt for MariaDB root password. Empty = no password.
    On mismatch, show error and re-prompt indefinitely
    (until the user enters matching passwords or presses Ctrl+C to abort).
    """
    print("\033[1;36m[i] MariaDB root password\033[0m")
    print("\033[1;33m    Leave empty and press Enter for NO password (default)\033[0m")

    while True:
        try:
            pw = getpass.getpass("\033[1;33m  Password: \033[0m").strip()
        except Exception:
            pw = ""

        # Empty = no password → accept immediately
        if not pw:
            return ""

        try:
            confirm = getpass.getpass("\033[1;33m  Confirm : \033[0m").strip()
        except Exception:
            confirm = ""

        if pw == confirm:
            return pw

        # Mismatch → error + retry
        print("\033[1;31m [!] Passwords do not match. Please try again.\033[0m")
        print()


# ===========================================================================
# .my.cnf helpers
# ===========================================================================
def _sql_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


def write_my_cnf(password: str, sock_path: Path):
    lines = ["[client]", "user = root"]
    if password:
        lines.append(f'password = "{password}"')
    lines.append(f"socket = {sock_path}")
    MY_CNF_FILE.write_text("\n".join(lines) + "\n")
    try:
        os.chmod(MY_CNF_FILE, 0o600)
    except Exception:
        pass


def read_password_from_my_cnf() -> str:
    if not MY_CNF_FILE.exists():
        return ""
    try:
        for line in MY_CNF_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("password"):
                _, _, val = line.partition("=")
                return val.strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


# ===========================================================================
# PHP introspection
# ===========================================================================
def get_php_ini_path() -> Path:
    try:
        result = subprocess.run(["php", "--ini"], capture_output=True, text=True)
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.endswith("php.ini") and line.startswith("/"):
                    return Path(line)
    except Exception:
        pass
    for candidate in [PREFIX / "etc/php/php.ini", PREFIX / "lib/php.ini", PREFIX / "etc/php.ini"]:
        if candidate.exists():
            return candidate
    return PREFIX / "etc/php/php.ini"


def php_loaded_extensions() -> set:
    try:
        r = subprocess.run(["php", "-m"], capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            return {ln.strip().lower() for ln in r.stdout.splitlines()
                    if ln.strip() and not ln.strip().startswith("[")}
    except Exception:
        pass
    return set()


def php_extension_dir() -> Path:
    try:
        r = subprocess.run(["php", "-n", "-r", 'echo ini_get("extension_dir");'],
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            lines = [ln.strip() for ln in r.stdout.strip().splitlines() if ln.strip()]
            if lines:
                p = Path(lines[-1])
                if p.is_absolute():
                    return p
    except Exception:
        pass
    try:
        r = subprocess.run(["php", "-i"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                if line.lower().startswith("extension_dir"):
                    _, _, val = line.partition("=>")
                    val = val.strip()
                    if val and val.startswith("/"):
                        return Path(val)
    except Exception:
        pass
    return PHP_LIB_DIR


def scan_available_so(ext_dir: Path) -> set:
    found = set()
    try:
        if ext_dir.exists():
            for so in ext_dir.glob("*.so"):
                found.add(so.stem)
    except Exception:
        pass
    return found


def clean_php_ini_legacy(ini_path: Path) -> int:
    if not ini_path.exists():
        return 0
    try:
        content = ini_path.read_text()
    except Exception:
        return 0
    new_content, n = re.subn(
        r"^[ \t]*extension[ \t]*=[ \t]*[^\r\n]*[\r\n]?",
        "", content, flags=re.MULTILINE)
    if n > 0:
        ini_path.write_text(new_content)
    return n


# ===========================================================================
# Web root helpers
# ===========================================================================
def enforce_htdocs_permissions() -> int:
    if not HTDOCS_DIR.exists():
        return 0
    changed = 0
    try:
        if (HTDOCS_DIR.stat().st_mode & 0o777) != 0o755:
            os.chmod(HTDOCS_DIR, 0o755)
            changed += 1
    except Exception:
        pass
    try:
        for root, dirs, files in os.walk(HTDOCS_DIR):
            for d in dirs:
                p = os.path.join(root, d)
                try:
                    if (os.stat(p).st_mode & 0o777) != 0o755:
                        os.chmod(p, 0o755)
                        changed += 1
                except Exception:
                    pass
            for f in files:
                p = os.path.join(root, f)
                try:
                    if (os.stat(p).st_mode & 0o777) not in (0o644, 0o755):
                        os.chmod(p, 0o644)
                        changed += 1
                except Exception:
                    pass
    except Exception:
        pass
    return changed


def verify_htdocs_readable(verbose: bool = True) -> bool:
    ok = True
    if not HTDOCS_DIR.exists():
        if verbose:
            print(f"\033[1;31m [!] Web root missing: {HTDOCS_DIR} \033[0m")
        return False
    if not os.access(str(HTDOCS_DIR), os.R_OK):
        if verbose:
            print("\033[1;31m [!] Web root not readable \033[0m")
        ok = False
    if not os.access(str(HTDOCS_DIR), os.X_OK):
        if verbose:
            print("\033[1;31m [!] Web root not traversable \033[0m")
        ok = False
    idx = HTDOCS_DIR / "index.php"
    if not idx.exists():
        if verbose:
            print("\033[1;31m [!] index.php missing \033[0m")
        ok = False
    else:
        try:
            idx.read_text()
        except Exception as e:
            if verbose:
                print(f"\033[1;31m [!] Cannot read {idx}: {e} \033[0m")
            ok = False
    try:
        list(HTDOCS_DIR.iterdir())
    except Exception as e:
        if verbose:
            print(f"\033[1;31m [!] Cannot list web root: {e} \033[0m")
        ok = False
    return ok


def print_htdocs_diagnostic():
    print("\033[1;36m [i] Web root diagnostic: \033[0m")
    print(f"\033[1;36m     path      : {HTDOCS_DIR} \033[0m")
    try:
        print(f"\033[1;36m     realpath  : {HTDOCS_DIR.resolve()} \033[0m")
    except Exception as e:
        print(f"\033[1;33m     realpath  : (failed: {e}) \033[0m")
    if HTDOCS_DIR.exists():
        try:
            print(f"\033[1;36m     mode      : {oct(HTDOCS_DIR.stat().st_mode & 0o777)} \033[0m")
        except Exception:
            pass


# ===========================================================================
# MariaDB lifecycle (Python side)
# ===========================================================================
def start_mariadb_background():
    MYSQL_DATA_DIR.mkdir(parents=True, exist_ok=True)
    MYSQL_RUN_DIR.mkdir(parents=True, exist_ok=True)
    if MARIADB_SOCKET.exists():
        try:
            MARIADB_SOCKET.unlink()
        except Exception:
            pass
    if command_exists("mariadbd-safe"):
        cmd = f"mariadbd-safe --datadir='{MYSQL_DATA_DIR}' --socket='{MARIADB_SOCKET}'"
    else:
        cmd = f"mariadbd --datadir='{MYSQL_DATA_DIR}' --socket='{MARIADB_SOCKET}'"
    subprocess.Popen(cmd, shell=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(15):
        if MARIADB_SOCKET.exists():
            return True
        time.sleep(1)
    return MARIADB_SOCKET.exists()


def stop_mariadb_cleanly():
    if MARIADB_SOCKET.exists():
        run_cmd(f"{mysql_admin()} --socket='{MARIADB_SOCKET}' shutdown")
        time.sleep(2)
    for pattern in ("mariadbd-safe", "mysqld_safe"):
        run_cmd(f"pkill -TERM -f '{pattern}'")
    time.sleep(1)
    for pattern in ("mariadbd-safe", "mysqld_safe", "mariadbd", "mysqld"):
        run_cmd(f"pkill -TERM -f '{pattern}'")
    time.sleep(1)
    for pattern in ("mariadbd-safe", "mysqld_safe", "mariadbd", "mysqld"):
        run_cmd(f"pkill -KILL -f '{pattern}'")


def repair_root_if_unix_socket():
    if not MARIADB_SOCKET.exists():
        return
    cli = mysql_client()
    r = subprocess.run(
        f"{cli} -u root --socket='{MARIADB_SOCKET}' -e 'SELECT 1;'",
        shell=True, capture_output=True, text=True, timeout=10)
    if r.returncode == 0:
        return
    err = (r.stderr or "").lower()
    if "1698" not in err and "unix_socket" not in err and "access denied" not in err:
        return

    print("\033[1;33m [*] Detected broken root auth — repairing via skip-grant-tables...\033[0m")
    stop_mariadb_cleanly()
    time.sleep(2)

    if command_exists("mariadbd-safe"):
        cmd = (f"mariadbd-safe --skip-grant-tables --skip-networking "
               f"--datadir='{MYSQL_DATA_DIR}' --socket='{MARIADB_SOCKET}'")
    else:
        cmd = (f"mariadbd --skip-grant-tables --skip-networking "
               f"--datadir='{MYSQL_DATA_DIR}' --socket='{MARIADB_SOCKET}'")
    subprocess.Popen(cmd, shell=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ok = False
    for _ in range(15):
        if MARIADB_SOCKET.exists():
            ok = True
            break
        time.sleep(1)
    if not ok:
        print("\033[1;31m [!] Repair failed: MariaDB did not start.\033[0m")
        return
    time.sleep(2)

    fix_sql = (
        "UPDATE mysql.user SET plugin='mysql_native_password' "
        "WHERE User='root' AND Host='localhost';"
        "UPDATE mysql.user SET Password='' "
        "WHERE User='root' AND Host='localhost';"
        "UPDATE mysql.user SET authentication_string='' "
        "WHERE User='root' AND Host='localhost';"
        "FLUSH PRIVILEGES;"
    )
    subprocess.run(
        f"{cli} -u root --socket='{MARIADB_SOCKET}' -e \"{fix_sql}\"",
        shell=True, capture_output=True, text=True)

    stop_mariadb_cleanly()
    time.sleep(2)

    if start_mariadb_background():
        r = subprocess.run(
            f"{cli} -u root --socket='{MARIADB_SOCKET}' -e 'SELECT 1;'",
            shell=True, capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            print("\033[1;32m [✓] Root authentication repaired successfully. \033[0m")
        else:
            print("\033[1;33m [!] Repair attempted but root still not accessible.\033[0m")


# ===========================================================================
# Setup: MariaDB
# ===========================================================================
def setup_mariadb():
    try:
        MYSQL_DATA_DIR.mkdir(parents=True, exist_ok=True)
        MYSQL_RUN_DIR.mkdir(parents=True, exist_ok=True)

        if MARIADB_SOCKET.exists():
            try:
                MARIADB_SOCKET.unlink()
            except Exception:
                pass

        fresh_install = not (MYSQL_DATA_DIR / "mysql").exists()

        if fresh_install:
            run_cmd(f"mariadb-install-db --auth-root-authentication-method=normal "
                    f"--datadir='{MYSQL_DATA_DIR}'")
            print("\033[1;32m [✓] MariaDB database initialized (normal auth). \033[0m")
        else:
            print("\033[1;36m [i] Existing MariaDB data detected — preserving databases. \033[0m")

        if not start_mariadb_background():
            print("\033[1;31m [!] Failed to start MariaDB. \033[0m")
            return False

        repair_root_if_unix_socket()
        cli = mysql_client()

        if MARIADB_SOCKET.exists():
            sec_sql = (
                "DELETE FROM mysql.user WHERE User='';"
                "DELETE FROM mysql.user WHERE User='root' AND Host NOT IN "
                "('localhost', '127.0.0.1', '::1');"
                "DROP DATABASE IF EXISTS test;"
                "DELETE FROM mysql.db WHERE Db='test' OR Db='test\\_%';"
                "FLUSH PRIVILEGES;"
            )
            r = subprocess.run(
                f"{cli} -u root --socket='{MARIADB_SOCKET}' -e \"{sec_sql}\"",
                shell=True, capture_output=True, text=True)
            if r.returncode == 0:
                print("\033[1;32m [✓] MariaDB Security Hardening applied. \033[0m")
            else:
                snippet = (r.stderr or "").strip().splitlines()
                snippet = snippet[0][:200] if snippet else "unknown error"
                print(f"\033[1;33m [!] Hardening note: {snippet} \033[0m")

        if REINSTALL_MODE:
            print("\033[1;36m [i] Reinstall mode — preserving root credentials. \033[0m")
            return True

        write_my_cnf("", MARIADB_SOCKET)

        if DB_ROOT_PASSWORD:
            tmp_sql = TMP_DIR / "myserver_setpw.sql"
            TMP_DIR.mkdir(parents=True, exist_ok=True)
            escaped = _sql_escape(DB_ROOT_PASSWORD)
            tmp_sql.write_text(
                f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{escaped}';\n"
                f"FLUSH PRIVILEGES;\n"
            )
            r = subprocess.run(
                f"{cli} -u root --socket='{MARIADB_SOCKET}' < '{tmp_sql}'",
                shell=True, capture_output=True, text=True)
            try:
                tmp_sql.unlink()
            except Exception:
                pass
            if r.returncode == 0:
                write_my_cnf(DB_ROOT_PASSWORD, MARIADB_SOCKET)
                print("\033[1;32m [✓] MariaDB root password set. \033[0m")
            else:
                snippet = (r.stderr or "").strip().splitlines()
                snippet = snippet[0][:200] if snippet else "unknown error"
                print(f"\033[1;33m [!] Password note: {snippet} \033[0m")
        else:
            r = subprocess.run(
                f"{cli} -u root --socket='{MARIADB_SOCKET}' -e "
                f"\"ALTER USER 'root'@'localhost' IDENTIFIED BY ''; FLUSH PRIVILEGES;\"",
                shell=True, capture_output=True, text=True)
            if r.returncode == 0:
                print("\033[1;36m [i] MariaDB root has no password. \033[0m")
            else:
                snippet = (r.stderr or "").strip().splitlines()
                snippet = snippet[0][:200] if snippet else "unknown error"
                print(f"\033[1;33m [!] Note: {snippet} \033[0m")

        return True
    except Exception as e:
        print(f"\033[1;31m [!] MariaDB init error: {e}\033[0m")
        return False


# ===========================================================================
# Setup: Redis / PHP-FPM / SSL / Nginx / php.ini / htdocs
# ===========================================================================
def setup_redis():
    try:
        redis_data = PREFIX / "var/lib/redis"
        log_dir = PREFIX / "var/log"
        redis_data.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)
        (PREFIX / "etc/redis.conf").write_text(
            f"dir {redis_data}\nport 6379\nbind 127.0.0.1\ndaemonize yes\n"
            f"logfile {log_dir}/redis.log\nignore-warnings ARM64-COW-BUG\n")
        print("\033[1;32m [✓] Redis configured (ARM64 warning suppressed). \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] Redis init error: {e}\033[0m")
        return False


def setup_php_fpm():
    try:
        PHP_FPM_DIR.mkdir(parents=True, exist_ok=True)
        (PHP_FPM_DIR / "www.conf").write_text("""\
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
        print("\033[1;32m [✓] PHP-FPM configured (Port 9000, Termux-safe). \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] PHP-FPM config error: {e}\033[0m")
        return False


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
        print("\033[1;32m [✓] SSL Certificates generated (key chmod 600). \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] SSL generation error: {e}\033[0m")
        return False


def setup_nginx():
    try:
        conf_path = NGINX_DIR / "nginx.conf"
        cert_path = SSL_DIR / "server.crt"
        key_path = SSL_DIR / "server.key"

        common = f"""\
        location ~ ^/phpmyadmin/.*\\.php$ {{
            try_files $uri =404;
            include fastcgi_params;
            fastcgi_pass php_fpm;
            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
            fastcgi_read_timeout 300;
        }}

        location ~ ^(.*)/$ {{
            try_files $1/index.php =404;
            include fastcgi_params;
            fastcgi_pass php_fpm;
            fastcgi_param SCRIPT_FILENAME $document_root$1/index.php;
            fastcgi_param PATH_INFO "";
            fastcgi_read_timeout 300;
        }}

        location ~ \\.php$ {{
            try_files $uri =404;
            include fastcgi_params;
            fastcgi_pass php_fpm;
            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
            fastcgi_read_timeout 300;
        }}

        location / {{
            try_files $uri /index.php?$args;
        }}

        location ~ /\\. {{
            deny all;
        }}
"""

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
    gzip_types text/plain text/css text/xml text/javascript
        application/javascript application/json application/xml
        application/xml+rss application/x-font-ttf font/opentype image/svg+xml;

    upstream php_fpm {{ server 127.0.0.1:9000; }}

    server {{
        listen 8080;
        server_name localhost;
        root {HTDOCS_DIR};
        index index.php index.html index.htm;
        client_max_body_size 512M;
        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;
{common}
    }}

    server {{
        listen 8443 ssl;
        server_name localhost;
        ssl_certificate "{cert_path}";
        ssl_certificate_key "{key_path}";
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;
        ssl_prefer_server_ciphers on;
        root {HTDOCS_DIR};
        index index.php index.html index.htm;
        client_max_body_size 512M;
        add_header Strict-Transport-Security "max-age=31536000" always;
        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;
{common}
    }}
}}
"""
        conf_path.write_text(nginx_config)
        (PREFIX / "var/log").mkdir(parents=True, exist_ok=True)
        print("\033[1;32m [✓] Nginx configured. \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] Nginx config error: {e}\033[0m")
        return False


def create_php_ini():
    php_ini_path = get_php_ini_path()
    PHP_CONFD_DIR.mkdir(parents=True, exist_ok=True)
    TMP_DIR.mkdir(parents=True, exist_ok=True)

    removed = clean_php_ini_legacy(php_ini_path)
    if removed:
        print(f"\033[1;33m [*] Removed {removed} legacy 'extension=' line(s). \033[0m")

    ext_dir = php_extension_dir()
    print(f"\033[1;36m [i] PHP extension_dir = {ext_dir} \033[0m")

    available_so = scan_available_so(ext_dir)
    if available_so:
        print(f"\033[1;36m [i] Available .so files: {', '.join(sorted(available_so))} \033[0m")

    loaded_before = php_loaded_extensions()

    php_ini_content = f"""\
upload_max_filesize = 512M
post_max_size = 512M
memory_limit = 512M
max_execution_time = 300
error_reporting = E_ALL & ~E_DEPRECATED
display_errors = On
date.timezone = UTC

extension_dir = "{ext_dir}"
cgi.fix_pathinfo=0

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

    synced_so = []
    for ext in PHP_EXPECTED_EXTENSIONS:
        ini_file = PHP_CONFD_DIR / f"{ext}.ini"
        if ext in loaded_before:
            if ini_file.exists():
                try:
                    ini_file.unlink()
                except Exception:
                    pass
            continue
        if ext in available_so:
            desired = f"extension={ext}.so\n"
            try:
                if not ini_file.exists() or ini_file.read_text() != desired:
                    ini_file.write_text(desired)
                    synced_so.append(ext)
            except Exception:
                pass
            continue
        if ini_file.exists():
            try:
                ini_file.unlink()
            except Exception:
                pass

    if synced_so:
        print(f"\033[1;32m [✓] Registered via conf.d: {', '.join(synced_so)} \033[0m")

    loaded_sorted = sorted(loaded_before)
    preview = ", ".join(loaded_sorted[:15])
    suffix = "..." if len(loaded_sorted) > 15 else ""
    print(f"\033[1;32m [✓] PHP loaded {len(loaded_sorted)} extensions: {preview}{suffix} \033[0m")
    return True


def setup_htdocs():
    try:
        HTDOCS_DIR.mkdir(parents=True, exist_ok=True)
        if not (HTDOCS_DIR / "index.php").exists():
            (HTDOCS_DIR / "index.php").write_text(
                "<?php echo '<h1>Nginx + PHP-FPM Server is Running!</h1>'; ?>")
        info_dir = HTDOCS_DIR / "phpinfo"
        info_dir.mkdir(exist_ok=True)
        (info_dir / "index.php").write_text("<?php phpinfo(); ?>")
        changed = enforce_htdocs_permissions()
        if changed:
            print(f"\033[1;32m [✓] htdocs permissions normalized ({changed} entries). \033[0m")
        else:
            print("\033[1;32m [✓] htdocs permissions already correct. \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] htdocs error: {e}\033[0m")
        return False


# ===========================================================================
# phpMyAdmin
# ===========================================================================
PMA_STORAGE_BLOCK = """\
$cfg['Servers'][$i]['pmadb'] = 'phpmyadmin';
$cfg['Servers'][$i]['bookmarktable'] = 'pma__bookmark';
$cfg['Servers'][$i]['relation'] = 'pma__relation';
$cfg['Servers'][$i]['table_info'] = 'pma__table_info';
$cfg['Servers'][$i]['table_coords'] = 'pma__table_coords';
$cfg['Servers'][$i]['pdf_pages'] = 'pma__pdf_pages';
$cfg['Servers'][$i]['column_info'] = 'pma__column_info';
$cfg['Servers'][$i]['history'] = 'pma__history';
$cfg['Servers'][$i]['table_uiprefs'] = 'pma__table_uiprefs';
$cfg['Servers'][$i]['tracking'] = 'pma__tracking';
$cfg['Servers'][$i]['userconfig'] = 'pma__userconfig';
$cfg['Servers'][$i]['recent'] = 'pma__recent';
$cfg['Servers'][$i]['favorite'] = 'pma__favorite';
$cfg['Servers'][$i]['users'] = 'pma__users';
$cfg['Servers'][$i]['usergroups'] = 'pma__usergroups';
$cfg['Servers'][$i]['navigationhiding'] = 'pma__navigationhiding';
$cfg['Servers'][$i]['savedsearches'] = 'pma__savedsearches';
$cfg['Servers'][$i]['central_columns'] = 'pma__central_columns';
$cfg['Servers'][$i]['designer_settings'] = 'pma__designer_settings';
$cfg['Servers'][$i]['export_templates'] = 'pma__export_templates';
"""


def setup_phpmyadmin_storage(pma_dir: Path) -> bool:
    sql_create_tables = pma_dir / "sql" / "create_tables.sql"
    if not sql_create_tables.exists():
        print(f"\033[1;33m [!] Missing {sql_create_tables} — skipping storage setup. \033[0m")
        return False
    if not MARIADB_SOCKET.exists():
        print("\033[1;33m [!] MariaDB not running — skipping storage setup. \033[0m")
        return False

    cli = mysql_client()
    r = subprocess.run(
        f"{cli} -u root --socket='{MARIADB_SOCKET}' -e "
        f"\"CREATE DATABASE IF NOT EXISTS phpmyadmin "
        f"DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\"",
        shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        snippet = (r.stderr or "").strip().splitlines()
        snippet = snippet[0][:200] if snippet else "unknown error"
        print(f"\033[1;33m [!] CREATE DATABASE failed: {snippet} \033[0m")
        return False

    r = subprocess.run(
        f"{cli} -u root --socket='{MARIADB_SOCKET}' --force phpmyadmin < '{sql_create_tables}'",
        shell=True, capture_output=True, text=True)
    if r.returncode != 0:
        snippet = (r.stderr or "").strip().splitlines()
        snippet = snippet[0][:200] if snippet else "unknown error"
        print(f"\033[1;33m [!] Import note: {snippet} \033[0m")

    r = subprocess.run(
        f"{cli} -u root --socket='{MARIADB_SOCKET}' -N -B -e "
        f"\"SHOW TABLES FROM phpmyadmin LIKE 'pma\\\\_%';\"",
        shell=True, capture_output=True, text=True)
    tables = [ln for ln in r.stdout.splitlines() if ln.strip()]

    if len(tables) >= 15:
        print(f"\033[1;32m [✓] phpMyAdmin storage DB ready ({len(tables)} tables). \033[0m")
        return True
    if tables:
        print(f"\033[1;33m [!] phpMyAdmin storage partially set up ({len(tables)} tables). \033[0m")
        return True
    print("\033[1;33m [!] phpMyAdmin storage DB has no tables. \033[0m")
    return False


def patch_phpmyadmin_config(config_file: Path):
    if not config_file.exists():
        return
    try:
        content = config_file.read_text()
    except Exception:
        return
    if "['pmadb']" in content:
        return
    content += "\n" + PMA_STORAGE_BLOCK
    try:
        config_file.write_text(content)
    except Exception:
        pass


def install_phpmyadmin():
    pma_dir = HTDOCS_DIR / "phpmyadmin"
    is_update = pma_dir.exists()

    try:
        print("\033[1;34m [*] " + ("Updating" if is_update else "Downloading") + " phpMyAdmin... \033[0m")
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
                f"$cfg['blowfish_secret'] = '{secret}';", content)
            allow_nopass = "true" if not DB_ROOT_PASSWORD else "false"
            content = re.sub(
                r"\$cfg\['Servers'\]\[\$i\]\['AllowNoPassword'\]\s*=\s*(true|false);",
                f"$cfg['Servers'][$i]['AllowNoPassword'] = {allow_nopass};", content)
            if "AllowNoPassword" not in content:
                content += f"\n$cfg['Servers'][$i]['AllowNoPassword'] = {allow_nopass};\n"
            content = re.sub(
                r"\$cfg\['Servers'\]\[\$i\]\['host'\]\s*=\s*'localhost';",
                "$cfg['Servers'][$i]['host'] = '127.0.0.1';", content)
            pma_tmp = pma_dir / "tmp"
            pma_tmp.mkdir(exist_ok=True)
            content += f"\n$cfg['TempDir'] = '{pma_tmp}';\n"
            content += "\n" + PMA_STORAGE_BLOCK
            config_file.write_text(content)

        (pma_dir / "tmp").mkdir(exist_ok=True)
        patch_phpmyadmin_config(config_file)
        storage_ok = setup_phpmyadmin_storage(pma_dir)
        enforce_htdocs_permissions()

        print("\033[1;32m [✓] phpMyAdmin " + ("updated" if is_update else "installed") + ". \033[0m")
        if storage_ok:
            print("\033[1;32m [✓] phpMyAdmin configuration storage active. \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] phpMyAdmin error: {e}\033[0m")
        return False


# ===========================================================================
# CLI generator
# ===========================================================================
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
MYSQL_DATA_DIR="{MYSQL_DATA_DIR}"
MYSQL_RUN_DIR="{MYSQL_RUN_DIR}"
TUNNEL_PID_FILE="$PREFIX/tmp/cloudflared.pid"
TUNNEL_URL_FILE="$PREFIX/tmp/cloudflared.url"
TUNNEL_LOG="$PREFIX/tmp/cloudflared.log"
MARIADB_SOCKET="$MYSQL_RUN_DIR/mysqld.sock"

MYSQL_CLI=$(command -v mariadb || command -v mysql)
MYSQL_ADMIN=$(command -v mariadb-admin || command -v mysqladmin)

is_tunnel_running() {{
    if [ -f "$TUNNEL_PID_FILE" ]; then
        TPID=$(cat "$TUNNEL_PID_FILE" 2>/dev/null)
        if [ -n "$TPID" ] && kill -0 "$TPID" 2>/dev/null; then return 0; fi
    fi
    pgrep -f "cloudflared tunnel" > /dev/null && return 0
    return 1
}}

get_tunnel_url() {{
    [ -f "$TUNNEL_URL_FILE" ] && cat "$TUNNEL_URL_FILE" 2>/dev/null
}}

has_internet() {{
    curl -s --max-time 5 -o /dev/null -w "%{{http_code}}" https://1.1.1.1 2>/dev/null | grep -qE '^[23]' && return 0
    curl -s --max-time 5 -o /dev/null https://www.google.com 2>/dev/null && return 0
    return 1
}}

open_browser() {{
    command -v termux-open-url &> /dev/null && termux-open-url "http://localhost:8080" > /dev/null 2>&1 &
    return 0
}}

server_is_running() {{
    pgrep -f nginx > /dev/null || pgrep -f php-fpm > /dev/null || pgrep -f "mariadb|mysqld" > /dev/null || pgrep -f redis-server > /dev/null
}}

start_mariadb_background() {{
    mkdir -p "$MYSQL_DATA_DIR" "$MYSQL_RUN_DIR"
    [ -S "$MARIADB_SOCKET" ] && rm -f "$MARIADB_SOCKET"
    [ ! -d "$MYSQL_DATA_DIR/mysql" ] && mariadb-install-db --auth-root-authentication-method=normal --datadir="$MYSQL_DATA_DIR" > /dev/null 2>&1
    if command -v mariadbd-safe &> /dev/null; then
        mariadbd-safe --datadir="$MYSQL_DATA_DIR" --socket="$MARIADB_SOCKET" > /dev/null 2>&1 &
    else
        mariadbd --datadir="$MYSQL_DATA_DIR" --socket="$MARIADB_SOCKET" > /dev/null 2>&1 &
    fi
    local i=0
    while [ $i -lt 15 ]; do
        [ -S "$MARIADB_SOCKET" ] && return 0
        sleep 1
        i=$((i+1))
    done
    [ -S "$MARIADB_SOCKET" ]
}}

stop_mariadb_cleanly() {{
    if [ -S "$MARIADB_SOCKET" ]; then
        "$MYSQL_ADMIN" --socket="$MARIADB_SOCKET" shutdown 2>/dev/null
        sleep 2
    fi
    pkill -TERM -f "mariadbd-safe" > /dev/null 2>&1
    pkill -TERM -f "mysqld_safe"   > /dev/null 2>&1
    sleep 1
    pkill -TERM -f "mariadbd|mysqld" > /dev/null 2>&1
    sleep 1
    pkill -KILL -f "mariadbd|mysqld" > /dev/null 2>&1
}}

sync_php_extensions() {{
    local ext_dir
    ext_dir=$(php -n -r 'echo ini_get("extension_dir");' 2>/dev/null | tail -n1)
    [ -z "$ext_dir" ] && ext_dir="$PHP_LIB_DIR"
    mkdir -p "$ext_dir" "$PHP_CONFD_DIR" 2>/dev/null
    local loaded
    loaded=$(php -m 2>/dev/null | tr 'A-Z' 'a-z')
    for ext in gd sodium redis apcu imagick; do
        if echo "$loaded" | grep -qx "$ext"; then
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

check_webroot() {{
    [ -d "$HTDOCS_DIR" ] || {{ echo -e "\033[1;31m[!] Web root missing\033[0m"; return 1; }}
    if [ ! -r "$HTDOCS_DIR" ] || [ ! -x "$HTDOCS_DIR" ]; then
        chmod 755 "$HTDOCS_DIR" 2>/dev/null
        find "$HTDOCS_DIR" -type d -exec chmod 755 {{}} \; 2>/dev/null
        find "$HTDOCS_DIR" -type f -exec chmod 644 {{}} \; 2>/dev/null
    fi
    return 0
}}

ensure_pma_storage() {{
    [ -S "$MARIADB_SOCKET" ] || return 0
    local count
    count=$("$MYSQL_CLI" -u root --socket="$MARIADB_SOCKET" -N -B -e \
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='phpmyadmin' AND table_name LIKE 'pma\\\\_%';" 2>/dev/null)
    [ -z "$count" ] && return 0
    [ "$count" -gt 0 ] 2>/dev/null && return 0
    local pma_sql="$HTDOCS_DIR/phpmyadmin/sql/create_tables.sql"
    [ -f "$pma_sql" ] || return 0
    echo -e "\033[1;34m[*] Setting up phpMyAdmin configuration storage...\033[0m"
    "$MYSQL_CLI" -u root --socket="$MARIADB_SOCKET" -e \
        "CREATE DATABASE IF NOT EXISTS phpmyadmin DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" 2>/dev/null
    "$MYSQL_CLI" -u root --socket="$MARIADB_SOCKET" --force phpmyadmin < "$pma_sql" 2>/dev/null
    echo -e "\033[1;32m[OK] phpMyAdmin storage ready.\033[0m"
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
    is_tunnel_running && echo -e " Tunnel:   \033[1;32mRunning [OK]\033[0m" || echo -e " Tunnel:   \033[1;31mStopped [X]\033[0m"
    echo -e "\033[1;35m===============================================\033[0m\n"

    SVC_INFO=0
    server_is_running && SVC_INFO=1
    TUNNEL_URL_VAL=$(get_tunnel_url)
    TUNNEL_ACTIVE=0
    is_tunnel_running && [ -n "$TUNNEL_URL_VAL" ] && TUNNEL_ACTIVE=1

    if [ "$SVC_INFO" -eq 1 ] || [ "$TUNNEL_ACTIVE" -eq 1 ]; then
        echo -e "\033[1;36m============= [ SERVER INFORMATION ] =============\033[0m"
        echo -e " Web Root Path : \033[1;33m$HTDOCS_DIR\033[0m"
        echo -e " HTTP URL      : \033[1;34mhttp://localhost:8080\033[0m"
        echo -e " HTTPS URL     : \033[1;32mhttps://localhost:8443\033[0m"
        echo -e " phpMyAdmin    : \033[1;35mhttp://localhost:8080/phpmyadmin\033[0m"
        [ "$TUNNEL_ACTIVE" -eq 1 ] && echo -e " Global URL    : \033[1;32m$TUNNEL_URL_VAL\033[0m" || echo -e " Global URL    : \033[1;31mInactive\033[0m"
        echo -e "\033[1;36m==================================================\033[0m\n"
    fi
}}

start_services() {{
    sync_php_extensions
    check_webroot
    echo -e "\033[1;34m[+] Starting MariaDB...\033[0m"
    if ! pgrep -f "mariadb|mysqld" > /dev/null; then
        start_mariadb_background
        echo -e "\033[1;33m[*] Waiting for MariaDB socket...\033[0m"
    fi
    ensure_pma_storage

    echo -e "\033[1;34m[+] Starting Redis...\033[0m"
    mkdir -p "$PREFIX/var/lib/redis" "$PREFIX/var/log"
    if ! pgrep -f redis-server > /dev/null; then
        if [ -f "$PREFIX/etc/redis.conf" ]; then
            redis-server "$PREFIX/etc/redis.conf" > /dev/null 2>&1
        else
            redis-server --daemonize yes --ignore-warnings ARM64-COW-BUG > /dev/null 2>&1
        fi
    fi
    echo -e "\033[1;34m[+] Starting PHP-FPM...\033[0m"
    pgrep -f php-fpm > /dev/null || php-fpm > /dev/null 2>&1
    echo -e "\033[1;34m[+] Starting Nginx...\033[0m"
    pgrep -f nginx > /dev/null || nginx > /dev/null 2>&1
    sleep 1.5
    echo -e "\033[1;32m[OK] Services started successfully.\033[0m"
    echo -e "\033[1;33m[*] Opening http://localhost:8080 in browser...\033[0m"
    open_browser
    sleep 1
}}

stop_services() {{
    is_tunnel_running && disable_internet
    echo -e "\033[1;33m[*] Stopping all services (graceful)...\033[0m"
    stop_mariadb_cleanly
    pkill -f nginx > /dev/null 2>&1
    pkill -f php-fpm > /dev/null 2>&1
    pkill -f redis-server > /dev/null 2>&1
    echo -e "\033[1;31m[OK] All services stopped safely.\033[0m"
    sleep 1
}}

restart_services() {{ stop_services; sleep 1; start_services; }}

enable_internet() {{
    if ! server_is_running; then
        echo -e "\033[1;31m[!] Server is not running.\033[0m"
        sleep 2
        return
    fi
    is_tunnel_running && {{ echo -e "\033[1;33m[i] Tunnel already running.\033[0m"; sleep 1.5; return; }}
    has_internet || {{ echo -e "\033[1;31m[!] No internet.\033[0m"; sleep 2; return; }}
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
        FOUND_URL=$(grep -oE 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | head -n1)
        [ -n "$FOUND_URL" ] && break
    done
    if [ -n "$FOUND_URL" ]; then
        echo "$FOUND_URL" > "$TUNNEL_URL_FILE"
        echo -e "\033[1;32m[OK] Global URL: $FOUND_URL\033[0m"
    else
        echo -e "\033[1;31m[!] Failed to obtain tunnel URL.\033[0m"
        disable_internet
    fi
    sleep 2
}}

disable_internet() {{
    is_tunnel_running || {{ echo -e "\033[1;33m[i] Tunnel already disabled.\033[0m"; sleep 1; return; }}
    echo -e "\033[1;33m[*] Stopping Cloudflare tunnel...\033[0m"
    if [ -f "$TUNNEL_PID_FILE" ]; then
        TPID=$(cat "$TUNNEL_PID_FILE" 2>/dev/null)
        [ -n "$TPID" ] && {{ kill "$TPID" 2>/dev/null; sleep 1; kill -9 "$TPID" 2>/dev/null; }}
    fi
    pkill -f "cloudflared tunnel" > /dev/null 2>&1
    rm -f "$TUNNEL_PID_FILE" "$TUNNEL_URL_FILE" "$TUNNEL_LOG"
    echo -e "\033[1;31m[OK] Internet tunnel disabled.\033[0m"
    sleep 1
}}

quickstart_menu() {{
    if ! server_is_running; then
        echo -e "\033[1;31m[!] The server is not running.\033[0m"
        echo -e "\033[1;33m    Please start it first: myserver start\033[0m"
        sleep 3
        return
    fi
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
    WP_DIR="$HTDOCS_DIR/wordpress"
    [ -d "$WP_DIR" ] && {{ echo -e "\033[1;31m[!] $WP_DIR exists.\033[0m"; read -p "Enter..."; return; }}
    echo -e "\033[1;33m[*] Downloading WordPress...\033[0m"
    mkdir -p "$PREFIX/tmp"
    curl -sL https://wordpress.org/latest.tar.gz -o "$PREFIX/tmp/wordpress.tar.gz"
    [ ! -s "$PREFIX/tmp/wordpress.tar.gz" ] && {{ echo -e "\033[1;31m[!] Download failed.\033[0m"; read -p "Enter..."; return; }}
    tar -xf "$PREFIX/tmp/wordpress.tar.gz" -C "$HTDOCS_DIR"
    rm -f "$PREFIX/tmp/wordpress.tar.gz"
    if [ -S "$MARIADB_SOCKET" ]; then
        "$MYSQL_CLI" -u root --socket="$MARIADB_SOCKET" -e "CREATE DATABASE IF NOT EXISTS wordpress DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" 2>/dev/null
    fi
    chmod 755 "$HTDOCS_DIR" 2>/dev/null
    find "$HTDOCS_DIR" -type d -exec chmod 755 {{}} \; 2>/dev/null
    find "$HTDOCS_DIR" -type f -exec chmod 644 {{}} \; 2>/dev/null
    echo -e "\033[1;32m[✓] WordPress installed!\033[0m"
    echo -e " URL: \033[1;34mhttp://localhost:8080/wordpress\033[0m"
    read -p "Press Enter to continue..."
}}

install_laravel() {{
    command -v composer &> /dev/null || pkg install composer -y
    read -p "Project folder name [default: laravel]: " PROJECT_NAME
    PROJECT_NAME=${{PROJECT_NAME:-laravel}}
    LARAVEL_DIR="$HTDOCS_DIR/$PROJECT_NAME"
    [ -d "$LARAVEL_DIR" ] && {{ echo -e "\033[1;31m[!] Exists.\033[0m"; read -p "Enter..."; return; }}
    composer create-project --prefer-dist laravel/laravel "$LARAVEL_DIR"
    DB_NAME=$(echo "$PROJECT_NAME" | tr '-' '_')
    if [ -S "$MARIADB_SOCKET" ]; then
        "$MYSQL_CLI" -u root --socket="$MARIADB_SOCKET" -e "CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" 2>/dev/null
    fi
    chmod 755 "$HTDOCS_DIR" 2>/dev/null
    find "$HTDOCS_DIR" -type d -exec chmod 755 {{}} \; 2>/dev/null
    find "$HTDOCS_DIR" -type f -exec chmod 644 {{}} \; 2>/dev/null
    echo -e "\033[1;32m[✓] Laravel installed!\033[0m"
    echo -e " URL: \033[1;34mhttp://localhost:8080/$PROJECT_NAME/public\033[0m"
    read -p "Press Enter to continue..."
}}

install_nextcloud() {{
    NC_DIR="$HTDOCS_DIR/nextcloud"
    [ -d "$NC_DIR" ] && {{ echo -e "\033[1;31m[!] Exists.\033[0m"; read -p "Enter..."; return; }}
    mkdir -p "$PREFIX/tmp"
    curl -sL https://download.nextcloud.com/server/releases/latest.zip -o "$PREFIX/tmp/nextcloud.zip"
    [ ! -s "$PREFIX/tmp/nextcloud.zip" ] && {{ echo -e "\033[1;31m[!] Download failed.\033[0m"; read -p "Enter..."; return; }}
    unzip -q "$PREFIX/tmp/nextcloud.zip" -d "$HTDOCS_DIR"
    rm -f "$PREFIX/tmp/nextcloud.zip"
    NC_DB_PASS=$(head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 20)
    NC_DB_USER="ncuser"
    if [ -S "$MARIADB_SOCKET" ]; then
        "$MYSQL_CLI" -u root --socket="$MARIADB_SOCKET" <<SQL 2>/dev/null
CREATE DATABASE IF NOT EXISTS nextcloud DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$NC_DB_USER'@'127.0.0.1' IDENTIFIED BY '$NC_DB_PASS';
CREATE USER IF NOT EXISTS '$NC_DB_USER'@'localhost' IDENTIFIED BY '$NC_DB_PASS';
GRANT ALL PRIVILEGES ON nextcloud.* TO '$NC_DB_USER'@'127.0.0.1';
GRANT ALL PRIVILEGES ON nextcloud.* TO '$NC_DB_USER'@'localhost';
FLUSH PRIVILEGES;
SQL
    fi
    chmod 755 "$HTDOCS_DIR" 2>/dev/null
    find "$HTDOCS_DIR" -type d -exec chmod 755 {{}} \; 2>/dev/null
    find "$HTDOCS_DIR" -type f -exec chmod 644 {{}} \; 2>/dev/null
    echo -e "\033[1;32m[✓] Nextcloud installed!\033[0m"
    echo -e " DB User: \033[1;33m$NC_DB_USER\033[0m"
    echo -e " DB Pass: \033[1;33m$NC_DB_PASS\033[0m  \033[1;31m(save this!)\033[0m"
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
        [ "$MODE" = "auto" ] && sleep 1.2 || {{ echo -e "\033[1;31m[!] Connection failed.\033[0m"; read -p "Enter..."; }}
        return
    fi
    REMOTE_VER=$(grep -oP 'CURRENT_VERSION\s*=\s*"\K[^"]+' "$TMP_UPD" 2>/dev/null || echo "0.0.0")
    echo -e "  - Installed : \033[1;33m$LOCAL_VER\033[0m"
    echo -e "  - Remote    : \033[1;32m$REMOTE_VER\033[0m"

    if [ "$LOCAL_VER" != "$REMOTE_VER" ]; then
        echo -e "\n\033[1;35m[!] New version ($REMOTE_VER) available!\033[0m"
        echo -e "\033[1;33m[*] Changelog:\033[0m"
        PARSER="$PREFIX/tmp/changelog_parser.py"
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
        print("  - General fixes.")
except Exception:
    print("  - General fixes.")
PYEOF
        python3 "$PARSER" "$TMP_UPD"
        rm -f "$PARSER"
        echo ""
        read -p "Download and install update now? (y/N): " confirm
        case "$confirm" in
            [yY]*)
                echo -e "\033[1;33m[*] Stopping services...\033[0m"
                stop_services
                echo -e "\033[1;34m[*] Installing update (DBs+htdocs preserved)...\033[0m"
                MYSERVER_SKIP_AUTOUPDATE=1 MYSERVER_REINSTALL=1 python3 "$TMP_UPD"
                rm -f "$TMP_UPD"
                echo -e "\n\033[1;32m[OK] Updated to $REMOTE_VER!\033[0m"
                read -r
                export MYSERVER_SKIP_AUTOUPDATE=1
                exec "$PREFIX/bin/myserver"
                ;;
            *)
                rm -f "$TMP_UPD"
                [ "$MODE" != "auto" ] && read -p "Enter..." || sleep 1
                ;;
        esac
    else
        echo -e "\033[1;32m[OK] Already on latest ($LOCAL_VER).\033[0m"
        rm -f "$TMP_UPD"
        [ "$MODE" != "auto" ] && read -p "Enter..." || sleep 1.2
    fi
}}

reinstall_server() {{
    echo -e "\033[1;35m============================================\033[0m"
    echo -e "\033[1;35m   REINSTALL MYSERVER STACK (Fix Issues)    \033[0m"
    echo -e "\033[1;35m============================================\033[0m"
    echo -e " \033[1;32m✓\033[0m Databases will be \033[1;32mpreserved\033[0m"
    echo -e " \033[1;32m✓\033[0m htdocs contents will be \033[1;32mpreserved\033[0m"
    echo -e " \033[1;33m↻\033[0m phpMyAdmin will be \033[1;33mupdated\033[0m to latest"
    echo ""
    read -p "Reinstall myserver? (y/N): " confirm
    case "$confirm" in
        [yY]*)
            echo -e "\033[1;36m[*] Downloading latest installer...\033[0m"
            mkdir -p "$PREFIX/tmp"
            TMP_UPD="$PREFIX/tmp/install_server_latest.py"
            curl -sL --max-time 30 "$GITHUB_RAW_URL/install_server.py" -o "$TMP_UPD" 2>/dev/null
            if [ ! -s "$TMP_UPD" ]; then
                echo -e "\033[1;31m[!] Download failed.\033[0m"
                rm -f "$TMP_UPD"
                read -p "Enter..."
                return
            fi
            stop_services
            echo -e "\033[1;34m[*] Reinstalling (DBs+htdocs preserved)...\033[0m"
            MYSERVER_SKIP_AUTOUPDATE=1 MYSERVER_REINSTALL=1 python3 "$TMP_UPD"
            rm -f "$TMP_UPD"
            echo -e "\n\033[1;32m[OK] Reinstall completed!\033[0m"
            read -r
            export MYSERVER_SKIP_AUTOUPDATE=1
            exec "$PREFIX/bin/myserver"
            ;;
        *) echo -e "\033[1;36m[INFO] Cancelled.\033[0m"; sleep 1 ;;
    esac
}}

uninstall_server() {{
    echo -e "\033[1;31m============================================\033[0m"
    echo -e "\033[1;31m   WARNING: UNINSTALL MYSERVER STACK        \033[0m"
    echo -e "\033[1;31m============================================\033[0m"
    echo -e " This will \033[1;31mPERMANENTLY DELETE\033[0m:"
    echo -e "   \033[1;31m✗\033[0m All server configuration files"
    echo -e "   \033[1;31m✗\033[0m \033[1;31mALL user databases\033[0m (WordPress, Nextcloud, Laravel, ...)"
    echo -e "   \033[1;31m✗\033[0m The MariaDB data directory"
    echo -e "   \033[1;31m✗\033[0m The web root: \033[1;33m$HTDOCS_DIR\033[0m (including ALL contents)"
    echo -e "   \033[1;31m✗\033[0m ~/.my.cnf and the myserver CLI"
    echo ""
    read -p $'\033[1;31mAre you sure? Type "yes" to confirm: \033[0m' confirm
    case "$confirm" in
        yes|YES|Yes|y|Y|[yY][eE][sS])
            stop_services

            echo -e "\033[1;33m[*] Starting MariaDB to drop databases...\033[0m"
            if start_mariadb_background; then
                DBS=$("$MYSQL_CLI" -u root --socket="$MARIADB_SOCKET" -N -B -e \
                    "SHOW DATABASES WHERE \`Database\` NOT IN ('mysql','information_schema','performance_schema','sys');" 2>/dev/null)
                for db in $DBS; do
                    [ -z "$db" ] && continue
                    echo -e "  \033[1;31m✗\033[0m Dropping database: \033[1;33m$db\033[0m"
                    "$MYSQL_CLI" -u root --socket="$MARIADB_SOCKET" -e "DROP DATABASE IF EXISTS \`$db\`;" 2>/dev/null
                done
                echo -e "\033[1;32m[OK] All user databases dropped.\033[0m"
                stop_mariadb_cleanly
            else
                echo -e "\033[1;33m[!] MariaDB failed to start — proceeding without DB drop.\033[0m"
            fi

            echo -e "\033[1;33m[*] Removing configuration files...\033[0m"
            rm -rf "$PREFIX/etc/nginx/ssl"
            rm -f "$PREFIX/etc/nginx/nginx.conf"
            rm -f "$PREFIX/etc/php-fpm.d/www.conf"
            rm -f "$VERSION_FILE"
            rm -f "$TUNNEL_PID_FILE" "$TUNNEL_URL_FILE" "$TUNNEL_LOG"
            rm -f "$PREFIX/etc/myserver_htdocs_path"
            rm -f "$HOME/.my.cnf"

            for ext in gd sodium redis apcu imagick mysqli pdo_mysql mbstring openssl curl zip xml intl bcmath; do
                rm -f "$PHP_CONFD_DIR/$ext.ini"
            done

            echo -e "\033[1;33m[*] Removing MariaDB data directory...\033[0m"
            rm -rf "$MYSQL_DATA_DIR"
            rm -rf "$MYSQL_RUN_DIR"
            echo -e "\033[1;32m[OK] MariaDB data wiped.\033[0m"

            echo -e "\033[1;33m[*] Removing web root and its contents...\033[0m"
            rm -rf "$HTDOCS_DIR"
            echo -e "\033[1;32m[OK] Web root deleted.\033[0m"

            rm -f "$PREFIX/bin/myserver"
            echo ""
            echo -e "\033[1;32m[✓] Uninstalled completely.\033[0m"
            exit 0
            ;;
        *) echo -e "\033[1;36m[INFO] Uninstall cancelled.\033[0m"; sleep 1 ;;
    esac
}}

if [ -n "$1" ]; then
    case "$1" in
        start) start_services ;;
        stop) stop_services ;;
        restart) restart_services ;;
        status) show_banner_and_status; read -p "Press Enter..." ;;
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

if [ -z "$MYSERVER_SKIP_AUTOUPDATE" ]; then
    echo -e "\033[1;36m[*] Checking for updates...\033[0m"
    sleep 0.6
    update_server auto
fi

while true; do
    show_banner_and_status
    if server_is_running; then
        SERVER_RUNNING=1
    else
        SERVER_RUNNING=0
    fi

    if [ "$SERVER_RUNNING" -eq 1 ]; then
        echo -e "\033[1;33mSelect an option:\033[0m"
        echo -e "\033[1;33m 1) stop             (Stop all services)\033[0m"
        is_tunnel_running && echo -e "\033[1;33m 2) Disable Internet (disable internet access)\033[0m" || echo -e "\033[1;33m 2) Enable Internet  (enable internet access)\033[0m"
        echo -e "\033[1;33m 3) restart          (Restart all services)\033[0m"
        echo -e "\033[1;33m 4) quickstart       (Install WP / Laravel / Nextcloud)\033[0m"
        echo -e "\033[1;33m 5) refresh status   (Re-check server status)\033[0m"
        echo -e "\033[1;33m 6) update           (Check and apply updates)\033[0m"
        echo -e "\033[1;33m 7) reinstall        (To fix issues — keeps DBs+htdocs)\033[0m"
        echo -e "\033[1;33m 8) uninstall        (Remove server + DBs + htdocs)\033[0m"
        echo -e "\033[1;33m 9) exit             (Exit & Stop Server)\033[0m"
        echo ""
        read -p $'\033[1;33mEnter choice [1-9]: \033[0m' choice
        case "$choice" in
            1|stop) stop_services ;;
            2) is_tunnel_running && disable_internet || enable_internet ;;
            3|restart) restart_services ;;
            4|quickstart) quickstart_menu ;;
            5|refresh) continue ;;
            6|update) update_server manual ;;
            7|reinstall) reinstall_server ;;
            8|uninstall|delete) uninstall_server ;;
            9|exit) stop_services; echo -e "\033[1;32mServer stopped.\033[0m"; exit 0 ;;
            *) echo -e "\033[1;31mInvalid.\033[0m"; sleep 1 ;;
        esac
    else
        echo -e "\033[1;33mSelect an option:\033[0m"
        echo -e "\033[1;33m 1) start            (Start all services)\033[0m"
        echo -e "\033[1;33m 2) refresh status   (Re-check server status)\033[0m"
        echo -e "\033[1;33m 3) update           (Check and apply updates)\033[0m"
        echo -e "\033[1;33m 4) reinstall        (To fix issues — keeps DBs+htdocs)\033[0m"
        echo -e "\033[1;33m 5) uninstall        (Remove server + DBs + htdocs)\033[0m"
        echo -e "\033[1;33m 6) exit\033[0m"
        echo ""
        read -p $'\033[1;33mEnter choice [1-6]: \033[0m' choice
        case "$choice" in
            1|start) start_services ;;
            2|refresh) continue ;;
            3|update) update_server manual ;;
            4|reinstall) reinstall_server ;;
            5|uninstall|delete) uninstall_server ;;
            6|exit) echo -e "\033[1;32mBye!\033[0m"; exit 0 ;;
            *) echo -e "\033[1;31mInvalid.\033[0m"; sleep 1 ;;
        esac
    fi
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


# ===========================================================================
# Cleanup
# ===========================================================================
def cleanup_repository():
    try:
        cwd = Path.cwd().resolve()
        forbidden = {HOME, PREFIX, Path('/'), Path('/data'),
                     Path('/data/data'), Path('/data/data/com.termux'),
                     Path('/data/data/com.termux/files')}
        if cwd in forbidden:
            return
        if not (cwd / "install_server.py").exists() or not (cwd / ".git").exists():
            return
        try:
            result = subprocess.run(["git", "-C", str(cwd), "remote", "-v"],
                                    capture_output=True, text=True, timeout=5)
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


# ===========================================================================
# Main
# ===========================================================================
def main():
    global HTDOCS_DIR, DB_ROOT_PASSWORD, REINSTALL_MODE

    try:
        existing_data = (MYSQL_DATA_DIR / "mysql").exists()
        existing_cnf = MY_CNF_FILE.exists()
        REINSTALL_MODE = existing_data and existing_cnf
        if os.environ.get("MYSERVER_REINSTALL") == "1":
            REINSTALL_MODE = True

        if REINSTALL_MODE:
            print(f"\033[1;33m[+] Reinstall mode — v{CURRENT_VERSION} \033[0m")
            print("\033[1;32m [✓] Databases will be preserved \033[0m")
            print("\033[1;32m [✓] htdocs will be preserved \033[0m")
            print("\033[1;33m [↻] phpMyAdmin will be refreshed \033[0m")
        else:
            print(f"\033[1;33m[+] Deploying Advanced Nginx + PHP-FPM Server Stack v{CURRENT_VERSION}...\033[0m")

        ensure_fzf()

        saved_path = None
        if HTDOCS_PATH_FILE.exists():
            try:
                saved_path = HTDOCS_PATH_FILE.read_text().strip()
            except Exception:
                saved_path = None

        if saved_path:
            HTDOCS_DIR = Path(saved_path)
            print(f"\033[1;36m [i] Web root: {HTDOCS_DIR} \033[0m")
        else:
            HTDOCS_DIR = ask_web_root_location()
            try:
                HTDOCS_PATH_FILE.parent.mkdir(parents=True, exist_ok=True)
                HTDOCS_PATH_FILE.write_text(str(HTDOCS_DIR))
            except Exception:
                pass
            print(f"\033[1;32m [✓] Web root set to: {HTDOCS_DIR} \033[0m")

        if REINSTALL_MODE:
            DB_ROOT_PASSWORD = read_password_from_my_cnf()
            if DB_ROOT_PASSWORD:
                print("\033[1;36m [i] Reusing existing MariaDB password from ~/.my.cnf \033[0m")
            else:
                print("\033[1;36m [i] MariaDB root has no password (preserved). \033[0m")
        else:
            print()
            DB_ROOT_PASSWORD = ask_db_password()
            if DB_ROOT_PASSWORD:
                print("\033[1;32m [✓] MariaDB root password will be set. \033[0m")
            else:
                print("\033[1;33m [i] MariaDB root will have NO password. \033[0m")
            print()

        ini_path = get_php_ini_path()
        if ini_path.exists():
            removed = clean_php_ini_legacy(ini_path)
            if removed:
                print(f"\033[1;33m [*] Removed {removed} legacy 'extension=' line(s). \033[0m")

        php_ext_pkgs = " ".join(sorted(set(PHP_EXT_PACKAGES.values())))
        core_pkgs = ("nginx php php-fpm mariadb redis openssl-tool "
                     "curl tar unzip git wget cloudflared fzf")
        install_cmd = f"pkg install -y {core_pkgs} {php_ext_pkgs}"

        steps = [
            ("Updating Packages", "pkg update -y"),
            ("Storage Setup", None),
            ("Installing Core Software", install_cmd),
            ("MariaDB Initialization", setup_mariadb),
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
                if not (HOME / "storage").exists() and "storage" in str(HTDOCS_DIR):
                    subprocess.run("termux-setup-storage", shell=True)
                    time.sleep(3)
            elif callable(action):
                if not action():
                    raise Exception(f"Failed at step: {desc}")
            elif isinstance(action, str):
                run_cmd(action)

        enforce_htdocs_permissions()
        print_htdocs_diagnostic()
        if not verify_htdocs_readable():
            print("\033[1;33m [!] Web root readability check FAILED. \033[0m")
        else:
            print("\033[1;32m [✓] Web root is readable by all users. \033[0m")

        print("\033[1;34m[+] Stopping MariaDB (post-install)...\033[0m")
        stop_mariadb_cleanly()
        if is_process_running("mariadbd") or is_process_running("mysqld"):
            print("\033[1;33m [!] MariaDB still running after shutdown. \033[0m")
        else:
            print("\033[1;32m [✓] MariaDB stopped cleanly. \033[0m")

        print(f"\n\033[1;32m[✓] {'Reinstall' if REINSTALL_MODE else 'Server Stack Deployed'} Successfully!\033[0m")
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