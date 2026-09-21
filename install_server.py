#!/data/data/com.termux/files/usr/bin/python3

import os
import sys
import time
import shutil
import re
import subprocess
import random
import string
from pathlib import Path

# Current Version & Release Notes
CURRENT_VERSION = "1.6.5"
CHANGELOG = [
    "Added Developer information section to the CLI status interface",
    "Preserved ARM64 kernel warning bypass for Redis on Android",
    "Maintained full English interactive interface and session re-exec logic"
]

# System and Environment Paths
PREFIX = Path(os.environ.get('PREFIX', '/data/data/com.termux/files/usr'))
HOME = Path.home()
HTDOCS_DIR = HOME / "storage/shared/htdocs"
NGINX_DIR = PREFIX / "etc/nginx"
PHP_FPM_DIR = PREFIX / "etc/php-fpm.d"
SSL_DIR = NGINX_DIR / "ssl"
TMP_DIR = PREFIX / "tmp"
VERSION_FILE = PREFIX / "etc/myserver_version"
REPO_DIR = Path(__file__).resolve().parent

GITHUB_RAW_URL = "https://raw.githubusercontent.com/elias0esmail/termux-web-server/main"

def run_cmd(cmd, check=False):
    return subprocess.run(cmd, shell=True, check=check, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def setup_mariadb():
    try:
        data_dir = PREFIX / "var/lib/mysql"
        run_dir = PREFIX / "var/run"
        data_dir.mkdir(parents=True, exist_ok=True)
        run_dir.mkdir(parents=True, exist_ok=True)
        if not (data_dir / "mysql").exists():
            run_cmd(f"mariadb-install-db --datadir='{data_dir}'")
            print("\033[1;32m [✓] MariaDB database initialized. \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] MariaDB init error: {e}\033[0m")
        return False

def setup_redis():
    try:
        redis_data = PREFIX / "var/lib/redis"
        log_dir = PREFIX / "var/log"
        redis_data.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)
        
        redis_conf = PREFIX / "etc/redis.conf"
        redis_conf_content = f"dir {redis_data}\nport 6379\nbind 127.0.0.1\ndaemonize yes\nlogfile {log_dir}/redis.log\nignore-warnings ARM64-COW-BUG\n"
        redis_conf.write_text(redis_conf_content)
        
        print("\033[1;32m [✓] Redis configured (ARM64 warning suppressed). \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] Redis init error: {e}\033[0m")
        return False

def setup_php_fpm():
    try:
        PHP_FPM_DIR.mkdir(parents=True, exist_ok=True)
        www_conf = PHP_FPM_DIR / "www.conf"
        
        conf_content = """\
[www]
user = nobody
group = nobody
listen = 127.0.0.1:9000
pm = dynamic
pm.max_children = 10
pm.start_servers = 2
pm.min_spare_servers = 1
pm.max_spare_servers = 3
"""
        www_conf.write_text(conf_content)
        print("\033[1;32m [✓] PHP-FPM configured (Port 9000). \033[0m")
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
""")
        run_cmd(f"openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout '{key_path}' -out '{cert_path}' -config '{openssl_cnf}'")
        print("\033[1;32m [✓] SSL Certificates generated. \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] SSL generation error: {e}\033[0m")
        return False

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
    gzip on;

    # HTTP Server (Port 8080)
    server {{
        listen 8080;
        listen [::]:8080;
        server_name localhost;
        root {HTDOCS_DIR};
        index index.php index.html;

        location / {{
            try_files $uri $uri/ /index.php?$query_string;
        }}

        location ~ \\.php$ {{
            fastcgi_pass 127.0.0.1:9000;
            fastcgi_index index.php;
            include fastcgi_params;
            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        }}
    }}

    # HTTPS Server (Port 8443)
    server {{
        listen 8443 ssl;
        listen [::]:8443 ssl;
        server_name localhost;

        ssl_certificate "{cert_path}";
        ssl_certificate_key "{key_path}";
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;

        root {HTDOCS_DIR};
        index index.php index.html;

        location / {{
            try_files $uri $uri/ /index.php?$query_string;
        }}

        location ~ \\.php$ {{
            fastcgi_pass 127.0.0.1:9000;
            fastcgi_index index.php;
            include fastcgi_params;
            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        }}
    }}
}}
"""
        conf_path.write_text(nginx_config)
        print("\033[1;32m [✓] Nginx configured with PHP-FPM & SSL. \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] Nginx config error: {e}\033[0m")
        return False

