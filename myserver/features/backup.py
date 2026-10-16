"""Full-stack backup & restore as .tar.gz archives.

Archive layout:
    manifest.json
    htdocs/...                                  (user data + phpMyAdmin config)
    mysql/all-databases.sql                     (user databases only)
    ssl/{server.crt,server.key,custom.?}        (SSL certificates)
    config/{nginx.conf,www.conf,php.ini,my.cnf}

Design notes:
    * phpMyAdmin is treated as a *tool*, not user data. Its binary tree
      (vendor/, libraries/, setup/, etc.) is excluded from backups to keep
      archives small. Only htdocs/phpmyadmin/config.inc.php is preserved.
      On restore, phpMyAdmin is reinstalled fresh from upstream, then the
      saved config.inc.php is written back. This guarantees the latest
      secure version after every restore.
    * System databases (mysql, information_schema, ...) are excluded from
      the dump so restores do not clobber server users.
    * Database listing uses information_schema.SCHEMATA (reliable on all
      MariaDB/MySQL versions) instead of SHOW DATABASES WHERE (which
      silently returns zero rows on some MariaDB builds).
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


MANIFEST_VERSION = 1
SYSTEM_DBS = ("mysql", "information_schema", "performance_schema", "sys")

# phpMyAdmin paths (relative to htdocs)
PMA_DIRNAME   = "phpmyadmin"
PMA_KEEP_ONLY = {"config.inc.php"}   # ← only this file survives backup

# Minimum size (bytes) for a SQL dump to be considered "meaningful".
# Anything below this is treated as "no databases" and skipped on restore.
MIN_SQL_DUMP_SIZE = 200


# ---------------------------------------------------------------------------
def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _read_version() -> str:
    try:
        return paths.VERSION_FILE.read_text().strip() or "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
def _list_user_databases() -> list[str]:
    """Return user databases (excluding system schemas).

    Uses information_schema.SCHEMATA, NOT `SHOW DATABASES WHERE Database
    NOT IN (...)`. The latter returns zero rows silently on many MariaDB
    versions because the column name is case-sensitive and its availability
    varies. information_schema.SCHEMATA works reliably on all versions.
    """
    cli = helpers.mysql_client()
    r = helpers.run_cmd_capture(
        f"{cli} -u root --socket='{paths.MARIADB_SOCKET}' -N -B -e "
        f"\"SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
        f"WHERE SCHEMA_NAME NOT IN "
        f"('mysql','information_schema','performance_schema','sys');\"",
        timeout=15)
    if r.returncode != 0:
        err = (r.stderr or "").strip().splitlines()
        ui.warn(f"DB list failed: {err[0][:200] if err else 'unknown error'}")
        return []

    dbs = [ln.strip() for ln in (r.stdout or "").splitlines() if ln.strip()]
    if dbs:
        ui.info(f"Found {len(dbs)} user database(s): {', '.join(dbs)}")
    else:
        ui.warn("No user databases found to back up.")
    return dbs


# ---------------------------------------------------------------------------
def _ignore_for_backup(dirpath: str, names: list[str]) -> set[str]:
    """Custom ignore filter for `shutil.copytree`.

    Rules:
      * Skip junk everywhere: .git, node_modules, caches, temp dirs, *.log.
      * Inside htdocs/phpmyadmin/: keep only config.inc.php, skip everything
        else (vendor/, libraries/, setup/, tmp/, ... — will be reinstalled).
    """
    ignored: set[str] = set()

    # --- junk across the tree ---
    for n in names:
        if n in (".git", "node_modules", "cache", ".cache",
                 ".myserver-cache", "tmp", "temp"):
            ignored.add(n)
        elif n.endswith(".log"):
            ignored.add(n)

    # --- special handling for htdocs/phpmyadmin/ ---
    try:
        rel = os.path.relpath(dirpath, paths.HTDOCS_DIR)
    except ValueError:
        rel = ""

    # Normalize to forward slashes and strip leading './'
    rel = rel.replace(os.sep, "/").lstrip("./")

    if rel == PMA_DIRNAME:
        for n in names:
            if n not in PMA_KEEP_ONLY:
                ignored.add(n)

    return ignored


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

        # ---- configs ----
        cfg_dir = tmp / "config"
        cfg_dir.mkdir(exist_ok=True)
        for src, dst in (
            (paths.NGINX_CONF,           "nginx.conf"),
            (paths.PHP_FPM_CONF,         "www.conf"),
            (helpers.get_php_ini_path(), "php.ini"),
            (paths.MY_CNF_FILE,          "my.cnf"),
        ):
            try:
                if src.exists():
                    shutil.copy2(src, cfg_dir / dst)
            except Exception as e:
                ui.warn(f"Config copy failed ({dst}): {e}")

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

    # import once at the top of restore so we can use it in except/finally
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
        if not dump.exists():
            ui.warn("No SQL dump in archive — DB restore skipped.")
        elif dump.stat().st_size < MIN_SQL_DUMP_SIZE:
            ui.warn(f"SQL dump too small ({dump.stat().st_size} bytes) — "
                    f"likely empty; DB restore skipped.")
            ui.info("Tip: this archive was created by an older version of "
                    "myserver. Databases were not captured. Create a fresh "
                    "backup with the current version.")
        elif not mariadb.start_mariadb_background():
            ui.warn("MariaDB did not start — DB restore skipped.")
        else:
            ui.info(f"Restoring databases from "
                    f"{dump.stat().st_size / 1024:.1f} KB dump...")
            cli = helpers.mysql_client()
            with open(dump, "rb") as f:
                r = subprocess.run(
                    [cli, "-u", "root", f"--socket={paths.MARIADB_SOCKET}"],
                    stdin=f, stderr=subprocess.PIPE)
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
        nginx.enforce_htdocs_permissions(paths.HTDOCS_DIR)

        # ---- phpMyAdmin reinstall (not stored in backup) ----
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
                    ui.warn("phpMyAdmin reinstall failed — reinstall later:")
                    ui.info("  myserver → 5 → 4   (or 'myserver quickstart')")
            except Exception as e:
                ui.warn(f"phpMyAdmin reinstall error: {e}")

        # ---- stop services (return to clean idle state) ----
        # MariaDB was started above for the SQL import; php-fpm/nginx may
        # have been auto-started by reinstall_phpmyadmin's PHP calls.
        # We deliberately return the system to "stopped" so the user
        # starts services explicitly with `myserver start`.
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
        # Try to leave services stopped even on failure
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
    """Interactive restore: show backups via fzf (arrow keys), then restore."""
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
        default=0)

    # --- Cancel ---
    if idx == len(options) - 1:
        ui.info("Cancelled.")
        return False

    # --- Manual path ---
    if idx == len(options) - 2:
        try:
            path = input(f"{ui.C_YELLOW}Archive path: {ui.C_RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            return False
        if not path:
            ui.info("Cancelled.")
            return False
        return restore(path)

    # --- Chosen backup ---
    selected = backups[idx]
    print()
    ui.info(f"Selected: {selected.name}")
    return restore(str(selected))