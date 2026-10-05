# -*- coding: utf-8 -*-
"""guji-page ↔ guji-format（book-text 的 lines.md + 伴生层）双向转换。F3 道，overview#398（A1/A2）。

规范与取舍见 `doc/formats/format_merge_a1.md`。一句话：**book-text 存 guji-format，lines.md 是文本真源；
guji-page 是 CV 内部与交换格式，由它生成 lines.md、pages.json 与各伴生层的初值；锚点以 CV 格 id 为准，
数 lines.md 推出来的位置只做校验。**

一章（book-text 的 `NNN`，可跨多页）一组文件：

| 文件 | 内容 | 从 guji-page 哪里来 |
|---|---|---|
| `NNN.lines.md` | 原刻逐列分行的 guji-markdown（`to_guji_markdown`，与 Step9 9.1 逐字相同） | `text` + `lacuna` + `zi` + 列/段 |
| `NNN.pages.json` | `guji-pages/0.1`：每页 canvas/图/版框/列条带/字格坐标，每格带锚点 `页:列:格[子列]` 与字偏移 | 其余几何、`glyphs`、`marks` |
| `NNN.proof.json` | `guji-proof/0.1`：每格 method/review/channel/cand（校对模式用，可整份不发） | `glyphs[].method/review/channel/cand` |
| `NNN.norm.json` | `guji-norm/0.1`：规范层逐位物化与例外（方案 C） | `norm` |
| `NNN.zi.json` | `guji-zi/0.1`：未收字的近似字与关系（原形在 lines.md 的 `:zi[…]`） | `zi` 的 `rel` 与 `text[i]` |
| `NNN.punct.json`／`NNN.entity.json` | 文本侧产出，本模块只**按锚点重挂**、不改其余内容 | — |

**字偏移**（`o`、`char_offset`）= 本章 lines.md 的字元序号：`[[]]`、`□{guess=…}`、`:zi[…]` 各算 1，
夹注 `<右|左>` 先右后左，页注 `<!-- pN -->`、`^`、`.`、空白不算。等于 guji-page 各页 `text` 首尾相接后的下标。

锚点（`a`）= CV 格 id 去掉册前缀：`<页>:<列>:<格>[a|b]`，页 = 工作区页号、列 = Step3 物理列号（空列也占号）、
格 = Step3 slot（抬头为负、没有 0）。来自真实几何，**不从 lines.md 数**；`derive_anchors()` 是数出来的那一套
（`scripts/test_vol02_extract.py::build_anchor_map` 的修正版），只用来对账。
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any, Iterable

from . import guji_page as gp

PAGES_SCHEMA = "guji-pages/0.1"
PROOF_SCHEMA = "guji-proof/0.1"
NORM_SCHEMA = "guji-norm/0.1"
ZI_SCHEMA = "guji-zi/0.1"

# 字框上进 proof.json 的字段（其余几何进 pages.json）；`text` 换成全章偏移 `o`、`cv_id` 换成锚点 `a`
PROOF_KEYS = ("method", "review", "channel", "cand", "conf")
_GLYPH_DROP = ("text", "cv_id", "ext") + PROOF_KEYS
# 格上等于缺省值的字段不写（读回时补）；`col`/`slot` 能从锚点推出来时也不写
CELL_DEFAULTS = {"lane": "main", "glyph_id": None, "by": {"box": "cv", "text": "cv"}}
# guji-page 页级块里原样进 pages.json 的
_PAGE_KEEP = ("page_id", "page", "image", "canvas", "producers", "marks", "warnings")


# ───────────────────────── 锚点 ─────────────────────────

def anchor_of(cv_id: str | None) -> str | None:
    """CV 格 id `vol03:39:9:21a` → 锚点 `39:9:21a`（去掉册前缀）。"""
    if not cv_id:
        return None
    parts = cv_id.split(":")
    return ":".join(parts[1:]) if len(parts) == 4 else cv_id


def parse_anchor(a: str) -> tuple[int, int, int, str]:
    m = re.fullmatch(r"(\d+):(\d+):(-?\d+)([ab]?)", a)
    if not m:
        raise ValueError(f"锚点格式不对：{a!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)


# ───────────────────────── lines.md 解析 ─────────────────────────

_PAGE_RE = re.compile(r"^<!--\s*p(\d+)\s*-->$")
_PREFIX = re.compile(r"^(\^*)(\.*)")
_UNIT = re.compile(
    r"<(?P<jz>[^<>]*)>"
    r"|:jz\[(?P<solo>[^\]]*)\](?:\{[^}]*\})?"
    r"|:zi\[(?P<zi>[^\]]*)\](?:\{[^}]*\})?"
    r"|\[\[(?P<gap>[^\]]*)\]\]"
    r"|□\{guess=(?P<guess>[^}]*)\}"
    r"|(?P<ch>.)", re.S)
_INNER = re.compile(
    r":zi\[(?P<zi>[^\]]*)\](?:\{[^}]*\})?"
    r"|\[\[(?P<gap>[^\]]*)\]\]"
    r"|□\{guess=(?P<guess>[^}]*)\}"
    r"|(?P<ch>.)", re.S)


def _inner_tokens(s: str, lane: str) -> list[dict]:
    out = []
    for u in _INNER.finditer(s):
        if u.group("zi") is not None:
            out.append({"t": None, "zi": u.group("zi"), "lane": lane})
        elif u.group("gap") is not None:
            out.append({"t": gp.LACUNA_CHAR, "lacuna": True, "lane": lane,
                        **({"label": u.group("gap")} if u.group("gap") else {})})
        elif u.group("guess") is not None:
            out.append({"t": "□", "guess": u.group("guess"), "lane": lane})
        elif not u.group("ch").isspace():
            out.append({"t": u.group("ch"), "lane": lane})
    return out


def parse_lines_md(md: str) -> list[dict]:
    """lines.md → `[{page, lines: [{raised, dots, tokens: [{t, lane, lacuna?, zi?, guess?}]}]}]`。

    页注之前的行归到 `page=None`。`:jz[…]` 里 Step9 把阙文写成「□」（guji_page_v0.2 §10.1 已知例外），
    这里分不出来，读回时由 pages.json 的 `lacuna_extra` 补。
    """
    pages: list[dict] = []
    cur: dict | None = None
    for raw in md.splitlines():
        s = raw.strip()
        if not s:
            continue
        pm = _PAGE_RE.match(s)
        if pm:
            cur = {"page": int(pm.group(1)), "lines": []}
            pages.append(cur)
            continue
        if cur is None:
            cur = {"page": None, "lines": []}
            pages.append(cur)
        m = _PREFIX.match(s)
        raised, dots = len(m.group(1)), len(m.group(2))
        toks: list[dict] = []
        for u in _UNIT.finditer(s[m.end():]):
            if u.group("jz") is not None:
                body = u.group("jz")
                if "|" in body:
                    right, left = body.split("|", 1)
                    toks += _inner_tokens(right, "jz_r") + _inner_tokens(left, "jz_l")
                else:          # 只有一半的夹注：Step9 对 jz_r 或 jz_l 单独一段都这样写，分不出左右，记 jz_r
                    toks += _inner_tokens(body, "jz_r")
            elif u.group("solo") is not None:
                toks += _inner_tokens(u.group("solo"), "solo")
            elif u.group("zi") is not None:
                toks.append({"t": None, "zi": u.group("zi"), "lane": "main"})
            elif u.group("gap") is not None:
                toks.append({"t": gp.LACUNA_CHAR, "lacuna": True, "lane": "main",
                             **({"label": u.group("gap")} if u.group("gap") else {})})
            elif u.group("guess") is not None:
                toks.append({"t": "□", "guess": u.group("guess"), "lane": "main"})
            elif not u.group("ch").isspace():
                toks.append({"t": u.group("ch"), "lane": "main"})
        cur["lines"].append({"raised": raised, "dots": dots, "tokens": toks})
    return pages


def derive_anchors(md: str) -> list[dict]:
    """数 lines.md 推锚点（只做校验）：`build_anchor_map` 的修正版。

    相对原版修了三处：抬头格号跳过 0（`^^` 起于 −2、−1，然后 1，与 CV slot 一致）；`:zi[…]` 算一个字
    （原版把 `:`、`z`、`i`、`[`… 各算一字）；夹注只有一半时不再把整段当右半。**修不了的**：空列（lines.md 不出
    空行，列号从此错位）、行首/列中的排除格与留白格（md 里不留痕）——这些只能靠 pages.json 的锚点。
    返回逐字 `{o, a, t, lane}`。
    """
    out: list[dict] = []
    o = 0
    for pg in parse_lines_md(md):
        for li, line in enumerate(pg["lines"], start=1):
            grid = -line["raised"] if line["raised"] else line["dots"] + 1
            toks = line["tokens"]
            k = 0
            while k < len(toks):
                tk = toks[k]
                if tk["lane"] in ("jz_r", "jz_l"):
                    j = k
                    while j < len(toks) and toks[j]["lane"] in ("jz_r", "jz_l"):
                        j += 1
                    right = [t for t in toks[k:j] if t["lane"] == "jz_r"]
                    left = [t for t in toks[k:j] if t["lane"] == "jz_l"]
                    for sub, grp in (("a", right), ("b", left)):
                        g = grid
                        for t in grp:
                            out.append({"o": o, "a": f"{pg['page']}:{li}:{g}{sub}", "t": t, "lane": t["lane"]})
                            o += 1
                            g = _next(g)
                    for _ in range(max(len(right), len(left))):
                        grid = _next(grid)
                    k = j
                    continue
                out.append({"o": o, "a": f"{pg['page']}:{li}:{grid}", "t": tk, "lane": tk["lane"]})
                o += 1
                grid = _next(grid)
                k += 1
    return out


def _next(g: int) -> int:
    return 1 if g == -1 else g + 1


# ───────────────────────── guji-page → guji-format ─────────────────────────

def _glyph_at(page: dict) -> dict[int, dict]:
    """字元下标 → 覆盖它的（第一个）单字字框。"""
    at: dict[int, dict] = {}
    for g in page.get("glyphs", []):
        for i in range(*g["text"]):
            at.setdefault(i, g)
    return at


def to_guji_format(pages: list[dict], *, chapter: str = "001", punct: dict | None = None,
                   entity: dict | None = None) -> dict[str, Any]:
    """一章的 guji-page（按页序）→ `{文件名: 内容}`（lines.md 是 str，其余是 dict）。

    `punct`/`entity` 给了就按新锚点重挂（`reattach`），只改 `char_offset`/`span`，其余原样。
    v0/v0.1 页先 `upgrade()`。`ext` 不进任何文件（入库口径 = `strip_ext`）。
    """
    pages = [gp.upgrade(p) if p.get("schema") != gp.SCHEMA_ID else p for p in pages]
    if not pages:
        raise ValueError("没有页")
    p0 = pages[0]
    cv_book = (p0.get("volume") or {}).get("cv_book")
    md_parts, pj_pages, proof, norm_items, zi_items = [], [], [], [], []
    base = 0
    for page in pages:
        page = gp.strip_ext(page)
        n = len(page["text"])
        md = gp.to_guji_markdown(page)
        md_parts.append(md)
        at = _glyph_at(page)

        # md 表达不了的阙文（`:jz[…]` 里写成「□」的那些）记下来，读回时补
        parsed = [t for pg in parse_lines_md(md) for ln in pg["lines"] for t in ln["tokens"]]
        if len(parsed) != n:
            raise ValueError(f"{page['page_id']}：md 读回 {len(parsed)} 字元，text 有 {n} 个——转换器与导出器口径不一致")
        lac = gp.lacuna_set(page)
        lac_extra = sorted(i for i in lac if not parsed[i].get("lacuna"))

        cols = []
        for reg in page["regions"]:
            for col in reg["columns"]:
                c = copy.deepcopy(col)
                c["runs"] = [{"lane": r["lane"], "o": [r["text"][0] + base, r["text"][1] + base]} for r in col["runs"]]
                cols.append(c)
        regions = []
        for reg in page["regions"]:
            r = {k: v for k, v in reg.items() if k != "columns"}
            r["columns"] = [c["id"] for c in reg["columns"]]
            regions.append(r)

        cells = []
        for g in page["glyphs"]:
            s, e = g["text"]
            cell = {"id": g["id"], "a": anchor_of(g.get("cv_id")),
                    "o": (s + base) if e - s == 1 else [s + base, e + base],
                    "c": "".join(page["text"][s:e])}
            cell.update({k: g[k] for k in sorted(g) if k not in _GLYPH_DROP and k != "id"   # 键序固定：往返逐字节同
                         and not (k in CELL_DEFAULTS and g[k] == CELL_DEFAULTS[k])})
            if cell["a"]:
                _, cn, slot, _ = parse_anchor(cell["a"])
                if cell.get("col") == f"c{cn}" and cell.get("slot") == slot:
                    del cell["col"], cell["slot"]
            cells.append(cell)
            pr = {k: g[k] for k in PROOF_KEYS if k in g}
            if pr:
                proof.append({"id": g["id"], "a": cell["a"], **pr})

        for nm in page.get("norm", []):
            g = at.get(nm["i"])
            norm_items.append({"a": anchor_of(g.get("cv_id")) if g else None, "o": nm["i"] + base,
                               "c": page["text"][nm["i"]], **{k: v for k, v in nm.items() if k != "i"}})
        for z in page.get("zi", []):
            g = at.get(z["i"])
            zi_items.append({"a": anchor_of(g.get("cv_id")) if g else None, "o": z["i"] + base,
                             "near": None if page["text"][z["i"]] == gp.ZI_NO_NEAR else page["text"][z["i"]],
                             **{k: v for k, v in z.items() if k != "i"}})

        pj = {k: page[k] for k in _PAGE_KEEP if k in page}
        pj.update({"o": [base, base + n], "regions": regions, "columns": cols, "cells": cells})
        if lac_extra:
            pj["lacuna_extra"] = [i + base for i in lac_extra]
        pj_pages.append(pj)
        base += n

    head = {"book": p0.get("book"), "volume": p0.get("volume"), "chapter": chapter}
    lines_md = "\n".join(md_parts) + "\n"
    files: dict[str, Any] = {
        f"{chapter}.lines.md": lines_md,
        f"{chapter}.pages.json": {"schema": PAGES_SCHEMA, **head, "lines_file": f"{chapter}.lines.md",
                                  "page_schema": gp.SCHEMA_ID, "cv_book": cv_book, "n_chars": base,
                                  "cell_defaults": CELL_DEFAULTS,
                                  "pages": pj_pages},
        f"{chapter}.proof.json": {"schema": PROOF_SCHEMA, **head, "cells": proof},
        f"{chapter}.norm.json": {"schema": NORM_SCHEMA, **head, "table": None, "items": norm_items},
        f"{chapter}.zi.json": {"schema": ZI_SCHEMA, **head, "items": zi_items},
    }
    index = anchor_index(files[f"{chapter}.pages.json"])
    if punct is not None:
        files[f"{chapter}.punct.json"] = reattach(punct, index, lines_md)[0]
    if entity is not None:
        files[f"{chapter}.entity.json"] = reattach(entity, index, lines_md)[0]
    return files


# ───────────────────────── guji-format → guji-page ─────────────────────────

def from_guji_format(files: dict[str, Any], chapter: str | None = None) -> tuple[list[dict], dict]:
    """`{文件名: 内容}` → (guji-page v0.2 列表, 原样带回的伴生层 `{punct, entity}`)。

    文本以 lines.md 为准，pages.json 给几何与锚点；两边字数、字元对不上就报错（不静默兜底）。
    proof/norm/zi 缺文件时对应字段为空。
    """
    chapter = chapter or _chapter_of(files)
    md = files[f"{chapter}.lines.md"]
    pj = files[f"{chapter}.pages.json"]
    proof = {c["id"]: c for c in (files.get(f"{chapter}.proof.json") or {}).get("cells", [])}
    norm = (files.get(f"{chapter}.norm.json") or {}).get("items", [])
    zi = (files.get(f"{chapter}.zi.json") or {}).get("items", [])

    toks_by_page: dict[int | None, list[dict]] = {}
    for pg in parse_lines_md(md):
        toks_by_page.setdefault(pg["page"], []).extend(t for ln in pg["lines"] for t in ln["tokens"])
    flat = [t for pjp in pj["pages"] for t in toks_by_page.get(pjp["page"]["index"], [])]
    if len(flat) != pj["n_chars"]:
        raise ValueError(f"lines.md 有 {len(flat)} 字元，pages.json 记 {pj['n_chars']}——两份文件不是同一版")
    zi_by_o = {z["o"]: z for z in zi}

    out = []
    for pjp in pj["pages"]:
        lo, hi = pjp["o"]
        toks = flat[lo:hi]
        text, lacuna, zis = [], [], []
        for i, t in enumerate(toks):
            if t.get("zi") is not None:
                z = zi_by_o.get(lo + i, {})
                text.append(z.get("near") or gp.ZI_NO_NEAR)
                rec = {"i": i}
                key = "desc" if z.get("desc") is not None else "ids"
                rec[key] = t["zi"]
                rec["rel"] = z.get("rel") if z.get("near") else None
                zis.append(rec)
                continue
            text.append(t["t"])
            if t.get("lacuna") or (lo + i) in set(pjp.get("lacuna_extra", [])):
                lacuna.append(i)
        for c in pjp["cells"]:
            s, e = (c["o"], c["o"] + 1) if isinstance(c["o"], int) else tuple(c["o"])
            if "".join(text[s - lo:e - lo]) != c["c"] and not any(lo + k in zi_by_o for k in range(s - lo, e - lo)):
                raise ValueError(f"{pjp['page_id']} 格 {c.get('a')}：pages.json 记「{c['c']}」，"
                                 f"lines.md 是「{''.join(text[s - lo:e - lo])}」")

        cols_by_id = {}
        for c in pjp["columns"]:
            cc = copy.deepcopy(c)
            cc["runs"] = [{"lane": r["lane"], "text": [r["o"][0] - lo, r["o"][1] - lo]} for r in c["runs"]]
            cols_by_id[c["id"]] = cc
        regions = []
        for r in pjp["regions"]:
            rr = {k: v for k, v in r.items() if k != "columns"}
            rr["columns"] = [cols_by_id[cid] for cid in r["columns"]]
            regions.append(rr)

        glyphs = []
        for c in pjp["cells"]:
            s, e = (c["o"], c["o"] + 1) if isinstance(c["o"], int) else tuple(c["o"])
            g = {"id": c["id"], "text": [s - lo, e - lo]}
            if c.get("a") and "col" not in c:
                _, cn, slot, _ = parse_anchor(c["a"])
                g["col"], g["slot"] = f"c{cn}", slot
            for k, v in (pj.get("cell_defaults") or {}).items():
                g[k] = copy.deepcopy(v)
            for k, v in c.items():
                if k in ("id", "a", "o", "c"):
                    continue
                g[k] = v
            if c.get("a") is not None and pj.get("cv_book"):
                g["cv_id"] = f"{pj['cv_book']}:{c['a']}"
            pr = proof.get(c["id"], {})
            for k in PROOF_KEYS:
                if k in pr:
                    g[k] = pr[k]
            glyphs.append(g)

        page = {"schema": gp.SCHEMA_ID, "page_id": pjp["page_id"], "book": pj["book"], "volume": pj["volume"]}
        for k in ("page", "image", "canvas", "producers"):
            if k in pjp:
                page[k] = pjp[k]
        page.update({"text": text, "lacuna": lacuna,
                     "norm": [{"i": n["o"] - lo, **{k: v for k, v in n.items() if k not in ("a", "o", "c")}}
                              for n in norm if lo <= n["o"] < hi],
                     "zi": zis, "regions": regions, "glyphs": glyphs, "marks": pjp.get("marks", [])})
        if pjp.get("warnings"):
            page["warnings"] = pjp["warnings"]
        out.append(page)
    extras = {k: files.get(f"{chapter}.{k}.json") for k in ("punct", "entity")
              if files.get(f"{chapter}.{k}.json") is not None}
    return out, extras


def _chapter_of(files: dict) -> str:
    for name in files:
        if name.endswith(".lines.md"):
            return name[: -len(".lines.md")]
    raise ValueError("没有 *.lines.md")


# ───────────────────────── 锚点索引与伴生层重挂 ─────────────────────────

def anchor_index(pages_json: dict) -> dict[str, dict]:
    """pages.json → `{锚点: {o, c}}`（只收单字格；一格多字的格用不上字间标点）。"""
    idx: dict[str, dict] = {}
    for p in pages_json["pages"]:
        for c in p["cells"]:
            if c.get("a") and isinstance(c["o"], int):
                idx[c["a"]] = {"o": c["o"], "c": c["c"]}
    return idx


def _plain_chars(lines_md: str) -> list[str]:
    return [t["t"] if t.get("zi") is None else ":zi" for pg in parse_lines_md(lines_md)
            for ln in pg["lines"] for t in ln["tokens"]]


def reattach(layer: dict, index: dict[str, dict], lines_md: str) -> tuple[dict, dict]:
    """把 punct.json / entity.json 按锚点挂到当前 lines.md 上：锚点找得到且字对得上 → 用锚点的偏移；
    锚点不在（或是 lines.md 数出来的旧锚点、字对不上）→ 退到原 `char_offset` 并核 `pre_char`。

    返回 `(新 layer, 报告)`。只改偏移字段（`char_offset`、`span.start_offset/end_offset`），其余原样。
    报告 `{by_anchor, by_offset, lost}`：`lost` 是两条路都对不上的条目（交人看，不猜）。
    """
    chars = _plain_chars(lines_md)
    out = copy.deepcopy(layer)
    rep = {"by_anchor": 0, "by_offset": 0, "lost": []}

    def resolve(anchor: str | None, offset: int | None, ch: str | None) -> int | None:
        hit = index.get(anchor) if anchor else None
        if hit is not None and (not ch or hit["c"] == ch):
            rep["by_anchor"] += 1
            return hit["o"]
        if offset is not None and 0 <= offset < len(chars) and (not ch or chars[offset] == ch):
            rep["by_offset"] += 1
            return offset
        return None

    for p in out.get("punctuations", []):
        o = resolve(p.get("anchor"), p.get("char_offset"), p.get("pre_char"))
        if o is None:
            rep["lost"].append({"kind": "punct", "anchor": p.get("anchor"), "pre_char": p.get("pre_char")})
        else:
            p["char_offset"] = o
    for e in out.get("entities", []):
        anc, span = e.get("anchor") or {}, e.get("span") or {}
        txt = e.get("text") or ""
        s = resolve(anc.get("start"), span.get("start_offset"), txt[:1] or None)
        en = resolve(anc.get("end"), (span.get("end_offset") or 0) - 1 if span else None, txt[-1:] or None)
        if s is None or en is None:
            rep["lost"].append({"kind": "entity", "id": e.get("id"), "text": txt})
        else:
            e.setdefault("span", {})["start_offset"] = s
            e["span"]["end_offset"] = en + 1
    return out, rep


# ───────────────────────── 读写 ─────────────────────────

_ROW_LISTS = ("cells", "marks", "columns", "regions", "punctuations", "entities", "items")


def dumps(obj: Any) -> str:
    """JSON：外层缩进，`cells`/`marks`/`columns`/… 这类长列表**一元素一行**（紧凑）——git 按格比对，体积也小。"""
    def enc(o, ind):
        pad = " " * ind
        if isinstance(o, dict):
            if not o:
                return "{}"
            items = []
            for k, v in o.items():
                if k in _ROW_LISTS and isinstance(v, list) and v:
                    rows = ",\n".join(pad + "  " + json.dumps(x, ensure_ascii=False, separators=(",", ":")) for x in v)
                    items.append(f'{pad} {json.dumps(k, ensure_ascii=False)}: [\n{rows}\n{pad} ]')
                else:
                    items.append(f"{pad} {json.dumps(k, ensure_ascii=False)}: {enc(v, ind + 1)}")
            return "{\n" + ",\n".join(items) + "\n" + pad + "}"
        if isinstance(o, list) and o and all(isinstance(x, dict) for x in o):
            return "[\n" + ",\n".join(pad + " " + enc(x, ind + 1) for x in o) + "\n" + pad + "]"
        return json.dumps(o, ensure_ascii=False, separators=(",", ":"))
    return enc(obj, 0) + "\n"


def write_files(files: dict[str, Any], out_dir: Path | str) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, content in files.items():
        p = out / name
        p.write_text(content if isinstance(content, str) else dumps(content), encoding="utf-8")
        paths.append(p)
    return paths


def read_files(paths: Iterable[Path | str]) -> dict[str, Any]:
    files: dict[str, Any] = {}
    for p in map(Path, paths):
        txt = p.read_text(encoding="utf-8")
        files[p.name] = json.loads(txt) if p.suffix == ".json" else txt
    return files
