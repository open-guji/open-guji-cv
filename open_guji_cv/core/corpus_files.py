# -*- coding: utf-8 -*-
"""语料第三步：cv 仓里的底库语料表按 sha256 进出 R2（三系统设计，Sheldon 11-04）。

和模型、字体同一套（`core/model_pack.REGISTRY`、`core/font_files.py`）：cv 只带一张路径 → sha 表
``config/corpus-registry.json``，文件按 sha 从 R2 取回、**放回原位**（``config/groups/…``、``config/ids/…``、
``corpus/external/…``），读语料的代码、指纹一概不变。``guji corpus registry``／``upload``／``fetch``（不给 ``-w``）；
``guji pipeline`` 起跑前缺了自动补，测试开跑前缺了也补（`tests/conftest.py`）。

收哪些文件：`core/corpus_pin.ITEMS` 里根为 ``repo`` 的（与底库清单 ``b<M>`` 同一口径；字组 ``prompt.md``、
``unet.npz`` 不算语料）。等 rc 时把这些文件从 git 删掉，cv 就只剩这张表。
"""
from __future__ import annotations

import json
from pathlib import Path

from .model_pack import _sha256

REGISTRY = "config/corpus-registry.json"


def _root() -> Path:
    from . import model_pack
    return model_pack.REPO_ROOT


def repo_items() -> list[dict]:
    from .corpus_pin import ITEMS, _not_corpus
    root = _root()
    seen: dict[str, dict] = {}
    for _group, where, pat in ITEMS:
        if where != "repo":
            continue
        for p in sorted(root.glob(pat)):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if rel in seen or rel == REGISTRY or _not_corpus("repo", rel):
                continue
            seen[rel] = {"path": rel, "size": p.stat().st_size, "sha256": _sha256(p)}
    return [seen[k] for k in sorted(seen)]


def build_registry() -> dict:
    items = repo_items()
    p = _root() / REGISTRY
    p.write_text(json.dumps({"schema": "corpus-registry/1", "items": items}, ensure_ascii=False, indent=1) + "\n",
                 encoding="utf-8")
    return {"path": str(p), "items": len(items)}


def load_registry() -> list[dict]:
    p = _root() / REGISTRY
    if not p.is_file():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("items") or []


def missing() -> list[dict]:
    root = _root()
    return [i for i in load_registry() if not (root / i["path"]).exists()]
