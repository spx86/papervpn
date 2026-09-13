"""Import a live WebVPN session straight from a local browser profile.

Chrome/Chromium on Linux store cookies encrypted with AES-128-CBC. The key is
PBKDF2(SHA1, salt="saltysalt", 1 iteration, 16 bytes) over the "<Vendor> Safe
Storage" password kept in the login keyring (read here via the optional
`secretstorage` package). Several vendor secrets can coexist, so every
candidate key is tried and the one that yields a plausible ticket wins.
Firefox stores cookies in plaintext SQLite and is read directly.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import sqlite3
import tempfile
from pathlib import Path

CHROMIUM_DIRS = [
    "~/.config/google-chrome",
    "~/.config/chromium",
    "~/.config/BraveSoftware/Brave-Browser",
    "~/.config/microsoft-edge",
    "~/.config/vivaldi",
    "~/snap/chromium/common/chromium",
    "~/.var/app/com.google.Chrome/config/google-chrome",
    "~/.var/app/org.chromium.Chromium/config/chromium",
]

FIREFOX_GLOBS = [
    "~/.mozilla/firefox/*/cookies.sqlite",
    "~/snap/firefox/common/.mozilla/firefox/*/cookies.sqlite",
    "~/.var/app/org.mozilla.firefox/.mozilla/firefox/*/cookies.sqlite",
]

DEFAULT_HOSTS = ("hainanu.edu.cn",)
DEFAULT_NAMES = ("wengine_vpn_ticket", "route")
TICKET_RE = re.compile(r"[0-9a-fA-F]{8,64}")


def _staging_copy(db: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="papervpn-cookies-")) / db.name
    shutil.copy2(db, tmp)
    for suffix in ("-wal", "-shm", "-journal"):
        side = Path(str(db) + suffix)
        if side.is_file():
            shutil.copy2(side, Path(str(tmp) + suffix))
    return tmp


def _candidate_passwords() -> list[str]:
    out: list[str] = []
    try:
        import secretstorage

        conn = secretstorage.dbus_init()
        collection = secretstorage.get_default_collection(conn)
        if collection.is_locked():
            collection.unlock()
        for item in collection.get_all_items():
            label = item.get_label()
            attrs = item.get_attributes() or {}
            if "Safe Storage" in label or attrs.get("application") in ("chrome", "chromium"):
                try:
                    secret = item.get_secret().decode("utf-8", "replace")
                except Exception:
                    continue
                if secret and secret not in out:
                    out.append(secret)
    except Exception:
        pass
    out.append("peanuts")  # last-resort fallback when no keyring is available
    return out


def _derive_key(password: str):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    return PBKDF2HMAC(
        algorithm=hashes.SHA1(), length=16, salt=b"saltysalt", iterations=1
    ).derive(password.encode())


def _decrypt(value: bytes, key) -> str | None:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    if value[:3] not in (b"v10", b"v11"):
        return None
    decryptor = Cipher(algorithms.AES(key), modes.CBC(b" " * 16)).decryptor()
    plain = decryptor.update(value[3:]) + decryptor.finalize()
    plain = plain[32:]  # Chrome prepends a 32-byte SHA256 tag
    if plain and 1 <= plain[-1] <= 16:
        plain = plain[:-plain[-1]]
    return plain.decode("utf-8", "replace")


def _valid(name: str, value: str) -> bool:
    return bool(TICKET_RE.fullmatch(value or ""))


def _from_chromium(hosts, names, keys) -> dict:
    found: dict[str, dict] = {}
    for base in CHROMIUM_DIRS:
        root = Path(os.path.expanduser(base))
        if not root.is_dir():
            continue
        for db in list(root.glob("*/Cookies")) + list(root.glob("Cookies")):
            try:
                tmp = _staging_copy(db)
                con = sqlite3.connect(tmp)
                placeholders = ",".join("?" * len(names))
                rows = con.execute(
                    f"select host_key,name,encrypted_value,path,is_secure from cookies "
                    f"where name in ({placeholders})",
                    names,
                ).fetchall()
                con.close()
                for host, name, value, path, secure in rows:
                    if name in found or not any(h in host for h in hosts):
                        continue
                    for key in keys:
                        try:
                            val = _decrypt(bytes(value), key)
                        except Exception:
                            continue
                        if val and _valid(name, val):
                            found[name] = {
                                "name": name,
                                "value": val,
                                "domain": host,
                                "path": path or "/",
                                "secure": bool(secure),
                            }
                            break
            except Exception:
                continue
            finally:
                try:
                    shutil.rmtree(tmp.parent)
                except Exception:
                    pass
    return found


def _from_firefox(hosts, names) -> dict:
    found: dict[str, dict] = {}
    for pattern in FIREFOX_GLOBS:
        for db in [Path(p) for p in glob.glob(os.path.expanduser(pattern))]:
            try:
                tmp = _staging_copy(db)
                con = sqlite3.connect(tmp)
                placeholders = ",".join("?" * len(names))
                rows = con.execute(
                    f"select host,name,value,path,isSecure from moz_cookies "
                    f"where name in ({placeholders})",
                    names,
                ).fetchall()
                con.close()
                for host, name, value, path, secure in rows:
                    if name in found or not any(h in host for h in hosts):
                        continue
                    if value and _valid(name, value):
                        found[name] = {
                            "name": name,
                            "value": value,
                            "domain": host,
                            "path": path or "/",
                            "secure": bool(secure),
                        }
            except Exception:
                continue
            finally:
                try:
                    shutil.rmtree(tmp.parent)
                except Exception:
                    pass
    return found


def read_session_cookies(hosts=DEFAULT_HOSTS, names=DEFAULT_NAMES) -> list[dict]:
    keys = [_derive_key(pw) for pw in _candidate_passwords()]
    found = _from_chromium(hosts, names, keys)
    if "wengine_vpn_ticket" not in found:
        found.update(_from_firefox(hosts, names))
    order = [n for n in names if n in found]
    return [found[n] for n in order]
