"""Minimal stdio MCP server exposing the WebVPN downloader as agent tools.

Speaks newline-delimited JSON-RPC 2.0 (the MCP stdio transport) with no third
party dependency, so any MCP-capable agent can call it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from .config import DEFAULT_OUTPUT
from .downloader import Downloader
from .session import (
    NotAuthenticated,
    build_session,
    check_session,
    describe_cookies,
    refresh_key_iv,
    require_session,
)

PROTOCOL_VERSION = "2024-11-05"

TOOLS = [
    {
        "name": "download_paper",
        "description": (
            "Download a single paywalled paper PDF through the Hainan University WebVPN. "
            "Accepts a WebVPN-proxied URL (https://webvpn.hainanu.edu.cn/https/...), a "
            "publisher URL, or a DOI. Downloads slowly and one at a time."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "WebVPN URL, publisher URL, or DOI"},
                "output_dir": {"type": "string", "description": "destination directory"},
                "filename": {"type": "string", "description": "optional output filename"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "download_papers",
        "description": "Download several papers sequentially with polite delays. Refuses large batches.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "urls": {"type": "array", "items": {"type": "string"}},
                "output_dir": {"type": "string"},
                "max": {"type": "integer", "description": "max downloads this run (default 10)"},
            },
            "required": ["urls"],
        },
    },
    {
        "name": "check_session",
        "description": "Report whether the current WebVPN session is authenticated.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _text(msg: str, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": msg}], "isError": is_error}


def _call_tool(name: str, args: dict) -> dict:
    if name == "check_session":
        session = build_session()
        ok = check_session(session)
        cookies = ", ".join(describe_cookies(session)) or "(none)"
        text = f"authenticated: {ok}\ncookies: {cookies}"
        if not ok:
            text += ("\nsession expired. Renew with: papervpn login --from-chrome "
                     "(imports the live ticket from the logged-in browser)")
        return _text(text, is_error=not ok)

    session = build_session()
    try:
        require_session(session, bool(describe_cookies(session)))
    except NotAuthenticated as exc:
        return _text(str(exc), is_error=True)
    refresh_key_iv(session)

    out_dir = Path(args.get("output_dir") or DEFAULT_OUTPUT)
    if name == "download_paper":
        dl = Downloader(session, out_dir=out_dir, max_per_run=1)
        r = dl.download(args["url"], args.get("filename"))
        return _text(f"{r.status}: {r.path or r.url}" + (f" [{r.detail}]" if r.detail else ""),
                     is_error=r.status == "failed")

    if name == "download_papers":
        urls = args.get("urls") or []
        max_per_run = int(args.get("max") or 10)
        if len(urls) > 50:
            return _text("refusing: more than 50 URLs in one call", is_error=True)
        dl = Downloader(session, out_dir=out_dir, max_per_run=max_per_run)
        lines = []
        for r in dl.download_many(urls):
            lines.append(f"{r.status}: {r.path or r.url}" + (f" [{r.detail}]" if r.detail else ""))
        return _text("\n".join(lines), is_error=not lines)

    return _text(f"unknown tool {name}", is_error=True)


def _handle(msg: dict) -> dict | None:
    method = msg.get("method")
    mid = msg.get("id")
    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": mid,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "papervpn", "version": "0.1.0"},
            },
        }
    if method in ("notifications/initialized", "initialized"):
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = msg.get("params") or {}
        result = _call_tool(params.get("name"), params.get("arguments") or {})
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    if mid is None:
        return None
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = _handle(msg)
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
