# MyServer --- Termux Web Server

**A local web development stack for Android powered by Termux.**
<br/><br/><br/>

<p align="center">
<img src="https://github.com/elias0esmail/termux-web-server/blob/main/Screenshot.jpg"/>
</p>
<p align="center">
<img src="https://github.com/elias0esmail/termux-web-server/blob/main/Screenshot1.jpg"/>
</p>
<br/><br/><br/>

MyServer helps you install and manage a practical PHP web-server
environment on Android. It brings together Nginx, PHP-FPM, MariaDB,
Redis, HTTPS support, phpMyAdmin, backups, diagnostics, and an optional
Cloudflare Tunnel in one command-line manager.

> **Intended use:** local development, testing, and personal projects.
> Review the security notes before exposing a server to a network or
> using it with sensitive or production data.

## Features

-   **Nginx** for serving websites and proxying PHP requests.
-   **PHP + PHP-FPM** for PHP applications.
-   **MariaDB** for relational databases.
-   **Redis** for cache and other application workloads.
-   **HTTPS/SSL** with a default self-signed certificate and support for
    importing a custom certificate and key.
-   **phpMyAdmin** for browser-based database administration.
-   **Cloudflare Tunnel** to make a local HTTP service reachable through
    a public URL when explicitly enabled.
-   **Live Reload** to refresh browser pages during development when
    watched files change.
-   **Backup and restore** for website files, databases, configuration,
    and SSL material.
-   **Diagnostics and logs** to help troubleshoot the environment.
-   **Service controls** for starting, stopping, restarting, and
    checking the stack.
-   **Quickstart** helper for setting up supported application
    frameworks.
-   **Optional boot integration** using Termux:Boot when available.

## Requirements

