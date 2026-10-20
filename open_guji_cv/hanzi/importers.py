# -*- coding: utf-8 -*-
"""各来源 → 行。每个函数只吃文本／已解析的对象，吐 `(rows, stats)`，不碰文件系统，便于自造数据测试。

边的行是 `schema.TABLES["edges"]` 的列序：`(a, b, rel, directed, src, sense, ref, note)`。
- `directed=1`：a 是正字（繁体、本字），b 是异体（简体、借字）；
- `directed=0`：无向，`a`、`b` 先按原样给，构建时再按码位排成 a<b。

现役来源（Unihan 变体、cjkvi、yitizi、local_edges）的跳行规矩与 `scripts/build_variants.py` 逐条相同，
这样 `export_variants_json()` 能重放现役 `variants.json`（总设计 A1）。
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter

from . import schema as S
from .ids import IDC as _IDC
from .ids import split_alternatives

Edge = tuple[str, str, str, int, str, str, str, str]

_CP_RE = re.compile(r"U\+([0-9A-Fa-f]+)")


def is_han(c: str) -> bool:
    """单个汉字（含扩展区），不要私用区、部首、兼容区重复字。与 `variant_sources.is_han` 同口径。"""
    if len(c) != 1:
        return False
    o = ord(c)
    if 0xE000 <= o <= 0xF8FF or o >= 0xF0000:
        return False
    if unicodedata.normalize("NFC", c) != c:
        return False
    return unicodedata.category(c) == "Lo" and o >= 0x3400


# ── Unihan ───────────────────────────────────────────────

_UNIHAN_REL = {
    "kSemanticVariant": (S.VARIANT, 0),
    "kSpecializedSemanticVariant": (S.VARIANT_PARTIAL, 0),
    "kZVariant": (S.Z, 0),
    "kSimplifiedVariant": (S.SIMP, 1),
    "kTraditionalVariant": (S.SIMP, 1),
    "kSpoofingVariant": (S.SPOOF, 0),
}


def unihan_variants(text: str) -> tuple[list[Edge], dict]:
    """Unihan_Variants.txt → 边。值里 `<kMatthews,…` 是字典出处，记进 ref。

    kTraditionalVariant 的键是简体、值是繁体：掉头成 (繁, 简)。"""
    rows: list[Edge] = []
    st = Counter()
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        cp_s, prop, val = parts
        if prop not in _UNIHAN_REL:
            continue
        rel, directed = _UNIHAN_REL[prop]
        a = chr(int(cp_s[2:], 16))
        for tok in val.split():
            m = _CP_RE.match(tok)
            if not m:
                st["token_bad"] += 1
                continue
            b = chr(int(m.group(1), 16))
            if a == b:
                st["self_loop"] += 1
                continue
            ref = tok[m.end():].lstrip("<")
            x, y = (b, a) if prop == "kTraditionalVariant" else (a, b)
            rows.append((x, y, rel, directed, f"unihan:{prop}", "", ref, ""))
            st[prop] += 1
    st["edges"] = len(rows)
    return rows, dict(st)


_UNIHAN_CHAR_FIELDS = {"kRSUnicode": "rs", "kTotalStrokes": "strokes",
                       "kIRGKangXi": "kangxi", "kDefinition": "def"}


def unihan_chars(texts: list[str]) -> tuple[list[tuple], dict]:
    """Unihan 各文件 → chars 行。只收统一汉字（兼容区折掉，见需求 §3.1）。"""
    acc: dict[str, dict[str, str]] = {}
    for text in texts:
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t", 2)
            if len(parts) < 3 or not parts[0].startswith("U+"):
                continue
            ch = chr(int(parts[0][2:], 16))
            if unicodedata.normalize("NFC", ch) != ch:
                continue
            d = acc.setdefault(ch, {})
            col = _UNIHAN_CHAR_FIELDS.get(parts[1])
            if col:
                d[col] = parts[2]
    rows = []
    for ch, d in acc.items():
        strokes = d.get("strokes", "").split(" ")[0]
        rows.append((ch, ord(ch), S.block_of(ch), d.get("rs", ""),
                     int(strokes) if strokes.isdigit() else 0,
                     d.get("kangxi", ""), d.get("def", "")))
    return rows, {"chars": len(rows), "by_block": dict(Counter(r[2] for r in rows))}


# ── cjkvi-variants ───────────────────────────────────────

#: cjkvi 关系标签 → (rel, directed)。没列的按 variant 有向。
_CJKVI_REL = {
    "hydzd/simplified": (S.SIMP, 1),
    "cjkvi/simplified": (S.SIMP, 1),
    "cjkvi/traditional": (S.SIMP, 1),
    "cjkvi/variant-simplified": (S.SIMP, 1),
    "cjkvi/pseudo-simplified": (S.SIMP, 1),
    "hydcd/borrowed": (S.BORROW, 0),
}


def cjkvi_variants(text: str, tag: str) -> tuple[list[Edge], list[tuple], dict]:
    """`字,关系,字[,注]` → (边, 未编码形, stats)。

    第三列是 IDS 串（含 ⿰ 等描述符）的行不丢：进 `forms`，归属正字记第一列。
    其余跳行规矩同 `build_variants.parse_cjkvi_variants`。"""
    rows: list[Edge] = []
    forms: list[tuple] = []
    st = Counter()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(",")
        if len(parts) < 3:
            st["line_short"] += 1
            continue
        a, rel, b = parts[0].strip(), parts[1].strip(), parts[2].strip()
        if "/" in a or a.startswith("<"):
            st["line_meta"] += 1
            continue
        if not S.is_legacy_cjk(a):
            st["col1_bad"] += 1
            continue
        if not S.is_legacy_cjk(b):
            st["col3_bad"] += 1
            if len(b) > 1 and any(c in _IDC for c in b):
                forms.append((b, a, tag, rel))
                st["forms"] += 1
            continue
        if a == b:
            st["self_loop"] += 1
            continue
        if rel == "cjkvi/traditional":
            a, b = b, a
        r, directed = _CJKVI_REL.get(rel, (S.VARIANT, 1))
        ref = parts[3].strip() if len(parts) > 3 else ""
        rows.append((a, b, r, directed, tag, "", ref, ""))
    st["edges"] = len(rows)
    return rows, forms, dict(st)


# ── yitizi ───────────────────────────────────────────────

_YITIZI_RE = re.compile(r"yitiziData\s*:\s*(\{.*?\n\})", re.DOTALL)


def yitizi(js_text: str) -> tuple[list[Edge], dict]:
    m = _YITIZI_RE.search(js_text)
    if not m:
        raise ValueError("yitizi index.js 里找不到 yitiziData——上游格式变了")
    data = json.loads(m.group(1))
    rows: list[Edge] = []
    st = Counter()
    for a, vs in data.items():
        if not S.is_legacy_cjk(a):
            st["key_bad"] += 1
            continue
        for b in vs:
            if not S.is_legacy_cjk(b):
                st["value_bad"] += 1
                continue
            if a == b:
                st["self_loop"] += 1
                continue
            rows.append((a, b, S.VARIANT, 0, "yitizi", "", "", ""))
    st["edges"] = len(rows)
    return rows, dict(st)


# ── 部件檢索 ─────────────────────────────────────────────

def charcomp_rt(dt_lines: list[str], rt_lines: list[str]) -> tuple[list[Edge], dict]:
    """dt 每行的首字是字头，rt 同行：`~` 之后是异体（variant），之前是部件對應字（related）。无向。"""
    rows: list[Edge] = []
    st = Counter()
    for d, r in zip(dt_lines, rt_lines):
        head = json.loads(d)[:1]
        val = json.loads(r)
        if not is_han(head):
            continue
        pre, _, post = val.partition("~")
        for part, rel in ((pre, S.RELATED), (post, S.VARIANT)):
            for c in part:
                if c.isspace() or c == head or not is_han(c):
                    continue
                rows.append((head, c, rel, 0, "charcomp:rt", "", "", ""))
                st[rel] += 1
    st["edges"] = len(rows)
    return rows, dict(st)


# ── 本项目 ───────────────────────────────────────────────

def local_edges(doc: dict) -> tuple[list[Edge], dict]:
    """config/variants/local_edges.json → 边。带 `directed` 的存成 (正字, 异体) 有向行。"""
    rows: list[Edge] = []
    for e in doc.get("edges", []):
        tags = list(e.get("tags") or ["local:keben"])
        d = e.get("directed")
        why = " ".join(str(e.get("why", "")).split())
        for t in tags:
            if d:
                rows.append((d["regular"], d["variant"], S.VARIANT, 1, t, "", "", why))
            else:
                rows.append((e["a"], e["b"], S.VARIANT, 0, t, "", "", why))
    return rows, {"edges": len(rows)}


def never_group(doc: dict) -> tuple[list[Edge], dict]:
    ev = doc.get("_evidence") or {}
    rows: list[Edge] = []
    for a, b in doc.get("pairs", []):
        note = " ".join(str(ev.get(f"{a}/{b}") or ev.get(f"{b}/{a}") or "").split())
        rows.append((a, b, S.DISTINCT, 0, "local:never", "", "", note))
    return rows, {"edges": len(rows)}


def near_pairs(text: str, src: str) -> tuple[list[tuple], dict]:
    """形近对表（`a\\tb\\tkind\\tscore\\tdetail`）→ near 行，记原文件行号以复现同分时的次序。"""
    rows = []
    for ln, line in enumerate(text.splitlines()):
        if not line or line.startswith(("#", "a\t")):
            continue
        a, b, kind, score, detail = (line.split("\t") + [""] * 5)[:5]
        rows.append((a, b, src, kind, float(score), detail, ln))
    return rows, {"pairs": len(rows)}


def zi_cache(docs: list[dict]) -> tuple[list[Edge], dict]:
    """字统网缓存 `{q, fam}` → 无向 variant 边，来源 `zi`。只收派生的族关系事实。"""
    rows: list[Edge] = []
    for d in docs:
        q = d.get("q", "")
        if not is_han(q):
            continue
        for c in d.get("fam") or ():
            if is_han(c) and c != q:
                rows.append((q, c, S.VARIANT, 0, "zi", "", "", ""))
    return rows, {"queried": len(docs), "edges": len(rows)}


# ── IDS ──────────────────────────────────────────────────

def ids_yibai(text: str, src: str) -> list[tuple]:
    """yi-bai/ids：`字\\t写法(地区);写法…[\\t写法…]`。"""
    out = []
    for ln in text.splitlines():
        if not ln or ln.startswith("#"):
            continue
        parts = ln.split("\t")
        if len(parts) < 2:
            continue
        for col in parts[1:]:
            for seq, regs in split_alternatives(col):
                if seq:
                    out.append((parts[0], src, seq, ",".join(sorted(regs))))
    return out
