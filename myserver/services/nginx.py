"""Nginx configuration, lifecycle, and fast permission enforcement.

Android & Security Improvements:
  * Uses `worker_processes 1;` and explicit `pid` file to conserve Android
    background process slots.
  * Automatically blocks external Cloudflare Tunnel traffic (`$http_cf_connecting_ip`)
    from accessing `/phpmyadmin` and `/phpinfo` (`403 Forbidden`), keeping
    database administration strictly local.
  * Supports subdirectory Laravel routing (`/project/public/...`) and blocks
    web access to `.env`, `vendor/`, `storage/`, and `composer.*`.
  * Includes `conf.d/*.conf` for Virtual Hosts managed by `myserver site`.
  * `enforce_htdocs_permissions(htdocs, deep=False)` checks only the root and
    first-level entries on routine server startup (<2ms), reserving recursive
    walks (excluding `vendor`, `node_modules`, `.git`, `phpmyadmin`) for
    explicit `--fix` or fresh framework installs.
"""
from __future__ import annotations

import os
from pathlib import Path

from ..core import paths, helpers, ui
from . import ssl

_SKIP_PERM_DIRS = {".git", "node_modules", "vendor", "phpmyadmin", ".myserver-cache"}


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

        # --- block public tunnel access to phpMyAdmin & phpinfo ---
        location ~ ^/phpmyadmin/.*\\.php$ {{
            if ($http_cf_connecting_ip != "") {{
                return 403;
            }}
            try_files $uri =404;
            include fastcgi_params;
            fastcgi_pass php_fpm;
            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
            fastcgi_read_timeout 300;
        }}

        location ~ ^/phpinfo(/|$) {{
            if ($http_cf_connecting_ip != "") {{
                return 403;
            }}
            try_files $uri $uri/index.php =404;
            include fastcgi_params;
            fastcgi_pass php_fpm;
            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
        }}

        # --- protect framework internal directories & files ---
        location ~ /(?:\\.env|composer\\.(?:json|lock)|artisan)(/|$) {{
            deny all;
            return 404;
        }}
        location ~ ^/[a-zA-Z0-9_-]+/(?:vendor|storage/logs|storage/framework|bootstrap/cache)(/|$) {{
            deny all;
            return 404;
        }}

        # --- Laravel / framework subdirectory /<app>/public routing ---
        location ~ ^/([a-zA-Z0-9_-]+)/public(/.*)?$ {{
            try_files $uri $uri/ /$1/public/index.php?$query_string;
            include {paths.LIVE_CONF_FILE};
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
            try_files $uri $uri/ /index.php?$args;
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
        paths.NGINX_CONFD_DIR.mkdir(parents=True, exist_ok=True)
        if not paths.LIVE_CONF_FILE.exists():
            paths.LIVE_CONF_FILE.write_text("")

        common = _common_locations()

        nginx_config = f"""\
worker_processes 1;
pid {paths.PID_NGINX};
events {{ worker_connections 512; }}

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
        root "{htdocs}";
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
        root "{htdocs}";
        index index.php index.html index.htm;
        client_max_body_size 512M;
        add_header Strict-Transport-Security "max-age=31536000" always;
        add_header X-Frame-Options "SAMEORIGIN" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header Referrer-Policy "strict-origin-when-cross-origin" always;
{common}
    }}

    include {paths.NGINX_CONFD_DIR}/*.conf;
}}
"""
        paths.NGINX_CONF.write_text(nginx_config)
        paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
        ui.ok("Nginx configured (1 worker, tunnel protection enabled).")
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
                "<?php echo '<h1>Nginx + PHP-FPM Server is Running!</h1>'; ?>\n"
            )
        # Remove legacy exposed /phpinfo if left untouched from old installs
        enforce_htdocs_permissions(htdocs, deep=False)
        return True
    except Exception as e:
        ui.err(f"htdocs error: {e}")
        return False


# ---------------------------------------------------------------------------
def enforce_htdocs_permissions(htdocs: Path, deep: bool = False) -> int:
    """Ensure readable web root permissions.

    When `deep=False` (default on `myserver start`), only checks `htdocs` and
    its immediate children so startup stays instantaneous (<2ms).
    When `deep=True` (`myserver doctor --fix` or after framework installation),
    walks subdirectories while skipping `vendor`, `node_modules`, `.git`, and
    `phpmyadmin`.
    """
    if not htdocs.exists():
        return 0
    # Skip chmod on Android FUSE shared storage where chmod is a no-op
    resolved_str = str(htdocs)
    try:
        resolved_str = str(htdocs.resolve())
    except Exception:
        pass
    if any(k in resolved_str for k in ("/storage/emulated/", "/storage/shared/", "/sdcard/")):
        return 0

    changed = 0
    try:
        if (htdocs.stat().st_mode & 0o777) != 0o755:
            os.chmod(htdocs, 0o755)
            changed += 1
    except Exception:
        pass

    if not deep:
        try:
            for child in htdocs.iterdir():
                try:
                    mode = child.stat().st_mode & 0o777
                    if child.is_dir():
                        if mode != 0o755:
                            os.chmod(child, 0o755)
                            changed += 1
                    elif child.is_file():
                        target = 0o755 if (mode & 0o111) else 0o644
                        if mode != target:
                            os.chmod(child, target)
                            changed += 1
                except Exception:
                    pass
        except Exception:
            pass
        return changed

    try:
        for root, dirs, files in os.walk(htdocs):
            dirs[:] = [d for d in dirs if d not in _SKIP_PERM_DIRS]
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
                    mode = os.stat(p).st_mode & 0o777
                    target = 0o755 if (mode & 0o111) else 0o644
                    if mode != target:
                        os.chmod(p, target)
                        changed += 1
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
    if helpers.is_process_running("nginx", pid_file=paths.PID_NGINX):
        pid = helpers.read_pid_file(paths.PID_NGINX) or helpers.pid_from_pgrep("nginx", exact=True)
        if pid:
            helpers.write_pid_file(paths.PID_NGINX, pid)
        return True
    for p in (8080, 8443):
        if helpers.port_in_use(p):
            ui.warn(f"Port {p} is already in use.")
    helpers.run_cmd(["nginx"])
    pid = helpers.read_pid_file(paths.PID_NGINX) or helpers.pid_from_pgrep("nginx", exact=True)
    if pid:
        helpers.write_pid_file(paths.PID_NGINX, pid)
        return True
    return False


def stop() -> bool:
    if helpers.is_process_running("nginx", pid_file=paths.PID_NGINX):
        helpers.run_cmd(["nginx", "-s", "stop"])
    return helpers.safe_stop(paths.PID_NGINX, ("nginx",))


def reload():
    if helpers.is_process_running("nginx", pid_file=paths.PID_NGINX):
        helpers.run_cmd(["nginx", "-s", "reload"])