-   Android with [Termux](https://github.com/termux/termux-app)
    installed from a supported source.
-   A working Termux package repository and internet access for
    installation and updates.
-   Sufficient free storage for packages, website files, databases,
    logs, and backups.
-   Optional: Termux:Boot for starting services after device boot.
-   Optional: Cloudflare Tunnel (`cloudflared`) for public access; the
    installer attempts to install the required package.

MyServer targets Termux and Termux-like environments. Behavior can vary
with Android restrictions, Termux package versions, and device
power-management settings.

## Installation

### 1. Update Termux packages

``` bash
pkg update -y && pkg upgrade -y
```

### 2. Install prerequisites

``` bash
pkg install -y python git curl
```

### 3. Download the repository

``` bash
git clone https://github.com/elias0esmail/termux-web-server.git
cd termux-web-server
```

### 4. Run the installer

``` bash
python install.py
```

The installer installs the required packages and configures the stack.
During a fresh installation, it asks where to create the web root and
whether to set a MariaDB root password.

Choose a strong database password. Avoid leaving the database
administrator account without a password, especially if the device may
be reachable from other devices.

After installation, launch the manager:

``` bash
myserver
```

### One-command installation

The repository also documents this convenience command:

``` bash
curl -fsSL https://raw.githubusercontent.com/elias0esmail/termux-web-server/main/install.sh | bash
```

**Security note:** piping a remote script directly to a shell runs code
from the network immediately. For greater control, download and inspect
the script before executing it.

## Default local URLs

The installer reports the URLs after a successful setup. The current
configuration uses these default ports:

  ------------------------------------------------------------------------------------
  Service                 Default URL / port                   Notes
  ----------------------- ------------------------------------ -----------------------
  Website over HTTP       `http://localhost:8080`              Local web server

  Website over HTTPS      `https://localhost:8443`             Uses a self-signed
                                                               certificate by default

  phpMyAdmin              `http://localhost:8080/phpmyadmin`   Database administration
                                                               interface

  PHP-FPM                 `127.0.0.1:9000`                     Internal FastCGI
                                                               endpoint; do not expose
                                                               publicly

  Live Reload             `127.0.0.1:35730`                    Local development
                                                               helper
  ------------------------------------------------------------------------------------

The default web root is `~/htdocs`. The installer can instead use shared
phone storage, typically `~/storage/shared/htdocs`, after Termux storage
access is configured.

A self-signed certificate may trigger a browser warning. That is
expected unless the certificate is explicitly trusted by the client.

## Command reference

Run `myserver help` to display the command list supported by the
installed version.

### Service management

``` bash
myserver start
myserver stop
myserver restart
myserver status
```

### Live Reload

``` bash
myserver live-start
myserver live-status
myserver live-restart
myserver live-stop
```

The manager also supports `live-enable`, `live-disable`, and
`live-toggle`.

### Public access with Cloudflare Tunnel

``` bash
myserver internet-enable
myserver internet-disable
```

Enabling a tunnel can expose the local website to the public internet.
Before enabling it, check application authentication, debug settings,
uploaded files, secrets, database administration endpoints, and any
development-only routes. Do not assume a local-only application is safe
to publish.

### Backups and restore

``` bash
myserver backup
myserver backup-list
myserver restore /path/to/backup.tar.gz
```

Restore can overwrite the current web root, databases, SSL files, and
configuration. Read the prompts carefully and keep an independent copy
of important data before restoring.

### Diagnostics and logs

``` bash
myserver doctor
myserver logs nginx
myserver logs php
myserver logs redis
myserver logs live
myserver logs tunnel
```

### SSL certificate management

``` bash
myserver ssl-info
myserver ssl-import /path/to/certificate.pem /path/to/private-key.pem
myserver ssl-remove
```

Use a certificate and private key that belong together. Keep private
keys confidential and protect their filesystem permissions.

### Other maintenance commands

``` bash
myserver version
myserver update
myserver reinstall
myserver quickstart
myserver wake-lock
myserver wake-status
myserver wake-unlock
myserver uninstall
```

**Warning:** `myserver uninstall` is destructive. It can remove the web
root, databases, server configuration, and related files. Create and
verify backups before using it.

## Application setup

Place a PHP project inside the configured web root. For frameworks such
as Laravel, configure the web server's document root to the framework's
public directory and follow the framework's production deployment
guidance before exposing the application publicly.

Do not place `.env` files, private keys, database dumps, source-control
metadata, or other secrets in a publicly served directory. Confirm that
hidden files and sensitive paths are blocked as expected, and test the
final configuration.

The `myserver quickstart` command provides a framework setup helper.
Available options may vary by installed version.

## Backup recommendations

-   Create backups before upgrades, reinstallations, configuration
    changes, or restores.
-   Store at least one copy outside the phone, such as on a trusted
    computer or encrypted external storage.
-   Periodically test restoration on a separate test location or device.
-   Treat backup archives as sensitive: they may contain database
    contents, application secrets, configuration, and private SSL keys.
-   Do not assume that a backup is valid merely because the archive file
    exists.

## Security considerations

MyServer is a convenience manager for a mobile development environment,
not a substitute for a production server security review.

-   **Network exposure:** verify which interfaces each service listens
    on. Do not expose MariaDB, Redis, PHP-FPM, or Live Reload to
    untrusted networks.
-   **Database credentials:** set a strong password and use separate,
    least-privilege database accounts for applications.
-   **Public tunnels:** a Cloudflare Tunnel URL can make a local
    application publicly reachable. Disable debug mode and protect
    administrative routes before enabling it.
-   **HTTPS:** the default self-signed certificate is for local use and
    is not automatically trusted by browsers.
-   **Updates:** review changes and keep a known-good backup before
    updating. The updater downloads the repository's current main-branch
    archive, so the installed code can change as the branch changes.
-   **Backups and restore:** only restore archives you trust. Verify
    backups before relying on them for disaster recovery.
-   **Android background limits:** battery optimization and process
    management can stop background services. Test the behavior on your
    device and use Termux:Boot only if you understand its requirements.

## Troubleshooting

### The website does not open

1.  Run `myserver status`.
2.  Run `myserver doctor`.
3.  Inspect the logs with `myserver logs nginx` and `myserver logs php`.
4.  Confirm the service is listening on the expected port and that the
    device has not restricted Termux in the background.

### PHP pages fail

1.  Check `myserver logs php`.
2.  Confirm PHP-FPM is running.
3.  Check that the required PHP extensions for your application are
    installed and enabled.
4.  Review file permissions and the application's own logs.

### Database connection fails

1.  Check `myserver status` and `myserver doctor`.
2.  Confirm MariaDB is running.
3.  Verify the database name, username, password, and socket/host used
    by the application.
4.  Avoid using the database root account from the application.

### Phone storage is inaccessible

Run Termux's storage setup when needed:

``` bash
termux-setup-storage
```

Grant the requested Android permission, then check that the configured
web-root path exists.

### Cloudflare Tunnel does not start

1.  Confirm the local HTTP site works at `http://localhost:8080`.
2.  Check connectivity and DNS.
3.  Inspect `myserver logs tunnel`.
4.  Remember that the tunnel requires internet access and is separate
    from the local web server.

## Project layout

The main package is organized by responsibility:

``` text
myserver/
├── core/       # Shared helpers, paths, and UI utilities
├── services/   # Nginx, PHP, MariaDB, Redis, and SSL setup
├── features/   # Backups, diagnostics, tunnel, and Live Reload
├── cli/        # Command dispatch, menus, and service control
└── i18n/       # Localization resources
```

Other important files include:

-   `install.py` --- installs packages and configures the server stack.
-   `VERSION` --- current project version.
-   `CHANGELOG.md` --- release history.
-   `install.sh` --- convenience installer, if present in the selected
    repository revision.

The exact files and commands can change between revisions; use
`myserver help` and the repository's current source as the authority for
the installed version.

## Contributing

Issues and pull requests are welcome. When reporting a problem, include:

-   Android version and device architecture.
-   Termux source and version.
-   Python and PHP versions.
-   The command that failed and the complete relevant error output.
-   Relevant logs with passwords, tokens, private URLs, and other
    sensitive values removed.

For code changes, prefer focused commits and include reproducible tests
or manual test steps, especially for installation, upgrades, service
lifecycle, and backup/restore behavior.

## License

The repository's license file is the authoritative source for licensing
terms. Review it before redistributing or incorporating this project
into another product.

## Repository

-   GitHub: https://github.com/elias0esmail/termux-web-server
-   Issues: https://github.com/elias0esmail/termux-web-server/issues
