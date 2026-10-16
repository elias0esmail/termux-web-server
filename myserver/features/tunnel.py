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


# ---------------------------------------------------------------------------
def enable():
    if not helpers.is_process_running("nginx"):
        ui.err("Server is not running.")
        return False

    if is_running():
        ui.info("Tunnel already running.")
        return True

    if not helpers.command_exists("cloudflared"):
        ui.warn("cloudflared not found — installing...")
        helpers.run_cmd("pkg install -y cloudflared")
        if not helpers.command_exists("cloudflared"):
            ui.err("Failed to install cloudflared.")
            return False

    # Informational check — NOT a blocker.
    # cloudflared will fail with its own clear message if offline.
    online, diag = helpers.check_internet()
    if online:
        ui.info(f"Internet: {diag}")
    else:
        ui.warn(f"Internet check inconclusive ({diag}).")
        ui.info("Proceeding anyway — cloudflared will report if truly offline.")

    ui.step("Starting Cloudflare tunnel...")
    for f in (paths.PID_TUNNEL, paths.TUNNEL_URL_FILE, paths.TUNNEL_LOG):
        try:
            if f.exists():
                f.unlink()
        except Exception:
            pass

    with open(paths.TUNNEL_LOG, "ab") as logf:
        proc = subprocess.Popen(
            ["cloudflared", "tunnel", "--url", "http://localhost:8080",
             "--no-autoupdate"],
            stdout=logf, stderr=logf, stdin=subprocess.DEVNULL,
            start_new_session=True)
    helpers.write_pid_file(paths.PID_TUNNEL, proc.pid)

    ui.info("Waiting for public URL (up to 45s)...")
    found = ""
    for _ in range(45):
        time.sleep(1)
        # process died?
        if not helpers.pid_alive(proc.pid):
            break
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

    # failure — inspect log to give the user a precise reason
    tail = ""
    try:
        tail = paths.TUNNEL_LOG.read_text(errors="ignore")
    except Exception:
        pass

    ui.err("Failed to obtain tunnel URL.")
    if "no such host" in tail.lower() or "dns" in tail.lower():
        ui.warn("Possible DNS problem — try: ping google.com")
    elif "connection refused" in tail.lower():
        ui.warn("Nginx may not be listening on 8080.")
    elif "network is unreachable" in tail.lower():
        ui.warn("No internet from cloudflared's view.")
    elif tail.strip():
        # show last few lines
        lines = [l for l in tail.splitlines() if l.strip()]
        print(f"{ui.C_YELLOW}--- last cloudflared output ---{ui.C_RESET}")
        for ln in lines[-8:]:
            print(f"  {ln}")
        print(f"{ui.C_YELLOW}------------------------------{ui.C_RESET}")
    ui.info(f"Full log: {paths.TUNNEL_LOG}")

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
            ui.warn("URL not yet assigned.")
    else:
        ui.err("Tunnel: STOPPED")