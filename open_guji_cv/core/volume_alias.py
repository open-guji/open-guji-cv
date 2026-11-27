"""册的旧名（2026-11-27 用户定册号位数统一、老书 cv 册名也改）：读的时候把旧名换成新名。

## 为什么

册名改了（殿本 `vol01`→`01`、脉经 `01`→`1`、北行 `bxgb`→`1`…），中心库里挂着旧名的记录有几十万行
（事件、锚点、钉子账、清单）。逐行改写风险大，也破「只追加」的规矩。所以**旧记录不改写**：
册 yaml 写 `aliases: [vol01]`，事件等读取入口在内存里把旧名换成新名，下游读者看到的全是新名。
从改名那天起新写的记录一律用新名。

## 规定

- 册 yaml（`books/<新名>.yaml`）写 `aliases:`，列这册以前用过的册名；一个旧名只许属于一册。
- 换的地方：`target.book`、`target.key` 里册名那一段、`payload` 的 `cell`／`book`，
  以及顶层 `book`（uid 流）。事件 id、批次名、`migrated_from` 之类的历史记录不换。
- **字形库实例 id 不换**（`v2:vol01:…`、`payload.instance_id`）：字形库不改名，实例 id 是不透明编号，
  换了就对不上库里的实例（如 glyph_audit 撤库事件）。
- 没有任何册写 `aliases` 时什么都不做（老书行为逐位不变）。

只读 yaml，不进任何 Step 的指纹。
"""
from __future__ import annotations

import re
from pathlib import Path

#: 带前缀的键（`cols:vol02:171`、`colborder:vol01:47:2:top`）：前缀以字母开头。字形库实例命名空间（`v2:`、`v1:`）除外。
#: 字形库实例 id 的命名空间前缀：实例 id 不透明，改册名不换（11-27）。
INSTANCE_NS = frozenset({"v1", "v2"})
_PREFIXED = re.compile(r"^(?P<pre>[a-z][a-z0-9_]*):(?P<book>[^:/]+)(?P<rest>[:/].*)?$")
_PLAIN = re.compile(r"^(?P<book>[^:/]+)(?P<rest>[:/].*)$")

_FILE_CACHE: dict[str, tuple[tuple[int, int], tuple[str, ...]]] = {}


def _aliases_of(p: Path) -> tuple[str, ...]:
    st = p.stat()
    sig = (st.st_mtime_ns, st.st_size)
    hit = _FILE_CACHE.get(str(p))
    if hit is not None and hit[0] == sig:
        return hit[1]
    out: tuple[str, ...] = ()
    text = p.read_text(encoding="utf-8")
    if "aliases" in text:
        import yaml
        try:
            d = yaml.safe_load(text)
        except yaml.YAMLError:
            d = None
        v = d.get("aliases") if isinstance(d, dict) else None
        if isinstance(v, (list, tuple)):
            out = tuple(str(x) for x in v if x not in (None, ""))
        elif v not in (None, ""):
            out = (str(v),)
    _FILE_CACHE[str(p)] = (sig, out)
    return out


def alias_map(books_dir: Path | None) -> dict[str, str]:
    """`books/` 下各册 yaml 的 `aliases` → {旧名: 新名}。读不到目录给空表。

    每次只 stat 各 yaml，内容按 (mtime, 大小) 缓存。同一个旧名写在两册里报错（不猜）。"""
    if books_dir is None:
        from .book import _workspace_books_dir
        books_dir = _workspace_books_dir()
        if books_dir is None:
            return {}
    d = Path(books_dir)
    if not d.is_dir():
        return {}
    out: dict[str, str] = {}
    for p in sorted(d.glob("*.yaml")):
        try:
            names = _aliases_of(p)
        except OSError:
            continue
        for a in names:
            if a in out and out[a] != p.stem:
                raise ValueError(f"册旧名 {a} 同时写在 {out[a]}.yaml 与 {p.stem}.yaml 的 aliases 里")
            if a != p.stem:
                out[a] = p.stem
    return out


def rename_key(key: str | None, amap: dict[str, str]) -> str | None:
    """键里册名那一段换成新名：`vol01:22:5:4`、`vol01/50:7:21`、`cols:vol02:171`；`v2:vol01:…` 是字形库实例 id，不换。"""
    if not key or not amap:
        return key
    if key in amap:
        return amap[key]
    m = _PLAIN.match(key)
    if m and m.group("book") in amap:
        return amap[m.group("book")] + m.group("rest")
    m = _PREFIXED.match(key)
    if m and m.group("pre") not in INSTANCE_NS and m.group("book") in amap:
        return f"{m.group('pre')}:{amap[m.group('book')]}{m.group('rest') or ''}"
    return key


_PAYLOAD_KEYS = ("cell",)


def alias_event_dict(e: dict, amap: dict[str, str]) -> dict:
    """事件 dict 换名；没有要换的原样返回同一个对象，有就返回改过的浅拷贝（不改入参）。"""
    if not amap:
        return e
    out = e
    t = e.get("target")
    if isinstance(t, dict):
        nb, nk = t.get("book"), rename_key(t.get("key"), amap)
        if nb in amap:
            nb = amap[nb]
        if nb != t.get("book") or nk != t.get("key"):
            out = dict(out)
            out["target"] = {**t, "book": nb, "key": nk} if "book" in t else {**t, "key": nk}
    p = e.get("payload")
    if isinstance(p, dict):
        upd = {k: rename_key(p[k], amap) for k in _PAYLOAD_KEYS if isinstance(p.get(k), str)}
        if isinstance(p.get("book"), str) and p["book"] in amap:
            upd["book"] = amap[p["book"]]
        upd = {k: v for k, v in upd.items() if v != p.get(k)}
        if upd:
            out = dict(out) if out is e else out
            out["payload"] = {**p, **upd}
    if isinstance(e.get("book"), str) and e["book"] in amap:
        out = dict(out) if out is e else out
        out["book"] = amap[e["book"]]
    return out
