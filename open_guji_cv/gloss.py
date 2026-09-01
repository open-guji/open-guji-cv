"""单字速查释义（审阅界面候选注记用）。

数据由 ``scripts/build_gloss.py`` 分层合并（moe/kangxi/unihan），懒加载
``config/gloss/gloss.json``。释义在构建时已截短到一行，本模块不再加工。

与 :mod:`open_guji_cv.variants` 配合：``annotate()`` 一次拿到
「释义 + 读音 + 与另一组字的异体/通假关系」，审阅界面按需渲染。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DEFAULT_GLOSS_PATH = (Path(__file__).resolve().parents[1]
                      / "config" / "gloss" / "gloss.json")


@lru_cache(maxsize=1)
def _table(path: str | None = None) -> dict:
    p = Path(path) if path else DEFAULT_GLOSS_PATH
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def gloss_of(char: str) -> dict:
    """char → {"d": 释义, "p": 拼音, "s": 来源}（缺哪项就没哪个键）。"""
    return _table().get(char, {})


def annotate(char: str, others: tuple[str, ...] = ()) -> dict:
    """候选注记：释义/读音 + 与 others 中各字的异体/通假关系。

    others 传同一字位的其余候选：审阅者最需要知道的是「这几个候选
    互相是什么关系」——异体（同一个词，挑字形贴合的）还是通假
    （不同的词，按文意挑）。
    """
    from .variants import variants_of
    info = dict(gloss_of(char))
    rels = []
    if others:
        vmap = {v: tags for v, tags in variants_of(char)}
        for o in others:
            if o == char or o not in vmap:
                continue
            tags = vmap[o]
            kind = ("通假" if all(t == "hydzd-borrowed" for t in tags)
                    else "異體")
            rels.append({"char": o, "kind": kind})
    if rels:
        info["rel"] = rels
    return info
