"""Deterministic per-host WebVPN token cache and (optional) AES-CFB codec.

The Hainan WebVPN is a 网瑞达 / Wengine gateway. A proxied URL looks like:

    https://webvpn.hainanu.edu.cn/https/<TOKEN>/<original-path>

where <TOKEN> = IV(16 bytes) + AES-CFB(hostname) and is deterministic per host.
Because the deployment key is not public, tokens are cached on first sight and
reused; when a key+IV is available the codec can also synthesize new tokens.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .config import SEED_TOKENS, TOKEN_CACHE, WEBVPN_AES_IV, WEBVPN_AES_KEY


def _load_cache() -> dict:
    cache = {"tokens": {}, "hosts": {}}
    if TOKEN_CACHE.is_file():
        try:
            data = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
            cache["tokens"] = data.get("tokens", {})
            cache["hosts"] = data.get("hosts", {})
        except Exception:
            pass
    for host, token in SEED_TOKENS.items():
        cache["tokens"].setdefault(host, token)
        cache["hosts"].setdefault(token, host)
    return cache


_CACHE = _load_cache()


def _save_cache() -> None:
    try:
        TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_CACHE.write_text(json.dumps(_CACHE, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def token_for_host(host: str) -> str | None:
    cached = _CACHE["tokens"].get(host)
    if cached:
        return cached
    key, iv = effective_key_iv()
    if key and iv:
        token = (iv + _aes_cfb(key, iv, host.encode())).hex()
        remember(host, token)
        return token
    return None


def host_for_token(token: str) -> str | None:
    host = _CACHE["hosts"].get(token)
    if host:
        return host
    decoded = decode_token(token)
    return decoded


def remember(host: str, token: str) -> None:
    _CACHE["tokens"][host] = token
    _CACHE["hosts"][token] = host
    _save_cache()


def all_tokens() -> dict:
    return dict(_CACHE["tokens"])


def iv_bytes_from_token(token: str) -> bytes:
    raw = bytes.fromhex(token)
    return raw[:16]


def _aes_cfb(key: bytes, iv: bytes, data: bytes) -> bytes:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    enc = Cipher(algorithms.AES(key), modes.CFB(iv)).encryptor()
    return enc.update(data) + enc.finalize()


def effective_key_iv() -> tuple[bytes | None, bytes | None]:
    key = WEBVPN_AES_KEY.encode() if WEBVPN_AES_KEY else None
    iv = WEBVPN_AES_IV.encode() if WEBVPN_AES_IV else None
    if key is None:
        cached = _CACHE.get("aes_key")
        key = cached.encode() if cached else None
    if iv is None:
        cached = _CACHE.get("aes_iv")
        iv = cached.encode() if cached else None
    return key, iv


def remember_key_iv(key: str, iv: str | None = None) -> None:
    _CACHE["aes_key"] = key
    _CACHE["aes_iv"] = iv or key
    _save_cache()


def encode_host(host: str, key: str | None = None, iv: str | None = None) -> str:
    k, i = effective_key_iv()
    if key:
        k = key.encode()
    if iv:
        i = iv.encode()
    if not k or not i:
        raise RuntimeError(
            "AES key/IV unknown for this deployment; pass --key/--iv or run "
            "`papervpn key-discover` after logging in."
        )
    return (i + _aes_cfb(k, i, host.encode())).hex()


def decode_token(token: str, key: str | None = None, iv: str | None = None) -> str | None:
    k, i = effective_key_iv()
    if key:
        k = key.encode()
    if iv:
        i = iv.encode()
    try:
        raw = bytes.fromhex(token)
    except ValueError:
        return None
    if not k or not i:
        return None
    try:
        plain = _aes_cfb(k, i, raw[16:])
        return plain.decode("utf-8")
    except Exception:
        return None


if not TOKEN_CACHE.is_file():
    _save_cache()
