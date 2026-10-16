from __future__ import annotations

from ..core import paths, helpers, ui


def setup() -> bool:
    try:
        redis_data = paths.PREFIX / "var/lib/redis"
        log_dir = paths.LOG_DIR
        redis_data.mkdir(parents=True, exist_ok=True)
        log_dir.mkdir(parents=True, exist_ok=True)
        (paths.PREFIX / "etc/redis.conf").write_text(
            f"dir {redis_data}\nport 6379\nbind 127.0.0.1\ndaemonize yes\n"
            f"logfile {log_dir}/redis.log\nignore-warnings ARM64-COW-BUG\n")
        ui.ok("Redis configured (ARM64 warning suppressed).")
        return True
    except Exception as e:
        ui.err(f"Redis init error: {e}")
        return False


def start() -> bool:
    if helpers.is_process_running("redis-server"):
        pid = helpers.pid_from_pgrep("redis-server")
        if pid:
            helpers.write_pid_file(paths.PID_REDIS, pid)
        return True
    conf = paths.PREFIX / "etc/redis.conf"
    if conf.exists():
        helpers.run_cmd(f"redis-server '{conf}'")
    else:
        helpers.run_cmd("redis-server --daemonize yes --ignore-warnings ARM64-COW-BUG")
    pid = helpers.pid_from_pgrep("redis-server")
    if pid:
        helpers.write_pid_file(paths.PID_REDIS, pid)
        return True
    return False


def stop() -> bool:
    helpers.run_cmd("redis-cli -h 127.0.0.1 -p 6379 shutdown nosave")
    return helpers.safe_stop(paths.PID_REDIS, ("redis-server",))