"""Browser-based fetch fallback for publishers behind JS/anti-bot challenges.

ScienceDirect serves a `cra_js_challenge` interstitial for the article and
`pdfft` endpoints, which `requests` cannot clear. Playwright drives system
Chrome to solve it; the PDF then arrives as an `application/pdf` response
(rendered by Chrome's internal PDF viewer), whose body we capture.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import publishers, webvpn
from .cookies import load_cookies

BLOCK_MARKERS = ("problem providing the content", "cpe00001", "cra_js_challenge")


@dataclass
class BrowserResult:
    status: str
    path: str | None = None
    size: int | None = None
    detail: str | None = None


def available() -> bool:
    try:
        import playwright  # noqa: F401

        return True
    except ImportError:
        return False


def _seed_cookies(cookie_source: str | None) -> list[dict]:
    out = []
    for c in load_cookies(cookie_source):
        if not c.get("name"):
            continue
        out.append(
            {
                "name": c["name"],
                "value": c.get("value", ""),
                "domain": c.get("domain") or "webvpn.hainanu.edu.cn",
                "path": c.get("path") or "/",
            }
        )
    return out


def _default_headless() -> bool:
    return not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _blocked(body: str) -> bool:
    low = body.lower()
    return any(m in low for m in BLOCK_MARKERS)


def _save(out_dir: Path, name: str, body: bytes) -> BrowserResult:
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    dest = out_dir / _sanitize(name)
    dest.write_bytes(body)
    return BrowserResult("ok", path=str(dest), size=len(body))


def _filename(url: str, rel: str | None) -> str:
    m = publishers.SD_PII.search(url)
    if m:
        return f"{m.group(1).upper()}.pdf"
    if rel:
        m = publishers.SD_CDN_PII.search(rel)
        if m:
            return f"{m.group(1).upper()}.pdf"
    base = Path(url.split("?")[0]).name
    return base if base.lower().endswith(".pdf") else "paper.pdf"


def download_via_browser(
    url: str,
    out_dir: Path | str,
    filename: str | None = None,
    headless: bool | None = None,
    cookie_source: str | None = None,
    timeout_ms: int = 90000,
) -> BrowserResult:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return BrowserResult("failed", detail="playwright not installed")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    headless = _default_headless() if headless is None else headless
    seed = _seed_cookies(cookie_source)
    is_sd = publishers.detect_publisher(url) == "elsevier"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome",
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            ctx = browser.new_context(
                accept_downloads=True,
                user_agent=None,
            )
            ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
            )
            ctx.add_cookies(seed)
            page = ctx.new_page()

            captured: list = []

            def _on_response(resp):
                try:
                    ct = (resp.headers.get("content-type") or "").lower()
                    if resp.status == 200 and ct.startswith("application/pdf"):
                        captured.append(resp)
                except Exception:
                    pass

            page.on("response", _on_response)

            if is_sd:
                try:
                    page.goto(webvpn.build_for_host("www.sciencedirect.com", "/"),
                              wait_until="domcontentloaded", timeout=timeout_ms)
                    page.wait_for_timeout(2000)
                except Exception:
                    pass

            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

            rel = None
            for _ in range(12):
                page.wait_for_timeout(2500)
                if _blocked(page.inner_text("body")):
                    return BrowserResult(
                        "failed",
                        detail="ScienceDirect anti-bot block (CPE00001); retry in a "
                        "few minutes.",
                    )
                if is_sd and publishers._sd_pdfdownload_path(page.content()):
                    rel = publishers._sd_pdfdownload_path(page.content())
                    break
                if not is_sd:
                    break

            pdf_url = webvpn.build(webvpn.parse(url).token, rel) if (is_sd and rel) else url

            try:
                page.goto(pdf_url, referer=url, wait_until="domcontentloaded", timeout=timeout_ms)
            except Exception:
                pass

            name = filename or _filename(url, rel)
            for _ in range(40):
                page.wait_for_timeout(1000)
                for resp in list(captured):
                    try:
                        body = resp.body()
                    except Exception:
                        continue
                    if body[:5] == b"%PDF-":
                        return _save(out_dir, name, body)
                if _blocked(page.inner_text("body")):
                    return BrowserResult("failed", detail="ScienceDirect anti-bot block (CPE00001)")

            resp = ctx.request.get(pdf_url, headers={"Referer": url})
            body = resp.body()
            if body[:5] == b"%PDF-":
                return _save(out_dir, name, body)
            return BrowserResult("failed", detail="no PDF response captured")
        finally:
            browser.close()


def _sanitize(name: str) -> str:
    base = Path(name).name or "paper.pdf"
    if not base.lower().endswith(".pdf"):
        base += ".pdf"
    return re.sub(r"[^\w.\-（）()]+", "_", base)[:180]
