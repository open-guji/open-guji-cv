# -*- coding: utf-8 -*-
"""字形系统第三步：字体档按 sha256 进出 R2（三系统设计，Sheldon 11-04）。

cv 仓 ``fonts/``（约 194 MB，字形库 ``kind='font'`` 与 5-b 生僻字模板的真源，见 ``fonts/README.md``）
和模型一样改成「cv 只带路径 → sha 表，文件按 sha 从 R2 取回、放回 ``fonts/<路径>``」：读字体的代码、
指纹一概不变。表 ``config/font-registry.json``，``guji font registry|upload|fetch``；``guji pipeline``
起跑前缺了自动补。

**商业字体不进 R2**：``fonts/kangxi/``（TypeLand 康熙字典体）R2 是公开只读的，不能把它放上去，
仍随 cv 仓走（``SKIP``）。
"""
from __future__ import annotations

import json
from pathlib import Path

from .model_pack import REPO_ROOT, _sha256  # noqa: F401  （REPO_ROOT 测试里会换）

REGISTRY = "config/font-registry.json"
FONT_DIR = "fonts"
#: 不进表、不上 R2 的：商业字体整目录；目录说明
SKIP_DIRS = ("fonts/kangxi/",)
SKIP_NAMES = {"README.md"}


def _root() -> Path:
    from . import model_pack
    return model_pack.REPO_ROOT


def repo_items() -> list[dict]:
    """``fonts/`` 下要进表的文件（含各字体的授权文本，随字体一起取回）。"""
    root = _root()
    out = []
    for p in sorted((root / FONT_DIR).rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if p.name in SKIP_NAMES or any(rel.startswith(d) for d in SKIP_DIRS):
            continue
        out.append({"path": rel, "size": p.stat().st_size, "sha256": _sha256(p)})
    return out


def build_registry() -> dict:
    items = repo_items()
    p = _root() / REGISTRY
    p.write_text(json.dumps({"schema": "font-registry/1", "items": items}, ensure_ascii=False, indent=1) + "\n",
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