def create_php_ini():
    php_ini_path = PREFIX / 'etc/php/php.ini'
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    
    php_ini_content = f"""\
upload_max_filesize = 256M
post_max_size = 512M
memory_limit = 512M
max_execution_time = 180
error_reporting = E_ALL & ~E_DEPRECATED
display_errors = On
date.timezone = UTC

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

; Enable extensions
extension=mysqli
extension=pdo_mysql
extension=mbstring
extension=openssl
extension=curl
extension=zip
extension=gd
"""
    try:
        php_ini_path.parent.mkdir(parents=True, exist_ok=True)
        php_ini_path.write_text(php_ini_content)
        print("\033[1;32m [✓] php.ini updated & PHP Sessions initialized. \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] php.ini error: {e}\033[0m")
        return False

def setup_htdocs():
    try:
        HTDOCS_DIR.mkdir(parents=True, exist_ok=True)
        (HTDOCS_DIR / "index.php").write_text("<?php echo '<h1>Nginx + PHP-FPM Server is Running!</h1>'; ?>")
        
        info_dir = HTDOCS_DIR / "phpinfo"
        info_dir.mkdir(exist_ok=True)
        (info_dir / "index.php").write_text("<?php phpinfo(); ?>")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] htdocs error: {e}\033[0m")
        return False

def install_phpmyadmin():
    pma_dir = HTDOCS_DIR / "phpmyadmin"
    is_update = pma_dir.exists()

    try:
        if is_update:
            print("\033[1;34m [*] Checking and updating phpMyAdmin to latest version... \033[0m")
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
            secret = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
            content = config_sample.read_text()
            content = re.sub(r"\$cfg\['blowfish_secret'\]\s*=\s*'';|\$cfg\['blowfish_secret'\]\s*=\s*\".*\";", f"$cfg['blowfish_secret'] = '{secret}';", content)
            content = re.sub(r"\$cfg\['Servers'\]\[\$i\]\['AllowNoPassword'\]\s*=\s*false;", "$cfg['Servers'][$i]['AllowNoPassword'] = true;", content)
            content = re.sub(r"\$cfg\['Servers'\]\[\$i\]\['host'\]\s*=\s*'localhost';", "$cfg['Servers'][$i]['host'] = '127.0.0.1';", content)
            
            pma_tmp = pma_dir / "tmp"
            pma_tmp.mkdir(exist_ok=True)
            content += f"\n$cfg['TempDir'] = '{pma_tmp}';\n"
            
            config_file.write_text(content)

        pma_tmp = pma_dir / "tmp"
        pma_tmp.mkdir(exist_ok=True)

        if is_update:
            print("\033[1;32m [✓] phpMyAdmin updated to latest version successfully. \033[0m")
        else:
            print("\033[1;32m [✓] phpMyAdmin installed with login configuration. \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] phpMyAdmin error: {e}\033[0m")
        return False

def create_myserver_cli():
    bin_path = PREFIX / "bin/myserver"
    VERSION_FILE.write_text(CURRENT_VERSION)

    script_content = f"""#!/data/data/com.termux/files/usr/bin/bash

PREFIX="{PREFIX}"
HTDOCS_DIR="{HTDOCS_DIR}"
VERSION_FILE="{VERSION_FILE}"
GITHUB_RAW_URL="{GITHUB_RAW_URL}"

show_banner_and_status() {{
    clear
    echo -e "\\033[1;36m"
    echo "  __  __       _____                                "
    echo " |  \\/  |     / ____|                               "
    echo " | \\  / |0_ _| (___   ___  _ __ __   _____ _ __ "
    echo " | |\\/| | | | |\\___ \\ / _ \\| '__|\\ \\ / / _ \\ '__|"
    echo " | |  | | |_| |____) |  __/| |    \\ V /  __/ |   "
    echo " |_|  |_|\\__, |_____/ \\___||_|     \\_/ \\___|_|   "
    echo "          __/ |                                  "
    echo "         |___/        Server Manager v{CURRENT_VERSION}  "
    echo -e "\\033[0m"

    echo -e "\\033[1;33m═════════════════ [ DEVELOPER INFO ] ═════════════════\\033[0m"
    echo -e " 👤 Developer : \\033[1;37mElias Esmail\\033[0m"
    echo -e " 📱 WhatsApp  : \\033[1;32mhttps://api.whatsapp.com/send?phone=967771902342\\033[0m"
    echo -e " 🔗 GitHub    : \\033[1;36mhttps://github.com/elias0esmail\\033[0m"
    echo -e "\\033[1;33m══════════════════════════════════════════════════════\\033[0m\\n"
    
    echo -e "\\033[1;35m═════════════════ [ SERVICES STATUS ] ═════════════════\\033[0m"
    pgrep -f nginx > /dev/null && echo -e " Nginx:    \\033[1;32mRunning [✓]\\033[0m" || echo -e " Nginx:    \\033[1;31mStopped [✗]\\033[0m"
    pgrep -f php-fpm > /dev/null && echo -e " PHP-FPM:  \\033[1;32mRunning [✓]\\033[0m" || echo -e " PHP-FPM:  \\033[1;31mStopped [✗]\\033[0m"
    pgrep -f "mariadb|mysqld" > /dev/null && echo -e " MariaDB:  \\033[1;32mRunning [✓]\\033[0m" || echo -e " MariaDB:  \\033[1;31mStopped [✗]\\033[0m"
    pgrep -f redis-server > /dev/null && echo -e " Redis:    \\033[1;32mRunning [✓]\\033[0m" || echo -e " Redis:    \\033[1;31mStopped [✗]\\033[0m"
    echo -e "\\033[1;35m═══════════════════════════════════════════════════════\\033[0m\\n"

    if pgrep -f nginx > /dev/null || pgrep -f php-fpm > /dev/null || pgrep -f "mariadb|mysqld" > /dev/null || pgrep -f redis-server > /dev/null; then
        echo -e "\\033[1;36m═════════════════ [ SERVER INFORMATION ] ═════════════════\\033[0m"
        echo -e " 📂 Web Root Path : \\033[1;33m$HTDOCS_DIR\\033[0m"
        echo -e " 🌐 HTTP URL     : \\033[1;34mhttp://localhost:8080\\033[0m"
        echo -e " 🔒 HTTPS URL    : \\033[1;32mhttps://localhost:8443\\033[0m"
        echo -e " 🗄️  phpMyAdmin   : \\033[1;35mhttp://localhost:8080/phpmyadmin\\033[0m"
        echo -e "\\033[1;36m══════════════════════════════════════════════════════════\\033[0m\\n"
    fi

}}

start_services() {{
    echo -e "\\033[1;34m[+] Starting MariaDB...\\033[0m"
    mkdir -p "$PREFIX/var/lib/mysql" "$PREFIX/var/run"
    if ! pgrep -f "mariadb|mysqld" > /dev/null; then
        if [ ! -d "$PREFIX/var/lib/mysql/mysql" ]; then
            mariadb-install-db --datadir="$PREFIX/var/lib/mysql" > /dev/null 2>&1
        fi
        if command -v mariadbd-safe &> /dev/null; then
            mariadbd-safe --datadir="$PREFIX/var/lib/mysql" > /dev/null 2>&1 &
        elif command -v mysqld_safe &> /dev/null; then
            mysqld_safe --datadir="$PREFIX/var/lib/mysql" > /dev/null 2>&1 &
        else
            mariadbd --datadir="$PREFIX/var/lib/mysql" > /dev/null 2>&1 &
        fi
    fi

    echo -e "\\033[1;34m[+] Starting Redis...\\033[0m"
    mk