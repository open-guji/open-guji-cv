"""连中心库 Postgres：``GUJI_DATA_PG_DSN``，没有就从 ``NEON_DATABASE_URL`` 在本进程起 443 桥。"""
from __future__ import annotations

import os


def main_endpoint() -> str | None:
    """``NEON_DATABASE_URL`` 指的端点 id（正式库 main）。"""
    import urllib.parse as u
    url = os.environ.get("NEON_DATABASE_URL")
    if not url:
        return None
    return (u.urlparse(url).hostname or "").split(".")[0].removesuffix("-pooler") or None


def connect(endpoint: str | None = None):
    """``endpoint`` 给了就连 Neon 的那个端点（同项目、同账号的别的分支，如 ci）。"""
    import psycopg
    dsn = None if endpoint else os.environ.get("GUJI_DATA_PG_DSN")
    if not dsn:
        url = os.environ.get("NEON_DATABASE_URL")
        if not url:
            raise SystemExit("要连库：设 GUJI_DATA_PG_DSN，或 NEON_DATABASE_URL（自动经 443 桥）")
        from .wsbridge import neon_dsn_via_bridge
        dsn = neon_dsn_via_bridge(url, endpoint=endpoint)
    return psycopg.connect(dsn)
