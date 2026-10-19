"""按分支名查 Neon 端点 id，让 push／sync 能直连实验分支（``exp/GUJI-<号>-…``）。

要 ``NEON_API_KEY``；项目 id 用 ``NEON_PROJECT_ID``，缺省是中心库项目 ``aged-credit-71244565``。
口令不经这里：连库仍用 ``NEON_DATABASE_URL`` 里的账号（Neon 子分支继承父分支的角色与口令）。
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.request

API = "https://console.neon.tech/api/v2"
DEFAULT_PROJECT = "aged-credit-71244565"


def _get(path: str) -> dict:
    key = os.environ.get("NEON_API_KEY")
    if not key:
        raise SystemExit("要连实验分支：设 NEON_API_KEY（项目环境变量里有）")
    ca = os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE")
    ctx = ssl.create_default_context(cafile=ca) if ca else ssl.create_default_context()
    req = urllib.request.Request(API + path, headers={"authorization": f"Bearer {key}",
                                                      "accept": "application/json"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
        return json.loads(r.read())


def branch_endpoint(name: str, project: str | None = None) -> str:
    """分支 ``name`` 的读写端点 id（如 ``ep-xxx``）。没有这个分支或它没有读写端点就报错。"""
    project = project or os.environ.get("NEON_PROJECT_ID") or DEFAULT_PROJECT
    branches = {b["name"]: b["id"] for b in _get(f"/projects/{project}/branches")["branches"]}
    if name not in branches:
        raise SystemExit(f"中心库没有分支 {name}：先 guji db branch create {name}")
    for e in _get(f"/projects/{project}/endpoints")["endpoints"]:
        if e.get("branch_id") == branches[name] and e.get("type") == "read_write":
            return str(e["id"])
    raise SystemExit(f"分支 {name} 没有读写端点")
