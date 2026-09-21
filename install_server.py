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
CURRENT_VERSION = "2.0.3"
CHANGELOG = [
    "Fixed Nginx configuration syntax error caused by unescaped variable in f-string",
    "Shortened option 2 menu text to Enable/Disable Internet with description",
    "Updated menu UI colors for all options to yellow",
    "Maintained Cloudflare Tunnel and PHP 8.x/Python 3.12+ compatibility"
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
TUNNEL_LOG = TMP_DIR / "cloudflared.log"
TUNNEL_URL_FILE = TMP_DIR / "cloudflared_url.txt"
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

        openssl_cnf = SSL_DIR / "openssl.cnf"
        openssl_cnf.write_text("""\
[req]
distinguished_name = req_distinguished_name
x509_extensions = v3_req
prompt = no

[req_distinguished_name]
C = YE
ST = Sanaa
L = Sanaa
O = Termux Development Server
OU = Local Dev
CN = localhost

[v3_req]
basicConstraints = CA:FALSE
keyUsage = nonRepudiation, digitalSignature, keyEncipherment
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
IP.1 = 127.0.0.1
""")
        run_cmd(f"openssl req -x509 -nodes -days 365 -newkey rsa:2048 -keyout '{key_path}' -out '{cert_path}' -config '{openssl_cnf}'")
        
        public_cert = HOME / "storage/shared/server.crt"
        if (HOME / "storage/shared").exists():
            shutil.copy(cert_path, public_cert)

        print("\033[1;32m [✓] SSL Certificates generated (v3_req SAN enabled). \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] SSL generation error: {e}\033[0m")
        return False

def setup_nginx():
    try:
        conf_path = NGINX_DIR / "nginx.conf"
        cert_path = SSL_DIR / "server.crt"
        key_path = SSL_DIR / "server.key"
        
        (PREFIX / "var/log/nginx").mkdir(parents=True, exist_ok=True)
        (PREFIX / "var/run").mkdir(parents=True, exist_ok=True)

        nginx_config = f"""\
worker_processes 2;
pid {PREFIX}/var/run/nginx.pid;
error_log {PREFIX}/var/log/nginx/error.log info;

events {{ worker_connections 1024; }}

http {{
    include mime.types;
    default_type application/octet-stream;
    sendfile on;
    keepalive_timeout 65;
    gzip on;
    access_log {PREFIX}/var/log/nginx/access.log;

    # HTTP Server (Port 8080)
    server {{
        listen 8080;
        listen [::]:8080;
        server_name localhost;
        root {HTDOCS_DIR};
        index index.php index.html;

        location / {{
            try_files $uri $uri/ /index.php?$args;
        }}

        location ~ \\.php$ {{
            fastcgi_pass 127.0.0.1:9000;
            fastcgi_index index.php;
            include fastcgi_params;
            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        }}

        location ~ /\\.ht {{
            deny all;
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
            try_files $uri $uri/ /index.php?$args;
        }}

        location ~ \\.php$ {{
            fastcgi_pass 127.0.0.1:9000;
            fastcgi_index index.php;
            include fastcgi_params;
            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        }}

        location ~ /\\.ht {{
            deny all;
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
        index_file = HTDOCS_DIR / "index.php"
        if not index_file.exists():
            index_file.write_text("<?php echo '<h1>Nginx + PHP-FPM Server is Running!</h1>'; ?>")
        
        htaccess_file = HTDOCS_DIR / ".htaccess"
        if not htaccess_file.exists():
            htaccess_content = """# Default Apache / Nginx Fallback .htaccess Configuration
<IfModule mod_rewrite.c>
    RewriteEngine On
    RewriteBase /
    RewriteCond %{REQUEST_FILENAME} !-f
    RewriteCond %{REQUEST_FILENAME} !-d
    RewriteRule ^ index.php [L]
</IfModule>
"""
            htaccess_file.write_text(htaccess_content)
            print("\033[1;32m [✓] Default .htaccess file created in root htdocs. \033[0m")

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
HOME_DIR="{HOME}"
HTDOCS_DIR="{HTDOCS_DIR}"
VERSION_FILE="{VERSION_FILE}"
GITHUB_RAW_URL="{GITHUB_RAW_URL}"
CURRENT_VERSION="{CURRENT_VERSION}"
TUNNEL_LOG="$PREFIX/tmp/cloudflared.log"
TUNNEL_URL_FILE="$PREFIX/tmp/cloudflared_url.txt"

check_server_running() {{
    if pgrep -f "nginx" > /dev/null || pgrep -f "php-fpm" > /dev/null || pgrep -f "mariadbd|mysqld" > /dev/null || pgrep -f "redis-server" > /dev/null; then
        return 0
    else
        return 1
    fi
}}

check_auto_update() {{
    if ping -c 1 -W 2 8.8.8.8 > /dev/null 2>&1 || curl -s --connect-timeout 2 https://www.google.com > /dev/null 2>&1; then
        LOCAL_VER=$(cat "$VERSION_FILE" 2>/dev/null || echo "$CURRENT_VERSION")
        TMP_AUTO_UPD="$PREFIX/tmp/install_server_auto_check.py"
        mkdir -p "$PREFIX/tmp"
        
        curl -sL --connect-timeout 3 "$GITHUB_RAW_URL/install_server.py" -o "$TMP_AUTO_UPD"
        
        if [ -s "$TMP_AUTO_UPD" ]; then
            REMOTE_VER=$(python3 -c '
import re
try:
    with open("'"$TMP_AUTO_UPD"'", "r", encoding="utf-8") as f:
        m = re.search(r"CURRENT_VERSION\\s*=\\s*\"([^\"]+)\"", f.read())
        print(m.group(1) if m else "'"$LOCAL_VER"'")
except Exception:
    print("'"$LOCAL_VER"'")
')
            
            if [ "$LOCAL_VER" != "$REMOTE_VER" ] && [ -n "$REMOTE_VER" ]; then
                echo -e "\\n\\033[1;35m══════════════════════════════════════════════════════\\033[0m"
                echo -e "\\033[1;33m 🚀 NEW UPDATE AVAILABLE: Version $REMOTE_VER (Current: $LOCAL_VER)\\033[0m"
                echo -e "\\033[1;35m══════════════════════════════════════════════════════\\033[0m"
                echo -e "\\033[1;36m📋 Release Details & What's New:\\033[0m"
                python3 -c '
import ast, re
try:
    with open("'"$TMP_AUTO_UPD"'", "r", encoding="utf-8") as f:
        content = f.read()
    match = re.search(r"CHANGELOG\\s*=\\s*(\\[.*?\\])", content, re.DOTALL)
    if match:
        log_list = ast.literal_eval(match.group(1))
        for item in log_list:
            print("  • " + str(item))
    else:
        print("  • General fixes, stability improvements, and updates.")
except Exception:
    print("  • General fixes, stability improvements, and updates.")
'
                echo ""
                read -p "Would you like to install this update now? (y/N): " confirm_update
                case "$confirm_update" in
                    [yY][eE][sS]|[yY])
                        echo -e "\\033[1;33m[*] Stopping running services before update...\\033[0m"
                        stop_services
                        echo -e "\\033[1;34m[*] Installing update...\\033[0m"
                        python3 "$TMP_AUTO_UPD"
                        rm -f "$TMP_AUTO_UPD"
                        echo -e "\\n\\033[1;32m[✓] Updated to version $REMOTE_VER successfully!\\033[0m"
                        echo -e "\\033[1;36m[*] Press Enter to launch updated myserver manager...\\033[0m"
                        read -r
                        exec "$PREFIX/bin/myserver"
                        ;;
                    *)
                        echo -e "\\033[1;33m[i] Update postponed. Starting server manager...\\033[0m\\n"
                        rm -f "$TMP_AUTO_UPD"
                        sleep 1
                        ;;
                esac
            else
                rm -f "$TMP_AUTO_UPD"
            fi
        else
            rm -f "$TMP_AUTO_UPD"
        fi
    fi
}}

show_banner_and_status() {{
    clear
    echo -e "\\033[1;36m"
    echo "  __  __       _____                                "
    echo " |  \\\\/  |     / ____|                               "
    echo " | \\\\  / |0_ _| (___   ___  _ __ __   _____ _ __ "
    echo " | |\\\\/| | | | |\\\\___ \\\\ / _ \\\\| '__|\\\\ \\\\ / / _ \\\\ '__|"
    echo " | |  | | |_| |____) |  __/| |    \\\\ V /  __/ |   "
    echo " |_|  |_|\\\\__, |_____/ \\\\___||_|     \\\\_/ \\\\___|_|   "
    echo "          __/ |                                  "
    echo "         |___/        Server Manager v$CURRENT_VERSION  "
    echo -e "\\033[0m"

    echo -e "\\033[1;33m═════════════════ [ DEVELOPER INFO ] ═════════════════\\033[0m"
    echo -e " 👤 Developer : \\033[1;37mElias Esmail\\033[0m"
    echo -e " 📱 WhatsApp  : \\033[1;32m+967771902342\\033[0m"
    echo -e " 🔗 GitHub    : \\033[1;36mhttps://github.com/elias0esmail\\033[0m"
    echo -e "\\033[1;33m══════════════════════════════════════════════════════\\033[0m\\n"
    
    echo -e "\\033[1;35m═════════════════ [ SERVICES STATUS ] ═════════════════\\033[0m"
    pgrep -f "nginx" > /dev/null && echo -e " Nginx:    \\033[1;32mRunning [✓]\\033[0m" || echo -e " Nginx:    \\033[1;31mStopped [✗]\\033[0m"
    pgrep -f "php-fpm" > /dev/null && echo -e " PHP-FPM:  \\033[1;32mRunning [✓]\\033[0m" || echo -e " PHP-FPM:  \\033[1;31mStopped [✗]\\033[0m"
    pgrep -f "mariadbd|mysqld" > /dev/null && echo -e " MariaDB:  \\033[1;32mRunning [✓]\\033[0m" || echo -e " MariaDB:  \\033[1;31mStopped [✗]\\033[0m"
    pgrep -f "redis-server" > /dev/null && echo -e " Redis:    \\033[1;32mRunning [✓]\\033[0m" || echo -e " Redis:    \\033[1;31mStopped [✗]\\033[0m"
    echo -e "\\033[1;35m═══════════════════════════════════════════════════════\\033[0m\\n"

    if check_server_running; then
        echo -e "\\033[1;36m═════════════════ [ SERVER INFORMATION ] ═════════════════\\033[0m"
        echo -e " 📂 Web Root Path : \\033[1;33m$HTDOCS_DIR\\033[0m"
        echo -e " 🌐 HTTP URL     : \\033[1;34mhttp://localhost:8080\\033[0m"
        echo -e " 🔒 HTTPS URL    : \\033[1;32mhttps://localhost:8443\\033[0m"
        echo -e " 🗄️  phpMyAdmin   : \\033[1;35mhttp://localhost:8080/phpmyadmin\\033[0m"
        
        if pgrep -f "cloudflared tunnel" > /dev/null && [ -s "$TUNNEL_URL_FILE" ]; then
            G_URL=$(cat "$TUNNEL_URL_FILE")
            echo -e " 🌍 Global URL    : \\033[1;32m$G_URL\\033[0m"
        else
            echo -e " 🌍 Global URL    : \\033[1;31mdisabled\\033[0m"
        fi
        echo -e "\\033[1;36m══════════════════════════════════════════════════════════\\033[0m\\n"
    fi
}}

start_services() {{
    echo -e "\\033[1;34m[+] Starting MariaDB...\\033[0m"
    mkdir -p "$PREFIX/var/lib/mysql" "$PREFIX/var/run"
    if ! pgrep -f "mariadbd|mysqld" > /dev/null; then
        if [ ! -d "$PREFIX/var/lib/mysql/mysql" ]; then
            mariadb-install-db --datadir="$PREFIX/var/lib/mysql" > /dev/null 2>&1
        fi
        mysqld_safe --datadir="$PREFIX/var/lib/mysql" > /dev/null 2>&1 &
    fi

    echo -e "\\033[1;34m[+] Starting Redis...\\033[0m"
    mkdir -p "$PREFIX/var/lib/redis" "$PREFIX/var/log"
    if ! pgrep -f redis-server > /dev/null; then
        if [ -f "$PREFIX/etc/redis.conf" ]; then
            redis-server "$PREFIX/etc/redis.conf" > /dev/null 2>&1
        else
            redis-server --daemonize yes --ignore-warnings ARM64-COW-BUG > /dev/null 2>&1
        fi
    fi

    echo -e "\\033[1;34m[+] Starting PHP-FPM...\\033[0m"
    if ! pgrep -f php-fpm > /dev/null; then
        php-fpm > /dev/null 2>&1
    fi

    echo -e "\\033[1;34m[+] Starting Nginx...\\033[0m"
    if ! pgrep -f nginx > /dev/null; then
        mkdir -p "$PREFIX/var/log/nginx" "$PREFIX/var/run"
        nginx > /dev/null 2>&1
    fi

    sleep 1.5
    echo -e "\\033[1;32m[✓] Services started successfully.\\033[0m"

    echo -e "\\033[1;33m[*] Launching HTTPS URL in browser...\\033[0m"
    if command -v termux-open &> /dev/null; then
        termux-open https://localhost:8443
    elif command -v xdg-open &> /dev/null; then
        xdg-open https://localhost:8443
    fi
    sleep 1.5
}}

stop_services() {{
    echo -e "\\033[1;33m[*] Stopping all services...\\033[0m"
    stop_internet_access_silent
    pkill -f nginx > /dev/null 2>&1
    pkill -f php-fpm > /dev/null 2>&1
    pkill -f redis-server > /dev/null 2>&1
    pkill -f mariadbd > /dev/null 2>&1
    pkill -f mysqld > /dev/null 2>&1
    pkill -f mariadb > /dev/null 2>&1
    sleep 1
    
    echo -e "\\033[1;31m[✓] All services stopped.\\033[0m"
    sleep 1
}}

toggle_internet_access() {{
    if pgrep -f "cloudflared tunnel" > /dev/null; then
        stop_internet_access
    else
        start_internet_access
    fi
}}

start_internet_access() {{
    if ! pgrep -f "nginx" > /dev/null && ! pgrep -f "php-fpm" > /dev/null; then
        echo -e "\\033[1;31m[!] يجب عليك تشغيل السيرفر أولاً قبل تفعيل هذه الخدمة.\\033[0m"
        read -p "Press Enter to continue..."
        return
    fi

    if ! ping -c 1 -W 2 8.8.8.8 > /dev/null 2>&1 && ! curl -s --connect-timeout 2 https://www.google.com > /dev/null 2>&1; then
        echo -e "\\033[1;31m[!] يجب أن يتوفر وصول للإنترنت لتفعيل هذه الخدمة.\\033[0m"
        read -p "Press Enter to continue..."
        return
    fi

    echo -e "\\033[1;34m[*] Enabling Internet Access via Cloudflare Tunnel...\\033[0m"
    mkdir -p "$PREFIX/tmp"
    rm -f "$TUNNEL_LOG" "$TUNNEL_URL_FILE"

    cloudflared tunnel --url http://localhost:8080 > "$TUNNEL_LOG" 2>&1 &
    
    echo -n "  Fetching Global URL"
    for i in {{1..15}}; do
        echo -n "."
        sleep 1
        if grep -q "trycloudflare.com" "$TUNNEL_LOG"; then
            G_URL=$(grep -oE 'https://[-a-zA-Z0-9@:%._\\+~#=]+\\.trycloudflare\\.com' "$TUNNEL_LOG" | head -n 1)
            if [ -n "$G_URL" ]; then
                echo "$G_URL" > "$TUNNEL_URL_FILE"
                echo -e "\\n\\033[1;32m[✓] Global Access Enabled Successfully!\\033[0m"
                echo -e " 🌍 Global URL: \\033[1;36m$G_URL\\033[0m"
                read -p "Press Enter to continue..."
                return
            fi
        fi
    done

    echo -e "\\n\\033[1;31m[!] Failed to establish Cloudflare Tunnel. Please try again.\\033[0m"
    stop_internet_access_silent
    read -p "Press Enter to continue..."
}}

stop_internet_access() {{
    echo -e "\\033[1;33m[*] Disabling Internet Access...\\033[0m"
    stop_internet_access_silent
    echo -e "\\033[1;32m[✓] Internet Access disabled.\\033[0m"
    sleep 1
}}

stop_internet_access_silent() {{
    pkill -9 -f "cloudflared tunnel" > /dev/null 2>&1
    rm -f "$TUNNEL_LOG" "$TUNNEL_URL_FILE"
}}

restart_services() {{
    stop_services
    sleep 1
    start_services
}}

fix_server() {{
    echo -e "\\033[1;33m[*] Starting complete server stack wipe and fresh re-installation...\\033[0m"
    stop_services

    echo -e "\\033[1;33m[*] Deleting all configurations, binaries, databases and version files (except $HTDOCS_DIR)...\\033[0m"
    rm -rf "$PREFIX/etc/nginx"
    rm -rf "$PREFIX/etc/php-fpm.d"
    rm -f "$PREFIX/etc/php/php.ini"
    rm -f "$PREFIX/etc/redis.conf"
    rm -rf "$PREFIX/var/lib/mysql"
    rm -rf "$PREFIX/var/lib/redis"
    rm -rf "$PREFIX/var/log"
    rm -rf "$PREFIX/tmp"
    rm -f "$HOME_DIR/storage/shared/server.crt"
    rm -f "$VERSION_FILE"
    rm -f "$PREFIX/bin/myserver"

    mkdir -p "$PREFIX/tmp"
    TMP_INSTALL="$PREFIX/tmp/install_server_fresh.py"

    echo -e "\\033[1;36m[*] Fetching fresh installation script from repository...\\033[0m"
    curl -sL "$GITHUB_RAW_URL/install_server.py" -o "$TMP_INSTALL"

    if [ -s "$TMP_INSTALL" ]; then
        echo -e "\\033[1;34m[*] Executing fresh setup & phpMyAdmin update...\\033[0m"
        python3 "$TMP_INSTALL"
        rm -f "$TMP_INSTALL"
        echo -e "\\n\\033[1;32m[✓] Server repaired and reinstalled completely! Your web root ($HTDOCS_DIR) remains safe.\\033[0m"
        echo -e "\\033[1;36m[*] Launching updated myserver binary...\\033[0m"
        read -p "Press Enter to continue..."
        exec "$PREFIX/bin/myserver"
    else
        echo -e "\\033[1;31m[!] Failed to download fresh installation script. Check your internet connection.\\033[0m"
        read -p "Press Enter to continue..."
    fi
}}

update_server() {{
    echo -e "\\033[1;36m[*] Checking for updates from remote repository...\\033[0m"
    LOCAL_VER=$(cat "$VERSION_FILE" 2>/dev/null || echo "$CURRENT_VERSION")
    
    mkdir -p "$PREFIX/tmp"
    TMP_UPD="$PREFIX/tmp/install_server_latest.py"
    curl -sL "$GITHUB_RAW_URL/install_server.py" -o "$TMP_UPD"
    
    if [ ! -s "$TMP_UPD" ]; then
        echo -e "\\033[1;31m[!] Connection failed or remote script missing.\\033[0m"
        rm -f "$TMP_UPD"
        read -p "Press Enter to continue..."
        return
    fi
    
    REMOTE_VER=$(python3 -c '
import re
try:
    with open("'"$TMP_UPD"'", "r", encoding="utf-8") as f:
        m = re.search(r"CURRENT_VERSION\\s*=\\s*\"([^\"]+)\"", f.read())
        print(m.group(1) if m else "'"$LOCAL_VER"'")
except Exception:
    print("'"$LOCAL_VER"'")
')
    
    echo -e "  - Installed Version : \\033[1;33m$LOCAL_VER\\033[0m"
    echo -e "  - Remote Version    : \\033[1;32m$REMOTE_VER\\033[0m"
    
    if [ "$LOCAL_VER" != "$REMOTE_VER" ]; then
        echo -e "\\n\\033[1;35m[!] New version ($REMOTE_VER) available!\\033[0m"
        echo -e "\\033[1;33m📋 What's new in this release:\\033[0m"
        python3 -c '
import ast, re
try:
    with open("'"$TMP_UPD"'", "r", encoding="utf-8") as f:
        content = f.read()
    match = re.search(r"CHANGELOG\\s*=\\s*(\\[.*?\\])", content, re.DOTALL)
    if match:
        log_list = ast.literal_eval(match.group(1))
        for item in log_list:
            print("  • " + str(item))
    else:
        print("  • General fixes, stability improvements, and updates.")
except Exception:
    print("  • General fixes, stability improvements, and updates.")
'
        echo ""
        read -p "Download and install update now? (y/N): " confirm
        case "$confirm" in
            [yY][eE][sS]|[yY])
                echo -e "\\033[1;33m[*] Stopping running services before update...\\033[0m"
                stop_services
                echo -e "\\033[1;34m[*] Installing update...\\033[0m"
                python3 "$TMP_UPD"
                rm -f "$TMP_UPD"
                echo -e "\\n\\033[1;32m[✓] Updated to version $REMOTE_VER successfully!\\033[0m"
                echo -e "\\033[1;36m[*] Press Enter to close this session and launch updated myserver...\\033[0m"
                read -r
                exec "$PREFIX/bin/myserver"
                ;;
            *)
                echo -e "\\033[1;33m[i] Update cancelled by user.\\033[0m"
                rm -f "$TMP_UPD"
                read -p "Press Enter to continue..."
                ;;
        esac
    else
        echo -e "\\033[1;32m[✓] You are already on the latest version ($LOCAL_VER).\\033[0m"
        rm -f "$TMP_UPD"
        read -p "Press Enter to continue..."
    fi
}}

uninstall_server() {{
    echo -e "\\033[1;31m════════════════════════════════════════════\\033[0m"
    echo -e "\\033[1;31m   ⚠️  WARNING: UNINSTALL MYSERVER STACK  ⚠️ \\033[0m"
    echo -e "\\033[1;31m════════════════════════════════════════════\\033[0m"
    read -p "Are you sure you want to completely uninstall myserver? (y/N): " confirm
    case "$confirm" in
        [yY][eE][sS]|[yY])
            echo -e "\\033[1;33m[*] Stopping all services...\\033[0m"
            stop_services

            echo -e "\\033[1;33m[*] Removing configuration files and certificates...\\033[0m"
            rm -rf "$PREFIX/etc/nginx"
            rm -rf "$PREFIX/etc/php-fpm.d"
            rm -f "$PREFIX/etc/php/php.ini"
            rm -f "$PREFIX/etc/redis.conf"
            rm -rf "$PREFIX/var/lib/mysql"
            rm -rf "$PREFIX/var/lib/redis"
            rm -rf "$PREFIX/var/log"
            rm -f "$HOME_DIR/storage/shared/server.crt"
            rm -f "$VERSION_FILE"
            
            read -p "Do you also want to delete the web root ($HTDOCS_DIR)? (y/N): " del_web
            case "$del_web" in
                [yY][eE][sS]|[yY])
                    rm -rf "$HTDOCS_DIR"
                    echo -e "\\033[1;32m[✓] Web root deleted.\\033[0m"
                    ;;
                *)
                    echo -e "\\033[1;36m[i] Web root preserved.\\033[0m"
                    ;;
            esac

            rm -f "$PREFIX/bin/myserver"
            echo -e "\\033[1;32m[✓] Uninstalled successfully.\\033[0m"
            exit 0
            ;;
        *)
            echo -e "\\033[1;36m[i] Uninstall cancelled.\\033[0m"
            sleep 1
            ;;
    esac
}}

if [ -z "$1" ]; then
    check_auto_update
fi

if [ -n "$1" ]; then
    case "$1" in
        start) start_services ;;
        stop) stop_services ;;
        restart) restart_services ;;
        status) show_banner_and_status; read -p "Press Enter to continue..." ;;
        fix) fix_server ;;
        update) update_server ;;
        delete|uninstall) uninstall_server ;;
        *) echo "Usage: myserver [start|stop|restart|status|fix|update|uninstall]" ;;
    esac
    exit 0
fi

while true; do
    show_banner_and_status
    echo -e "\\033[1;33mSelect an option:\\033[0m"
    
    if check_server_running; then
        echo -e "\\033[1;33m 1) stop           (Stop all services)\\033[0m"
    else
        echo -e "\\033[1;33m 1) start          (Start all services)\\033[0m"
    fi
    
    if pgrep -f "cloudflared tunnel" > /dev/null && [ -s "$TUNNEL_URL_FILE" ]; then
        echo -e "\\033[1;33m 2) Disable Internet(Disable global Cloudflare access)\\033[0m"
    else
        echo -e "\\033[1;33m 2) Enable Internet (Enable global Cloudflare access)\\033[0m"
    fi
    
    echo -e "\\033[1;33m 3) restart        (Restart all services)\\033[0m"
    echo -e "\\033[1;33m 4) refresh status (Re-check server status)\\033[0m"
    echo -e "\\033[1;33m 5) fix            (To fix issues)\\033[0m"
    echo -e "\\033[1;33m 6) update         (Check and apply updates)\\033[0m"
    echo -e "\\033[1;33m 7) uninstall      (Remove server stack)\\033[0m"
    echo -e "\\033[1;33m 8) exit\\033[0m"
    echo ""
    read -p "Enter choice [1-8]: " choice

    case "$choice" in
        1)
            if check_server_running; then
                stop_services
            else
                start_services
            fi
            ;;
        2) toggle_internet_access ;;
        3) restart_services ;;
        4|refresh) continue ;;
        5) fix_server ;;
        6) update_server ;;
        7|uninstall|delete) uninstall_server ;;
        8|exit)
            stop_services
            echo -e "\\033[1;32mServer stopped and exited successfully.\\033[0m"
            exit 0
            ;;
        *) echo -e "\\033[1;31mInvalid choice!\\033[0m"; sleep 1 ;;
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

def cleanup_repository():
    try:
        cwd = Path.cwd().resolve()
        if cwd not in [HOME, PREFIX, Path('/'), Path('/data/data/com.termux/files')]:
            if (cwd / "install_server.py").exists() or (cwd / ".git").exists():
                print("\033[1;33m[*] Cleaning up downloaded repository folder...\033[0m")
                os.chdir(HOME)
                shutil.rmtree(cwd, ignore_errors=True)
                print("\033[1;32m[✓] Downloaded repository folder deleted successfully.\033[0m")
    except Exception as e:
        print(f"\033[1;31m [!] Cleanup notice: {e}\033[0m")

def main():
    try:
        print(f"\033[1;33m[+] Deploying Advanced Nginx + PHP-FPM Server Stack v{CURRENT_VERSION}...\033[0m")
        
        steps = [
            ("Updating Packages", "pkg update -y && pkg upgrade -y"),
            ("Storage Setup", None),
            ("Installing Core Software & Cloudflared", "pkg install -y nginx php php-fpm mariadb redis openssl-tool curl tar git wget cloudflared"),
            ("MariaDB Initialization", setup_mariadb),
            ("Redis Setup", setup_redis),
            ("PHP-FPM Configuration", setup_php_fpm),
            ("SSL Certificate Setup", setup_ssl),
            ("Nginx Server Setup", setup_nginx),
            ("PHP Configuration & Sessions Fix", create_php_ini),
            ("Web Root Setup", setup_htdocs),
            ("phpMyAdmin Installation", install_phpmyadmin),
            ("CLI Configuration", create_myserver_cli)
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
