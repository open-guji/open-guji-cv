"""字组提示词模板的渲染：模板（``config/groups/<组>/prompt.md``，全局层）里的 ``{{名字}}`` 占位符用本书的变量填
（书名那一句等，书层语料，见 doc/design/语料库分层版本.md 4.1）。

单独成模块、不改 ``ctx_l3``：``ctx_l3`` 在 ``seed_admit`` 的 ``code_deps`` 里，改它会让各书产物过期；
提示词只在离线造批、不进 Step 运行路径。没有占位符的提示词渲染结果与 ``ctx_l3.load_prompt`` 逐字相同。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .ctx_l3 import build_batch, load_prompt

_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


def book_prompt_vars(ws: str | Path | None = None) -> dict[str, str]:
    """本书的提示词变量：数据目录 ``config/groups/book_prompt.json``，形如 ``{"book_desc": "《四庫全書總目》殿本刻本"}``；
    没有这个文件 → 空字典。"""
    from ..core.workspace import data_root
    d = data_root(Path(ws) if ws else None)
    f = d / "config" / "groups" / "book_prompt.json" if d else None
    return json.loads(f.read_text(encoding="utf-8")) if f and f.is_file() else {}


def render_body(body: str, book_vars: dict[str, str] | None, where: str = "") -> str:
    missing = sorted({k for k in _PLACEHOLDER.findall(body) if k not in (book_vars or {})})
    if missing:
        raise KeyError(f"提示词 {where} 里有占位符 {missing}，本书没有提供（config/groups/book_prompt.json）")
    return _PLACEHOLDER.sub(lambda m: book_vars[m.group(1)], body) if book_vars else body


def load_rendered_prompt(path: str | Path, book_vars: dict[str, str] | None = None) -> tuple[dict, str]:
    meta, body = load_prompt(path)
    return meta, render_body(body, book_vars, str(path))


def build_batch_rendered(prompt_path: str | Path, cells: list[dict], book_vars: dict[str, str] | None = None) -> str:
    """同 ``ctx_l3.build_batch``，提示词里的占位符先用 ``book_vars`` 填。"""
    import tempfile
    _, body = load_rendered_prompt(prompt_path, book_vars)
    with tempfile.TemporaryDirectory() as d:                 # build_batch 只收路径：把渲染后的正文交给它拼逐条输入
        q = Path(d) / "p.md"
        q.write_text(body, encoding="utf-8")
        return build_batch(q, cells)
