"""Static configuration and on-disk paths for the papervpn tool."""
from __future__ import annotations

import os
from pathlib import Path

WEBVPN_HOST = os.environ.get("PAPERVPN_HOST", "webvpn.hainanu.edu.cn")
WEBVPN_BASE = f"https://{WEBVPN_HOST}"

WEBVPN_AES_KEY = os.environ.get("PAPERVPN_AES_KEY") or None
WEBVPN_AES_IV = os.environ.get("PAPERVPN_AES_IV") or None

HOME = Path(os.environ.get("PAPERVPN_HOME", Path.home()))
STATE_DIR = Path(os.environ.get("PAPERVPN_STATE", HOME / ".papervpn"))
try:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass

TOKEN_CACHE = STATE_DIR / "tokens.json"
COOKIE_FILE = STATE_DIR / "cookies.json"
STORAGE_STATE = STATE_DIR / "storage_state.json"
BROWSER_PROFILE = STATE_DIR / "browser_profile"
HISTORY_FILE = STATE_DIR / "downloads.json"
DEFAULT_OUTPUT = Path(os.environ.get("PAPERVPN_OUTPUT", Path.cwd() / "papers"))

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

SEED_TOKENS = {
    "ieeexplore.ieee.org": "32393332413339303239333421416369b6cd061f5bb167165629106d881cd9a038c615",
    "pdf.sciencedirectassets.com": (
        "32393332413339303239333421416369afcc055450a2621c4a2f5b60840bd9ed0a332cea44c0c5b9d96d0b"
    ),
    "authserver.hainanu.edu.cn": (
        "32393332413339303239333421416369bedd171250a4790f413e106c8c10d2eff7e80656ae294cd71e"
    ),
}

SCHEME_PREFIXES = ("https-", "http-", "https", "http")

PROXY_REQUIRED_HOSTS = {
    "ieeexplore.ieee.org",
    "www.sciencedirect.com",
    "sciencedirect.com",
    "pdf.sciencedirectassets.com",
    "link.springer.com",
    "onlinelibrary.wiley.com",
    "pubs.acs.org",
    "pubs.rsc.org",
    "www.tandfonline.com",
    "journals.sagepub.com",
    "www.jstor.org",
    "www.cnki.net",
    "kns.cnki.net",
    "dl.acm.org",
    "www.nature.com",
    "www.science.org",
    "academic.oup.com",
    "www.cambridge.org",
}
