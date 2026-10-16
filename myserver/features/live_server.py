#!/data/data/com.termux/files/usr/bin/python3
"""
myserver-live — Live Reload helper for Termux Web Server.

- Uses inotifywait when available (efficient, event-driven).
- Falls back to polling every 3 seconds.
- 300ms debounce on file changes.
- Honors `.myserver-ignore` at the watched root.
- SSE clients capped at MYSERVER_LIVE_MAX_CLIENTS (default 50).
- Idle clients auto-disconnected after 90s without ping.
- Binds to 127.0.0.1 only.
"""
from __future__ import annotations

import fnmatch
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# ---------------------------------------------------------------------------
HTDOCS_DIR    = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "htdocs"
PORT          = int(sys.argv[2]) if len(sys.argv) > 2 else 35730
PID_FILE      = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("/tmp/myserver-live.pid")
LOG_FILE      = Path(sys.argv[4]) if len(sys.argv) > 4 else Path("/tmp/myserver-live.log")

MAX_CLIENTS   = int(os.environ.get("MYSERVER_LIVE_MAX_CLIENTS", "50"))
IDLE_TIMEOUT  = 90        # seconds
DEBOUNCE_MS   = 300
POLL_FALLBACK = 3.0       # seconds
IGNORE_FILE   = HTDOCS_DIR / ".myserver-ignore"

DEFAULT_IGNORE_DIRS = {
    ".git", "node_modules", "vendor", "cache", ".cache", "__pycache__",
    ".idea", ".vscode", "storage/framework", "storage/logs",
}
DEFAULT_IGNORE_EXTS = {".log", ".tmp", ".swp", ".swo", ".lock", ".pid"}

# ---------------------------------------------------------------------------
_state_lock = threading.Lock()
_clients: list[dict] = []          # [{"wfile": wfile, "last": ts, "id": int}]
_shutdown = threading.Event()
_debounce_timer: threading.Timer | None = None
_debounce_lock = threading.Lock()
_ignore_patterns: list[str] = []   # fnmatch patterns


def log(msg: str):
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
def _load_ignore():
    """Load ignore patterns from .myserver-ignore + defaults."""
    global _ignore_patterns
    pats: list[str] = []
    for d in DEFAULT_IGNORE_DIRS:
        pats.append(f"*/{d}/*")
    if IGNORE_FILE.exists():
        try:
            for raw in IGNORE_FILE.read_text().splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if not line.startswith("*") and "/" not in line:
                    line = f"*/{line}/*"
                pats.append(line)
        except Exception as e:
            log(f"ignore file read error: {e}")
    _ignore_patterns = pats
    log(f"loaded {len(pats)} ignore pattern(s)")


def _is_ignored(path: str) -> bool:
    try:
        rel = str(Path(path).resolve().relative_to(HTDOCS_DIR.resolve()))
    except Exception:
        rel = path
    ext = os.path.splitext(rel)[1].lower()
    if ext in DEFAULT_IGNORE_EXTS:
        return True
    # normalize to forward slashes for matching
    rel_fwd = rel.replace(os.sep, "/")
    for pat in _ignore_patterns:
        if fnmatch.fnmatch(rel_fwd, pat) or fnmatch.fnmatch("/" + rel_fwd, pat):
            return True
    for d in DEFAULT_IGNORE_DIRS:
        if f"/{d}/" in f"/{rel_fwd}/":
            return True
    return False


# ---------------------------------------------------------------------------
def _broadcast():
    msg = b"event: reload\ndata: change\n\n"
    with _state_lock:
        dead = []
        for c in _clients:
            try:
                c["wfile"].write(msg)
                c["wfile"].flush()
                c["last"] = time.time()
            except Exception:
                dead.append(c)
        for c in dead:
            try:
                _clients.remove(c)
            except Exception:
                pass
    if dead:
        log(f"broadcast: removed {len(dead)} dead client(s)")


def _schedule_broadcast():
    """Debounce — restart timer on every event."""
    global _debounce_timer
    with _debounce_lock:
        if _debounce_timer is not None:
            _debounce_timer.cancel()
        t = threading.Timer(DEBOUNCE_MS / 1000.0, _broadcast)
        t.daemon = True
        t.start()
        _debounce_timer = t


# ---------------------------------------------------------------------------
# inotify path
# ---------------------------------------------------------------------------
def _has_inotifywait() -> bool:
    from shutil import which
    return which("inotifywait") is not None


def _run_inotify():
    log("watcher: inotifywait (event-driven)")
    cmd = ["inotifywait", "-m", "-r", "-q",
           "--format", "%w%f|%e", str(HTDOCS_DIR)]
    while not _shutdown.is_set():
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, bufsize=1)
        except Exception as e:
            log(f"inotifywait spawn failed: {e} — falling back to polling")
            return _run_polling()

        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                if _shutdown.is_set():
                    break
                line = line.strip()
                if not line or "|" not in line:
                    continue
                path, _event = line.split("|", 1)
                if _is_ignored(path):
                    continue
                log(f"change: {path}")
                _schedule_broadcast()
        except Exception as e:
            log(f"inotify loop error: {e}")
        finally:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        if _shutdown.is_set():
            return
        log("inotifywait died — restarting in 2s")
        time.sleep(2)


