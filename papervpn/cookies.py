"""Cookie loading and session-cookie validation for the WebVPN gateway."""
from __future__ import annotations

import json
import re
from http.cookiejar import CookieJar, Cookie
from pathlib import Path

from .config import COOKIE_FILE, STORAGE_STATE


def parse_cookie_header(text: str) -> list[dict]:
    cookies = []
    for part in text.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        cookies.append({"name": name.strip(), "value": value.strip(), "domain": "", "path": "/"})
    return cookies


_CURL_PATTERNS = [
    re.compile(r"(?:-H|--header)\s+'cookie:\s*([^']+)'", re.IGNORECASE),
    re.compile(r'(?:-H|--header)\s+"cookie:\s*([^"]+)"', re.IGNORECASE),
    re.compile(r"(?:-b|--cookie)\s+'([^']+)'", re.IGNORECASE),
    re.compile(r'(?:-b|--cookie)\s+"([^"]+)"', re.IGNORECASE),
]


def parse_curl_cookie(text: str) -> list[dict]:
    for pat in _CURL_PATTERNS:
        m = pat.search(text)
        if m:
            return parse_cookie_header(m.group(1))
    return []


def _from_storage_state(path: Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "cookies" in data:
        return list(data["cookies"])
    if isinstance(data, list):
        return data
    raise ValueError(f"unsupported cookie json shape in {path}")


def _from_netscape(path: Path) -> list[dict]:
    out = []
    for line in Path(path).read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) < 7:
            continue
        domain, _flag, cpath, secure, _expiry, name, value = fields[:7]
        out.append({"name": name, "value": value, "domain": domain, "path": cpath or "/"})
    return out


def load_cookies(explicit: str | None = None) -> list[dict]:
    if explicit:
        if explicit.lstrip().startswith(("curl ", "curl\n")) or "-H '" in explicit or '-H "' in explicit:
            curl_cookies = parse_curl_cookie(explicit)
            if curl_cookies:
                return curl_cookies
        if "=" in explicit and ";" in explicit and not explicit.strip().startswith(("{", "[")):
            return parse_cookie_header(explicit)
        p = Path(explicit)
        if p.is_file():
            if p.suffix == ".txt":
                return _from_netscape(p)
            return _from_storage_state(p)
        return parse_cookie_header(explicit)

    if COOKIE_FILE.is_file():
        return _from_storage_state(COOKIE_FILE)
    if STORAGE_STATE.is_file():
        return _from_storage_state(STORAGE_STATE)
    for cand in (Path("cookies.txt"), Path("cookies.json")):
        if cand.is_file():
            if cand.suffix == ".txt":
                return _from_netscape(cand)
            return _from_storage_state(cand)
    return []


def install_cookies(session, cookies: list[dict]) -> None:
    jar: CookieJar = session.cookies
    for c in cookies:
        name = c.get("name")
        value = c.get("value")
        if not name:
            continue
        domain = c.get("domain") or ".hainanu.edu.cn"
        cookie = Cookie(
            version=0,
            name=name,
            value=value or "",
            port=None,
            port_specified=False,
            domain=domain,
            domain_specified=bool(c.get("domain")),
            domain_initial_dot=bool(c.get("domain", "").startswith(".")),
            path=c.get("path") or "/",
            path_specified=True,
            secure=bool(c.get("secure", True)),
            expires=None,
            discard=False,
            comment=None,
            comment_url=None,
            rest={},
            rfc2109=False,
        )
        jar.set_cookie(cookie)


_TICKET_RE = re.compile(r"wengine_vpn_ticket=([^;\s]+)")


def has_ticket(cookies: list[dict]) -> bool:
    return any(c.get("name") == "wengine_vpn_ticket" for c in cookies)


def ticket_from_text(text: str) -> str | None:
    m = _TICKET_RE.search(text)
    return m.group(1) if m else None
