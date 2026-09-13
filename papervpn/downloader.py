"""Polite, one-at-a-time PDF downloader with de-duplication history."""
from __future__ import annotations

import hashlib
import json
import random
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

import requests

from .config import DEFAULT_OUTPUT, HISTORY_FILE, PROXY_REQUIRED_HOSTS
from . import browser, publishers, tokens, webvpn

SAFE = re.compile(r"[^\w.\-（）()]+")


@dataclass
class Result:
    url: str
    status: str
    path: str | None = None
    size: int | None = None
    detail: str | None = None


def _load_history() -> dict:
    if HISTORY_FILE.is_file():
        try:
            return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_history(history: dict) -> None:
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _key_for(url: str) -> str:
    identity = (
        _arn(url)
        or _pii(url)
        or hashlib.sha1(url.encode()).hexdigest()[:16]
    )
    return identity


def _arn(url: str) -> str | None:
    m = publishers.IEEE_ARNUMBER.search(url)
    return f"ieee-{m.group(1)}" if m else None


def _pii(url: str) -> str | None:
    m = publishers.SD_PII.search(url) or publishers.SD_CDN_PII.search(url)
    return f"sd-{m.group(1).upper()}" if m else None


def _sanitize(name: str) -> str:
    name = unquote(name).strip().replace("/", "_")
    name = SAFE.sub("_", name)
    return name[:180] or "paper"


def _filename_from(target, headers: dict) -> str:
    if target.filename_hint:
        return _sanitize(target.filename_hint)
    cd = headers.get("Content-Disposition", "")
    m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", cd, re.IGNORECASE)
    if m:
        return _sanitize(m.group(1))
    base = Path(urlsplit(target.url).path).name
    if base and base.lower().endswith(".pdf"):
        return _sanitize(base)
    return _sanitize(_key_for(target.url)) + ".pdf"


