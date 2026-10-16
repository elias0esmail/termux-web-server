"""Manage the Live Reload helper (install/start/stop/status)."""
from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from ..core import paths, helpers, ui
from ..services import nginx

# ---------------------------------------------------------------------------
LIVE_CONF_ENABLED = """\
# Live Reload injection — only honored when .livereload marker exists.
sub_filter '</body>' '<script src="/__live.js"></script></body>';
sub_filter_once on;
sub_filter_types text/html;
"""


# ---------------------------------------------------------------------------
def install_binary() -> bool:
    """Copy live_server.py from the installed package into $PREFIX/bin."""
    try:
        src = Path(__file__).resolve().parent / "live_server.py"
        if not src.exists():
            ui.err(f"live_server.py not found at {src}")
            return False
        content = src.read_text()
        if not content.startswith("#!"):
            content = "#!/data/data/com.termux/files/usr/bin/python3\n" + content
        paths.BIN_MYSERVER_LIVE.write_text(content)
        paths.BIN_MYSERVER_LIVE.chmod(0o755)
        paths.LIVE_CONF_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not paths.LIVE_CONF_FILE.exists():
            paths.LIVE_CONF_FILE.write_text("")
        ui.ok("Live Reload server installed.")
        return True
    except Exception as e:
        ui.err(f"Live Reload install error: {e}")
        return False


# ---------------------------------------------------------------------------
def is_running() -> bool:
    if paths.PID_LIVE.exists():
        pid = helpers.read_pid_file(paths.PID_LIVE)
        if pid and helpers.pid_alive(pid):
            return True
    return helpers.is_process_running("myserver-live")


# ---------------------------------------------------------------------------
def _write_conf_enabled():
    paths.LIVE_CONF_FILE.write_text(LIVE_CONF_ENABLED)


def _write_conf_disabled():
    paths.LIVE_CONF_FILE.write_text("")


def _marker_exists() -> bool:
    return (paths.HTDOCS_DIR / paths.LIVE_MARKER_FILE).exists()


def _ensure_marker() -> bool:
    """Live reload injection requires .livereload marker in web root.
       Ask user whether to create it now."""
    if _marker_exists():
        return True
    ui.warn(f"Marker file '{paths.LIVE_MARKER_FILE}' not found in web root.")
    ui.info("This marker enables safe HTML injection — required for Live Reload.")
    if not ui.confirm(f"Create {paths.LIVE_MARKER_FILE} in {paths.HTDOCS_DIR}?", default=True):
        ui.warn("Skipped — Live Reload will run but won't inject the client script.")
        return False
    try:
        (paths.HTDOCS_DIR / paths.LIVE_MARKER_FILE).write_text(
            "# Presence of this file enables Live Reload HTML injection.\n")
        ui.ok(f"Marker created: {paths.HTDOCS_DIR / paths.LIVE_MARKER_FILE}")
        return True
    except Exception as e:
        ui.err(f"Could not create marker: {e}")
        return False


# ---------------------------------------------------------------------------
def start() -> bool:
    from ..services import nginx as ngx

    if not (helpers.is_process_running("nginx")
            or helpers.is_process_running("php-fpm")):
        ui.err("Server is not running — start it first.")
        return False

    if is_running():
        ui.info("Live Reload already running.")
        return True

    if not paths.BIN_MYSERVER_LIVE.exists():
        ui.err(f"Live server binary missing: {paths.BIN_MYSERVER_LIVE}")
        return False

    if helpers.port_in_use(paths.LIVE_PORT):
        ui.err(f"Port {paths.LIVE_PORT} is already in use.")
        return False

    # marker + conf
    _ensure_marker()

    ui.step(f"Starting Live Reload on port {paths.LIVE_PORT}...")
    for f in (paths.PID_LIVE, paths.LIVE_LOG_FILE):
        try:
            if f.exists():
                f.unlink()
        except Exception:
            pass

    with open(paths.LIVE_LOG_FILE, "ab") as logf:
        subprocess.Popen(
            [str(paths.BIN_MYSERVER_LIVE),
             str(paths.HTDOCS_DIR),
             str(paths.LIVE_PORT),
             str(paths.PID_LIVE),
             str(paths.LIVE_LOG_FILE)],
            stdout=logf, stderr=logf,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    for _ in range(5):
        time.sleep(1)
        if is_running():
            break

    if not is_running():
        ui.err(f"Failed to start Live Reload. Check: {paths.LIVE_LOG_FILE}")
        return False

    _write_conf_enabled()
    nginx.reload()
    ui.ok("Live Reload enabled (auto-refresh on save).")
    ui.info(f"Watching: {paths.HTDOCS_DIR}")
    return True


# ---------------------------------------------------------------------------
def stop(quiet: bool = False) -> bool:
    if not is_running():
        _write_conf_disabled()
        nginx.reload()
        if not quiet:
            ui.info("Live Reload already stopped.")
        return True

    if not quiet:
        ui.step("Stopping Live Reload...")

    helpers.safe_stop(paths.PID_LIVE, ("myserver-live",))
    _write_conf_disabled()
    nginx.reload()

    if not quiet:
        ui.ok("Live Reload disabled.")
    return True


def restart() -> bool:
    stop(quiet=True)
    time.sleep(1)
    return start()


def status():
    if is_running():
        pid = helpers.read_pid_file(paths.PID_LIVE)
        ui.ok(f"Live Reload: RUNNING (port {paths.LIVE_PORT}, pid {pid})")
        print(f"  Watching  : {paths.HTDOCS_DIR}")
        print(f"  Log       : {paths.LIVE_LOG_FILE}")
        print(f"  Max SSE   : {paths.LIVE_MAX_CLIENTS} clients")
        print(f"  Ignore    : {paths.HTDOCS_DIR / paths.LIVE_IGNORE_FILE} "
              f"{'(present)' if (paths.HTDOCS_DIR / paths.LIVE_IGNORE_FILE).exists() else '(none)'}")
        print(f"  Marker    : {paths.HTDOCS_DIR / paths.LIVE_MARKER_FILE} "
              f"{'(present)' if _marker_exists() else '(missing)'}")
        if not _marker_exists():
            ui.warn("Marker missing — client script will NOT be injected.")
    else:
        ui.err("Live Reload: STOPPED")


def toggle():
    if is_running():
        stop()
    else:
        start()


def tail_log(lines: int = 30):
    if not paths.LIVE_LOG_FILE.exists():
        ui.warn("No log file yet.")
        return
    try:
        content = paths.LIVE_LOG_FILE.read_text().splitlines()
        for ln in content[-lines:]:
            print(ln)
    except Exception as e:
        ui.err(f"Could not read log: {e}")