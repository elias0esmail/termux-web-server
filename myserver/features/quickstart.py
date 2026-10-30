"""Framework installers: phpMyAdmin, WordPress, Laravel, Nextcloud.

Security & Architecture Improvements:
  * Strictly validates project/database names via `helpers.is_safe_identifier()`
    to block command and SQL injection.
  * Executes all SQL statements via `helpers.run_mysql_query()` over `stdin`
    with `shell=False`.
  * Automatically registers a dedicated Virtual Host for Laravel projects so
    routing works out of the box without exposing `.env` or `vendor/`.
"""
from __future__ import annotations

import re
import secrets
import subprocess
from pathlib import Path

from ..core import paths, helpers, ui
from . import vhost


# ===========================================================================
# phpMyAdmin
# ===========================================================================
PMA_STORAGE_BLOCK = """\
$cfg['Servers'][$i]['pmadb'] = 'phpmyadmin';
$cfg['Servers'][$i]['bookmarktable'] = 'pma__bookmark';
$cfg['Servers'][$i]['relation'] = 'pma__relation';
$cfg['Servers'][$i]['table_info'] = 'pma__table_info';
$cfg['Servers'][$i]['table_coords'] = 'pma__table_coords';
$cfg['Servers'][$i]['pdf_pages'] = 'pma__pdf_pages';
$cfg['Servers'][$i]['column_info'] = 'pma__column_info';
$cfg['Servers'][$i]['history'] = 'pma__history';
$cfg['Servers'][$i]['table_uiprefs'] = 'pma__table_uiprefs';
$cfg['Servers'][$i]['tracking'] = 'pma__tracking';
$cfg['Servers'][$i]['userconfig'] = 'pma__userconfig';
$cfg['Servers'][$i]['recent'] = 'pma__recent';
$cfg['Servers'][$i]['favorite'] = 'pma__favorite';
$cfg['Servers'][$i]['users'] = 'pma__users';
$cfg['Servers'][$i]['usergroups'] = 'pma__usergroups';
$cfg['Servers'][$i]['navigationhiding'] = 'pma__navigationhiding';
$cfg['Servers'][$i]['savedsearches'] = 'pma__savedsearches';
$cfg['Servers'][$i]['central_columns'] = 'pma__central_columns';
$cfg['Servers'][$i]['designer_settings'] = 'pma__designer_settings';
$cfg['Servers'][$i]['export_templates'] = 'pma__export_templates';
"""


def _setup_pma_storage(pma_dir: Path) -> bool:
    sql_file = pma_dir / "sql" / "create_tables.sql"
    if not sql_file.exists() or not paths.MARIADB_SOCKET.exists():
        return False
    helpers.run_mysql_query(
        "CREATE DATABASE IF NOT EXISTS phpmyadmin "
        "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
    )
    try:
        sql_text = sql_file.read_text(errors="ignore")
        helpers.run_mysql_query(sql_text, database="phpmyadmin", batch=False, force=True, timeout=30)
    except Exception:
        return False
    r = helpers.run_mysql_query("SHOW TABLES FROM phpmyadmin LIKE 'pma\\_%';")
    return len([ln for ln in (r.stdout or "").splitlines() if ln.strip()]) >= 15


def _patch_pma_config(cfg: Path):
    if not cfg.exists():
        return
    try:
        content = cfg.read_text()
        if "['pmadb']" in content:
            return
        cfg.write_text(content + "\n" + PMA_STORAGE_BLOCK)
    except Exception:
        pass


