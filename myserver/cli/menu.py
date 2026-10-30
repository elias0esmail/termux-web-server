"""Interactive TUI menu for myserver."""
from __future__ import annotations

from ..core import paths, helpers, ui
from ..features import backup, db_cli, doctor, live_reload, quickstart, tunnel, vhost
from ..services import mariadb, redis, ssl
from . import services_ctl


BANNER = r"""
   __  __       _____                              
  |  \/  |     / ____|                             
  | \  / |_   | (___   ___ _ ____   _____ _ __     
  | |\/| | | | |\___ \ / _ \ '__\ \ / / _ \ '__|    
  | |  | | |_| |____) |  __/ |   \ V /  __/ |       
  |_|  |_|\__, |_____/ \___|_|    \_/ \___|_|       
            __/ |                                   
           |___/                                    
"""


# ---------------------------------------------------------------------------
def _render_banner(version: str):
    print(f"{ui.C_CYAN}{BANNER}{ui.C_RESET}")
    print(f"{ui.C_YELLOW}      Server Manager  v{version}{ui.C_RESET}")
    print(f"{ui.C_YELLOW}============= [ DEVELOPER INFO ] =============={ui.C_RESET}")
    print(f" Developer : {ui.C_GREEN}Elias Esmail{ui.C_RESET}")
    print(f" WhatsApp  : {ui.C_GREEN}+967771902342{ui.C_RESET}")
    print(f" GitHub    : {ui.C_CYAN}https://github.com/elias0esmail{ui.C_RESET}")
    print(f"{ui.C_YELLOW}================================================{ui.C_RESET}\n")


def _render_status():
    s = services_ctl.status()
    proc_count, rss_mb = helpers.count_user_processes()
    proc_color = ui.C_GREEN if proc_count < 24 else (ui.C_YELLOW if proc_count < 30 else ui.C_RED)

    print(f"{ui.C_MAGENTA}============= [ SERVICES STATUS ] ============={ui.C_RESET}")
    for key, label, pfile in (
        ("nginx",   "Nginx:      ", paths.PID_NGINX),
        ("php-fpm", "PHP-FPM:    ", paths.PID_PHP),
        ("mariadb", "MariaDB:    ", paths.PID_MARIADB),
        ("redis",   "Redis:      ", paths.PID_REDIS),
        ("tunnel",  "Tunnel:     ", paths.PID_TUNNEL),
        ("live",    "Live Reload:", paths.PID_LIVE),
    ):
        if s[key]:
            pid = helpers.read_pid_file(pfile)
            mem = helpers.process_rss_mb(pid)
            extra = f" (port {paths.LIVE_PORT})" if key == "live" else ""
            if mem > 0:
                extra += f" [{mem:.0f} MB]"
            print(f" {label} {ui.C_GREEN}Running [OK]{ui.C_RESET}{extra}")
        else:
            note = " (disabled)" if (key == "redis" and not redis.is_enabled()) else ""
            print(f" {label} {ui.C_RED}Stopped [X]{ui.C_RESET}{note}")
    print(f" Processes:   {proc_color}{proc_count}/{paths.ANDROID_PHANTOM_LIMIT} Android limit{ui.C_RESET} (~{rss_mb:.1f} MB total)")
    print(f"{ui.C_MAGENTA}==============================================={ui.C_RESET}\n")

    if s["nginx"] or s["tunnel"]:
        lan_ip = helpers.get_lan_ip()
        sites = vhost.list_sites()
        print(f"{ui.C_CYAN}============= [ SERVER INFORMATION ] ============={ui.C_RESET}")
        print(f" Web Root Path : {ui.C_YELLOW}{paths.HTDOCS_DIR}{ui.C_RESET}")
        print(f" HTTP URL      : {ui.C_BLUE}http://localhost:8080{ui.C_RESET}")
        if lan_ip:
            print(f" LAN Wi-Fi URL : {ui.C_BLUE}http://{lan_ip}:8080{ui.C_RESET}")
        print(f" HTTPS URL     : {ui.C_GREEN}https://localhost:8443{ui.C_RESET}")
        print(f" phpMyAdmin    : {ui.C_MAGENTA}http://localhost:8080/phpmyadmin{ui.C_RESET} (Local Only)")
        if sites:
            for vs in sites:
                print(f" VHost [{vs['name']}] : {ui.C_CYAN}http://localhost:{vs['port']}{ui.C_RESET} ({vs['type']})")
        url = tunnel.get_url()
        if s["tunnel"] and url:
            print(f" Global URL    : {ui.C_GREEN}{url}{ui.C_RESET}")
        else:
            print(f" Global URL    : {ui.C_RED}Inactive{ui.C_RESET}")
        if ssl.is_self_signed():
            print(f" {ui.C_YELLOW}Note: HTTPS uses a self-signed certificate "
                  f"(browser warning is normal){ui.C_RESET}")
        print(f"{ui.C_CYAN}=================================================={ui.C_RESET}\n")


