# Changelog

## [2.21.2] — 2026-10-16

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