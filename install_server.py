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

# رقم الإصدار الحالي
CURRENT_VERSION = "1.3.0"

# إعداد مسارات النظام والبيئة
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
        data_dir.mkdir(parents=True, exist_ok=True)
        if not any(data_dir.iterdir()):
            run_cmd(f"mariadb-install-db --datadir='{data_dir}'")
            print("\033[1;32m [✓] MariaDB database initialized. \033[0m")
        return True
    except Exception as e:
        print(f"\033[1;31m [!] MariaDB init error: {e}\033[0m")
        return False

def setup_redis():
    try:
        redis_data = PREFIX / "var/lib/redis"
        redis_data.mkdir(parents=True, exist_ok=True)
        redis_conf = PREFIX / "etc/redis.conf"
        if not redis_conf.exists():
            redis_conf.write_text(f"dir {redis_data}\ndaemonize yes\nport 6379\n")
        print("\033[1;32m [✓] Redis configured. \033[0m")
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
    if pma_dir.exists():
        print("\033[1;33m [!] phpMyAdmin already installed. \033[0m")
        return True

    try:
        print("\033[1;34m [*] Downloading phpMyAdmin... \033[0m")
        TMP_DIR.mkdir(parents=True, exist_ok=True)
        tar_file = TMP_DIR / "pma.tar.gz"
        url = "https://www.phpmyadmin.net/downloads/phpMyAdmin-latest-all-languages.tar.gz"
        
        run_cmd(f"curl -sL '{url}' -o '{tar_file}'")
        pma_dir.mkdir(parents=True, exist_ok=True)
        run_cmd(f"tar -xf '{tar_file}' -C '{pma_dir}' --strip-components=1")
        if tar_file.exists():
            tar_file.unlink()

        config_sample = pma_dir / "config.sample.inc.php"
        config_file = pma_dir / "config.inc.php"

        secret = ''.join(random.choices(string.ascii_letters + string.digits, k=32))

        if config_sample.exists():
            content = config_sample.read_text()
            content = re.sub(r"\$cfg\['blowfish_secret'\]\s*=\s*'';|\$cfg\['blowfish_secret'\]\s*=\s*\".*\";", f"$cfg['blowfish_secret'] = '{secret}';", content)
            content = re.sub(r"\$cfg\['Servers'\]\[\$i\]\['AllowNoPassword'\]\s*=\s*false;", "$cfg['Servers'][$i]['AllowNoPassword'] = true;", content)
            content = re.sub(r"\$cfg\['Servers'\]\[\$i\]\['host'\]\s*=\s*'localhost';", "$cfg['Servers'][$i]['host'] = '127.0.0.1';", content)
            
            pma_tmp = pma_dir / "tmp"
            pma_tmp.mkdir(exist_ok=True)
            content += f"\n$cfg['TempDir'] = '{pma_tmp}';\n"
            
            config_file.write_text(content)

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
    
    echo -e "\\033[1;35m═════════════════ [ حالة الخادم ] ═════════════════\\033[0m"
    pgrep nginx > /dev/null && echo -e " Nginx:    \\033[1;32mيعمل [✓]\\033[0m" || echo -e " Nginx:    \\033[1;31mمتوقف [✗]\\033[0m"
    pgrep php-fpm > /dev/null && echo -e " PHP-FPM:  \\033[1;32mيعمل [✓]\\033[0m" || echo -e " PHP-FPM:  \\033[1;31mمتوقف [✗]\\033[0m"
    (pgrep mysqld > /dev/null || pgrep mariadbd > /dev/null) && echo -e " MariaDB:  \\033[1;32mيعمل [✓]\\033[0m" || echo -e " MariaDB:  \\033[1;31mمتوقف [✗]\\033[0m"
    pgrep redis-server > /dev/null && echo -e " Redis:    \\033[1;32mيعمل [✓]\\033[0m" || echo -e " Redis:    \\033[1;31mمتوقف [✗]\\033[0m"
    echo -e "\\033[1;35m═════════════════════════════════════════════════\\033[0m\\n"
}}

