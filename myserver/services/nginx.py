from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ..core import paths, helpers, ui
from . import ssl

# ---------------------------------------------------------------------------
def _common_locations() -> str:
    return f"""\
        # --- live reload endpoints ---
        location = /__live.js {{
            proxy_pass http://127.0.0.1:{paths.LIVE_PORT}/__live.js;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_cache off;
            add_header Cache-Control "no-store, no-cache, must-revalidate";
        }}

        location ~ ^/__live/ {{
            proxy_pass http://127.0.0.1:{paths.LIVE_PORT};
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header Connection '';
            proxy_buffering off;
            proxy_cache off;
            proxy_read_timeout 24h;
            chunked_transfer_encoding off;
        }}

        # --- block phpMyAdmin sensitive paths ---
        location ~ ^/phpmyadmin/(config\\.inc\\.php|setup|libraries|tmp|sql|scripts)/? {{
            deny all;
            return 404;
        }}
        location ~ ^/phpmyadmin/\\..* {{
            deny all;
            return 404;
        }}

        location ~ ^/phpmyadmin/.*\\.php$ {{
            try_files $uri =404;
            include fastcgi_params;
            fastcgi_pass php_fpm;
            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
            fastcgi_read_timeout 300;
        }}

        # --- directory index fallback ---
        location ~ ^(.*)/$ {{
            try_files $1/index.php @html_dir;
            include fastcgi_params;
            fastcgi_pass php_fpm;
            fastcgi_param SCRIPT_FILENAME $document_root$1/index.php;
            fastcgi_param PATH_INFO "";
            fastcgi_read_timeout 300;
        }}

        location @html_dir {{
            rewrite ^(.*)/$ $1/index.html last;
        }}

        location ~ \\.php$ {{
            try_files $uri =404;
            include fastcgi_params;
            fastcgi_pass php_fpm;
            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
            fastcgi_read_timeout 300;
            include {paths.LIVE_CONF_FILE};
        }}

        location / {{
            try_files $uri /index.php?$args;
            include {paths.LIVE_CONF_FILE};
        }}

        location ~ /\\. {{
            deny all;
        }}
"""


# ---------------------------------------------------------------------------
def setup(htdocs: Path) -> bool:
    try:
        cert, key = ssl.active_cert_pair()

        paths.LIVE_CONF_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not paths.LIVE_CONF_FILE.exists():
            paths.LIVE_CONF_FILE.write_text("")

        common = _common_locations()

        nginx_config = f"""\
worker_processes 2;
events {{ worker_connections 1024; }}

http {{
    include mime.types;
    default_type application/octet-stream;
    sendfile on;
    keepalive_timeout 65;

    sub_filter_once off;
    sub_filter_types text/html;
    sub_filter_last_modified off;

    access_log {paths.LOG_DIR}/nginx-access.log;
    error_log  {paths.LOG_DIR}/nginx-error.log;

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
        root {htdocs};
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
        ssl_certificate "{cert}";
        ssl_certificate_key "{key}";
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_ciphers HIGH:!aNULL:!MD5;
        ssl_prefer_server_ciphers on;
        root {htdocs};
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
        paths.NGINX_CONF.write_text(nginx_config)
        paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
        ui.ok("Nginx configured.")
        return True
    except Exception as e:
        ui.err(f"Nginx config error: {e}")
        return False


# ---------------------------------------------------------------------------
def setup_htdocs(htdocs: Path) -> bool:
    try:
        htdocs.mkdir(parents=True, exist_ok=True)
        if not (htdocs / "index.php").exists():
            (htdocs / "index.php").write_text(
                "<?php echo '<h1>Nginx + PHP-FPM Server is Running!</h1>'; ?>")
        info_dir = htdocs / "phpinfo"
        info_dir.mkdir(exist_ok=True)
        (info_dir / "index.php").write_text("<?php phpinfo(); ?>")
        enforce_htdocs_permissions(htdocs)
        return True
    except Exception as e:
        ui.err(f"htdocs error: {e}")
        return False


# ---------------------------------------------------------------------------
def enforce_htdocs_permissions(htdocs: Path) -> int:
    if not htdocs.exists():
        return 0
    changed = 0
    try:
        if (htdocs.stat().st_mode & 0o777) != 0o755:
            os.chmod(htdocs, 0o755); changed += 1
    except Exception:
        pass
    try:
        for root, dirs, files in os.walk(htdocs):
            for d in dirs:
                p = os.path.join(root, d)
                try:
                    if (os.stat(p).st_mode & 0o777) != 0o755:
                        os.chmod(p, 0o755); changed += 1
                except Exception:
                    pass
            for f in files:
                p = os.path.join(root, f)
                try:
                    mode = os.stat(p).st_mode & 0o777
                    target = 0o755 if (mode & 0o111) else 0o644
                    if mode != target:
                        os.chmod(p, target); changed += 1
                except Exception:
                    pass
    except Exception:
        pass
    return changed


def print_htdocs_diagnostic(htdocs: Path):
    ui.info("Web root diagnostic:")
    print(f"      path     : {htdocs}")
    try:
        print(f"      realpath : {htdocs.resolve()}")
    except Exception as e:
        print(f"      realpath : (failed: {e})")
    if htdocs.exists():
        try:
            print(f"      mode     : {oct(htdocs.stat().st_mode & 0o777)}")
        except Exception:
            pass


# ---------------------------------------------------------------------------
def start() -> bool:
    if helpers.is_process_running("nginx"):
        pid = helpers.pid_from_pgrep("nginx")
        if pid:
            helpers.write_pid_file(paths.PID_NGINX, pid)
        return True
    for p in (8080, 8443):
        if helpers.port_in_use(p):
            ui.warn(f"Port {p} is already in use.")
    helpers.run_cmd("nginx")
    pid = helpers.pid_from_pgrep("nginx")
    if pid:
        helpers.write_pid_file(paths.PID_NGINX, pid)
        return True
    return False


def stop() -> bool:
    helpers.run_cmd("nginx -s stop")
    return helpers.safe_stop(paths.PID_NGINX, ("nginx",))


def reload():
    if helpers.is_process_running("nginx"):
        helpers.run_cmd("nginx -s reload")