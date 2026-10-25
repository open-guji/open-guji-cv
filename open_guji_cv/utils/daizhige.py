# -*- coding: utf-8 -*-
"""daizhige 逐列本（四庫總目）的读取：源记录 → 半叶 → 每列格位。

`scripts/dzg_import.py`（导入、页对照）、`scripts/dzg_layout.py`（格位表）和 Step3 自动配页
（`utils/page_align.py`、`steps/row_segment_pagemap.py`）共用这一份，口径只有一处：

- 一条源记录 ＝ 原书一个整叶，`cols` 的 `no` 0–8 是前半叶、9–17 是后半叶；我们一页 ＝ 一个半叶，
  列号 ＝ `no % 9 + 1`。
- 格位：daizhige 的 pos（`start` 起算，-1/-2 出格）→ 我们的 slot：pos≥0 → pos+1，pos<0 → pos。
- PUA 按本条 `pua_map` 换真字，映不上的、以及 `glyphs` 登记的缺字占位码记 `〓`。

源文件格式与来历见 `scripts/dzg_import.py` 模块头。
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

NCOL = 9
UNMAPPED = "〓"
#: 只有这么几个字的半叶算「少字」（卷末「皆附存目」之类），配页与报告里和满页分开
SHORT_CHARS = 6

_HAN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0003134f]")


def han_only(s: str) -> str:
    return "".join(_HAN_RE.findall(s))


def _is_pua(ch: str) -> bool:
    cp = ord(ch)
    return 0xE000 <= cp <= 0xF8FF or 0xF0000 <= cp <= 0x10FFFD


def _norm_field(v):
    """个别补丁记录把字段存成了 Python repr 字符串，读回来。"""
    if isinstance(v, str) and v[:1] in "[{":
        try:
            return ast.literal_eval(v)
        except (ValueError, SyntaxError):
            return v
    return v


def source_files(dz_dir: Path) -> list[Path]:
    """`corpus/daizhige/` 下的源文件 0001–0005.jsonl（总目）。"""
    return sorted(Path(dz_dir).glob("[0-9][0-9][0-9][0-9].jsonl"))


def load_records(path: Path) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            for k in ("cols", "geom", "roll", "book", "pua_map", "images", "glyphs"):
                if k in r:
                    r[k] = _norm_field(r[k])
            out.append(r)
    return out


def fix_pua(s: str, pua_map: dict | None, glyphs: dict | None = None) -> tuple[str, int]:
    """PUA → 真字（按本条 `pua_map`），映不上的记 `〓`；本条 `glyphs` 登记的缺字图占位码也记 `〓`。
    返回（新串，记成 `〓` 的个数）。"""
    if not s:
        return s, 0
    pm = pua_map or {}
    gl = glyphs if isinstance(glyphs, dict) else {}
    out, miss = [], 0
    for ch in s:
        if f"U+{ord(ch):04X}" in gl:
            out.append(UNMAPPED)
            miss += 1
        elif _is_pua(ch):
            real = pm.get(f"U+{ord(ch):04X}")
            if real:
                out.append(real)
            else:
                out.append(UNMAPPED)
                miss += 1
        else:
            out.append(ch)
    return "".join(out), miss


def column_plain(col: dict) -> str:
    """读序串：正文照录，小注先右行后左行，不带空格。用于检索与比对。"""
    out = []
    for run in col.get("runs", []):
        if run.get("t") == "note":
            out.append("".join(s for _, s in run.get("r", [])))
            out.append("".join(s for _, s in run.get("l", [])))
        else:
            out.append(run.get("s", ""))
    return "".join(out)


@dataclass
class Half:
    """一个半叶 ＝ 我们刻本的一页。`idx` 是 0001–0005 全局顺序号。"""
    idx: int
    file: str
    rid: str
    page: str
    side: int                       # 0 前半叶（列 0–8），1 后半叶（列 9–17）
    roll: str | None
    book: int | None
    cover: bool
    cols: list = field(default_factory=list)   # 本半叶的列（已按 no 排、PUA 已修）
    unmapped: int = 0

    @property
    def nchars(self) -> int:
        return sum(len(han_only(column_plain(c))) for c in self.cols)

    @property
    def key(self) -> str:
        """格位表、钉页表里认半叶用的写法：`0001-3561h0`。"""
        return f"{self.rid}h{self.side}"


def half_kind(h: Half) -> str:
    n = h.nchars
    return "empty" if n == 0 else ("short" if n <= SHORT_CHARS else "full")


def _fix_col(col: dict, pua_map, glyphs=None) -> tuple[dict, int]:
    miss = 0
    runs = []
    for run in col.get("runs", []):
        run = dict(run)
        if run.get("t") == "text":
            run["s"], m = fix_pua(run.get("s", ""), pua_map, glyphs)
            miss += m
        elif run.get("t") == "note":
            for side in ("r", "l"):
                segs = []
                for off, s in run.get(side, []):
                    s, m = fix_pua(s, pua_map, glyphs)
                    miss += m
                    segs.append([off, s])
                run[side] = segs
        runs.append(run)
    return {"no": col["no"], "runs": runs}, miss


def build_halves(files: list[Path]) -> list[Half]:
    halves: list[Half] = []
    for f in files:
        for r in load_records(f):
            cols = r.get("cols") if isinstance(r.get("cols"), list) else []
            roll = r["roll"].get("name") if isinstance(r.get("roll"), dict) else None
            book = r["book"].get("id") if isinstance(r.get("book"), dict) else None
            for side in (0, 1):
                mine, miss = [], 0
                for c in sorted(cols, key=lambda c: c["no"]):
                    if (c["no"] >= NCOL) == bool(side):
                        fc, m = _fix_col(c, r.get("pua_map"), r.get("glyphs"))
                        mine.append(fc)
                        miss += m
                halves.append(Half(len(halves), f.name, r["id"], str(r["page"]), side,
                                   roll, book, bool(r.get("cover")), mine, miss))
    return halves


# ── 一列的格位 ────────────────────────────────────────────

def slot_of(pos: int) -> int:
    return pos + 1 if pos >= 0 else pos


def column_layout(col: dict) -> dict | None:
    """daizhige 一列 → {slots, notes, half, raised}；空列 None。"""
    body, a, b = set(), set(), set()
    for r in col.get("runs", []):
        if r.get("t") == "text":
            body |= {slot_of(r["start"] + i) for i in range(len(r.get("s", "")))}
        elif r.get("t") == "note":
            for side, acc in (("r", a), ("l", b)):
                for off, s in r.get(side, []):
                    acc |= {slot_of(r["start"] + off + i) for i in range(len(s))}
    slots = body | a | b
    if not slots:
        return None
    neg = [s for s in slots if s < 0]
    return {"slots": sorted(slots), "notes": sorted(a & b), "half": sorted(a ^ b),
            "raised": -min(neg) if neg else 0}


def half_layout_rows(h: Half, vol: str, page: int) -> list[dict]:
    """一个半叶配给我们 `vol` 第 `page` 页后的格位表行（空列不写），格式同 `layout_slots.jsonl`。"""
    out = []
    for c in h.cols:
        lay = column_layout(c)
        if lay:
            out.append({"vol": vol, "page": page, "col": c["no"] % NCOL + 1, "dzg": h.key, **lay})
    return out


LAYOUT_FIELDS = ("slots", "notes", "half", "raised")


def apply_overrides(rows: list[dict], path: Path, vols: set[str] | None = None) -> list[dict]:
    """人核过的覆盖行（`layout_overrides.jsonl`：册/页/列 + 要改的字段 + why）盖到推出的行上；
    表里没有的列整行补进来。"""
    if not Path(path).exists():
        return rows
    at = {(r["vol"], r["page"], r["col"]): r for r in rows}
    for ln in Path(path).read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        o = json.loads(ln)
        if vols and o["vol"] not in vols:
            continue
        k = (o["vol"], o["page"], o["col"])
        r = at.get(k)
        if r is None:
            r = at[k] = {"vol": k[0], "page": k[1], "col": k[2], "dzg": "override",
                         "slots": [], "notes": [], "half": [], "raised": 0}
            rows.append(r)
        r.update({f: o[f] for f in LAYOUT_FIELDS if f in o})
    return rows