start_services() {{
    echo -e "\\033[1;34m[+] بدء تشغيل MariaDB...\\033[0m"
    mkdir -p "$PREFIX/var/lib/mysql"
    if command -v mariadbd-safe &> /dev/null; then
        mariadbd-safe --datadir="$PREFIX/var/lib/mysql" > /dev/null 2>&1 &
    else
        mysqld_safe --datadir="$PREFIX/var/lib/mysql" > /dev/null 2>&1 &
    fi

    echo -e "\\033[1;34m[+] بدء تشغيل Redis...\\033[0m"
    mkdir -p "$PREFIX/var/lib/redis"
    if [ -f "$PREFIX/etc/redis.conf" ]; then
        redis-server "$PREFIX/etc/redis.conf" --daemonize yes > /dev/null 2>&1
    else
        redis-server --daemonize yes > /dev/null 2>&1
    fi

    echo -e "\\033[1;34m[+] بدء تشغيل PHP-FPM...\\033[0m"
    php-fpm > /dev/null 2>&1

    echo -e "\\033[1;34m[+] بدء تشغيل Nginx...\\033[0m"
    nginx > /dev/null 2>&1

    echo -e "\\033[1;32m[✓] تم تشغيل جميع الخدمات بنجاح.\\033[0m"
    sleep 1.5
}}

stop_services() {{
    echo -e "\\033[1;33m[*] إيقاف جميع الخدمات...\\033[0m"
    pkill -f nginx > /dev/null 2>&1
    pkill -f php-fpm > /dev/null 2>&1
    pkill -f redis-server > /dev/null 2>&1
    pkill -f mysqld > /dev/null 2>&1
    pkill -f mariadbd > /dev/null 2>&1
    echo -e "\\033[1;31m[✓] تم إيقاف جميع الخدمات.\\033[0m"
    sleep 1.5
}}

restart_services() {{
    stop_services
    sleep 1
    start_services
}}

update_server() {{
    echo -e "\\033[1;36m[*] التحقق من التحديثات من المستودع...\\033[0m"
    LOCAL_VER=$(cat "$VERSION_FILE" 2>/dev/null || echo "{CURRENT_VERSION}")
    
    mkdir -p "$PREFIX/tmp"
    TMP_UPD="$PREFIX/tmp/install_server_latest.py"
    curl -sL "$GITHUB_RAW_URL/install_server.py" -o "$TMP_UPD"
    
    if [ ! -s "$TMP_UPD" ]; then
        echo -e "\\033[1;31m[!] فشل الاتصال بـ GitHub أو الملف غير موجود.\\033[0m"
        rm -f "$TMP_UPD"
        read -p "اضغط Enter للمتابعة..."
        return
    fi
    
    REMOTE_VER=$(grep -oP 'CURRENT_VERSION\\s*=\\s*"\\K[^"]+' "$TMP_UPD" 2>/dev/null || echo "0.0.0")
    
    echo -e "  - الإصدار المثبت: \\033[1;33m$LOCAL_VER\\033[0m"
    echo -e "  - الإصدار المتاح:  \\033[1;32m$REMOTE_VER\\033[0m"
    
    if [ "$LOCAL_VER" != "$REMOTE_VER" ]; then
        echo -e "\\033[1;35m[!] يتوفر إصدار جديد ($REMOTE_VER)!\\033[0m"
        read -p "هل تريد تنزيل وتثبيت التحديث الآن؟ (y/N): " confirm
        case "$confirm" in
            [yY][eE][sS]|[yY])
                echo -e "\\033[1;34m[*] جاري تحديث السيرفر...\\033[0m"
                python3 "$TMP_UPD"
                rm -f "$TMP_UPD"
                echo -e "\\033[1;32m[✓] تم تحديث myserver إلى الإصدار $REMOTE_VER بنجاح!\\033[0m"
                ;;
            *)
                echo -e "\\033[1;33m[i] تم إلغاء التحديث بواسطة المستخدم.\\033[0m"
                rm -f "$TMP_UPD"
                ;;
        esac
    else
        echo -e "\\033[1;32m[✓] أنت تستخدم أحدث إصدار بالفعل ($LOCAL_VER).\\033[0m"
        rm -f "$TMP_UPD"
    fi
    read -p "اضغط Enter للمتابعة..."
}}