# ---------------------------------------------------------------------------
# polling fallback
# ---------------------------------------------------------------------------
def _scan_mtimes() -> dict[str, int]:
    result: dict[str, int] = {}
    try:
        for root, dirs, files in os.walk(HTDOCS_DIR):
            dirs[:] = [d for d in dirs
                       if d not in DEFAULT_IGNORE_DIRS and not d.startswith(".")]
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in DEFAULT_IGNORE_EXTS:
                    continue
                p = os.path.join(root, f)
                if _is_ignored(p):
                    continue
                try:
                    result[p] = os.stat(p).st_mtime_ns
                except Exception:
                    pass
    except Exception as e:
        log(f"scan error: {e}")
    return result


def _run_polling():
    log(f"watcher: polling every {POLL_FALLBACK}s")
    last = _scan_mtimes()
    while not _shutdown.is_set():
        time.sleep(POLL_FALLBACK)
        cur = _scan_mtimes()
        if cur != last:
            changed = sum(1 for k in set(cur) | set(last)
                          if cur.get(k) != last.get(k))
            log(f"polling: {changed} file(s) changed")
            _schedule_broadcast()
            last = cur


# ---------------------------------------------------------------------------
# idle-client reaper
# ---------------------------------------------------------------------------
def _reap_idle():
    while not _shutdown.is_set():
        time.sleep(10)
        now = time.time()
        with _state_lock:
            stale = [c for c in _clients if now - c["last"] > IDLE_TIMEOUT]
            for c in stale:
                try:
                    c["wfile"].write(b": timeout\n\n")
                    c["wfile"].flush()
                except Exception:
                    pass
                try:
                    _clients.remove(c)
                except Exception:
                    pass
        if stale:
            log(f"reaped {len(stale)} idle client(s)")


# ---------------------------------------------------------------------------
JS_PAYLOAD = (
    "/* myserver live-reload client */\n"
    "(function(){\n"
    "  if (window.__myserverLiveLoaded) return;\n"
    "  window.__myserverLiveLoaded = true;\n"
    "  try {\n"
    "    var es = new EventSource('/__live/sse');\n"
    "    es.addEventListener('reload', function(){ location.reload(); });\n"
    "    es.onerror = function(){\n"
    "      try { es.close(); } catch(e) {}\n"
    "      setTimeout(function(){ window.__myserverLiveLoaded = false; location.reload(); }, 3000);\n"
    "    };\n"
    "  } catch(e) { /* EventSource unsupported */ }\n"
    "})();\n"
).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "myserver-live/2.21"

    def log_message(self, fmt, *args):
        pass

    # ---- SSE ----
    def _handle_sse(self):
        # only localhost (defense-in-depth — Nginx already enforces this)
        peer = self.client_address[0] if self.client_address else ""
        if peer not in ("127.0.0.1", "::1"):
            self.send_response(403)
            self.end_headers()
            return

        with _state_lock:
            if len(_clients) >= MAX_CLIENTS:
                self.send_response(503)
                self.send_header("Retry-After", "5")
                self.end_headers()
                log(f"rejected client (max {MAX_CLIENTS} reached)")
                return

        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
        except Exception:
            return

        entry = {"wfile": self.wfile, "last": time.time(), "id": id(self.wfile)}
        with _state_lock:
            _clients.append(entry)
            n = len(_clients)
        log(f"client connected ({n} total)")

        try:
            while not _shutdown.is_set():
                time.sleep(15)
                self.wfile.write(b": ping\n\n")
                self.wfile.flush()
                with _state_lock:
                    entry["last"] = time.time()
        except Exception:
            pass
        finally:
            with _state_lock:
                if entry in _clients:
                    _clients.remove(entry)
                n = len(_clients)
            log(f"client disconnected ({n} left)")

    def do_GET(self):
        path = self.path.split("?", 1)[0]

        if path == "/__live/sse":
            return self._handle_sse()

        if path == "/__live.js":
            body = JS_PAYLOAD
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception:
                pass
            return

        if path == "/__live/health":
            body = b"ok\n"
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception:
                pass
            return

        self.send_response(404)
        self.end_headers()


# ---------------------------------------------------------------------------
def _install_signal_handlers():
    def _stop(_sig, _frame):
        log("signal — shutting down")
        _shutdown.set()
        with _state_lock:
            for c in list(_clients):
                try:
                    c["wfile"].write(b": bye\n\n")
                    c["wfile"].flush()
                except Exception:
                    pass
    for s in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(s, _stop)
        except Exception:
            pass


def main():
    if not HTDOCS_DIR.exists():
        log(f"FATAL: htdocs not found: {HTDOCS_DIR}")
        print(f"htdocs not found: {HTDOCS_DIR}", file=sys.stderr)
        sys.exit(1)

    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))
    except Exception as e:
        log(f"pid file error: {e}")

    _load_ignore()
    _install_signal_handlers()

    try:
        server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
        server.daemon_threads = True
    except OSError as e:
        log(f"FATAL: cannot bind 127.0.0.1:{PORT} — {e}")
        print(f"cannot bind port {PORT}: {e}", file=sys.stderr)
        sys.exit(2)

    threading.Thread(target=server.serve_forever, daemon=True).start()
    threading.Thread(target=_reap_idle, daemon=True).start()

    if _has_inotifywait():
        watcher = threading.Thread(target=_run_inotify, daemon=True)
    else:
        watcher = threading.Thread(target=_run_polling, daemon=True)
    watcher.start()

    log(f"started: htdocs={HTDOCS_DIR} port={PORT} pid={os.getpid()} "
        f"max_clients={MAX_CLIENTS}")

    try:
        while not _shutdown.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        _shutdown.set()
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            PID_FILE.unlink()
        except Exception:
            pass
        log("stopped")


if __name__ == "__main__":
    main()