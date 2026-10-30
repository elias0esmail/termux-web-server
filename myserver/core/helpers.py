"""Generic helpers optimized for Android/Termux process constraints.

Key Android optimizations:
  * Commands run with `shell=False` by default (via `shlex.split`), avoiding
    an extra `/bin/sh -c` child process on every invocation.
  * Process discovery (`is_process_running`, `pid_from_pgrep`, `safe_stop`)
    inspects `/proc` and PID files directly in pure Python before falling
    back to `pgrep`/`pkill`, eliminating dozens of transient subprocesses.
  * Network reachability (`check_internet`) and LAN IP discovery (`get_lan_ip`)
    use Python's standard `urllib.request` and `socket` modules instead of
    spawning external `curl` or `ip` processes.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import paths

# ---------------------------------------------------------------------------
PHP_EXPECTED_EXTENSIONS = [
    "mysqli", "pdo_mysql", "mbstring", "openssl",
    "curl", "zip", "xml", "intl", "bcmath",
    "gd", "sodium", "redis", "apcu", "imagick",
]
PHP_EXT_PACKAGES = {
    "gd": "php-gd", "sodium": "php-sodium", "redis": "php-redis",
    "apcu": "php-apcu", "imagick": "php-imagick",
}

_SAFE_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


# ---------------------------------------------------------------------------
# Input validation & SemVer helpers
# ---------------------------------------------------------------------------
def is_safe_identifier(name: str, max_len: int = 64) -> bool:
    """Validate project, site, or database identifier (alphanumeric, _, -)."""
    if not name or len(name) > max_len:
        return False
    return bool(_SAFE_IDENTIFIER_RE.fullmatch(name))


def parse_semver(version_str: str) -> tuple[int, ...]:
    """Parse '2.22.0' into (2, 22, 0) for reliable numeric comparison."""
    cleaned = (version_str or "").strip().lstrip("vV").split("-", 1)[0]
    parts: list[int] = []
    for token in cleaned.split("."):
        m = re.match(r"^(\d+)", token.strip())
        parts.append(int(m.group(1)) if m else 0)
    return tuple(parts) if parts else (0, 0, 0)


def is_newer_version(local_ver: str, remote_ver: str) -> bool:
    """Return True only if remote_ver is strictly newer than local_ver."""
    return parse_semver(remote_ver) > parse_semver(local_ver)


# ---------------------------------------------------------------------------
# Safe subprocess wrappers (shell=False by default to save child processes)
# ---------------------------------------------------------------------------
def _normalize_cmd(cmd: list[str] | tuple[str, ...] | str) -> list[str]:
    if isinstance(cmd, (list, tuple)):
        return [str(x) for x in cmd]
    return shlex.split(cmd)


def run_cmd(cmd: list[str] | tuple[str, ...] | str,
            check: bool = False,
            shell: bool = False):
    """Run a command quietly. Defaults to shell=False to avoid extra /bin/sh."""
    args = cmd if shell else _normalize_cmd(cmd)
    return subprocess.run(
        args,
        shell=shell,
        check=check,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def run_cmd_capture(cmd: list[str] | tuple[str, ...] | str,
                    timeout: float | None = None,
                    input_text: str | None = None,
                    shell: bool = False):
    """Run a command and capture stdout/stderr with shell=False by default."""
    args = cmd if shell else _normalize_cmd(cmd)
    return subprocess.run(
        args,
        shell=shell,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def command_exists(cmd: str) -> bool:
    return shutil.which(cmd) is not None


# ---------------------------------------------------------------------------
# Pure-Python /proc inspection (avoids spawning pgrep/pkill on Android)
# ---------------------------------------------------------------------------
def _iter_proc_entries() -> list[tuple[int, str, str]]:
    """Return [(pid, comm, cmdline), ...] for processes visible in /proc.

    Skips the current Python process (`os.getpid()`).
    """
    proc_root = Path("/proc")
    if not proc_root.exists():
        return []
    my_pid = os.getpid()
    my_uid = os.getuid() if hasattr(os, "getuid") else None
    entries: list[tuple[int, str, str]] = []
    try:
        for item in os.listdir("/proc"):
            if not item.isdigit():
                continue
            pid = int(item)
            if pid == my_pid:
                continue
            pdir = proc_root / item
            try:
                if my_uid is not None and pdir.stat().st_uid != my_uid:
                    continue
                comm = ""
                comm_file = pdir / "comm"
                if comm_file.exists():
                    comm = comm_file.read_text(errors="ignore").strip()
                cmdline = ""
                cmd_file = pdir / "cmdline"
                if cmd_file.exists():
                    raw = cmd_file.read_bytes()
                    cmdline = raw.replace(b"\x00", b" ").decode("utf-8", errors="ignore").strip()
                if comm or cmdline:
                    entries.append((pid, comm, cmdline))
            except (PermissionError, FileNotFoundError, ProcessLookupError, OSError):
                continue
    except Exception:
        return []
    return entries


def is_process_running(pattern: str, pid_file: Path | None = None) -> bool:
    """Check if a process matching `pattern` is alive.

    1. Checks `pid_file` first if provided (zero subprocesses, O(1) syscall).
    2. Scans `/proc` in pure Python (supports regex or substring patterns).
    3. Falls back to `pgrep -f` only if `/proc` yielded no entries at all.
    """
    if pid_file is not None:
        pid = read_pid_file(pid_file)
        if pid and pid_alive(pid):
            return True

    entries = _iter_proc_entries()
    if entries:
        try:
            rx = re.compile(pattern)
            for _pid, comm, cmdline in entries:
                if rx.search(comm) or rx.search(cmdline):
                    return True
            return False
        except re.error:
            for _pid, comm, cmdline in entries:
                if pattern in comm or pattern in cmdline:
                    return True
            return False

    # Fallback if /proc is restricted on a non-standard environment
    r = subprocess.run(
        ["pgrep", "-f", pattern],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return r.returncode == 0


def pid_from_pgrep(pattern: str, exact: bool = False) -> int | None:
    """Find the first matching PID using pure-Python /proc scan first."""
    entries = _iter_proc_entries()
    if entries:
        for pid, comm, cmdline in entries:
            if exact:
                if comm == pattern or (cmdline and Path(cmdline.split()[0]).name == pattern):
                    return pid
            else:
                if pattern in comm or pattern in cmdline:
                    return pid
        return None

    try:
        flag = "-x" if exact else "-f"
        r = subprocess.run(["pgrep", flag, pattern], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return int(r.stdout.strip().splitlines()[0])
    except Exception:
        pass
    return None


def process_rss_mb(pid: int | None) -> float:
    """Return resident memory (VmRSS) in MB for `pid`, or 0.0 if unavailable."""
    if not pid:
        return 0.0
    try:
        status_path = Path(f"/proc/{pid}/status")
        if not status_path.exists():
            return 0.0
        for line in status_path.read_text(errors="ignore").splitlines():
            if line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    return round(int(parts[1]) / 1024.0, 1)
    except Exception:
        pass
    return 0.0


def count_user_processes() -> tuple[int, float]:
    """Return (process_count, total_rss_mb) for the current Termux UID.

    Helps monitor Android 12+ Phantom Process Killer limits (max 32).
    """
    entries = _iter_proc_entries()
    if not entries:
        return 1, process_rss_mb(os.getpid())
    total_rss = process_rss_mb(os.getpid())
    for pid, _comm, _cmd in entries:
        total_rss += process_rss_mb(pid)
    # +1 to include current Python process
    return len(entries) + 1, round(total_rss, 1)


# ---------------------------------------------------------------------------
# PID-file based safe killing
# ---------------------------------------------------------------------------
def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def read_pid_file(path: Path) -> int | None:
    try:
        txt = path.read_text().strip()
        return int(txt) if txt else None
    except Exception:
        return None


def write_pid_file(path: Path, pid: int):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(pid))
    except Exception:
        pass


def remove_pid_file(path: Path):
    try:
        path.unlink(missing_ok=True)
    except Exception:
        pass


def safe_stop(pid_file: Path, process_names: tuple[str, ...],
              grace: float = 2.0) -> bool:
    """Terminate a service safely without spawning extra pkill subprocesses:
        1. SIGTERM the exact PID from pid_file
        2. SIGTERM any matching exact binary names in /proc
        3. Wait up to `grace` seconds
        4. SIGKILL any survivors
       Returns True if the service is completely stopped afterwards.
    """
    target_pids: set[int] = set()
    pid = read_pid_file(pid_file)
    if pid and pid_alive(pid):
        target_pids.add(pid)

    entries = _iter_proc_entries()
    name_set = set(process_names)
    if entries:
        for ep, comm, cmdline in entries:
            exe_name = Path(cmdline.split()[0]).name if cmdline else ""
            if comm in name_set or exe_name in name_set:
                target_pids.add(ep)
    else:
        # Fallback if /proc is not readable
        for name in process_names:
            subprocess.run(
                ["pkill", "-x", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    for tpid in list(target_pids):
        try:
            os.kill(tpid, signal.SIGTERM)
        except Exception:
            pass

    if target_pids:
        deadline = time.time() + grace
        while time.time() < deadline:
            if not any(pid_alive(p) for p in target_pids):
                break
            time.sleep(0.12)

        for tpid in list(target_pids):
            if pid_alive(tpid):
                try:
                    os.kill(tpid, signal.SIGKILL)
                except Exception:
                    pass
        time.sleep(0.15)

    remove_pid_file(pid_file)
    return not any(is_process_running(n) for n in process_names)


# ---------------------------------------------------------------------------
# MariaDB helpers (safe stdin execution, zero shell injection)
# ---------------------------------------------------------------------------
def mariadb_is_running() -> bool:
    if is_process_running("mariadbd|mysqld", pid_file=paths.PID_MARIADB):
        return True
    for pat in ("mariadbd", "mysqld", "mariadbd-safe", "mysqld_safe"):
        if is_process_running(pat):
            return True
    return False


def mysql_client() -> str:
    return "mariadb" if command_exists("mariadb") else "mysql"


def mysql_admin() -> str:
    return "mariadb-admin" if command_exists("mariadb-admin") else "mysqladmin"


def mysql_dump() -> str:
    """Return the dump binary (mariadb-dump / mysqldump)."""
    if command_exists("mariadb-dump"):
        return "mariadb-dump"
    return "mysqldump"


def run_mysql_query(sql: str,
                    database: str | None = None,
                    timeout: float = 15.0,
                    batch: bool = True,
                    force: bool = False) -> subprocess.CompletedProcess:
    """Execute SQL safely via stdin with shell=False (immune to shell injection)."""
    cmd = [
        mysql_client(),
        "-u", "root",
        f"--socket={paths.MARIADB_SOCKET}",
    ]
    if batch:
        cmd.extend(["-N", "-B"])
    if force:
        cmd.append("--force")
    if database:
        cmd.append(database)
    return run_cmd_capture(cmd, timeout=timeout, input_text=sql, shell=False)


def sql_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


def cnf_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


# ---------------------------------------------------------------------------
# Pure-Python Internet & LAN IP checks (zero subprocesses)
# ---------------------------------------------------------------------------
_INTERNET_ENDPOINTS = (
    ("https://www.google.com/generate_204",      "Google"),
    ("https://www.cloudflare.com/cdn-cgi/trace", "Cloudflare"),
    ("https://api.github.com",                   "GitHub"),
    ("https://1.1.1.1",                          "Cloudflare DNS"),
)


def check_internet(timeout: int = 5) -> tuple[bool, str]:
    """Try HTTPS endpoints using Python's urllib (spawns 0 child processes)."""
    last_err = ""
    for url, name in _INTERNET_ENDPOINTS:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "myserver-healthcheck"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                code = getattr(resp, "status", 200)
                if 200 <= int(code) < 400:
                    return True, f"via {name} (HTTP {code})"
                last_err = f"{name} returned HTTP {code}"
        except urllib.error.HTTPError as e:
            if 200 <= e.code < 400:
                return True, f"via {name} (HTTP {e.code})"
            last_err = f"{name} HTTP {e.code}"
        except Exception as e:
            last_err = f"{name}: {type(e).__name__}"
    return False, last_err or "no endpoint reachable"


