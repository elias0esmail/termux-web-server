from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from ..core import paths, helpers, ui


OPENSSL_CNF = """\
[req]
distinguished_name = req_distinguished_name
x509_extensions = v3_req
prompt = no
default_bits = 2048

[req_distinguished_name]
C = US
ST = Dev
L = Local
O = TermuxServer
CN = localhost

[v3_req]
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
subjectAltName = @alt_names

[alt_names]
DNS.1 = localhost
IP.1 = 127.0.0.1
IP.2 = ::1
"""


# ---------------------------------------------------------------------------
def _active_cert_pair() -> tuple[Path, Path]:
    """Return (cert, key) preferring a user-provided custom pair."""
    if paths.CUSTOM_CERT.exists() and paths.CUSTOM_KEY.exists():
        return paths.CUSTOM_CERT, paths.CUSTOM_KEY
    return paths.DEFAULT_CERT, paths.DEFAULT_KEY


def active_cert_pair() -> tuple[Path, Path]:
    return _active_cert_pair()


def is_self_signed() -> bool:
    cert, _ = _active_cert_pair()
    return cert == paths.DEFAULT_CERT


# ---------------------------------------------------------------------------
def setup() -> bool:
    try:
        paths.SSL_DIR.mkdir(parents=True, exist_ok=True)
        cert, key = _active_cert_pair()
        if cert.exists() and key.exists():
            try:
                os.chmod(key, 0o600)
            except Exception:
                pass
            if is_self_signed():
                ui.info("Using existing self-signed certificate.")
            else:
                ui.ok("Using custom certificate.")
            return True

        # generate self-signed
        cnf = paths.SSL_DIR / "openssl.cnf"
        cnf.write_text(OPENSSL_CNF)
        helpers.run_cmd(
            f"openssl req -x509 -nodes -days 365 -newkey rsa:2048 "
            f"-keyout '{paths.DEFAULT_KEY}' -out '{paths.DEFAULT_CERT}' "
            f"-config '{cnf}'")
        try:
            os.chmod(paths.DEFAULT_KEY, 0o600)
            os.chmod(paths.SSL_DIR, 0o700)
        except Exception:
            pass
        ui.ok("SSL certificates generated (self-signed, key chmod 600).")
        return True
    except Exception as e:
        ui.err(f"SSL generation error: {e}")
        return False


# ---------------------------------------------------------------------------
def _openssl_text(cert: Path, field: str) -> str:
    try:
        r = subprocess.run(
            ["openssl", "x509", "-in", str(cert), "-noout", "-" + field],
            capture_output=True, text=True, timeout=8)
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return ""


def cert_info() -> dict:
    cert, key = _active_cert_pair()
    info = {
        "cert": str(cert),
        "key": str(key),
        "exists": cert.exists() and key.exists(),
        "self_signed": is_self_signed(),
        "subject": "",
        "issuer": "",
        "not_after": "",
        "not_before": "",
        "sha256": "",
        "days_left": None,
        "expired": False,
    }
    if not cert.exists():
        return info
    info["subject"]  = _openssl_text(cert, "subject")
    info["issuer"]   = _openssl_text(cert, "issuer")
    info["not_after"] = _openssl_text(cert, "enddate").replace("notAfter=", "")
    info["not_before"] = _openssl_text(cert, "startdate").replace("notBefore=", "")
    info["sha256"]   = _openssl_text(cert, "fingerprint").split("=", 1)[-1].strip()
    try:
        r = subprocess.run(
            ["openssl", "x509", "-in", str(cert), "-noout", "-enddate"],
            capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and "notAfter=" in r.stdout:
            date_str = r.stdout.strip().split("=", 1)[1]
            dt = datetime.strptime(date_str, "%b %d %H:%M:%S %Y %Z").replace(
                tzinfo=timezone.utc)
            delta = dt - datetime.now(timezone.utc)
            info["days_left"] = delta.days
            info["expired"] = delta.total_seconds() < 0
    except Exception:
        pass
    return info


def print_info():
    info = cert_info()
    if not info["exists"]:
        ui.err("No SSL certificate found.")
        return
    ui.info(f"Certificate : {info['cert']}")
    ui.info(f"Key         : {info['key']}")
    ui.info(f"Type        : {'self-signed' if info['self_signed'] else 'custom'}")
    ui.info(f"Subject     : {info['subject']}")
    ui.info(f"Issuer      : {info['issuer']}")
    ui.info(f"Valid from  : {info['not_before']}")
    ui.info(f"Valid until : {info['not_after']}")
    if info["days_left"] is not None:
        if info["expired"]:
            ui.err(f"Certificate EXPIRED {-info['days_left']} day(s) ago")
        else:
            ui.warn(f"Days remaining: {info['days_left']}")
    ui.info(f"SHA-256     : {info['sha256']}")
    if info["self_signed"]:
        print()
        ui.warn("Browsers will warn about this certificate.")
        ui.info("To install it on this phone:")
        print(f"    termux-open-url file://{info['cert']}")


def import_custom(cert_path: str, key_path: str) -> bool:
    c = Path(cert_path).expanduser()
    k = Path(key_path).expanduser()
    if not c.exists() or not k.exists():
        ui.err("Certificate or key file not found.")
        return False
    # validate pair
    r = subprocess.run(
        ["sh", "-c",
         f"openssl x509 -noout -modulus -in '{c}' | openssl md5; "
         f"openssl rsa -noout -modulus -in '{k}' 2>/dev/null | openssl md5"],
        capture_output=True, text=True)
    if r.returncode == 0:
        lines = [l for l in r.stdout.splitlines() if "MD5" in l]
        if len(lines) == 2 and lines[0] != lines[1]:
            ui.err("Certificate and key do NOT match.")
            return False
    try:
        paths.SSL_DIR.mkdir(parents=True, exist_ok=True)
        paths.CUSTOM_CERT.write_text(c.read_text())
        paths.CUSTOM_KEY.write_text(k.read_text())
        try:
            os.chmod(paths.CUSTOM_KEY, 0o600)
        except Exception:
            pass
        ui.ok("Custom certificate imported. Restart Nginx to apply.")
        return True
    except Exception as e:
        ui.err(f"Import failed: {e}")
        return False


def remove_custom() -> bool:
    removed = False
    for p in (paths.CUSTOM_CERT, paths.CUSTOM_KEY):
        if p.exists():
            try:
                p.unlink()
                removed = True
            except Exception:
                pass
    if removed:
        ui.ok("Custom certificate removed — reverting to self-signed.")
    else:
        ui.info("No custom certificate present.")
    return removed