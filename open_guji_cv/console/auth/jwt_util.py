# -*- coding: utf-8 -*-
"""极简 HS256 JWT：编/解 + 验签/验 `aud`/验 `exp`/验 `iss`。

**不加新依赖**（`PyJWT`/`python-jose` 都没在 pyproject 里）——HS256 就是
`base64url(header).base64url(payload)` 加一段 HMAC-SHA256，标准库够写。
两处在用：`id_token`（网站签发／`--dev-idp` 假签）与平台自己的会话 cookie
（`session.py`）。**只支持 HS256**——网站规格明确「先 HS256 共享密钥，
将来可换 RS256+JWKS」，真到那天再加一个 `alg` 分支，不预先做抽象。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


class TokenError(Exception):
    """签名不对／过期／`aud`／`iss` 不对，统一这一种，调用方不用分好几个 except。"""


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def encode(payload: dict, secret: str) -> str:
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    sig = hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url(sig)}"


def decode(token: str, secret: str, *, audience: str | None = None,
          issuer: str | None = None) -> dict:
    """验签 + 验过期 + （可选）验 `aud`/`iss`。任何一条不过 → `TokenError`。"""
    parts = token.split(".")
    if len(parts) != 3:
        raise TokenError("不是三段式 JWT")
    header_b64, body_b64, sig_b64 = parts
    expected = hmac.new(secret.encode(), f"{header_b64}.{body_b64}".encode(), hashlib.sha256).digest()
    try:
        got = _b64url_decode(sig_b64)
    except Exception as e:                                  # noqa: BLE001
        raise TokenError("签名段解不出来") from e
    if not hmac.compare_digest(expected, got):
        raise TokenError("签名不对")
    try:
        payload = json.loads(_b64url_decode(body_b64))
    except Exception as e:                                  # noqa: BLE001
        raise TokenError("payload 不是合法 JSON") from e
    exp = payload.get("exp")
    if exp is None or time.time() > float(exp):
        raise TokenError("过期")
    if audience is not None and payload.get("aud") != audience:
        raise TokenError("aud 不对")
    if issuer is not None and payload.get("iss") != issuer:
        raise TokenError("iss 不对")
    return payload


def pkce_challenge(verifier: str) -> str:
    """PKCE S256：`code_challenge = base64url(sha256(code_verifier))`。"""
    return _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
