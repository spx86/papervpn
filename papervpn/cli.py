"""Command line interface for papervpn."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import tokens, webvpn
from .config import BROWSER_PROFILE, COOKIE_FILE, DEFAULT_OUTPUT, STORAGE_STATE, WEBVPN_BASE
from .downloader import Downloader
from .session import (
    NotAuthenticated,
    build_session,
    check_session,
    describe_cookies,
    refresh_key_iv,
    require_session,
)


def cmd_login(args: argparse.Namespace) -> int:
    if getattr(args, "from_chrome", False):
        from .chrome_cookies import read_session_cookies

        cookies = read_session_cookies()
        if not cookies:
            print(
                "Could not find a WebVPN ticket in any Chrome/Chromium or Firefox profile.\n"
                "Make sure you are logged into https://webvpn.hainanu.edu.cn in that browser, "
                "then retry; or pass --cookie instead.",
                file=sys.stderr,
            )
            return 2
        COOKIE_FILE.write_text(json.dumps({"cookies": cookies}, indent=2), encoding="utf-8")
        print(f"Imported {len(cookies)} cookies from the browser -> {COOKIE_FILE}")
        session = build_session()
        ok = check_session(session)
        print("authenticated:", ok)
        if ok:
            kv = refresh_key_iv(session)
            if kv:
                print(f"discovered wrdvpnKey/IV -> {kv}")
        return 0 if ok else 1
    if args.cookie:
        from .cookies import load_cookies

        cookies = load_cookies(args.cookie)
        if not cookies:
            print("could not parse any cookies from the provided value", file=sys.stderr)
            return 2
        COOKIE_FILE.write_text(json.dumps({"cookies": cookies}, indent=2), encoding="utf-8")
        print(f"Saved {len(cookies)} cookies -> {COOKIE_FILE}")
        session = build_session()
        ok = check_session(session)
        print("authenticated:", ok)
        if ok:
            kv = refresh_key_iv(session)
            if kv:
                print(f"discovered wrdvpnKey/IV -> {kv}")
        return 0
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(
            "Playwright is not installed. Either pass a cookie directly:\n"
            "  papervpn login --cookie 'wengine_vpn_ticket=...'\n"
            "or install Playwright:\n"
            "  pip install 'papervpn[login]' && playwright install chromium",
            file=sys.stderr,
        )
        return 2
    BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE),
            channel=args.channel,
            headless=args.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.new_page()
        page.goto(f"{WEBVPN_BASE}/", wait_until="domcontentloaded")
        if not args.headless:
            print("Log in through the opened browser window. Press Enter here when done.")
            input()
        else:
            page.wait_for_timeout(args.wait * 1000)
        ctx.storage_state(path=str(STORAGE_STATE))
        cookies = ctx.cookies()
        COOKIE_FILE.write_text(json.dumps({"cookies": cookies}, indent=2), encoding="utf-8")
        ctx.close()
    print(f"Saved {len(cookies)} cookies -> {COOKIE_FILE}")
    session = build_session()
    print("Session valid:", check_session(session))
    return 0


def cmd_key_discover(args: argparse.Namespace) -> int:
    session = build_session(args.cookie)
    try:
        require_session(session, bool(describe_cookies(session)))
    except NotAuthenticated as exc:
        print(str(exc), file=sys.stderr)
        return 3
    kv = refresh_key_iv(session)
    if kv:
        print(f"wrdvpnKey = {kv[0]}\nwrdvpnIV  = {kv[1]}")
        print("cached; arbitrary hosts can now be encoded offline.")
        return 0
    print("could not read wrdvpnKey from /user/info", file=sys.stderr)
    return 1


def cmd_token(args: argparse.Namespace) -> int:
    if args.action == "list":
        for host, token in sorted(tokens.all_tokens().items()):
            print(f"{host:45s} {token}")
        return 0
    if args.action == "add":
        ref = webvpn.parse(args.url)
        host = args.host or ref.host
        if not host:
            print("Could not determine host; pass --host.", file=sys.stderr)
            return 2
        tokens.remember(host, ref.token)
        print(f"cached {host} -> {ref.token}")
        return 0
    return 2


def cmd_check(args: argparse.Namespace) -> int:
    session = build_session(args.cookie)
    ok = check_session(session)
    print("authenticated:", ok)
    print("cookies:", ", ".join(describe_cookies(session)) or "(none)")
    if not ok:
        print(
            "session expired. Renew with:  papervpn login --from-chrome\n"
            "(or paste a fresh cookie:      papervpn login --cookie '<copy-as-cURL>')",
            file=sys.stderr,
        )
        return 1
    kv = refresh_key_iv(session)
    if kv:
        print(f"wrdvpnKey: {kv[0]}  (arbitrary hosts can be encoded)")
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    session = build_session(args.cookie)
    try:
        require_session(session, bool(describe_cookies(session)))
    except NotAuthenticated as exc:
        print(str(exc), file=sys.stderr)
        return 3
    refresh_key_iv(session)
    urls = list(args.urls)
    if args.batch:
        batch_path = Path(args.batch)
        urls += [ln.strip() for ln in batch_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not urls:
        print("no URLs given", file=sys.stderr)
        return 2
    if len(urls) > args.hard_cap and not args.force:
        print(
            f"refusing to download {len(urls)} items in one run "
            f"(hard cap {args.hard_cap}). Split the batch or pass --force.",
            file=sys.stderr,
        )
        return 2
    dl = Downloader(
        session,
        out_dir=Path(args.output or DEFAULT_OUTPUT),
        min_delay=args.min_delay,
        max_delay=args.max_delay,
        max_per_run=args.max,
        use_browser="never" if args.no_browser else "auto",
        browser_headless=False if args.browser_headed else None,
    )
    results = dl.download_many(urls)
    ok = sum(1 for r in results if r.status in ("ok", "exists"))
    for r in results:
        tail = f" ({r.size} bytes)" if r.size else ""
        extra = f" [{r.detail}]" if r.detail else ""
        print(f"{r.status:8s} {r.path or r.url}{tail}{extra}")
    print(f"downloaded {ok}/{len(results)}")
    return 0 if ok or not results else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="papervpn", description="Download paywalled papers through the Hainan University WebVPN.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("login", help="log into WebVPN and save cookies")
    pl.add_argument("--cookie", help="paste a Cookie header, a 'Copy as cURL' command, or a file path")
    pl.add_argument("--from-chrome", action="store_true",
                    help="import the live ticket from your logged-in Chrome/Firefox profile")
    pl.add_argument("--headless", action="store_true")
    pl.add_argument("--wait", type=int, default=180, help="seconds to wait in headless mode")
    pl.add_argument("--channel", default="chrome", help="playwright browser channel (chrome/chromium)")
    pl.set_defaults(func=cmd_login)

    pk = sub.add_parser("key-discover", help="read wrdvpnKey/IV from the portal and cache them")
    pk.add_argument("--cookie", help="cookie header or path to cookies file")
    pk.set_defaults(func=cmd_key_discover)

    pt = sub.add_parser("token", help="manage the per-host token cache")
    pt.add_argument("action", choices=["list", "add"])
    pt.add_argument("url", nargs="?", help="a WebVPN URL for the host (for `add`)")
    pt.add_argument("--host", help="hostname the token corresponds to")
    pt.set_defaults(func=cmd_token)

    pc = sub.add_parser("check", help="check whether the current session is authenticated")
    pc.add_argument("--cookie", help="cookie header or path to cookies file")
    pc.set_defaults(func=cmd_check)

    pd = sub.add_parser("download", help="download one or more PDFs")
    pd.add_argument("urls", nargs="*", help="WebVPN or publisher URLs / DOIs")
    pd.add_argument("-b", "--batch", help="file with one URL per line")
    pd.add_argument("-o", "--output", help=f"output directory (default {DEFAULT_OUTPUT})")
    pd.add_argument("--cookie", help="cookie header or path to cookies file")
    pd.add_argument("--max", type=int, default=10, help="max downloads per run (default 10)")
    pd.add_argument("--hard-cap", type=int, default=50, help="refuse batches larger than this")
    pd.add_argument("--min-delay", type=float, default=3.0)
    pd.add_argument("--max-delay", type=float, default=8.0)
    pd.add_argument("--force", action="store_true", help="bypass the hard cap")
    pd.add_argument("--no-browser", action="store_true", help="never fall back to a real browser")
    pd.add_argument("--browser-headed", action="store_true", help="force a visible browser window")
    pd.set_defaults(func=cmd_download)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
