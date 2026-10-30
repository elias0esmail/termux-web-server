# Changelog

All notable changes to **MyServer (`termux-web-server`)** are documented in this file.

## [2.22.0] — 2026-10-30

### Security (Critical & High)
- **Cloudflare Tunnel Admin Isolation:** Blocked external tunnel requests (`$http_cf_connecting_ip`) to `/phpmyadmin` and `/phpinfo` with `HTTP 403 Forbidden` in `nginx.conf`, keeping database administration strictly local. Removed automatic creation of `/phpinfo/index.php` on fresh installs.
- **Shell & SQL Injection Protection:** Replaced `shell=True` command execution across all modules with `shell=False` argument lists, added `helpers.run_mysql_query()` passing SQL over `stdin`, and enforced strict identifier validation (`^[a-zA-Z0-9_-]{1,64}$`) in `quickstart.py`, `vhost.py`, and `db_cli.py`.
- **SemVer & SHA-256 Update Integrity:** Added semantic version comparison (`is_newer_version`) in `myserver update` to prevent accidental downgrades, plus optional `SHA256SUMS` verification for downloaded release archives.

### Android Process & Subprocess Optimization (Phantom Process Budget)
- **Zero-Subprocess `/proc` Inspection:** `is_process_running()`, `pid_from_pgrep()`, `safe_stop()`, and `count_user_processes()` now inspect PID files and `/proc` directly in pure Python before falling back to `pgrep`/`pkill`, eliminating dozens of transient child processes.
- **Pure-Python Network & LAN Checks:** `check_internet()` and `get_lan_ip()` now use Python's standard `urllib.request` and `socket` modules instead of spawning `curl` or shell subprocesses.
- **PHP-FPM `ondemand` Process Manager:** Switched PHP-FPM from `pm = dynamic` (up to 11 processes) to `pm = ondemand` (`pm.max_children = 4`, `10s` idle timeout), keeping 0 idle worker processes when inactive and saving up to 9 background process slots under Android 12+'s 32 phantom-process limit.
- **Single-Worker Nginx & Direct MariaDB Daemon:** Set `worker_processes 1;` in Nginx and launched `mariadbd` directly (`--performance-schema=OFF --max-connections=25`) without the `mariadbd-safe` shell wrapper.
- **Live Reload Thread Cap & Optional Redis Toggle:** Lowered default `MYSERVER_LIVE_MAX_CLIENTS` from 50 to 10 threads and added `myserver redis-disable` / `myserver redis-enable` to save a background process slot when Redis is not needed.
- **Live Android Process & RAM Monitor:** Added real-time Termux process count (`X/32 Android limit`) and per-service RSS memory reporting in `myserver status`, interactive menu, and `myserver doctor`.

### Added
- **Virtual Host Manager (`myserver site`):** Added `myserver site list`, `myserver site add <name> [path] [--port PORT] [--type php|laravel|wordpress|nextcloud]`, and `myserver site remove <name>` using `$PREFIX/etc/nginx/conf.d/*.conf`.
- **Database CLI (`myserver db`):** Added `myserver db list`, `create <name>`, `drop <name>`, `import <name> <file.sql>`, and `export <name> [out.sql]` commands.
- **Automated Test Suite & CI:** Added `pyproject.toml`, unit tests in `tests/test_myserver.py`, and GitHub Actions CI (`.github/workflows/ci.yml`).

### Changed & Fixed
- **Non-Destructive PHP Configuration:** Moved custom PHP settings to `$PREFIX/etc/php/conf.d/99-myserver.ini` instead of overwriting `$PREFIX/etc/php/php.ini`.
- **Fast Startup Permission Check:** `enforce_htdocs_permissions(deep=False)` now inspects only top-level `htdocs` entries on routine startup (<2ms), reserving recursive scans (excluding `vendor`, `node_modules`, `.git`, `phpmyadmin`) for `myserver doctor --fix`.
- **Safe Backup Directory Resolution:** `resolve_runtime_paths()` verifies `~/storage/shared` exists before using it, falling back to `~/myserver-backups` so `termux-setup-storage` is never broken by an unlinked folder.
- **Unified Database Listing & English-Only Codebase:** Updated `cmd_uninstall` to use `information_schema.SCHEMATA` via `mariadb.list_user_databases()`, deduplicated boot script setup in `install.py`, and removed unused `myserver/i18n` scaffolding.

## [2.21.4] — 2026-10-16

### Fixed (Critical)
- Live Reload now uses `inotifywait` (fallback polling every 3s). No more per-second CPU hammering.
- 300ms debounce on file changes to coalesce bursts.
- `.myserver-ignore` file to skip paths (default ignores `vendor`, `node_modules`, etc).
- Safe process termination via PID files + `pkill -x` (never `pkill -f`).
- `skip-grant-tables` repair now always runs with `--skip-networking` and verifies port 3306 is not listening.
- `sub_filter` injection only when `.livereload` marker exists in web root.
- `sub_filter` regex now anchors to end-of-body instead of any `</body>`.
- SSE clients capped at 50 (configurable via `MYSERVER_LIVE_MAX_CLIENTS`).
- SSE clients only from 127.0.0.1, 90-second idle timeout.
- phpMyAdmin sensitive directories blocked in Nginx (`config.inc.php`, `setup`, `libraries`, `tmp`, `sql`).

### Added
- `myserver backup` / `myserver restore` / `myserver backup-list` — full snapshot of htdocs, DBs, SSL, configs, `.my.cnf` as `.tar.gz` in `~/myserver-backups/`.
- `myserver doctor` — full diagnostic: packages, files, ports, permissions, DB, SSL, Internet.
- `myserver wake-lock` / `myserver wake-unlock` + auto on start/stop.
- Boot script auto-installed at `~/.termux/boot/start-myserver.sh` when Termux:Boot is present.
- `myserver ssl-info` — certificate details (type, expiry, SHA-256, download link).
- `myserver ssl-import <cert> <key>` — use custom certificate.
- Custom certificate detection: `ssl/custom.crt` + `ssl/custom.key` are used automatically.
- SSL warning displayed in interactive menu when using self-signed.

### Changed (Architecture)
- Project split into modular Python package (`myserver/core`, `services`, `features`, `cli`, `i18n`).
- Distribution changed to tarball (`install.sh` bootstrap). Old `install_server.py` URL still redirects for backward compatibility.
- `VERSION` and `CHANGELOG.md` are now separate root files (parsed at runtime).
- `bin/myserver` is now a Python shim (no more generated bash). Faster, more maintainable.
- Package installed to `$PREFIX/lib/myserver/`; CLI shim at `$PREFIX/bin/myserver`.

## [2.20.2] — previous stable
- (legacy version history preserved in git tags)