# ---------------------------------------------------------------------------
def _prompt(msg: str) -> str:
    try:
        return input(f"{ui.C_YELLOW}{msg}{ui.C_RESET}").strip()
    except (EOFError, KeyboardInterrupt):
        raise KeyboardInterrupt


def _interactive_sites_menu():
    while True:
        print()
        vhost.list_cmd()
        print()
        print(" 1) Add virtual host")
        print(" 2) Remove virtual host")
        print(" 3) Back")
        choice = _prompt("Select [1-3]: ")
        if choice == "1":
            name = _prompt("Site name (e.g. blog): ")
            if not name:
                continue
            stype = _prompt("Type [php/laravel/wordpress/nextcloud] (default php): ") or "php"
            p_str = _prompt("Port [leave empty for auto 8081+]: ")
            port = int(p_str) if p_str.isdigit() else None
            vhost.add_site(name, port=port, site_type=stype)
        elif choice == "2":
            name = _prompt("Site name to remove: ")
            if name:
                vhost.remove_site(name)
        elif choice == "3":
            return


def _interactive_db_menu():
    while True:
        print()
        db_cli.list_dbs()
        print()
        print(" 1) Create database")
        print(" 2) Drop database")
        print(" 3) Import SQL file")
        print(" 4) Export database to SQL")
        print(" 5) Back")
        choice = _prompt("Select [1-5]: ")
        if choice == "1":
            name = _prompt("Database name: ")
            if name:
                db_cli.create_db(name)
        elif choice == "2":
            name = _prompt("Database name to DROP: ")
            if name:
                db_cli.drop_db(name)
        elif choice == "3":
            name = _prompt("Target database name: ")
            sql_file = _prompt("Path to .sql file: ")
            if name and sql_file:
                db_cli.import_sql(name, sql_file)
        elif choice == "4":
            name = _prompt("Database name to export: ")
            out_file = _prompt("Output file path [default <db>.sql]: ") or None
            if name:
                db_cli.export_sql(name, out_file)
        elif choice == "5":
            return