class Downloader:
    def __init__(
        self,
        session: requests.Session,
        out_dir: Path | str = DEFAULT_OUTPUT,
        min_delay: float = 3.0,
        max_delay: float = 8.0,
        max_per_run: int = 10,
        skip_existing: bool = True,
        use_browser: str = "auto",
        browser_headless: bool | None = None,
    ) -> None:
        self.session = session
        self.out_dir = Path(out_dir)
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_per_run = max_per_run
        self.skip_existing = skip_existing
        self.use_browser = use_browser
        self.browser_headless = browser_headless
        self.history = _load_history()
        self._done = 0

    def _throttle(self) -> None:
        if self._done:
            time.sleep(random.uniform(self.min_delay, self.max_delay))

    def _ensure_proxied(self, url: str) -> str:
        if webvpn.is_webvpn_url(url):
            return url
        if url.startswith("10.") or "doi.org" in url:
            url = self._resolve_doi(url)
        if "linkinghub.elsevier.com" in url:
            m = re.search(r"/pii/([A-Za-z0-9]+)", url)
            if m:
                url = f"https://www.sciencedirect.com/science/article/pii/{m.group(1)}"
        host = urlsplit(url).netloc.lower()
        token = tokens.token_for_host(host)
        if token:
            split = urlsplit(url)
            path = split.path + (f"?{split.query}" if split.query else "")
            return webvpn.build(token, path)
        if host in PROXY_REQUIRED_HOSTS:
            raise RuntimeError(
                f"{host} must be accessed through the WebVPN but no token is cached. "
                f"Open any {host} page through the WebVPN once, then run "
                f"`papervpn token add <that-webvpn-url>`."
            )
        return url

    def _resolve_doi(self, url: str) -> str:
        doi = url.split("doi.org/", 1)[1] if "doi.org/" in url else url
        try:
            resp = self.session.get(f"https://doi.org/{doi}", allow_redirects=True,
                                    timeout=45, stream=True)
            resolved = resp.url
            resp.close()
            return resolved
        except requests.RequestException:
            return url

    def _browser_fallback(self, url: str, out_name: str | None, key: str) -> Result | None:
        if self.use_browser == "never" or not browser.available():
            return None
        br = browser.download_via_browser(
            url, self.out_dir, filename=out_name, headless=self.browser_headless
        )
        if br.status == "ok" and br.path:
            self._done += 1
            self.history[key] = {"path": br.path, "size": br.size, "url": url}
            _save_history(self.history)
        return Result(url, br.status, path=br.path, size=br.size, detail=br.detail)

    def download(self, raw_url: str, out_name: str | None = None) -> Result:
        if self._done >= self.max_per_run:
            return Result(raw_url, "skipped", detail=f"max_per_run={self.max_per_run} reached")

        try:
            url = self._ensure_proxied(raw_url)
        except Exception as exc:
            return Result(raw_url, "failed", detail=str(exc))
        key = _key_for(url)
        entry = self.history.get(key)
        if self.skip_existing and entry and Path(entry.get("path", "")).is_file():
            src = Path(entry["path"])
            if src.parent.resolve() != self.out_dir.resolve():
                self.out_dir.mkdir(parents=True, exist_ok=True)
                dest = self.out_dir / src.name
                if not dest.exists():
                    shutil.copy2(src, dest)
                self.history[key] = {"path": str(dest), "size": dest.stat().st_size, "url": url}
                _save_history(self.history)
                return Result(url, "exists", path=str(dest), size=dest.stat().st_size)
            return Result(url, "exists", path=entry["path"], size=entry.get("size"))

        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._throttle()
        is_elsevier = publishers.detect_publisher(url) == "elsevier"

        try:
            target = publishers.resolve(url, self.session)
        except Exception as exc:
            if is_elsevier:
                fb = self._browser_fallback(url, out_name, key)
                if fb is not None:
                    return fb
            return Result(url, "failed", detail=f"resolve: {exc}")

        if target.warmup_url:
            try:
                self.session.get(
                    target.warmup_url,
                    headers={"Referer": target.warmup_url},
                    timeout=60,
                )
            except requests.RequestException:
                pass

        headers = {"Referer": target.referer or target.warmup_url or url}
        headers.update(target.headers)

        try:
            resp = self.session.get(target.url, headers=headers, timeout=180, stream=True)
        except requests.RequestException as exc:
            if is_elsevier:
                fb = self._browser_fallback(url, out_name, key)
                if fb is not None:
                    return fb
            return Result(url, "failed", detail=f"request: {exc}")

        if resp.status_code >= 400:
            if is_elsevier:
                fb = self._browser_fallback(url, out_name, key)
                if fb is not None:
                    return fb
            return Result(url, "failed", detail=f"HTTP {resp.status_code}")

        content = resp.content
        if not publishers.looks_like_pdf(content, resp.headers.get("Content-Type", "")):
            if is_elsevier:
                fb = self._browser_fallback(url, out_name, key)
                if fb is not None:
                    return fb
            if b"/login" in content[:2000] or b"wengine" in content[:2000]:
                return Result(url, "failed", detail="session expired / login page returned")
            return Result(url, "failed", detail="response is not a PDF")

        name = _sanitize(out_name) if out_name else _filename_from(target, resp.headers)
        if not name.lower().endswith(".pdf"):
            name += ".pdf"
        dest = self.out_dir / name
        if dest.exists() and self.skip_existing:
            self.history[key] = {"path": str(dest), "size": dest.stat().st_size}
            _save_history(self.history)
            return Result(url, "exists", path=str(dest), size=dest.stat().st_size)

        dest.write_bytes(content)
        self._done += 1
        self.history[key] = {"path": str(dest), "size": len(content), "url": target.url}
        _save_history(self.history)
        return Result(url, "ok", path=str(dest), size=len(content))

    def download_many(self, urls: list[str]) -> list[Result]:
        results = []
        for u in urls:
            results.append(self.download(u))
            if self._done >= self.max_per_run:
                break
        return results
