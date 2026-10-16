#!/data/data/com.termux/files/usr/bin/python3
"""
myserver-live — Live Reload helper for Termux Web Server.

- Uses inotifywait when available (efficient, event-driven).
- Falls back to polling every 3 seconds.
- 500ms debounce on file changes.
- Honors .myserver-ignore at the watched root.
- Ignores only genuinely non-editable paths:
    * VCS:        .git, .svn, .hg
    * Editors:    .idea, .vscode, .vs
    * Deps:       node_modules, vendor, bower_components
    * Runtime:    __pycache__, .myserver-cache
    * Tool:       phpmyadmin  (writes tmp/sessions on every request)
  and by extension/name:
    * *.log *.tmp *.temp *.swp *.swo *.lock *.pid *.sess *.session
    * sess_*  .~lock.*
- SSE clients capped at MYSERVER_LIVE_MAX_CLIENTS (default 50).
- Idle clients auto-disconnected after 90s without ping.
- Binds to 127.0.0.1 only.
"""
from __future__ import annotations

import fnmatch
import os
import re as _re
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
DEBOUNCE_MS   = 500       # coalesce bursts of events
POLL_FALLBACK = 3.0       # seconds
IGNORE_FILE   = HTDOCS_DIR / ".myserver-ignore"

# ---------------------------------------------------------------------------
# IMPORTANT: keep this list SHORT and only include paths that genuinely
# cannot contain files a developer would edit. Overly broad lists hide
# legitimate changes (e.g. excluding `storage/` hides template edits in
# Laravel/Blade projects).
#
# Per-project silences belong in a `.myserver-ignore` file, not here.
# ---------------------------------------------------------------------------
DEFAULT_IGNORE_DIRS = {
    # --- VCS ---
    ".git", ".svn", ".hg",
    # --- Editors ---
    ".idea", ".vscode", ".vs",
    # --- Dependencies (huge, never edited by hand) ---
    "node_modules", "vendor", "bower_components",
    # --- Python cache ---
    "__pycache__",
    # --- Our own runtime cache ---
    ".myserver-cache",
    # --- phpMyAdmin: writes tmp/ and sessions on every request;
    #     this was the primary source of reload loops. ---
    "phpmyadmin",
}

# File extensions that never trigger reload.
DEFAULT_IGNORE_EXTS = {
    ".log", ".tmp", ".temp",
    ".swp", ".swo",               # vim swap files
    ".lock", ".pid",              # locks and pid files
    ".sess", ".session",          # PHP session files
}

# Filename prefixes that never trigger reload.
DEFAULT_IGNORE_PREFIXES = (
    "sess_",       # PHP session files: sess_abc123
    ".~lock.",     # LibreOffice / OpenOffice lock files
)


# ---------------------------------------------------------------------------
_state_lock = threading.Lock()
_clients: list[dict] = []
_shutdown = threading.Event()
_debounce_timer: threading.Timer | None = None
_debounce_lock = threading.Lock()
_ignore_patterns: list[str] = []


def log(msg: str):
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
def _load_ignore():
    """Load user ignore patterns from .myserver-ignore."""
    global _ignore_patterns
    pats: list[str] = []
    if IGNORE_FILE.exists():
        try:
            for raw in IGNORE_FILE.read_text().splitlines():
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                pats.append(line)
        except Exception as e:
            log(f"ignore file read error: {e}")
    _ignore_patterns = pats
    if pats:
        log(f"loaded {len(pats)} user ignore pattern(s)")


def _is_ignored(path: str) -> bool:
    """Return True if this path should NOT trigger a reload."""
    try:
        rel = str(Path(path).resolve().relative_to(HTDOCS_DIR.resolve()))
    except Exception:
        rel = path

    rel_fwd = rel.replace(os.sep, "/")
    basename = os.path.basename(rel_fwd)

    # --- extension filter ---
    ext = os.path.splitext(basename)[1].lower()
    if ext in DEFAULT_IGNORE_EXTS:
        return True

    # --- filename prefix filter (sess_xxx, .~lock.xxx) ---
    for prefix in DEFAULT_IGNORE_PREFIXES:
        if basename.startswith(prefix):
            return True

    # --- user-supplied patterns from .myserver-ignore ---
    for pat in _ignore_patterns:
        if fnmatch.fnmatch(rel_fwd, pat) or fnmatch.fnmatch("/" + rel_fwd, pat):
            return True

    # --- built-in directory filter: match any *parent* path component ---
    parts = rel_fwd.split("/")
    for part in parts[:-1]:          # all parent dirs except the filename
        if part in DEFAULT_IGNORE_DIRS:
            return True
    # also if the basename itself IS one of the excluded dir names
    if basename in DEFAULT_IGNORE_DIRS:
        return True

    return False


def _build_inotify_exclude_regex() -> str:
    """Build an --exclude regex for inotifywait.

    inotifywait matches this regex against the *full path* of every file.
    We anchor directory names to '/' boundaries and file prefixes to the
    beginning of the basename, to avoid false positives like matching
    'tmp' inside a folder named 'tmp-project'.
    """
    dirs = "|".join(
        _re.escape(d) for d in sorted(DEFAULT_IGNORE_DIRS, key=len, reverse=True)
    )
    exts = "|".join(
        _re.escape(e.lstrip(".")) for e in sorted(DEFAULT_IGNORE_EXTS)
    )
    prefixes = "|".join(
        _re.escape(p) for p in DEFAULT_IGNORE_PREFIXES
    )
    #   /DIR/              → directory boundary match
    #   \.(ext)$           → extension at end of path
    #   /prefix[^/]*$      → filename starting with prefix
    return (
        f"/({dirs})/"
        f"|\\.({exts})$"
        f"|/({prefixes})[^/]*$"
    )


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
    global _debounce_timer
    with _debounce_lock:
        if _debounce_timer is not None:
            _debounce_timer.cancel()
        t = threading.Timer(DEBOUNCE_MS / 1000.0, _broadcast)
        t.daemon = True
        t.start()
        _debounce_timer = t


# ---------------------------------------------------------------------------
def _has_inotifywait() -> bool:
    from shutil import which
    return which("inotifywait") is not None


def _run_inotify():
    log("watcher: inotifywait (event-driven)")
    exclude = _build_inotify_exclude_regex()
    cmd = [
        "inotifywait", "-m", "-r", "-q",
        "--exclude", exclude,
        "--format", "%w%f|%e",
        str(HTDOCS_DIR),
    ]
    log(f"inotify exclude: {exclude}")

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
def _scan_mtimes() -> dict[str, int]:
    result: dict[str, int] = {}
    try:
        for root, dirs, files in os.walk(HTDOCS_DIR):
            dirs[:] = [d for d in dirs
                       if d not in DEFAULT_IGNORE_DIRS and not d.startswith(".")]
            for f in files:
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
    server_version = "myserver-live/2.21.10"

    def log_message(self, fmt, *args):
        pass

    def _handle_sse(self):
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
        f"max_clients={MAX_CLIENTS} debounce={DEBOUNCE_MS}ms")

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