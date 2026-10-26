"""把一组册 yaml 里相同的部分抽成工作区基础配置（`config/book_defaults.yaml`），册 yaml 只留各自不同的。

强校验：每一册「基础配置 ∪ 瘦身后的册 yaml」解析出的字典必须与拆分前逐字段相等，有一册不等就整次不写。
用 ruamel 往返读写，基础配置和册 yaml 里保留原来的注释。设计见 doc/design/册配置分层与运行覆盖.md。
"""
from __future__ import annotations

import io
from pathlib import Path

import yaml

from .book_config import FORBIDDEN_IN_DEFAULTS, merge


class SplitError(RuntimeError):
    pass


def _common(docs: list[dict]) -> dict:
    """所有册里键和值都相同的部分（映射递归，标量／列表要整体相等）。"""
    first = docs[0]
    out: dict = {}
    for k, v in first.items():
        if all(k in d for d in docs[1:]):
            if isinstance(v, dict) and all(isinstance(d[k], dict) for d in docs[1:]):
                sub = _common([d[k] for d in docs])
                if sub:
                    out[k] = sub
            elif all(d[k] == v for d in docs[1:]):
                out[k] = v
    return out


def _prune_to(node, keep: dict) -> None:
    """ruamel 节点只留 `keep` 里有的键（递归）。"""
    for k in list(node.keys()):
        if k not in keep:
            del node[k]
        elif isinstance(keep[k], dict) and hasattr(node[k], "keys"):
            _prune_to(node[k], keep[k])


def _prune_same(node, base: dict) -> None:
    """ruamel 节点删掉与 `base` 相同的键（递归；映射删空后整键去掉）。"""
    for k in list(node.keys()):
        if k not in base:
            continue
        if isinstance(base[k], dict) and hasattr(node[k], "keys"):
            _prune_same(node[k], base[k])
            if not len(node[k]):
                del node[k]
        elif node[k] == base[k]:
            del node[k]


def _rt():
    from ruamel.yaml import YAML
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096
    y.allow_unicode = True
    return y


def _dump(y, node) -> str:
    buf = io.StringIO()
    y.dump(node, buf)
    return buf.getvalue()


def split(books_dir: Path, book_ids: list[str], *, header: str = "") -> dict:
    """返回 {"base": 基础配置文本, "books": {册: 新文本}, "base_dict": …}；不写盘。校验不过抛 SplitError。"""
    if len(book_ids) < 2:
        raise SplitError("至少两册才谈得上共用")
    y = _rt()
    texts = {b: (books_dir / f"{b}.yaml").read_text(encoding="utf-8") for b in book_ids}
    orig = {b: yaml.safe_load(t) or {} for b, t in texts.items()}
    base = {k: v for k, v in _common(list(orig.values())).items() if k not in FORBIDDEN_IN_DEFAULTS}
    if not base:
        raise SplitError("这些册没有可共用的部分")
    # 基础配置文本：取第一册，只留共用的键（保留它的注释）
    node = y.load(texts[book_ids[0]])
    _prune_to(node, base)
    body = _dump(y, node)
    lines = body.splitlines(keepends=True)
    while lines and lines[0].startswith("#"):       # 去掉第一册的册首说明注释（那是它自己的）
        lines.pop(0)
    base_text = (header or "") + "".join(lines)
    # 各册瘦身
    new_texts: dict[str, str] = {}
    for b in book_ids:
        n = y.load(texts[b])
        _prune_same(n, base)
        new_texts[b] = _dump(y, n)
    # 强校验
    base_parsed = yaml.safe_load(base_text) or {}
    if base_parsed != base:
        raise SplitError("基础配置文本解析后与算出的共用部分不一致，停")
    for b in book_ids:
        merged = merge(base_parsed, yaml.safe_load(new_texts[b]) or {})
        if merged != orig[b]:
            diff = sorted(k for k in set(merged) | set(orig[b]) if merged.get(k) != orig[b].get(k))
            raise SplitError(f"{b} 拆分后合并结果与原来不一致（字段：{', '.join(diff)}），整次不写")
    return {"base": base_text, "books": new_texts, "base_dict": base,
            "lines_before": {b: texts[b].count("\n") for b in book_ids},
            "lines_after": {b: new_texts[b].count("\n") for b in book_ids}}


def write_split(books_dir: Path, res: dict, base_path: Path) -> None:
    base_path.parent.mkdir(parents=True, exist_ok=True)
    base_path.write_text(res["base"], encoding="utf-8")
    for b, t in res["books"].items():
        (books_dir / f"{b}.yaml").write_text(t, encoding="utf-8")
