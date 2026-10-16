"""Interactive TUI menu for myserver."""
from __future__ import annotations

from ..core import paths, helpers, ui
from ..features import backup, doctor, live_reload, quickstart, tunnel
from ..services import mariadb, ssl
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
    print(f"{ui.C_MAGENTA}============= [ SERVICES STATUS ] ============={ui.C_RESET}")
    for key, label in (("nginx",   "Nginx:      "),
                       ("php-fpm", "PHP-FPM:    "),
                       ("mariadb", "MariaDB:    "),
                       ("redis",   "Redis:      "),
                       ("tunnel",  "Tunnel:     "),
                       ("live",    "Live Reload:")):
        if s[key]:
            extra = f" (port {paths.LIVE_PORT})" if key == "live" else ""
            print(f" {label} {ui.C_GREEN}Running [OK]{ui.C_RESET}{extra}")
        else:
            print(f" {label} {ui.C_RED}Stopped [X]{ui.C_RESET}")
    print(f"{ui.C_MAGENTA}==============================================={ui.C_RESET}\n")

    if s["nginx"] or s["tunnel"]:
        print(f"{ui.C_CYAN}============= [ SERVER INFORMATION ] ============={ui.C_RESET}")
        print(f" Web Root Path : {ui.C_YELLOW}{paths.HTDOCS_DIR}{ui.C_RESET}")
        print(f" HTTP URL      : {ui.C_BLUE}http://localhost:8080{ui.C_RESET}")
        print(f" HTTPS URL     : {ui.C_GREEN}https://localhost:8443{ui.C_RESET}")
        print(f" phpMyAdmin    : {ui.C_MAGENTA}http://localhost:8080/phpmyadmin{ui.C_RESET}")
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


# ---------------------------------------------------------------------------
def menu(version: str) -> None:
    from .commands import cmd_reinstall, cmd_uninstall, cmd_update

    while True:
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
                print(f"{ui.C_YELLOW} 6) backup                (Snapshot->~/myserver-backups){ui.C_RESET}")
                print(f"{ui.C_YELLOW} 7) doctor                (Diagnose issues){ui.C_RESET}")
                print(f"{ui.C_YELLOW} 8) logs                  (View service logs){ui.C_RESET}")
                print(f"{ui.C_YELLOW} 9) ssl-info              (Certificate details){ui.C_RESET}")
                print(f"{ui.C_YELLOW}10) refresh status        (Re-check server status){ui.C_RESET}")
                print(f"{ui.C_YELLOW}11) update                (Check GitHub){ui.C_RESET}")
                print(f"{ui.C_YELLOW}12) reinstall             (Keep DBs + htdocs){ui.C_RESET}")
                print(f"{ui.C_YELLOW}13) exit                  (Exit & stop server){ui.C_RESET}\n")
                choice = _prompt("Enter choice [1-13]: ")
                if   choice in ("1",  "stop"):          services_ctl.stop_all()
                elif choice in ("2",  "live-toggle"):   live_reload.toggle()
                elif choice == "3":                     (tunnel.disable() if tun_on
                                                          else tunnel.enable())
                elif choice in ("4",  "restart"):       services_ctl.restart_all()
                elif choice in ("5",  "quickstart"):    quickstart.menu(
                    paths.HTDOCS_DIR, mariadb.read_password_from_my_cnf())
                elif choice in ("6",  "backup"):        backup.create()
                elif choice in ("7",  "doctor"):        doctor.run()
                elif choice in ("8",  "logs"):
                    which = _prompt("Log target [nginx/php/redis/live/tunnel]: ") or "nginx"
                    services_ctl.tail_service_logs(which)
                elif choice in ("9",  "ssl-info"):      ssl.print_info()
                elif choice in ("10", "refresh"):       continue
                elif choice in ("11", "update"):        cmd_update(auto=False)
                elif choice in ("12", "reinstall"):     cmd_reinstall()
                elif choice in ("13", "exit"):
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
                if   choice in ("1",  "start"):   services_ctl.start_all()
                elif choice in ("2",  "refresh"): continue
                elif choice in ("3",  "backup-list"): backup.list_cmd()
                elif choice in ("4",  "restore"):
                    backup.choose_and_restore()
                elif choice in ("5",  "doctor"):  doctor.run()
                elif choice in ("6",  "ssl-info"): ssl.print_info()
                elif choice in ("7",  "update"):  cmd_update(auto=False)
                elif choice in ("8",  "reinstall"): cmd_reinstall()
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