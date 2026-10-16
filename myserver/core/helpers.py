"""Small generic helpers shared across modules."""
from __future__ import annotations

import os
import signal
import shutil
import subprocess
import time
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


# ---------------------------------------------------------------------------
def run_cmd(cmd: str, check: bool = False):
    return subprocess.run(cmd, shell=True, check=check,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_cmd_capture(cmd: str, timeout: float | None = None):
    return subprocess.run(cmd, shell=True, capture_output=True,
                          text=True, timeout=timeout)


def command_exists(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def is_process_running(pattern: str) -> bool:
    r = subprocess.run(["pgrep", "-f", pattern],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode == 0


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
        path.unlink()
    except Exception:
        pass


def safe_stop(pid_file: Path, process_names: tuple[str, ...],
              grace: float = 2.0) -> bool:
    """Terminate a service safely:
        1. SIGTERM the exact PID from pid_file
        2. wait for grace period
        3. SIGKILL if still alive
        4. fallback pkill -x on exact binary names (never -f)
       Returns True if the service is dead afterwards.
    """
    pid = read_pid_file(pid_file)
    if pid and pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
        deadline = time.time() + grace
        while time.time() < deadline:
            if not pid_alive(pid):
                break
            time.sleep(0.15)
        if pid_alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
                time.sleep(0.3)
            except Exception:
                pass

    for name in process_names:
        subprocess.run(["pkill", "-x", name],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(0.1)
    remove_pid_file(pid_file)

    return not any(is_process_running(n) for n in process_names)


def pid_from_pgrep(pattern: str) -> int | None:
    try:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return int(r.stdout.strip().splitlines()[0])
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# MariaDB helpers
# ---------------------------------------------------------------------------
def mariadb_is_running() -> bool:
    for pat in ("mariadbd-safe", "mysqld_safe", "mariadbd", "mysqld"):
        if is_process_running(pat):
            return True
    return False


def mysql_client() -> str:
    return "mariadb" if command_exists("mariadb") else "mysql"


def mysql_admin() -> str:
    return "mariadb-admin" if command_exists("mariadb-admin") else "mysqladmin"
  
def mysql_dump() -> str:
    """Return the dump binary (mariadb-dump / mysqldump).
       NOTE: this is different from mysql_client() which is the shell client."""
    if command_exists("mariadb-dump"):
        return "mariadb-dump"
    return "mysqldump"


def sql_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


def cnf_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')

# ---------------------------------------------------------------------------
# Internet check — tries multiple endpoints
# ---------------------------------------------------------------------------
_INTERNET_ENDPOINTS = (
    ("https://www.google.com/generate_204",  "Google"),
    ("https://api.github.com",               "GitHub"),
    ("https://1.1.1.1",                      "Cloudflare DNS"),
    ("https://www.cloudflare.com/cdn-cgi/trace", "Cloudflare Trace"),
)


def check_internet(timeout: int = 6) -> tuple[bool, str]:
    """Try several HTTPS endpoints; return (online, diagnostic).

    Tries the fastest / most reliable endpoints first. Any 2xx/3xx or 204
    response counts as success. Also accepts HTTP 204 for generate_204.
    """
    last_err = ""
    for url, name in _INTERNET_ENDPOINTS:
        try:
            r = subprocess.run(
                ["curl", "-s", "-L", "--max-time", str(timeout),
                 "-o", "/dev/null", "-w", "%{http_code}", url],
                capture_output=True, text=True, timeout=timeout + 4)
            code = (r.stdout or "").strip()
            if r.returncode == 0 and code[:1] in ("2", "3"):
                return True, f"via {name} (HTTP {code})"
            last_err = f"{name} returned {code or 'no-code'} (rc={r.returncode})"
        except subprocess.TimeoutExpired:
            last_err = f"{name} timed out"
        except Exception as e:
            last_err = f"{name}: {e}"
    return False, last_err or "no endpoint reachable"

# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------
def port_in_use(port: int) -> bool:
    for tool in ("ss", "netstat"):
        if not command_exists(tool):
            continue
        try:
            r = subprocess.run(
                ["sh", "-c",
                 f"{tool} -tln 2>/dev/null | awk '{{print $4}}' | grep -qE '[:.]{port}$'"],
                timeout=5)
            if r.returncode == 0:
                return True
        except Exception:
            continue
    return False


# ---------------------------------------------------------------------------
# PHP
# ---------------------------------------------------------------------------
def get_php_ini_path() -> Path:
    try:
        r = subprocess.run(["php", "--ini"], capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            for line in r.stdout.splitlines():
                line = line.strip()
                if line.endswith("php.ini") and line.startswith("/"):
                    return Path(line)
    except Exception:
        pass
    for c in (paths.PREFIX / "etc/php/php.ini",
              paths.PREFIX / "lib/php.ini",
              paths.PREFIX / "etc/php.ini"):
        if c.exists():
            return c
    return paths.PREFIX / "etc/php/php.ini"


def php_extension_dir() -> Path:
    for extra in ([], ["-n"]):
        try:
            r = subprocess.run(["php"] + extra +
                               ["-r", 'echo ini_get("extension_dir");'],
                               capture_output=True, text=True, timeout=8)
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
        r = subprocess.run(["php", "-m"], capture_output=True, text=True, timeout=15)
        if r.returncode == 0:
            return {l.strip().lower() for l in r.stdout.splitlines()
                    if l.strip() and not l.strip().startswith("[")}
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
        return paths.VERSION_FILE.read_text().strip() or "0.0.0"
    except Exception:
        return "0.0.0"