uninstall_server() {{
    echo -e "\\033[1;31m════════════════════════════════════════════\\033[0m"
    echo -e "\\033[1;31m   ⚠️  تحذير: إزالة خادم MYSERVER بالكامل  ⚠️ \\033[0m"
    echo -e "\\033[1;31m════════════════════════════════════════════\\033[0m"
    read -p "هل أنت تأكد من رغبتك في حذف myserver بالكامل؟ (y/N): " confirm
    case "$confirm" in
        [yY][eE][sS]|[yY])
            echo -e "\\033[1;33m[*] إيقاف جميع الخدمات...\\033[0m"
            stop_services

            echo -e "\\033[1;33m[*] حذف ملفات التكوين والملفات التنفيذية...\\033[0m"
            rm -rf "$PREFIX/etc/nginx/ssl"
            rm -f "$PREFIX/etc/nginx/nginx.conf"
            rm -f "$PREFIX/etc/php-fpm.d/www.conf"
            rm -f "$VERSION_FILE"
            
            read -p "هل تريد أيضاً حذف ملفات الويب ($HTDOCS_DIR)؟ (y/N): " del_web
            case "$del_web" in
                [yY][eE][sS]|[yY])
                    rm -rf "$HTDOCS_DIR"
                    echo -e "\\033[1;32m[✓] تم حذف مجلد موقع الويب.\\033[0m"
                    ;;
                *)
                    echo -e "\\033[1;36m[i] تم الاحتفاظ بمجلد موقع الويب.\\033[0m"
                    ;;
            esac

            rm -f "$PREFIX/bin/myserver"
            echo -e "\\033[1;32m[✓] تم إلغاء تثبيت myserver بنجاح.\\033[0m"
            exit 0
            ;;
        *)
            echo -e "\\033[1;36m[i] تم إلغاء الحذف.\\033[0m"
            sleep 1
            ;;
    esac
}}

# تنفيذ أمر مباشر إذا طُلِب عبر الوسطاء (مثال: myserver start)
if [ -n "$1" ]; then
    case "$1" in
        start) start_services ;;
        stop) stop_services ;;
        restart) restart_services ;;
        status) show_banner_and_status; read -p "اضغط Enter للمتابعة..." ;;
        update) update_server ;;
        delete|uninstall) uninstall_server ;;
        *) echo "الاستخدام: myserver [start|stop|restart|status|update|uninstall]" ;;
    esac
    exit 0
fi

# القائمة التفاعلية المستمرة
while true; do
    show_banner_and_status
    echo -e "\\033[1;33mاختر أحد الخيارات التالية:\\033[0m"
    echo " 1) start     (تشغيل جميع الخدمات)"
    echo " 2) stop      (إيقاف جميع الخدمات)"
    echo " 3) restart   (إعادة تشغيل جميع الخدمات)"
    echo " 4) update    (التحقق من التحديثات وتطبيقها)"
    echo " 5) uninstall (حذف الخادم وإلغاء التثبيت)"
    echo " 6) exit      (الخروج)"
    echo ""
    read -p "أدخل رقم الخيار [1-6]: " choice

    case "$choice" in
        1|start) start_services ;;
        2|stop) stop_services ;;
        3|restart) restart_services ;;
        4|update) update_server ;;
        5|uninstall|delete) uninstall_server ;;
        6|exit) echo -e "\\033[1;32mتم الخروج.\\033[0m"; exit 0 ;;
        *) echo -e "\\033[1;31mخيار غير صحيح!\\033[0m"; sleep 1 ;;
    esac
done
"""
    try:
        bin_path.write_text(script_content)
        bin_path.chmod(0o755)
        print("\033[1;32m [✓] CLI Tool 'myserver' configured with interactive menu. \033[0m")
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
            ("Installing Core Software", "pkg install -y nginx php php-fpm mariadb redis openssl-tool curl tar git wget"),
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