def install_phpmyadmin(htdocs: Path, db_password: str) -> bool:
    pma_dir = htdocs / "phpmyadmin"
    is_update = pma_dir.exists()
    try:
        ui.step(("Updating" if is_update else "Downloading") + " phpMyAdmin...")
        paths.TMP_DIR.mkdir(parents=True, exist_ok=True)
        tar_file = paths.TMP_DIR / "pma.tar.gz"
        url = "https://www.phpmyadmin.net/downloads/phpMyAdmin-latest-all-languages.tar.gz"

        r = subprocess.run(
            ["curl", "-fsSL", url, "-o", str(tar_file)],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0 or not tar_file.exists() or tar_file.stat().st_size == 0:
            ui.err("Failed to download phpMyAdmin.")
            return False

        cfg = pma_dir / "config.inc.php"
        saved = cfg.read_text() if (is_update and cfg.exists()) else None

        pma_dir.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(
            ["tar", "-xf", str(tar_file), "-C", str(pma_dir), "--strip-components=1"],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            ui.err(f"tar failed: {r.stderr[:200]}")
            return False
        tar_file.unlink(missing_ok=True)

        sample = pma_dir / "config.sample.inc.php"
        if saved:
            cfg.write_text(saved)
        elif sample.exists():
            secret = secrets.token_hex(16)
            content = sample.read_text()
            content = re.sub(
                r"\$cfg\['blowfish_secret'\]\s*=\s*'';|\$cfg\['blowfish_secret'\]\s*=\s*\".*\";",
                f"$cfg['blowfish_secret'] = '{secret}';",
                content,
            )
            allow = "true" if not db_password else "false"
            content = re.sub(
                r"\$cfg\['Servers'\]\[\$i\]\['AllowNoPassword'\]\s*=\s*(true|false);",
                f"$cfg['Servers'][$i]['AllowNoPassword'] = {allow};",
                content,
            )
            if "AllowNoPassword" not in content:
                content += f"\n$cfg['Servers'][$i]['AllowNoPassword'] = {allow};\n"
            content = re.sub(
                r"\$cfg\['Servers'\]\[\$i\]\['host'\]\s*=\s*'localhost';",
                "$cfg['Servers'][$i]['host'] = '127.0.0.1';",
                content,
            )
            pma_tmp = pma_dir / "tmp"
            pma_tmp.mkdir(exist_ok=True)
            content += f"\n$cfg['TempDir'] = '{pma_tmp}';\n"
            content += "\n" + PMA_STORAGE_BLOCK
            cfg.write_text(content)

        (pma_dir / "tmp").mkdir(exist_ok=True)
        _patch_pma_config(cfg)
        _setup_pma_storage(pma_dir)
        ui.ok(("phpMyAdmin updated." if is_update else "phpMyAdmin installed."))
        return True
    except Exception as e:
        ui.err(f"phpMyAdmin error: {e}")
        return False


# ===========================================================================
# WordPress
# ===========================================================================
def install_wordpress(htdocs: Path) -> bool:
    target = htdocs / "wordpress"
    if target.exists():
        ui.err(f"{target} already exists.")
        return False
    ui.step("Downloading WordPress...")
    paths.TMP_DIR.mkdir(parents=True, exist_ok=True)
    tar_file = paths.TMP_DIR / "wordpress.tar.gz"
    r = subprocess.run(
        ["curl", "-fsSL", "https://wordpress.org/latest.tar.gz", "-o", str(tar_file)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0 or not tar_file.exists():
        ui.err("Download failed.")
        return False
    r = subprocess.run(
        ["tar", "-xf", str(tar_file), "-C", str(htdocs)],
        capture_output=True,
        text=True,
    )
    tar_file.unlink(missing_ok=True)
    if r.returncode != 0:
        ui.err(f"Extraction failed: {r.stderr[:200]}")
        return False

    if paths.MARIADB_SOCKET.exists():
        helpers.run_mysql_query(
            "CREATE DATABASE IF NOT EXISTS `wordpress` "
            "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
        )
    ui.ok("WordPress installed → http://localhost:8080/wordpress")
    return True


# ===========================================================================
# Laravel
# ===========================================================================
def install_laravel(htdocs: Path, name: str = "laravel") -> bool:
    name = name.strip()
    if not helpers.is_safe_identifier(name):
        ui.err("Invalid project name. Use only letters, numbers, '-' or '_'.")
        return False

    target = htdocs / name
    if target.exists():
        ui.err(f"{target} already exists.")
        return False
    if not helpers.command_exists("composer"):
        ui.warn("Installing composer...")
        helpers.run_cmd(["pkg", "install", "-y", "composer"])
    if not helpers.command_exists("composer"):
        ui.err("composer not available.")
        return False

    ui.step(f"Running composer create-project laravel/laravel {name}...")
    r = subprocess.run(
        ["composer", "create-project", "--prefer-dist",
         "--no-interaction", "--no-progress",
         "laravel/laravel", str(target)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        ui.err(f"composer failed: {r.stderr[:300]}")
        return False

    db = name.replace("-", "_")
    if paths.MARIADB_SOCKET.exists() and helpers.is_safe_identifier(db):
        helpers.run_mysql_query(
            f"CREATE DATABASE IF NOT EXISTS `{db}` "
            "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
        )

    ui.ok(f"Laravel installed → http://localhost:8080/{name}/public")
    vhost.add_site(name, project_path=target, site_type="laravel")
    return True


# ===========================================================================
# Nextcloud
# ===========================================================================
def install_nextcloud(htdocs: Path) -> bool:
    target = htdocs / "nextcloud"
    if target.exists():
        ui.err(f"{target} already exists.")
        return False
    if not helpers.command_exists("unzip"):
        helpers.run_cmd(["pkg", "install", "-y", "unzip"])
    ui.step("Downloading Nextcloud...")
    paths.TMP_DIR.mkdir(parents=True, exist_ok=True)
    zip_file = paths.TMP_DIR / "nextcloud.zip"
    r = subprocess.run(
        ["curl", "-fsSL",
         "https://download.nextcloud.com/server/releases/latest.zip",
         "-o", str(zip_file)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0 or not zip_file.exists():
        ui.err("Download failed.")
        return False
    r = subprocess.run(
        ["unzip", "-q", str(zip_file), "-d", str(htdocs)],
        capture_output=True,
        text=True,
    )
    zip_file.unlink(missing_ok=True)
    if r.returncode != 0:
        ui.err(f"Unzip failed: {r.stderr[:200]}")
        return False

    db_user = "ncuser"
    db_pass = secrets.token_urlsafe(16)
    if paths.MARIADB_SOCKET.exists():
        escaped_pw = helpers.sql_escape(db_pass)
        sql = (
            "CREATE DATABASE IF NOT EXISTS `nextcloud` "
            "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;\n"
            f"CREATE USER IF NOT EXISTS '{db_user}'@'127.0.0.1' IDENTIFIED BY '{escaped_pw}';\n"
            f"CREATE USER IF NOT EXISTS '{db_user}'@'localhost' IDENTIFIED BY '{escaped_pw}';\n"
            f"GRANT ALL PRIVILEGES ON `nextcloud`.* TO '{db_user}'@'127.0.0.1';\n"
            f"GRANT ALL PRIVILEGES ON `nextcloud`.* TO '{db_user}'@'localhost';\n"
            "FLUSH PRIVILEGES;\n"
        )
        helpers.run_mysql_query(sql, batch=False)
        ui.ok("Nextcloud installed.")
        ui.info(f"DB user: {db_user}")
        ui.info(f"DB pass: {db_pass}   (save this!)")
    else:
        ui.warn("MariaDB not running — no DB created.")
    vhost.add_site("nextcloud", project_path=target, site_type="nextcloud")
    return True


# ===========================================================================
# interactive menu
# ===========================================================================
def menu(htdocs: Path, db_password: str = "") -> None:
    from ..services import nginx as ngx
    while True:
        print()
        print(f"{ui.C_MAGENTA}============================================{ui.C_RESET}")
        print(f"{ui.C_MAGENTA}      QUICKSTART FRAMEWORK INSTALLER        {ui.C_RESET}")
        print(f"{ui.C_MAGENTA}============================================{ui.C_RESET}")
        print(" 1) Install WordPress")
        print(" 2) Install Laravel (with dedicated VHost)")
        print(" 3) Install Nextcloud (with dedicated VHost)")
        print(" 4) Reinstall phpMyAdmin")
        print(" 5) Back")
        try:
            choice = input(f"{ui.C_YELLOW}Select [1-5]: {ui.C_RESET}").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if choice == "1":
            install_wordpress(htdocs)
            ngx.enforce_htdocs_permissions(htdocs / "wordpress", deep=True)
        elif choice == "2":
            try:
                name = input(f"{ui.C_YELLOW}Project name [laravel]: {ui.C_RESET}").strip() or "laravel"
            except (EOFError, KeyboardInterrupt):
                return
            if install_laravel(htdocs, name):
                ngx.enforce_htdocs_permissions(htdocs / name, deep=True)
        elif choice == "3":
            if install_nextcloud(htdocs):
                ngx.enforce_htdocs_permissions(htdocs / "nextcloud", deep=True)
        elif choice == "4":
            install_phpmyadmin(htdocs, db_password)
        elif choice == "5":
            return