# ---------------------------------------------------------------------------
def menu(version: str) -> None:
    from .commands import cmd_reinstall, cmd_uninstall, cmd_update

    while True:
        paths.resolve_runtime_paths()
        helpers.clear_screen()
        _render_banner(version)
        _render_status()

        running = services_ctl.any_running()
        live_on = live_reload.is_running()
        tun_on = tunnel.is_running()

        try:
            if running:
                live_label = ("Disable Live Reload   (auto-refresh off)"
                              if live_on else
                              "Enable Live Reload    (auto-refresh on)")
                tun_label = ("Disable Internet      (public URL off)"
                             if tun_on else
                             "Enable Internet       (public URL on)")
                print(f"{ui.C_YELLOW}Select an option:{ui.C_RESET}")
                print(f"{ui.C_YELLOW} 1) stop                  (Stop all services){ui.C_RESET}")
                print(f"{ui.C_YELLOW} 2) {live_label}{ui.C_RESET}")
                print(f"{ui.C_YELLOW} 3) {tun_label}{ui.C_RESET}")
                print(f"{ui.C_YELLOW} 4) restart               (Restart all services){ui.C_RESET}")
                print(f"{ui.C_YELLOW} 5) quickstart            (Install WP/Laravel/Nextcloud){ui.C_RESET}")
                print(f"{ui.C_YELLOW} 6) sites                 (Virtual Hosts manager){ui.C_RESET}")
                print(f"{ui.C_YELLOW} 7) db                    (Database CLI manager){ui.C_RESET}")
                print(f"{ui.C_YELLOW} 8) backup                (Snapshot -> {paths.BACKUP_DIR.name}){ui.C_RESET}")
                print(f"{ui.C_YELLOW} 9) doctor                (Diagnose issues){ui.C_RESET}")
                print(f"{ui.C_YELLOW}10) logs                  (View service logs){ui.C_RESET}")
                print(f"{ui.C_YELLOW}11) ssl-info              (Certificate details){ui.C_RESET}")
                print(f"{ui.C_YELLOW}12) refresh status        (Re-check server status){ui.C_RESET}")
                print(f"{ui.C_YELLOW}13) update                (Check GitHub){ui.C_RESET}")
                print(f"{ui.C_YELLOW}14) reinstall             (Keep DBs + htdocs){ui.C_RESET}")
                print(f"{ui.C_YELLOW}15) exit                  (Exit & stop server){ui.C_RESET}\n")
                choice = _prompt("Enter choice [1-15]: ")
                if   choice in ("1",  "stop"):          services_ctl.stop_all()
                elif choice in ("2",  "live-toggle"):   live_reload.toggle()
                elif choice == "3":                     (tunnel.disable() if tun_on
                                                          else tunnel.enable())
                elif choice in ("4",  "restart"):       services_ctl.restart_all()
                elif choice in ("5",  "quickstart"):    quickstart.menu(
                    paths.HTDOCS_DIR, mariadb.read_password_from_my_cnf())
                elif choice in ("6",  "sites", "site"): _interactive_sites_menu()
                elif choice in ("7",  "db"):            _interactive_db_menu()
                elif choice in ("8",  "backup"):        backup.create()
                elif choice in ("9",  "doctor"):        doctor.run()
                elif choice in ("10", "logs"):
                    which = _prompt("Log target [nginx/php/redis/live/tunnel]: ") or "nginx"
                    services_ctl.tail_service_logs(which)
                elif choice in ("11", "ssl-info"):      ssl.print_info()
                elif choice in ("12", "refresh"):       continue
                elif choice in ("13", "update"):        cmd_update(auto=False)
                elif choice in ("14", "reinstall"):     cmd_reinstall()
                elif choice in ("15", "exit"):
                    services_ctl.stop_all(quiet=True)
                    ui.ok("Server stopped. Bye!")
                    return
                else:
                    ui.err("Invalid choice.")
            else:
                print(f"{ui.C_YELLOW}Select an option:{ui.C_RESET}")
                print(f"{ui.C_YELLOW} 1) start           (Start all services){ui.C_RESET}")
                print(f"{ui.C_YELLOW} 2) refresh status  (Re-check server status){ui.C_RESET}")
                print(f"{ui.C_YELLOW} 3) backup-list     (List backups){ui.C_RESET}")
                print(f"{ui.C_YELLOW} 4) restore         (Restore from backup){ui.C_RESET}")
                print(f"{ui.C_YELLOW} 5) doctor          (Diagnose){ui.C_RESET}")
                print(f"{ui.C_YELLOW} 6) ssl-info        (Certificate details){ui.C_RESET}")
                print(f"{ui.C_YELLOW} 7) update          (Check updates){ui.C_RESET}")
                print(f"{ui.C_YELLOW} 8) reinstall       (Keep DBs + htdocs){ui.C_RESET}")
                print(f"{ui.C_YELLOW} 9) uninstall       (Remove EVERYTHING){ui.C_RESET}")
                print(f"{ui.C_YELLOW}10) exit{ui.C_RESET}\n")
                choice = _prompt("Enter choice [1-10]: ")
                if   choice in ("1",  "start"):       services_ctl.start_all()
                elif choice in ("2",  "refresh"):     continue
                elif choice in ("3",  "backup-list"): backup.list_cmd()
                elif choice in ("4",  "restore"):     backup.choose_and_restore()
                elif choice in ("5",  "doctor"):      doctor.run()
                elif choice in ("6",  "ssl-info"):    ssl.print_info()
                elif choice in ("7",  "update"):      cmd_update(auto=False)
                elif choice in ("8",  "reinstall"):   cmd_reinstall()
                elif choice in ("9",  "uninstall"):
                    if cmd_uninstall():
                        return
                elif choice in ("10", "exit"):
                    ui.ok("Bye!")
                    return
                else:
                    ui.err("Invalid choice.")
        except KeyboardInterrupt:
            print()
            return

        print()
        try:
            input(f"{ui.C_YELLOW}Press Enter to continue...{ui.C_RESET}")
        except (EOFError, KeyboardInterrupt):
            return