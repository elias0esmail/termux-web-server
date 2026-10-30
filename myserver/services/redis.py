"""Redis service setup and lifecycle with low-overhead Android tuning."""
from __future__ import annotations

from ..core import paths, helpers, ui


def is_enabled() -> bool:
    """Return True unless user explicitly disabled Redis to save processes."""
    return not paths.REDIS_DISABLED_FILE.exists()


def set_enabled(enabled: bool) -> None:
    if enabled:
        paths.REDIS_DISABLED_FILE.unlink(missing_ok=True)
    else:
        paths.REDIS_DISABLED_FILE.parent.mkdir(parents=True, exist_ok=True)
        paths.REDIS_DISABLED_FILE.write_text("1\n")


def setup() -> bool:
    try:
        redis_data = paths.PREFIX / "var/lib/redis"
        log_dir = paths.LOG_DIR
        redis_data.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)
        paths.REDIS_CONF.write_text(
            f"dir {redis_data}\n"
            f"port 6379\n"
            f"bind 127.0.0.1\n"
            f"daemonize yes\n"
            f"pidfile {paths.PID_REDIS}\n"
            f"logfile {log_dir}/redis.log\n"
            f"hz 10\n"
            f'save ""\n'
            f"maxmemory 64mb\n"
            f"maxmemory-policy allkeys-lru\n"
            f"ignore-warnings ARM64-COW-BUG\n"
        )
        ui.ok("Redis configured (low-memory Android profile, ARM64 warning suppressed).")
        return True
    except Exception as e:
        ui.err(f"Redis init error: {e}")
        return False


def start() -> bool:
    if not is_enabled():
        return True
    if helpers.is_process_running("redis-server", pid_file=paths.PID_REDIS):
        pid = helpers.read_pid_file(paths.PID_REDIS) or helpers.pid_from_pgrep("redis-server", exact=True)
        if pid:
            helpers.write_pid_file(paths.PID_REDIS, pid)
        return True
    if paths.REDIS_CONF.exists():
        helpers.run_cmd(["redis-server", str(paths.REDIS_CONF)])
    else:
        helpers.run_cmd([
            "redis-server",
            "--daemonize", "yes",
            "--pidfile", str(paths.PID_REDIS),
            "--ignore-warnings", "ARM64-COW-BUG",
        ])
    pid = helpers.read_pid_file(paths.PID_REDIS) or helpers.pid_from_pgrep("redis-server", exact=True)
    if pid:
        helpers.write_pid_file(paths.PID_REDIS, pid)
        return True
    return False


def stop() -> bool:
    if helpers.is_process_running("redis-server", pid_file=paths.PID_REDIS):
        helpers.run_cmd(["redis-cli", "-h", "127.0.0.1", "-p", "6379", "shutdown", "nosave"])
    return helpers.safe_stop(paths.PID_REDIS, ("redis-server",))