"""Full-stack backup & restore as .tar.gz archives.

Layout inside archive:
    manifest.json
    htdocs/...
    mysql/all-databases.sql
    ssl/{server.crt,server.key,custom.crt,custom.key?}
    config/nginx.conf
    config/www.conf
    config/php.ini
    config/my.cnf
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from ..core import paths, helpers, ui
from ..services import mariadb


MANIFEST_VERSION = 1


# ---------------------------------------------------------------------------
def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _read_version() -> str:
    try:
        return paths.VERSION_FILE.read_text().strip() or "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
def create(name: str | None = None) -> Path | None:
    paths.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = _timestamp()
    base = name.strip() if name else f"myserver-backup-{ts}"
    out = paths.BACKUP_DIR / f"{base}.tar.gz"
    if out.exists():
        ui.err(f"Backup already exists: {out}")
        return None

    ui.step(f"Creating backup: {out.name}")
    tmp = Path(tempfile.mkdtemp(prefix="myserver-backup-"))
    try:
        # ---- htdocs ----
        ui.info("Copying htdocs...")
        if paths.HTDOCS_DIR.exists():
            shutil.copytree(paths.HTDOCS_DIR, tmp / "htdocs", symlinks=False,
                            ignore=shutil.ignore_patterns(
                                "*.log", ".git", "node_modules", "vendor"))

        # ---- mysql dump ----
        ui.info("Dumping databases...")
        (tmp / "mysql").mkdir(exist_ok=True)
        dump_file = tmp / "mysql" / "all-databases.sql"
        if not mariadb.start_mariadb_background():
            ui.warn("MariaDB did not start — DB dump skipped.")
        else:
            cli = helpers.mysql_client()
            # excludes system schemas
            with open(dump_file, "wb") as f:
                r = subprocess.run(
                    [cli, "-u", "root", f"--socket={paths.MARIADB_SOCKET}",
                     "--single-transaction", "--routines", "--triggers",
                     "--events", "--all-databases",
                     "--ignore-table=mysql.user"],
                    stdout=f, stderr=subprocess.PIPE)
            if r.returncode != 0:
                ui.warn(f"mysqldump partial: {r.stderr.decode(errors='ignore')[:200]}")
            else:
                ui.ok("Database dump saved.")

        # ---- ssl ----
        ssl_dir = tmp / "ssl"
        ssl_dir.mkdir(exist_ok=True)
        for p in (paths.DEFAULT_CERT, paths.DEFAULT_KEY,
                  paths.CUSTOM_CERT, paths.CUSTOM_KEY):
            if p.exists():
                try:
                    shutil.copy2(p, ssl_dir / p.name)
                except Exception as e:
                    ui.warn(f"SSL copy failed ({p.name}): {e}")

        # ---- configs ----
        cfg_dir = tmp / "config"
        cfg_dir.mkdir(exist_ok=True)
        for src, dst in (
            (paths.NGINX_CONF,  "nginx.conf"),
            (paths.PHP_FPM_CONF, "www.conf"),
            (helpers.get_php_ini_path(), "php.ini"),
            (paths.MY_CNF_FILE, "my.cnf"),
        ):
            try:
                if src.exists():
                    shutil.copy2(src, cfg_dir / dst)
            except Exception as e:
                ui.warn(f"Config copy failed ({dst}): {e}")

        # ---- manifest ----
        manifest = {
            "format": MANIFEST_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "myserver_version": _read_version(),
            "htdocs_path": str(paths.HTDOCS_DIR),
            "includes": {
                "htdocs": (tmp / "htdocs").exists(),
                "mysql":  dump_file.exists(),
                "ssl":    any(ssl_dir.iterdir()),
                "config": True,
            },
        }
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2))

        # ---- tarball ----
        ui.info("Compressing archive...")
        with tarfile.open(out, "w:gz") as tar:
            tar.add(tmp, arcname=".")

        size_mb = out.stat().st_size / (1024 * 1024)
        ui.ok(f"Backup created: {out}  ({size_mb:.2f} MB)")
        return out
    except Exception as e:
        ui.err(f"Backup failed: {e}")
        try:
            if out.exists():
                out.unlink()
        except Exception:
            pass
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
def list_backups() -> list[Path]:
    if not paths.BACKUP_DIR.exists():
        return []
    return sorted(paths.BACKUP_DIR.glob("*.tar.gz"),
                  key=lambda p: p.stat().st_mtime, reverse=True)


def list_cmd():
    backups = list_backups()
    if not backups:
        ui.info(f"No backups found in {paths.BACKUP_DIR}")
        return
    ui.info(f"Backups in {paths.BACKUP_DIR}:")
    for b in backups:
        st = b.stat()
        dt = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
        size = st.st_size / (1024 * 1024)
        print(f"  {dt}  {size:>8.2f} MB  {b.name}")


# ---------------------------------------------------------------------------
def restore(archive_path: str, force: bool = False) -> bool:
    src = Path(archive_path).expanduser()
    if not src.exists():
        ui.err(f"Archive not found: {src}")
        return False

    ui.step(f"Verifying archive: {src.name}")
    tmp = Path(tempfile.mkdtemp(prefix="myserver-restore-"))
    try:
        with tarfile.open(src, "r:gz") as tar:
            # safe extract
            def _safe(member, dest):
                target = (dest / member.name).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    raise RuntimeError(f"Unsafe path in archive: {member.name}")
            for member in tar.getmembers():
                _safe(member, tmp)
            tar.extractall(tmp, filter="data")

        manifest_file = tmp / "manifest.json"
        if not manifest_file.exists():
            ui.err("Invalid archive: manifest.json missing.")
            return False
        try:
            manifest = json.loads(manifest_file.read_text())
        except Exception as e:
            ui.err(f"Bad manifest: {e}")
            return False

        print(f"  Format         : {manifest.get('format')}")
        print(f"  Created at     : {manifest.get('created_at')}")
        print(f"  Version        : {manifest.get('myserver_version')}")
        print(f"  Original path  : {manifest.get('htdocs_path')}")
        includes = manifest.get("includes", {})
        print(f"  Includes       : " +
              ", ".join(k for k, v in includes.items() if v))

        if not force:
            ui.warn("Restore will OVERWRITE current htdocs, databases, SSL, and configs.")
            if not ui.confirm("Continue?", default=False):
                ui.info("Cancelled.")
                return False

        # ---- safety snapshot of current state ----
        ui.step("Creating safety backup of current state...")
        safety = create(f"pre-restore-{_timestamp()}")
        if safety:
            ui.ok(f"Safety backup: {safety}")
        else:
            ui.warn("Safety backup failed — continuing anyway.")

        # ---- stop services ----
        from ..cli import services_ctl  # local import to avoid cycle
        services_ctl.stop_all(quiet=True)

        # ---- htdocs ----
        if (tmp / "htdocs").exists():
            ui.info("Restoring htdocs...")
            if paths.HTDOCS_DIR.exists():
                shutil.rmtree(paths.HTDOCS_DIR, ignore_errors=True)
            shutil.copytree(tmp / "htdocs", paths.HTDOCS_DIR)

        # ---- ssl ----
        if (tmp / "ssl").exists():
            ui.info("Restoring SSL...")
            paths.SSL_DIR.mkdir(parents=True, exist_ok=True)
            for f in (tmp / "ssl").iterdir():
                try:
                    shutil.copy2(f, paths.SSL_DIR / f.name)
                except Exception as e:
                    ui.warn(f"SSL restore failed ({f.name}): {e}")

        # ---- configs ----
        cfg = tmp / "config"
        if cfg.exists():
            ui.info("Restoring configs...")
            for name, dest in (
                ("nginx.conf", paths.NGINX_CONF),
                ("www.conf",   paths.PHP_FPM_CONF),
                ("php.ini",    helpers.get_php_ini_path()),
                ("my.cnf",     paths.MY_CNF_FILE),
            ):
                s = cfg / name
                if s.exists():
                    try:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(s, dest)
                    except Exception as e:
                        ui.warn(f"Config restore failed ({name}): {e}")

        # ---- mysql ----
        dump = tmp / "mysql" / "all-databases.sql"
        if dump.exists():
            ui.info("Restoring databases...")
            if not mariadb.start_mariadb_background():
                ui.warn("MariaDB did not start — DB restore skipped.")
            else:
                cli = helpers.mysql_client()
                with open(dump, "rb") as f:
                    r = subprocess.run(
                        [cli, "-u", "root", f"--socket={paths.MARIADB_SOCKET}"],
                        stdin=f, stderr=subprocess.PIPE)
                if r.returncode != 0:
                    ui.warn(f"DB restore partial: {r.stderr.decode(errors='ignore')[:200]}")
                else:
                    ui.ok("Databases restored.")

        # fix permissions
        from ..services import nginx
        nginx.enforce_htdocs_permissions(paths.HTDOCS_DIR)

        ui.ok("Restore complete. Start the server with: myserver start")
        return True
    except Exception as e:
        ui.err(f"Restore failed: {e}")
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def delete(archive_path: str) -> bool:
    p = Path(archive_path).expanduser()
    if not p.exists():
        ui.err(f"Not found: {p}")
        return False
    if not ui.confirm(f"Delete {p.name}?", default=False):
        return False
    try:
        p.unlink()
        ui.ok(f"Deleted: {p.name}")
        return True
    except Exception as e:
        ui.err(f"Delete failed: {e}")
        return False