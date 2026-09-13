"""Build and validate an authenticated requests session against the WebVPN."""
from __future__ import annotations

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import requests

from .config import USER_AGENT, WEBVPN_BASE
from .cookies import has_ticket, install_cookies, load_cookies
from . import tokens


class NotAuthenticated(RuntimeError):
    pass


def build_session(cookie_source: str | None = None) -> requests.Session:
    cookies = load_cookies(cookie_source)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
    )
    retry = Retry(total=2, backoff_factor=1.0, status_forcelist=(500, 502, 503, 504))
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    install_cookies(session, cookies)
    return session


def check_session(session: requests.Session) -> bool:
    try:
        resp = session.get(
            f"{WEBVPN_BASE}/portal",
            allow_redirects=False,
            timeout=30,
            verify=True,
        )
    except requests.RequestException:
        return False
    if resp.status_code in (301, 302, 303, 307, 308):
        location = resp.headers.get("Location", "")
        return "/login" not in location
    return resp.status_code == 200 and "/login" not in resp.url


def require_session(session: requests.Session, cookies_present: bool) -> None:
    if not check_session(session):
        hint = (
            "WebVPN session is missing or expired."
            if cookies_present
            else "No WebVPN cookies were found."
        )
        raise NotAuthenticated(
            f"{hint} Renew it with `papervpn login --from-chrome` (pulls the live "
            "ticket from your logged-in Chrome/Firefox), or `papervpn login "
            "--cookie '<copy-as-cURL>'`, or by logging into "
            f"{WEBVPN_BASE} in a browser."
        )


def describe_cookies(session: requests.Session) -> list[str]:
    return [c.name for c in session.cookies]


def refresh_key_iv(session: requests.Session) -> tuple[str, str] | None:
    """Pull wrdvpnKey/wrdvpnIV from the authenticated portal and cache them."""
    try:
        resp = session.get(f"{WEBVPN_BASE}/user/info", timeout=30)
        data = resp.json()
    except Exception:
        return None
    key = data.get("wrdvpnKey")
    iv = data.get("wrdvpnIV")
    if key and iv and key != "wrd":
        tokens.remember_key_iv(key, iv)
        return key, iv
    return None
