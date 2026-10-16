#!/data/data/com.termux/files/usr/bin/bash
# Bootstrap installer for myserver (Termux web server stack).
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/elias0esmail/termux-web-server/main/install.sh | bash
set -e

PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
REPO="elias0esmail/termux-web-server"
BRANCH="main"
TARBALL="https://github.com/${REPO}/archive/refs/heads/${BRANCH}.tar.gz"
TMP="${PREFIX}/tmp/myserver-install-$$"

echo -e "\033[1;36m[*] myserver bootstrap\033[0m"

# Minimal prerequisites
for pkg in curl tar python; do
    if ! command -v "$pkg" >/dev/null 2>&1; then
        echo -e "\033[1;33m[*] Installing $pkg...\033[0m"
        pkg install -y "$pkg" >/dev/null 2>&1 || true
    fi
done

if ! command -v python >/dev/null 2>&1 && ! command -v python3 >/dev/null 2>&1; then
    echo -e "\033[1;31m[!] Python is required but could not be installed.\033[0m"
    exit 1
fi
PY=$(command -v python3 || command -v python)

mkdir -p "$TMP"
echo -e "\033[1;34m[*] Downloading tarball...\033[0m"
if ! curl -fsSL "$TARBALL" -o "$TMP/src.tar.gz"; then
    echo -e "\033[1;31m[!] Download failed.\033[0m"
    rm -rf "$TMP"; exit 1
fi

echo -e "\033[1;34m[*] Extracting...\033[0m"
tar -xf "$TMP/src.tar.gz" -C "$TMP"
SRC="$TMP/termux-web-server-${BRANCH}"
[ -d "$SRC" ] || { echo -e "\033[1;31m[!] Bad archive.\033[0m"; rm -rf "$TMP"; exit 1; }

echo -e "\033[1;32m[✓] Launching installer...\033[0m"
cd "$SRC"
"$PY" install.py "$@"
RC=$?

# install.py cleans itself up normally; leave temp for debugging on failure.
if [ $RC -ne 0 ]; then
    echo -e "\033[1;31m[!] Installer exited with code $RC. Temp kept at: $TMP\033[0m"
    exit $RC
fi
rm -rf "$TMP" 2>/dev/null || true