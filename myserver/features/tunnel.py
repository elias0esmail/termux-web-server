"""Cloudflare tunnel management (global public URL)."""
from __future__ import annotations

import re
import subprocess
import time

from ..core import paths, helpers, ui


CLOUDFLARED_URL_RE = re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")


# ---------------------------------------------------------------------------
def is_running() -> bool:
    if paths.PID_TUNNEL.exists():
        pid = helpers.read_pid_file(paths.PID_TUNNEL)
        if pid and helpers.pid_alive(pid):
            return True
    return helpers.is_process_running("cloudflared tunnel")


def get_url() -> str:
    try:
        if paths.TUNNEL_URL_FILE.exists():
            return paths.TUNNEL_URL_FILE.read_text().strip()
    except Exception:
        pass
    return ""


def _has_internet() -> bool:
    r = helpers.run_cmd_capture(
        'curl -s --max-time 5 -o /dev/null -w "%{http_code}" https://1.1.1.1',
        timeout=10)
    return r.returncode == 0 and r.stdout.strip()[:1] in ("2", "3")


# ---------------------------------------------------------------------------
def enable():
    if not helpers.is_process_running("nginx"):
        ui.err("Server is not running.")
        return False

    if is_running():
        ui.info("Tunnel already running.")
        return True

    if not _has_internet():
        ui.err("No internet connection.")
        return False

    if not helpers.command_exists("cloudflared"):
        ui.warn("cloudflared not found — installing...")
        helpers.run_cmd("pkg install -y cloudflared")

    ui.step("Starting Cloudflare tunnel...")
    for f in (paths.PID_TUNNEL, paths.TUNNEL_URL_FILE, paths.TUNNEL_LOG):
        try:
            if f.exists():
                f.unlink()
        except Exception:
            pass

    with open(paths.TUNNEL_LOG, "ab") as logf:
        proc = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", "http://localhost:8080"],
            stdout=logf, stderr=logf, stdin=subprocess.DEVNULL,
            start_new_session=True)
    helpers.write_pid_file(paths.PID_TUNNEL, proc.pid)

    ui.info("Waiting for public URL...")
    found = ""
    for _ in range(30):
        time.sleep(1)
        try:
            txt = paths.TUNNEL_LOG.read_text(errors="ignore")
        except Exception:
            txt = ""
        m = CLOUDFLARED_URL_RE.search(txt)
        if m:
            found = m.group(0)
            break

    if found:
        paths.TUNNEL_URL_FILE.write_text(found)
        ui.ok(f"Global URL: {found}")
        return True

    ui.err("Failed to obtain tunnel URL.")
    disable()
    return False


def disable():
    if not is_running():
        ui.info("Tunnel already disabled.")
        return True
    ui.step("Stopping Cloudflare tunnel...")
    helpers.safe_stop(paths.PID_TUNNEL, ("cloudflared",))
    for f in (paths.TUNNEL_URL_FILE, paths.TUNNEL_LOG):
        try:
            if f.exists():
                f.unlink()
        except Exception:
            pass
    ui.ok("Internet tunnel disabled.")
    return True


def status():
    if is_running():
        url = get_url()
        ui.ok("Tunnel: RUNNING")
        if url:
            print(f"  URL: {url}")
    else:
        ui.err("Tunnel: STOPPED")