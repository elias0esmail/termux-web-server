"""Full-stack backup & restore as .tar.gz archives.

Archive layout:
    manifest.json
    htdocs/...                                  (user data + phpMyAdmin config)
    mysql/all-databases.sql                     (user databases only)
    ssl/{server.crt,server.key,custom.?}        (SSL certificates)
    config/{nginx.conf,www.conf,php.ini,99-myserver.ini,my.cnf,conf.d/}
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ..core import paths, helpers, ui
from ..services import mariadb


MANIFEST_VERSION = 2
SYSTEM_DBS = mariadb.SYSTEM_DBS

# phpMyAdmin paths (relative to htdocs)
PMA_DIRNAME   = "phpmyadmin"
PMA_KEEP_ONLY = {"config.inc.php"}   # only this file survives backup

MIN_SQL_DUMP_SIZE = 200


# ---------------------------------------------------------------------------
def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _read_version() -> str:
    return helpers.read_version()


def _list_user_databases() -> list[str]:
    return mariadb.list_user_databases(quiet=False)


# ---------------------------------------------------------------------------
def _ignore_for_backup(dirpath: str, names: list[str]) -> set[str]:
    """Custom ignore filter for `shutil.copytree`."""
    ignored: set[str] = set()

    for n in names:
        if n in (".git", "node_modules", "cache", ".cache",
                 ".myserver-cache", "tmp", "temp"):
            ignored.add(n)
        elif n.endswith(".log"):
            ignored.add(n)

    try:
        rel = os.path.relpath(dirpath, paths.HTDOCS_DIR)
    except ValueError:
        rel = ""

    rel = rel.replace(os.sep, "/").lstrip("./")

    if rel == PMA_DIRNAME:
        for n in names:
            if n not in PMA_KEEP_ONLY:
                ignored.add(n)

    return ignored


# ---------------------------------------------------------------------------
def create(name: str | None = None) -> Path | None:
    paths.resolve_runtime_paths()
    paths.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = _timestamp()
    base = name.strip() if name else f"myserver-backup-{ts}"
    out = paths.BACKUP_DIR / f"{base}.tar.gz"
    if out.exists():
        ui.err(f"Backup already exists: {out}")
        return None

    ui.step(f"Creating backup: {out.name}")
    tmp = Path(tempfile.mkdtemp(prefix="myserver-backup-"))
    db_ok = True
    pma_cfg_backed_up = False

    try:
        # ---- htdocs ----
        ui.info("Copying htdocs...")
        if paths.HTDOCS_DIR.exists():
            try:
                shutil.copytree(
                    paths.HTDOCS_DIR,
                    tmp / "htdocs",
                    symlinks=False,
                    ignore=_ignore_for_backup,
                )
            except Exception as e:
                ui.warn(f"htdocs copy partial: {e}")

        # ---- phpMyAdmin config check ----
        pma_cfg_backed_up = (tmp / "htdocs" / PMA_DIRNAME / "config.inc.php").exists()
        if pma_cfg_backed_up:
            ui.info("phpMyAdmin: config saved (binary will be reinstalled on restore).")

        # ---- mysql dump ----
        ui.info("Dumping databases...")
        (tmp / "mysql").mkdir(exist_ok=True)
        dump_file = tmp / "mysql" / "all-databases.sql"

        if not mariadb.start_mariadb_background():
            ui.warn("MariaDB did not start — DB dump skipped.")
            db_ok = False
            dump_file.write_text("-- MariaDB failed to start\n")
        else:
            dbs = _list_user_databases()
            if not dbs:
                ui.info("No user databases to dump.")
                dump_file.write_text("-- No user databases\n")
            else:
                dump_bin = helpers.mysql_dump()
                cmd = [
                    dump_bin,
                    "-u", "root",
                    f"--socket={paths.MARIADB_SOCKET}",
                    "--single-transaction",
                    "--routines",
                    "--triggers",
                    "--events",
                    "--databases", *dbs,
                ]
                with open(dump_file, "wb") as f:
                    r = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE)
                if r.returncode != 0:
                    err = (r.stderr or b"").decode(errors="ignore").strip()[:300]
                    ui.warn(f"mysqldump warning: {err}")
                    db_ok = False
                else:
                    size_kb = dump_file.stat().st_size / 1024
                    ui.ok(f"Database dump saved ({size_kb:.1f} KB, "
                          f"{len(dbs)} database(s)).")

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

        # ---- configs + virtual hosts ----
        cfg_dir = tmp / "config"
        cfg_dir.mkdir(exist_ok=True)
        for src, dst in (
            (paths.NGINX_CONF,           "nginx.conf"),
            (paths.PHP_FPM_CONF,         "www.conf"),
            (helpers.get_php_ini_path(), "php.ini"),
            (paths.PHP_MYSERVER_INI,     "99-myserver.ini"),
            (paths.MY_CNF_FILE,          "my.cnf"),
        ):
            try:
                if src.exists():
                    shutil.copy2(src, cfg_dir / dst)
            except Exception as e:
                ui.warn(f"Config copy failed ({dst}): {e}")

        if paths.NGINX_CONFD_DIR.exists() and any(paths.NGINX_CONFD_DIR.glob("*.conf")):
            try:
                shutil.copytree(paths.NGINX_CONFD_DIR, cfg_dir / "conf.d")
            except Exception as e:
                ui.warn(f"VHost conf.d copy failed: {e}")

        # ---- manifest ----
        dump_size = dump_file.stat().st_size if dump_file.exists() else 0
        manifest = {
            "format": MANIFEST_VERSION,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "myserver_version": _read_version(),
            "htdocs_path": str(paths.HTDOCS_DIR),
            "includes": {
                "htdocs":          (tmp / "htdocs").exists(),
                "phpmyadmin_cfg":  pma_cfg_backed_up,
                "mysql":           dump_size >= MIN_SQL_DUMP_SIZE,
                "ssl":             any(ssl_dir.iterdir()),
                "config":          True,
                "vhosts":          (cfg_dir / "conf.d").exists(),
            },
            "database_ok": db_ok,
            "sql_dump_bytes": dump_size,
        }
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2))

        # ---- tarball ----
        ui.info("Compressing archive...")
        with tarfile.open(out, "w:gz") as tar:
            tar.add(tmp, arcname=".")

        size_mb = out.stat().st_size / (1024 * 1024)
        ui.ok(f"Backup created: {out}  ({size_mb:.2f} MB)")
        if not db_ok:
            ui.warn("Note: database dump had warnings — verify the archive.")
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
    paths.resolve_runtime_paths()
    found: list[Path] = []
    for d in {paths.BACKUP_DIR, paths.HOME_BACKUP_DIR, paths.STORAGE_BACKUP_DIR}:
        try:
            if d.exists():
                found.extend(d.glob("*.tar.gz"))
        except Exception:
            pass
    unique = {p.resolve(): p for p in found}
    return sorted(unique.values(), key=lambda p: p.stat().st_mtime, reverse=True)


def list_cmd():
    backups = list_backups()
    if not backups:
        ui.info(f"No backups found in {paths.BACKUP_DIR}")
        return
    ui.info(f"Backups ({len(backups)}):")
    for b in backups:
        st = b.stat()
        dt = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
        size = st.st_size / (1024 * 1024)
        print(f"  {dt}  {size:>8.2f} MB  {b}")


# ---------------------------------------------------------------------------
def restore(archive_path: str, force: bool = False) -> bool:
    src = Path(archive_path).expanduser()
    if not src.exists():
        ui.err(f"Archive not found: {src}")
        return False

    ui.step(f"Verifying archive: {src.name}")
    tmp = Path(tempfile.mkdtemp(prefix="myserver-restore-"))

    from ..cli import services_ctl

    try:
        with tarfile.open(src, "r:gz") as tar:
            def _safe(member, dest):
                target = (dest / member.name).resolve()
                if not str(target).startswith(str(dest.resolve())):
                    raise RuntimeError(f"Unsafe path in archive: {member.name}")
            for member in tar.getmembers():
                _safe(member, tmp)
            try:
                tar.extractall(tmp, filter="data")
            except TypeError:
                tar.extractall(tmp)

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
            ui.warn("Restore will OVERWRITE current htdocs, databases, SSL, configs.")
            if not ui.confirm("Continue?", default=False):
                ui.info("Cancelled.")
                return False

        # ---- safety snapshot ----
        ui.step("Creating safety backup of current state...")
        safety = create(f"pre-restore-{_timestamp()}")
        if safety:
            ui.ok(f"Safety backup: {safety}")
        else:
            ui.warn("Safety backup failed — continuing anyway.")

        # ---- stop services ----
        services_ctl.stop_all(quiet=True)

        # ---- htdocs ----
        saved_pma_cfg_text: str | None = None
        pma_cfg_in_archive = tmp / "htdocs" / PMA_DIRNAME / "config.inc.php"
        if pma_cfg_in_archive.exists():
            try:
                saved_pma_cfg_text = pma_cfg_in_archive.read_text()
            except Exception as e:
                ui.warn(f"Could not read saved phpMyAdmin config: {e}")

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
                ("nginx.conf",      paths.NGINX_CONF),
                ("www.conf",        paths.PHP_FPM_CONF),
                ("php.ini",         helpers.get_php_ini_path()),
                ("99-myserver.ini", paths.PHP_MYSERVER_INI),
                ("my.cnf",          paths.MY_CNF_FILE),
            ):
                s = cfg / name
                if s.exists():
                    try:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(s, dest)
                    except Exception as e:
                        ui.warn(f"Config restore failed ({name}): {e}")
            if (cfg / "conf.d").exists():
                paths.NGINX_CONFD_DIR.mkdir(parents=True, exist_ok=True)
                for vconf in (cfg / "conf.d").glob("*.conf"):
                    try:
                        shutil.copy2(vconf, paths.NGINX_CONFD_DIR / vconf.name)
                    except Exception:
                        pass

        # ---- mysql ----
        dump = tmp / "mysql" / "all-databases.sql"
        if not dump.exists():
            ui.warn("No SQL dump in archive — DB restore skipped.")
        elif dump.stat().st_size < MIN_SQL_DUMP_SIZE:
            ui.warn(f"SQL dump too small ({dump.stat().st_size} bytes) — "
                    f"likely empty; DB restore skipped.")
        elif not mariadb.start_mariadb_background():
            ui.warn("MariaDB did not start — DB restore skipped.")
        else:
            ui.info(f"Restoring databases from "
                    f"{dump.stat().st_size / 1024:.1f} KB dump...")
            cli = helpers.mysql_client()
            with open(dump, "rb") as f:
                r = subprocess.run(
                    [cli, "-u", "root", f"--socket={paths.MARIADB_SOCKET}"],
                    stdin=f,
                    stderr=subprocess.PIPE,
                )
            if r.returncode != 0:
                err = (r.stderr or b"").decode(errors="ignore").strip()
                ui.err(f"DB restore FAILED (rc={r.returncode}):")
                for line in err.splitlines()[:8]:
                    print(f"    {line}")
                ui.info("The server continues, but data may be incomplete.")
            else:
                dbs_now = _list_user_databases()
                if dbs_now:
                    ui.ok(f"Databases restored ({len(dbs_now)}): "
                          + ", ".join(dbs_now))
                else:
                    ui.warn("Import succeeded but no user databases found.")

        # ---- fix permissions ----
        from ..services import nginx
        nginx.enforce_htdocs_permissions(paths.HTDOCS_DIR, deep=True)

        # ---- phpMyAdmin reinstall ----
        if saved_pma_cfg_text:
            ui.step("Reinstalling phpMyAdmin fresh (tool, not user data)...")
            try:
                from . import quickstart
                db_pass = mariadb.read_password_from_my_cnf()
                ok = quickstart.install_phpmyadmin(paths.HTDOCS_DIR, db_pass)
                if ok:
                    target_cfg = paths.HTDOCS_DIR / PMA_DIRNAME / "config.inc.php"
                    try:
                        target_cfg.write_text(saved_pma_cfg_text)
                        ui.ok("phpMyAdmin config.inc.php restored from backup.")
                    except Exception as e:
                        ui.warn(f"Could not restore saved phpMyAdmin config: {e}")
                else:
                    ui.warn("phpMyAdmin reinstall failed — reinstall later via 'myserver quickstart'.")
            except Exception as e:
                ui.warn(f"phpMyAdmin reinstall error: {e}")

        ui.step("Stopping services (idle state after restore)...")
        try:
            services_ctl.stop_all(quiet=True)
        except Exception as e:
            ui.warn(f"Could not stop all services cleanly: {e}")

        ui.ok("Restore complete. All services are stopped.")
        ui.info("Start when ready:  myserver start")
        return True

    except Exception as e:
        ui.err(f"Restore failed: {e}")
        try:
            services_ctl.stop_all(quiet=True)
        except Exception:
            pass
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
def choose_and_restore() -> bool:
    """Interactive restore: show backups via fzf, then restore."""
    backups = list_backups()
    if not backups:
        ui.warn(f"No backups found in {paths.BACKUP_DIR}")
        ui.info("Create one first:  myserver backup")
        return False

    options: list[str] = []
    for b in backups:
        try:
            st = b.stat()
            dt = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
            size = st.st_size / (1024 * 1024)
            options.append(f"{dt}   {size:>7.2f} MB   {b.name}")
        except Exception:
            options.append(b.name)

    options.append("── Enter path manually ──")
    options.append("── Cancel ──")

    idx = ui.choose_option(
        "Select a backup to restore",
        options,
        default=0,
    )

    if idx == len(options) - 1:
        ui.info("Cancelled.")
        return False

    if idx == len(options) - 2:
        try:
            path = input(f"{ui.C_YELLOW}Archive path: {ui.C_RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            return False
        if not path:
            ui.info("Cancelled.")
            return False
        return restore(path)

    selected = backups[idx]
    print()
    ui.info(f"Selected: {selected.name}")
    return restore(str(selected))