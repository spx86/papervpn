"""Resolve a proxied article/viewer URL into a concrete PDF URL per publisher."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from urllib.parse import urlencode, urlsplit

from . import webvpn

IEEE_ARNUMBER = re.compile(r"(?:arnumber[=/]|/document/)(\d+)")
SD_PII = re.compile(r"/pii/([A-Z0-9]{6,})", re.IGNORECASE)
SD_CDN_PII = re.compile(r"1-s2\.0-([A-Z0-9]+?)(?:-main\.pdf|/main\.pdf)", re.IGNORECASE)
SD_PDFURL = re.compile(r'pdfurl\s*=\s*"([^"]+)"', re.IGNORECASE)
SD_CITATION = re.compile(
    r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
SD_PDFFT = re.compile(r'["\'](https?:[^"\']*?/pdfft[^"\']*)["\']', re.IGNORECASE)

PDF_MAGIC = b"%PDF"


@dataclass
class PdfTarget:
    url: str
    publisher: str
    referer: str | None = None
    filename_hint: str | None = None
    warmup_url: str | None = None
    headers: dict = field(default_factory=dict)


def detect_publisher(url: str) -> str:
    path = urlsplit(url).path.lower()
    host = (webvpn.host_of(url) or "").lower()
    if "ieeexplore" in host or "/stamp/" in path or "/stampPDF/" in path or "/document/" in path:
        return "ieee"
    if "sciencedirect" in host or "elsevier" in host or "/science/article" in path or "/main.pdf" in path:
        return "elsevier"
    return "generic"


def resolve(url: str, session=None) -> PdfTarget:
    publisher = detect_publisher(url)
    if publisher == "ieee":
        return _resolve_ieee(url)
    if publisher == "elsevier":
        return _resolve_elsevier(url, session)
    return PdfTarget(url=url, publisher="generic")


def _resolve_ieee(url: str) -> PdfTarget:
    ref = webvpn.parse(url) if webvpn.is_webvpn_url(url) else None
    m = IEEE_ARNUMBER.search(url)
    if not m:
        raise RuntimeError(f"could not find an IEEE arnumber in {url}")
    arnumber = m.group(1)
    if ref is not None:
        stamp = webvpn.build(ref.token, f"/stamp/stamp.jsp?tp=&arnumber={arnumber}")
        pdf = webvpn.build(ref.token, f"/stampPDF/getPDF.jsp?tp=&arnumber={arnumber}&ref=")
    else:
        stamp = f"https://ieeexplore.ieee.org/stamp/stamp.jsp?tp=&arnumber={arnumber}"
        pdf = f"https://ieeexplore.ieee.org/stampPDF/getPDF.jsp?tp=&arnumber={arnumber}&ref="
    return PdfTarget(
        url=pdf,
        publisher="ieee",
        referer=stamp,
        warmup_url=stamp,
        filename_hint=f"{arnumber}.pdf",
        headers={"Accept": "application/pdf,text/html;q=0.9,*/*;q=0.8"},
    )


def _json_object_at(text: str, key: str):
    m = re.search(r'"%s"\s*:\s*\{' % re.escape(key), text)
    if not m:
        return None
    start = text.index("{", m.start())
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start : i + 1])
                except Exception:
                    return None
    return None


def _sd_pdfdownload_path(html: str) -> str | None:
    info = _json_object_at(html, "pdfDownload")
    if not info:
        return None
    um = info.get("urlMetadata") or {}
    path = (um.get("path") or "science/article/pii").strip("/")
    pii = um.get("pii")
    ext = um.get("pdfExtension") or "/pdfft"
    full = "/" + path + (f"/{pii}" if pii else "") + ext
    qp = um.get("queryParams") or {}
    if qp:
        full += "?" + urlencode(qp)
    return full


def _resolve_elsevier(url: str, session=None) -> PdfTarget:
    path = urlsplit(url).path.lower()
    if path.endswith(".pdf") or "/main.pdf" in path:
        pii = SD_PII.search(url) or SD_CDN_PII.search(url)
        return PdfTarget(
            url=url,
            publisher="elsevier",
            filename_hint=f"{pii.group(1).upper()}.pdf" if pii else None,
        )
    if session is None:
        raise RuntimeError("resolving a ScienceDirect article page requires a session")
    resp = session.get(url, headers={"Accept": "text/html"}, timeout=90)
    resp.raise_for_status()
    html = resp.text
    pii = SD_PII.search(url)
    name = f"{pii.group(1).upper()}.pdf" if pii else None

    rel = _sd_pdfdownload_path(html)
    if rel:
        if webvpn.is_webvpn_url(url):
            pdf_url = webvpn.build(webvpn.parse(url).token, rel)
        else:
            pdf_url = "https://www.sciencedirect.com" + rel
        return PdfTarget(url=pdf_url, publisher="elsevier", referer=url, filename_hint=name)

    for pattern in (SD_CITATION, SD_PDFURL, SD_PDFFT):
        m = pattern.search(html)
        if not m:
            continue
        pdf_url = m.group(1)
        if pdf_url.startswith("/") and webvpn.is_webvpn_url(url):
            pdf_url = webvpn.build(webvpn.parse(url).token, pdf_url)
        return PdfTarget(url=pdf_url, publisher="elsevier", referer=url, filename_hint=name)
    raise RuntimeError("no PDF link found on the ScienceDirect page")


def looks_like_pdf(content: bytes, content_type: str = "") -> bool:
    if content[:5] == PDF_MAGIC or content[:1024].lstrip().startswith(PDF_MAGIC):
        return True
    return "application/pdf" in (content_type or "").lower()
