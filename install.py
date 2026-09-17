#!/data/data/com.termux/files/usr/bin/python3

import os
import time
import shutil
import re
import subprocess
from pathlib import Path

# إعداد مسارات النظام والبيئة
PREFIX = Path(os.environ.get('PREFIX', '/data/data/com.termux/files/usr'))
HOME = Path.home()
HTDOCS_DIR = HOME / "storage/shared/htdocs"
NGINX_DIR = PREFIX / "etc/nginx"
PHP_FPM_DIR = PREFIX / "etc/php-fpm.d"
SSL_DIR = NGINX_DIR / "ssl"
REPO_DIR = Path(__file__).resolve().parent

def run_cmd(cmd, check=False):
    """تشغيل أوامر النظام بأمان دون إغراق الشاشة بالرسائل"""
    return subprocess.run(cmd, shell=True, check=check, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def setup_mariadb():
    """تهيئة وإعداد قاعدة البيانات MariaDB"""
    try:
        data_dir = PREFIX / "var/lib/mysql"
        if not data_dir.exists() or not any(data_dir.iterdir()):
            run_cmd("mariadb-install-db")
            print("\033[1;32m [✓] MariaDB database initialized. \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] MariaDB init error: {e}\033[0m")
        return False

def setup_php_fpm():
    """تهيئة PHP-FPM للاستماع على 127.0.0.1:9000"""
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
    """إنشاء شهادات SSL المخصصة لـ Nginx"""
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
    """إعداد ملف Nginx المتقدم لدعم HTTP/HTTPS و PHP-FPM"""
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

def setup_htdocs():
    """إنشاء مجلد htdocs الرئيسي والملفات الترحيبية"""
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
    """تنزيل وإعداد phpMyAdmin التلقائي"""
    pma_dir = HTDOCS_DIR / "phpmyadmin"
    if pma_dir.exists():
        print("\033[1;33m [!] phpMyAdmin already installed. \033[0m")
        return True

    try:
        print("\033[1;34m [*] Downloading phpMyAdmin... \033[0m")
        tar_file = HOME / "pma.tar.gz"
        url = "https://www.phpmyadmin.net/downloads/phpMyAdmin-latest-all-languages.tar.gz"
        
        run_cmd(f"curl -sL '{url}' -o '{tar_file}'")
        pma_dir.mkdir(parents=True, exist_ok=True)
        run_cmd(f"tar -xf '{tar_file}' -C '{pma_dir}' --strip-components=1")
        if tar_file.exists():
            tar_file.unlink()

        config_sample = pma_dir / "config.sample.inc.php"
        config_file = pma_dir / "config.inc.php"

        if config_sample.exists():
            content = config_sample.read_text()
            content = re.sub(r"\$cfg\['Servers'\]\[\$i\]\['AllowNoPassword'\]\s*=\s*false;", "$cfg['Servers'][$i]['AllowNoPassword'] = true;", content)
            content = re.sub(r"\$cfg\['Servers'\]\[\$i\]\['host'\]\s*=\s*'localhost';", "$cfg['Servers'][$i]['host'] = '127.0.0.1';", content)
            config_file.write_text(content)

        print("\033[1;32m [✓] phpMyAdmin ready. \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] phpMyAdmin error: {e}\033[0m")
        return False

def create_myserver_cli():
    """إنشاء أداة التحكم myserver مع التحديث التلقائي، معاينة Commit Log واستئذان المستخدم"""
    bin_path = PREFIX / "bin/myserver"
    script_content = f"""#!/data/data/com.termux/files/usr/bin/bash

REPO_PATH="{REPO_DIR}"

case "$1" in
    start)
        echo -e "\\033[1;34mStarting MariaDB...\\033[0m"
        mysqld_safe --datadir='{PREFIX}/var/lib/mysql' > /dev/null 2>&1 &
        echo -e "\\033[1;34mStarting Redis...\\033[0m"
        redis-server --daemonize yes > /dev/null 2>&1
        echo -e "\\033[1;34mStarting PHP-FPM...\\033[0m"
        php-fpm > /dev/null 2>&1
        echo -e "\\033[1;34mStarting Nginx...\\033[0m"
        nginx > /dev/null 2>&1
        echo -e "\\033[1;32mAll services started successfully.\\033[0m"
        ;;
    stop)
        echo -e "\\033[1;33mStopping services...\\033[0m"
        pkill -f nginx
        pkill -f php-fpm
        pkill -f redis-server
        pkill -f mysqld
        echo -e "\\033[1;31mAll services stopped.\\033[0m"
        ;;
    restart)
        $0 stop
        sleep 2
        $0 start
        ;;
    status)
        echo "=== Services Status ==="
        pgrep nginx > /dev/null && echo -e "Nginx:    \\033[1;32mRunning\\033[0m" || echo -e "Nginx:    \\033[1;31mStopped\\033[0m"
        pgrep php-fpm > /dev/null && echo -e "PHP-FPM:  \\033[1;32mRunning\\033[0m" || echo -e "PHP-FPM:  \\033[1;31mStopped\\033[0m"
        pgrep mysqld > /dev/null && echo -e "MariaDB:  \\033[1;32mRunning\\033[0m" || echo -e "MariaDB:  \\033[1;31mStopped\\033[0m"
        pgrep redis-server > /dev/null && echo -e "Redis:    \\033[1;32mRunning\\033[0m" || echo -e "Redis:    \\033[1;31mStopped\\033[0m"
        ;;
    update)
        echo -e "\\033[1;36mChecking for updates from GitHub...\\033[0m"
        if [ -d "$REPO_PATH/.git" ]; then
            cd "$REPO_PATH"
            git fetch origin > /dev/null 2>&1
            LOCAL=$(git rev-parse HEAD)
            REMOTE=$(git rev-parse @{{u}})
            if [ "$LOCAL" != "$REMOTE" ]; then
                echo -e "\\033[1;33m[!] New updates available on GitHub!\\033[0m"
                echo -e "\\033[1;35m--- List of New Changes (Commits) ---\\033[0m"
                git log HEAD..@{{u}} --pretty=format:'- %h: %s (%cr) <%an>'
                echo -e "\\n\\033[1;35m-------------------------------------\\033[0m"
                
                read -p "Do you want to apply these updates? (y/N): " confirm
                case "$confirm" in
                    [yY][eE][sS]|[yY])
                        echo -e "\\033[1;34mPulling latest changes from GitHub...\\033[0m"
                        git pull origin $(git rev-parse --abbrev-ref HEAD)
                        echo -e "\\033[1;34mRe-applying server setup...\\033[0m"
                        python3 "$REPO_PATH/install_server.py"
                        echo -e "\\033[1;32mServer updated successfully!\\033[0m"
                        ;;
                    *)
                        echo -e "\\033[1;33mUpdate process cancelled by user.\\033[0m"
                        ;;
                esac
            else
                echo -e "\\033[1;32m[✓] Server is already up to date.\\033[0m"
            fi
        else
            echo -e "\\033[1;31mError: $REPO_PATH is not a Git repository.\\033[0m"
        fi
        ;;
    *)
        echo "Usage: myserver {{start|stop|restart|status|update}}"
        ;;
esac
"""
    try:
        bin_path.write_text(script_content)
        bin_path.chmod(0o755)
        print("\033[1;32m [✓] CLI Tool 'myserver' configured. \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] CLI creation error: {e}\033[0m")
        return False

def create_php_ini():
    """ضبط إعدادات رفع الملفات والذاكرة في php.ini"""
    php_ini_path = PREFIX / 'etc/php/php.ini'
    php_ini_content = """\
upload_max_filesize = 256M
post_max_size = 512M
memory_limit = 512M
max_execution_time = 180
error_reporting = E_ALL & ~E_DEPRECATED
display_errors = On
date.timezone = UTC
"""
    try:
        php_ini_path.parent.mkdir(parents=True, exist_ok=True)
        php_ini_path.write_text(php_ini_content)
        print("\033[1;32m [✓] php.ini updated. \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] php.ini error: {e}\033[0m")
        return False

def main():
    try:
        print("\033[1;33m[+] Deploying Advanced Nginx + PHP-FPM Server Stack...\033[0m")
        
        steps = [
            ("Updating Packages", "pkg update -y && pkg upgrade -y"),
            ("Storage Setup", None),
            ("Installing Core Software", "pkg install -y nginx php php-fpm mariadb redis openssl-tool curl tar git wget"),
            ("MariaDB Initialization", setup_mariadb),
            ("PHP-FPM Configuration", setup_php_fpm),
            ("SSL Certificate Setup", setup_ssl),
            ("Nginx Server Setup", setup_nginx),
            ("Web Root Setup", setup_htdocs),
            ("phpMyAdmin Installation", install_phpmyadmin),
            ("CLI & Auto-Update Configuration", create_myserver_cli),
            ("PHP Configuration", create_php_ini)
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
        print("\033[1;35mControl Commands:\033[0m")
        print("  myserver start   - Start all services (Nginx, PHP-FPM, MariaDB, Redis)")
        print("  myserver stop    - Stop all services")
        print("  myserver status  - Check running status")
        print("  myserver update  - Preview changes & update from GitHub")

    except Exception as e:
        print(f"\033[1;31m[!] Installation Error: {e}\033[0m")
        exit(1)

if __name__ == "__main__":
    main()
