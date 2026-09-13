"""Parse and build WebVPN-proxied URLs."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from .config import WEBVPN_BASE, WEBVPN_HOST
from . import tokens


@dataclass
class ProxiedUrl:
    token: str
    scheme: str
    path: str
    query: str

    @property
    def host(self) -> str | None:
        return tokens.host_for_token(self.token)

    @property
    def suffix(self) -> str:
        return f"{self.path}" + (f"?{self.query}" if self.query else "")

    def proxied(self) -> str:
        return f"{WEBVPN_BASE}/{self.scheme}/{self.token}{self.suffix}"


_WEBVPN_RE = re.compile(
    r"^https?://(?P<host>[^/]+)/(?P<scheme>https?)(?:-(?P<port>\d+))?/(?P<token>[0-9a-fA-F]+)(?P<rest>/.*)?$"
)


def is_webvpn_url(url: str) -> bool:
    return WEBVPN_HOST in url and "/https/" in url


def parse(url: str) -> ProxiedUrl:
    parts = urlsplit(url)
    m = _WEBVPN_RE.match(f"{parts.scheme}://{parts.netloc}{parts.path}")
    if not m:
        raise ValueError(f"not a recognised WebVPN URL: {url}")
    token = m.group("token")
    rest = m.group("rest") or "/"
    rest_path, _, rest_query = rest.partition("?")
    if parts.query:
        rest_query = parts.query
    return ProxiedUrl(token=token, scheme=m.group("scheme"), path=rest_path, query=rest_query)


def build(token: str, path: str, scheme: str = "https") -> str:
    if not path.startswith("/"):
        path = "/" + path
    return f"{WEBVPN_BASE}/{scheme}/{token}{path}"


def build_for_host(host: str, path: str, scheme: str = "https") -> str:
    token = tokens.token_for_host(host)
    if not token:
        raise RuntimeError(
            f"no WebVPN token cached for host {host!r}. "
            f"Open any page on that host through the WebVPN once and run "
            f"`papervpn token add <webvpn-url>`, or provide --key/--iv."
        )
    return build(token, path, scheme)


def host_of(url: str) -> str | None:
    if is_webvpn_url(url):
        return parse(url).host
    return urlsplit(url).netloc or None