def get_lan_ip() -> str | None:
    """Discover the device's local Wi-Fi/LAN IPv4 address using a UDP socket."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0.2)
            # Does not send any packets on the wire
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------
def port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a TCP port is currently bound/listening using Python sockets."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.35)
            s.connect((host, port))
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, port))
            return False
    except OSError:
        return True


# ---------------------------------------------------------------------------
# PHP
# ---------------------------------------------------------------------------
def get_php_ini_path() -> Path:
    for c in (paths.PREFIX / "etc/php/php.ini",
              paths.PREFIX / "lib/php.ini",
              paths.PREFIX / "etc/php.ini"):
        if c.exists():
            return c
    try:
        r = subprocess.run(["php", "--ini"], capture_output=True, text=True, timeout=8)
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                line = line.strip()
                if line.endswith("php.ini") and line.startswith("/"):
                    return Path(line)
    except Exception:
        pass
    return paths.PREFIX / "etc/php/php.ini"


def php_extension_dir() -> Path:
    if paths.PHP_LIB_DIR.exists() and any(paths.PHP_LIB_DIR.glob("*.so")):
        return paths.PHP_LIB_DIR
    for extra in ([], ["-n"]):
        try:
            r = subprocess.run(
                ["php"] + extra + ["-r", 'echo ini_get("extension_dir");'],
                capture_output=True, text=True, timeout=8,
            )
            if r.returncode == 0 and r.stdout.strip():
                lines = [l.strip() for l in r.stdout.strip().splitlines() if l.strip()]
                if lines:
                    p = Path(lines[-1])
                    if p.is_absolute():
                        return p
        except Exception:
            continue
    return paths.PHP_LIB_DIR


def php_loaded_extensions() -> set[str]:
    try:
        r = subprocess.run(["php", "-m"], capture_output=True, text=True, timeout=12)
        if r.returncode == 0:
            return {
                l.strip().lower()
                for l in r.stdout.splitlines()
                if l.strip() and not l.strip().startswith("[")
            }
    except Exception:
        pass
    return set()


def scan_available_so(ext_dir: Path) -> set[str]:
    found: set[str] = set()
    try:
        if ext_dir.exists():
            for so in ext_dir.glob("*.so"):
                found.add(so.stem)
    except Exception:
        pass
    return found


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------
def now_ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def read_version() -> str:
    try:
        if paths.VERSION_FILE.exists():
            v = paths.VERSION_FILE.read_text().strip()
            if v:
                return v
    except Exception:
        pass
    try:
        from .. import __version__
        return __version__
    except Exception:
        return "2.22.0"


def clear_screen():
    """Clear terminal screen + scrollback (best-effort)."""
    try:
        print("\033[3J\033[2J\033[H", end="", flush=True)
    except Exception:
        pass