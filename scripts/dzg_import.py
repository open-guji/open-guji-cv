# -*- coding: utf-8 -*-
"""daizhige 逐列整理本导入（overview#195 P 道）。

    python scripts/dzg_import.py download   [--ws DIR] [--max N]
    python scripts/dzg_import.py manifest   [--ws DIR]
    python scripts/dzg_import.py convert    [--ws DIR]
    python scripts/dzg_import.py map        [--ws DIR] [--vols 01,03]
    python scripts/dzg_import.py compare    [--ws DIR] [--samples 10]

`--ws` 缺省读 `GUJI_WORKSPACE`（四庫總目书目录那一层）。

## 源文件是什么（2026-09-28 实测）

`https://sikuquanshu.daizhige.net/data/NNNN.jsonl` 是**整部文淵閣四庫**逐冊的
维基文库 ProofreadPage 校对结果，一行一条记录：

- **一条 ＝ 影印本一栏 ＝ 原书一个整叶**：`cols` 通常 18 列，`no` 0–8 是前半叶、
  9–17 是后半叶（`geom.ncol=9` 指半叶列数）。`page` 形如 `1-100b`，a/b 是影印本的
  上下栏，**不是**半叶。卷端牌记、插图是 `cover: true`、`cols` 为空的记录。
- 列 `runs[]`：`text` 带 `start`（列首空几格；`-1` 是出格抬头）；`note` 是双行小注，
  `r`/`l` 两行各是 `[[偏移, 文字], ...]`，偏移是**小注内部**的格位。
- `pua_map` 给出本条里 PUA 码位 → 真字；映不上的 PUA 本工具记作 `〓`。
- **0001–0005 是總目**（0005 尾部附《四庫抽燬書提要》），0006 起是別的书。
  所以 `download` 收到**第一个不含總目的文件就停**，不一路试到 404（那是 1500 冊）。

## 我们一页 ＝ daizhige 一个半叶（列一一对应）

vol01 用字形库 instances、vol01–10 用人读锚点（`corpus/daizhige/anchors.json`，
每冊 4–9 处「第 p 页首列文字」）实测：半叶顺序与我们页序一一对应，只有三类错位——

1. daizhige 卷端牌记（`cover`，占 2 个空半叶），刻本没有；
2. 卷末空半叶，刻本有时有（全空页）有时没有；
3. 刻本冊中卷端前的书签宽图（vol04 p129，宽 > 3500 px），daizhige 没有。

`map` 把锚点当硬约束，锚点之间用 DP 配「有字页 ↔ 有字半叶」、「空页 ↔ 空半叶」，
正文页配不上（我们多）或有字半叶配不上（我们缺页）都记罚分并报出来。
空白判定只看墨量（`ink`），少字页（整页只有「本也」两字）会被判成空，
所以「空页 ↔ 少字半叶」也允许，代价略高。

## 产物（都在 ws `corpus/`，原始 jsonl 一个字节不改）

- `daizhige/NNNN.jsonl` ＋ `daizhige/manifest.json`（文件号、冊、卷起止、条数、sha256）
- `siku_daizhige.txt`：引擎能读的逐列整理本，一行 ＝ 一列（`line_is_column: true`）：
  列首 `start` 个全角空格、段间空格按格位补齐、小注写成 `<右行|左行>`
  （与 `render/guji_markdown.py` 同一记法）。每个半叶前一行 `#@ <id> <page> h<0|1>`
  （纯 ASCII，`report/witness.py` 整行剥 `#`，`align_ref` 只取汉字，都不受影响）。
- `daizhige/columns.jsonl`：无损的逐列结构（含 `start=-1`、小注分段偏移），给 D 道按坐标用。
- `daizhige/page_map.jsonl` ＋ `page_map_summary.json`：我们 volNN 第 p 页 → 半叶。
- `daizhige/compare_guangpan.json`：与光盘版逐列比对的数与抽样。
"""
from __future__ import annotations

import argparse
import ast
import difflib
import hashlib
import json
import os
import random
import re
import sys
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

URL = "https://sikuquanshu.daizhige.net/data/{:04d}.jsonl"
#: 總目（1）与附在 0005 尾部的四庫抽燬書提要（2）。
ZONGMU_BOOK_IDS = {1, 2}
FULL = "　"
UNMAPPED = "〓"
NCOL = 9
VOLS = [f"{i:02d}" for i in range(1, 11)]

_HAN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿\U00020000-\U0003134f]")


def is_han(ch: str) -> bool:
    return bool(_HAN_RE.fullmatch(ch))


def han_only(s: str) -> str:
    return "".join(_HAN_RE.findall(s))


def _is_pua(ch: str) -> bool:
    cp = ord(ch)
    return 0xE000 <= cp <= 0xF8FF or 0xF0000 <= cp <= 0x10FFFD


# ── 读源文件 ───────────────────────────────────────────────

def _norm_field(v):
    """个别补丁记录把字段存成了 Python repr 字符串，读回来。"""
    if isinstance(v, str) and v[:1] in "[{" :
        try:
            return ast.literal_eval(v)
        except (ValueError, SyntaxError):
            return v
    return v


def load_records(path: Path) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            r = json.loads(line)
            for k in ("cols", "geom", "roll", "book", "pua_map", "images"):
                if k in r:
                    r[k] = _norm_field(r[k])
            out.append(r)
    return out


def fix_pua(s: str, pua_map: dict | None) -> tuple[str, int]:
    """PUA → 真字（按本条 `pua_map`），映不上的记 `〓`。返回（新串，映不上的个数）。"""
    if not s:
        return s, 0
    pm = pua_map or {}
    out, miss = [], 0
    for ch in s:
        if _is_pua(ch):
            real = pm.get(f"U+{ord(ch):04X}")
            if real:
                out.append(real)
            else:
                out.append(UNMAPPED)
                miss += 1
        else:
            out.append(ch)
    return "".join(out), miss


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


def _fix_col(col: dict, pua_map) -> tuple[dict, int]:
    miss = 0
    runs = []
    for run in col.get("runs", []):
        run = dict(run)
        if run.get("t") == "text":
            run["s"], m = fix_pua(run.get("s", ""), pua_map)
            miss += m
        elif run.get("t") == "note":
            for side in ("r", "l"):
                segs = []
                for off, s in run.get(side, []):
                    s, m = fix_pua(s, pua_map)
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
                        fc, m = _fix_col(c, r.get("pua_map"))
                        mine.append(fc)
                        miss += m
                halves.append(Half(len(halves), f.name, r["id"], str(r["page"]), side,
                                   roll, book, bool(r.get("cover")), mine, miss))
    return halves


# ── 一列的两种写法 ────────────────────────────────────────

def _note_line(segs) -> str:
    out, pos = [], 0
    for off, s in segs:
        if off > pos:
            out.append(FULL * (off - pos))
            pos = off
        out.append(s)
        pos += len(s)
    return "".join(out)


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


def column_line(col: dict) -> str:
    """引擎用的一行：格位用全角空格补齐，小注 `<右|左>`。

    `start=-1`（出格抬头）不补空格——txt 里表达不了负格位，无损信息在 columns.jsonl。
    """
    out, cur = [], 0
    for run in col.get("runs", []):
        start = run.get("start", cur)
        if start is not None and start > cur:
            out.append(FULL * (start - cur))
            cur = start
        elif start is not None and start >= 0:
            cur = max(cur, start)
        if run.get("t") == "note":
            r, l = _note_line(run.get("r", [])), _note_line(run.get("l", []))
            out.append(f"<{r}|{l}>")
            cur += max(len(r), len(l))
        else:
            s = run.get("s", "")
            out.append(s)
            cur += len(s)
    return "".join(out)


# ── download / manifest ──────────────────────────────────

def cmd_download(ws: Path, max_n: int = 60) -> None:
    d = ws / "corpus" / "daizhige"
    d.mkdir(parents=True, exist_ok=True)
    for i in range(1, max_n + 1):
        url = URL.format(i)
        try:
            with urllib.request.urlopen(url, timeout=120) as resp:
                data = resp.read()
        except urllib.error.HTTPError as e:
            print(f"{i:04d}: HTTP {e.code}，停")
            break
        books = set()
        for line in data.decode("utf-8").splitlines():
            if line.strip():
                b = _norm_field(json.loads(line).get("book"))
                if isinstance(b, dict):
                    books.add(b.get("id"))
        if not books & ZONGMU_BOOK_IDS:
            print(f"{i:04d}: 已不是總目（book {sorted(books)[:5]}），停")
            break
        (d / f"{i:04d}.jsonl").write_bytes(data)
        print(f"{i:04d}: {len(data)} bytes")
    cmd_manifest(ws)


def source_files(ws: Path) -> list[Path]:
    return sorted((ws / "corpus" / "daizhige").glob("[0-9][0-9][0-9][0-9].jsonl"))


def cmd_manifest(ws: Path) -> dict:
    items = []
    for f in source_files(ws):
        recs = load_records(f)
        rolls = [r["roll"]["name"] for r in recs if isinstance(r.get("roll"), dict)]
        books = Counter(r["book"]["name"] for r in recs if isinstance(r.get("book"), dict))
        items.append({
            "file": f.name, "url": URL.format(int(f.stem)),
            "ce": int(f.stem), "records": len(recs), "halves": 2 * len(recs),
            "cover_records": sum(1 for r in recs if r.get("cover")),
            "roll_first": rolls[0] if rolls else None, "roll_last": rolls[-1] if rolls else None,
            "page_first": str(recs[0]["page"]), "page_last": str(recs[-1]["page"]),
            "books": dict(books), "bytes": f.stat().st_size,
            "sha256": hashlib.sha256(f.read_bytes()).hexdigest(),
        })
    man = {"source": "https://sikuquanshu.daizhige.net/data/",
           "note": "文淵閣四庫全書 維基文庫 ProofreadPage 逐列校對本；0001–0005 為總目，"
                   "0006 起為別書，不收。原文件未改動一個字節。",
           "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
           "files": items}
    out = ws / "corpus" / "daizhige" / "manifest.json"
    out.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"manifest: {len(items)} 个文件 → {out}")
    return man


# ── convert ──────────────────────────────────────────────

TXT_NAME = "siku_daizhige.txt"
TXT_HEADER = (
    "# daizhige 逐列整理本（文淵閣四庫全書總目，sikuquanshu.daizhige.net/data/0001–0005.jsonl，"
    "即維基文庫 ProofreadPage 逐列校對本）。一行＝一列（line_is_column），列首全角空格＝start 格數，"
    "雙行小注寫作<右行|左行>，映不上的PUA缺字記〓。每個半葉前一行「#@ 記錄id 頁 h0/h1」。"
    "由 open-guji-cv scripts/dzg_import.py convert 生成，勿手改。"
)


def convert(halves: list[Half]) -> tuple[list[str], list[dict], dict]:
    lines = [TXT_HEADER]
    cols_out = []
    stats = Counter()
    for h in halves:
        if not h.cols:
            stats["empty_halves"] += 1
            continue
        lines.append(f"#@ {h.rid} {h.page} h{h.side}")
        stats["halves"] += 1
        stats["unmapped_pua"] += h.unmapped
        for c in h.cols:
            ln = column_line(c)
            lines.append(ln)
            stats["columns"] += 1
            stats["han"] += len(han_only(ln))
            starts = [r.get("start") for r in c["runs"]]
            if starts and starts[0] is not None and starts[0] < 0:
                stats["raised_columns"] += 1
            cols_out.append({"half": h.idx, "id": h.rid, "page": h.page, "side": h.side,
                             "col": c["no"] % NCOL, "roll": h.roll, "runs": c["runs"],
                             "line": ln})
    return lines, cols_out, dict(stats)


def cmd_convert(ws: Path) -> None:
    halves = build_halves(source_files(ws))
    lines, cols, stats = convert(halves)
    (ws / "corpus" / TXT_NAME).write_text("\n".join(lines) + "\n", encoding="utf-8")
    with open(ws / "corpus" / "daizhige" / "columns.jsonl", "w", encoding="utf-8") as f:
        for c in cols:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(json.dumps(stats, ensure_ascii=False))


# ── map：我们的页 → 半叶 ───────────────────────────────────

BLANK_INK = 0.02
LOW_INK = 0.035
WIDE_PX = 3500
SHORT_CHARS = 6


def page_ink(path: Path) -> tuple[int, int, float]:
    """（宽，高，去掉界栏竖线后中心区的墨量）。只用来分「有字/空」。"""
    import numpy as np
    from PIL import Image
    im = Image.open(path).convert("L")
    w, h = im.size
    a = np.asarray(im.resize((w // 4, h // 4))) < 128
    hh, ww = a.shape
    c = a[int(hh * .2):int(hh * .8), int(ww * .15):int(ww * .85)]
    c = c[:, c.mean(0) < .5]
    return w, h, float(c.mean()) if c.size else 0.0


def page_kind(p: int, w: int, ink: float) -> str:
    if p == 1:
        return "cover"
    if w > WIDE_PX:
        return "wide"
    if ink < BLANK_INK:
        return "blank"
    if ink < LOW_INK:
        return "low"
    return "text"


def half_kind(h: Half) -> str:
    n = h.nchars
    return "empty" if n == 0 else ("short" if n <= SHORT_CHARS else "full")


INF = float("inf")
#: 配对代价。None ＝ 不许配。
PAIR_COST = {
    ("text", "full"): 0, ("text", "short"): 0,
    ("low", "full"): .3, ("low", "short"): 0, ("low", "empty"): .3,
    ("blank", "empty"): 0, ("blank", "short"): .5,
}
SKIP_PAGE = {"text": 5, "low": 1, "blank": .2, "wide": 0, "cover": 0}
SKIP_HALF = {"full": 5, "short": 1, "empty": .2}


def align_segment(pages: list[tuple[int, str]], hs: list[tuple[int, str]],
                  free_tail: bool = False) -> tuple[list[tuple[int, int]], float]:
    """编辑距离式 DP：`pages`＝[(页, kind)]，`hs`＝[(半叶 idx, kind)]。
    返回配上的 [(页, 半叶)] 与总代价。`free_tail` 时多出来的尾部半叶不计罚。"""
    n, m = len(pages), len(hs)
    D = [[INF] * (m + 1) for _ in range(n + 1)]
    B = [[None] * (m + 1) for _ in range(n + 1)]
    D[0][0] = 0
    for i in range(n + 1):
        for j in range(m + 1):
            d = D[i][j]
            if d == INF:
                continue
            if i < n and j < m:
                c = PAIR_COST.get((pages[i][1], hs[j][1]))
                if c is not None and d + c < D[i + 1][j + 1]:
                    D[i + 1][j + 1], B[i + 1][j + 1] = d + c, (i, j, "pair")
            if i < n:
                c = d + SKIP_PAGE[pages[i][1]]
                if c < D[i + 1][j]:
                    D[i + 1][j], B[i + 1][j] = c, (i, j, "skip_page")
            if j < m:
                c = d + SKIP_HALF[hs[j][1]]
                if c < D[i][j + 1]:
                    D[i][j + 1], B[i][j + 1] = c, (i, j, "skip_half")
    j_end = min(range(m + 1), key=lambda j: D[n][j]) if free_tail else m
    pairs, i, j = [], n, j_end
    while (i, j) != (0, 0):
        pi, pj, op = B[i][j]
        if op == "pair":
            pairs.append((pages[pi][0], hs[pj][0]))
        i, j = pi, pj
    return pairs[::-1], D[n][j_end]


def resolve_anchor(halves: list[Half], snippet: str, expect: int | None) -> int:
    """锚点文字 → 半叶 idx。`=` 开头要求整列相等，否则子串。多命中取离 `expect` 最近的。"""
    exact = snippet.startswith("=")
    s = snippet.lstrip("=")
    hits = sorted({h.idx for h in halves for c in h.cols
                   if (column_plain(c) == s if exact else s in column_plain(c))})
    if not hits:
        raise ValueError(f"锚点找不到：{snippet}")
    if expect is None:
        if len(hits) > 1:
            raise ValueError(f"首锚点不唯一：{snippet} → {hits[:5]}")
        return hits[0]
    return min(hits, key=lambda i: (abs(i - expect), i))


def map_volume(vol: str, halves: list[Half], anchors: list, pages: dict[int, tuple[int, int, float]]):
    """一冊：锚点 ＋ 段内 DP → [(页, 半叶 idx 或 None, 怎么来的)]。"""
    kinds = {p: page_kind(p, pages[p][0], pages[p][2]) for p in pages}
    last_page = max(pages)
    fixed: list[tuple[int, int]] = []
    for p, snip in anchors:
        expect = fixed[-1][1] + (p - fixed[-1][0]) if fixed else None
        fixed.append((p, resolve_anchor(halves, snip, expect)))
    fixed.sort()
    result: dict[int, tuple[int | None, str]] = {p: (h, "anchor") for p, h in fixed}
    cost_total = 0.0
    segs = list(zip(fixed, fixed[1:])) + [(fixed[-1], (last_page + 1, None))]
    for (pa, ha), (pb, hb) in segs:
        tail = hb is None
        hb_ = min(len(halves), ha + 1 + (pb - pa) + 12) if tail else hb
        ps = [(p, kinds[p]) for p in range(pa + 1, pb)]
        hs = [(i, half_kind(halves[i])) for i in range(ha + 1, hb_)]
        pairs, cost = align_segment(ps, hs, free_tail=tail)
        cost_total += cost
        got = dict(pairs)
        for p, _ in ps:
            result[p] = (got.get(p), "dp")
    # 首锚点前（封面、书签页）
    for p in range(1, fixed[0][0]):
        result[p] = (None, "front")
    rows = []
    used = set()
    for p in sorted(result):
        h, how = result[p]
        row = {"vol": f"vol{vol}", "page": p, "kind": kinds[p], "ink": round(pages[p][2], 4),
               "how": how, "half": h}
        if h is not None:
            hf = halves[h]
            used.add(h)
            row.update({"dzg_id": hf.rid, "dzg_page": hf.page, "side": hf.side,
                        "roll": hf.roll, "dzg_kind": half_kind(hf), "dzg_chars": hf.nchars})
        rows.append(row)
    lo = fixed[0][1]
    hi = max(used) if used else lo
    missing = [halves[i] for i in range(lo, hi + 1) if i not in used and half_kind(halves[i]) != "empty"]
    text_unmapped = [r["page"] for r in rows if r["half"] is None and r["kind"] in ("text", "low")
                     and r["how"] != "front"]
    summary = {
        "vol": f"vol{vol}", "pages": last_page,
        "text_pages": sum(1 for r in rows if r["kind"] in ("text", "low") and r["how"] != "front"),
        "mapped": sum(1 for r in rows if r["half"] is not None),
        "mapped_to_text_half": sum(1 for r in rows if r["half"] is not None and r["dzg_kind"] != "empty"),
        "our_text_pages_without_source": text_unmapped,
        "dzg_halves_span": [halves[lo].rid + f"h{halves[lo].side}", halves[hi].rid + f"h{halves[hi].side}"],
        "dzg_page_span": [halves[lo].page, halves[hi].page],
        "rolls": sorted({halves[i].roll for i in range(lo, hi + 1) if halves[i].roll},
                        key=lambda r: [x.roll for x in halves].index(r)),
        "dzg_text_halves_missing_in_our_scan": [f"{h.rid} {h.page} h{h.side} ({h.nchars}字)" for h in missing],
        "offsets": sorted(Counter(r["half"] - r["page"] for r in rows if r["half"] is not None).items()),
        "dp_cost": round(cost_total, 2),
        "wide_pages": [r["page"] for r in rows if r["kind"] == "wide"],
        "blank_pages": [r["page"] for r in rows if r["kind"] == "blank"],
    }
    return rows, summary


def cmd_map(ws: Path, vols: list[str]) -> None:
    halves = build_halves(source_files(ws))
    anchors = json.loads((ws / "corpus" / "daizhige" / "anchors.json").read_text(encoding="utf-8"))
    all_rows, sums = [], []
    for v in vols:
        d = ws / "data_full" / "zongmu" / f"vol{v}"
        pages = {int(f.stem): page_ink(f) for f in d.glob("*.png") if f.stem.isdigit()}
        rows, summ = map_volume(v, halves, anchors[f"vol{v}"], pages)
        all_rows += rows
        sums.append(summ)
        print(json.dumps({k: summ[k] for k in ("vol", "pages", "text_pages", "mapped_to_text_half",
                                               "our_text_pages_without_source", "offsets")},
                         ensure_ascii=False))
        for x in summ["dzg_text_halves_missing_in_our_scan"]:
            print("   我们缺：", x)
    out = ws / "corpus" / "daizhige"
    with open(out / "page_map.jsonl", "w", encoding="utf-8") as f:
        for r in all_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (out / "page_map_summary.json").write_text(json.dumps(sums, ensure_ascii=False, indent=1) + "\n",
                                               encoding="utf-8")


# ── compare：对光盘版 ─────────────────────────────────────

GUANGPAN = "zongmu_wenyuange_wikisource.txt"
#: 卷端题。两边同出一源，题里的毛病也一样（「巻」、卷一丢了「一」），所以
#: 两边都按题行切段、按顺序配对，不靠 `roll` 字段也不靠卷名字面相等。
_ROLL_RE = re.compile(r"^欽定四庫全書總目[卷巻]")


def _stream(lines: list[tuple[str, dict]]) -> tuple[str, list[int], list[dict]]:
    """[(行, 元信息)] → (汉字流, 每字所属行号, 行元信息)。"""
    s, owner = [], []
    for k, (ln, _) in enumerate(lines):
        for ch in han_only(ln):
            s.append(ch)
            owner.append(k)
    return "".join(s), owner, [m for _, m in lines]


def split_rolls(lines: list[tuple[str, dict]]) -> list[tuple[str, list]]:
    """[(行, 元信息)] → [(题, 行段)]；第一个题之前的归 `(卷前)`。"""
    out: list[tuple[str, list]] = [("(卷前)", [])]
    for ln, meta in lines:
        h = han_only(ln)
        if not h:
            continue
        if len(h) <= 16 and _ROLL_RE.match(h):
            out.append((h, []))
        out[-1][1].append((ln, meta))
    return [x for x in out if x[1]]


def guangpan_lines(path: Path) -> list[tuple[str, dict]]:
    return [(ln, {"line": no})
            for no, ln in enumerate(path.read_text(encoding="utf-8").split("\n"), 1)
            if not ln.startswith("#")]


def dzg_lines(halves: list[Half]) -> list[tuple[str, dict]]:
    return [(column_plain(c), {"half": h.idx, "id": h.rid, "page": h.page,
                               "side": h.side, "col": c["no"] % NCOL,
                               "notes": [han_only("".join(t for _, t in r.get("r", []) + r.get("l", [])))
                                         for r in c["runs"] if r.get("t") == "note"]})
            for h in halves for c in h.cols]


def classify(a: str, b: str, vm) -> str:
    """一处字差异的类别（a＝光盘版，b＝daizhige）。"""
    if not a:
        return "dzg多字"
    if not b:
        return "dzg少字"
    if UNMAPPED in b:
        return "dzg缺字〓"
    if len(a) == len(b) == 1 and vm is not None and vm.semantic(a) == vm.semantic(b):
        return "异体"
    return "字不同"


def compare_roll(a_lines, b_lines, vm):
    A, a_owner, a_meta = _stream(a_lines)
    B, b_owner, b_meta = _stream(b_lines)
    sm = difflib.SequenceMatcher(None, A, B, autojunk=False)
    b2a = [None] * len(B)
    diffs = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(j2 - j1):
                b2a[j1 + k] = i1 + k
            continue
        if op == "replace" and (i2 - i1) == (j2 - j1):
            for k in range(i2 - i1):
                diffs.append((i1 + k, i1 + k + 1, j1 + k, j1 + k + 1))
        else:
            diffs.append((i1, i2, j1, j2))
    # 列边界：b 列首尾对到 a 行首尾
    a_first = {}
    a_last = {}
    for pos, k in enumerate(a_owner):
        a_first.setdefault(k, pos)
        a_last[k] = pos
    a_starts = set(a_first.values())
    a_ends = set(a_last.values())
    b_first, b_last = {}, {}
    for pos, k in enumerate(b_owner):
        b_first.setdefault(k, pos)
        b_last[k] = pos
    cols = Counter()
    for k in b_first:
        s, e = b2a[b_first[k]], b2a[b_last[k]]
        cols["columns"] += 1
        # 列首／列尾字本身是 dzg 多出来的（光盘版丢了小注）就对不上位置，分开计
        if s is None or e is None:
            cols["unmapped_edge"] += 1
        hs, he = s is not None and s in a_starts, e is not None and e in a_ends
        cols["start_hit"] += hs
        cols["end_hit"] += he
        cols["both_hit"] += hs and he
    out = []
    for i1, i2, j1, j2 in diffs:
        a, b = A[i1:i2], B[j1:j2]
        cat = classify(a, b, vm)
        bk = b_owner[j1] if j1 < len(B) else b_owner[-1]
        if cat == "dzg多字":
            # 多出来的是不是一段小注（光盘版那份抓取丢夹注的老毛病）
            notes = b_meta[bk].get("notes") or []
            cat = "光盘缺小注" if any(b in n or n in b for n in notes if n) else "光盘缺正文"
        if max(len(a), len(b)) > 20:
            cat += "(>20字)"
        ak = a_owner[i1] if i1 < len(A) else a_owner[-1]
        out.append({"cat": cat, "guangpan": a, "dzg": b,
                    "ctx_guangpan": A[max(0, i1 - 6):i2 + 6], "ctx_dzg": B[max(0, j1 - 6):j2 + 6],
                    "n": max(len(a), len(b)),
                    "dzg_at": {k: v for k, v in b_meta[bk].items() if k != "notes"},
                    "guangpan_line": a_meta[ak]["line"]})
    return cols, out, len(A), len(B), sm.ratio()


def cmd_compare(ws: Path, n_samples: int = 10) -> None:
    halves = build_halves(source_files(ws))
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from open_guji_cv.clustering.variants import VariantMap
        vm = VariantMap.load()
    except Exception as e:  # noqa: BLE001 —— 没有异体表只是少一类
        print("VariantMap 装不上，异体不单列：", e)
        vm = None
    gp = split_rolls(guangpan_lines(ws / "corpus" / GUANGPAN))
    dz = split_rolls(dzg_lines(halves))
    cols_t, diffs, lens = Counter(), [], Counter()
    per_roll = {}
    title_mismatch = []
    tsm = difflib.SequenceMatcher(None, [t for t, _ in gp], [t for t, _ in dz], autojunk=False)
    pairs = []
    for op, i1, i2, j1, j2 in tsm.get_opcodes():
        if op == "equal" or (op == "replace" and i2 - i1 == j2 - j1):
            pairs += list(zip(range(i1, i2), range(j1, j2)))
        else:
            title_mismatch.append([[t for t, _ in gp[i1:i2]], [t for t, _ in dz[j1:j2]]])
    for i, j in pairs:
        (tg, a_lines), (td, b_lines) = gp[i], dz[j]
        if tg != td:
            title_mismatch.append([tg, td])
        cols, ds, la, lb, ratio = compare_roll(a_lines, b_lines, vm)
        cols_t.update(cols)
        diffs += [dict(d, roll=td) for d in ds]
        lens["guangpan_han"] += la
        lens["dzg_han"] += lb
        per_roll[td] = {"ratio": round(ratio, 4), "columns": cols["columns"], "both_hit": cols["both_hit"],
                        "diffs": len(ds)}
    # page_map 反查：落在我们 vol01–10 哪一页
    inv = {}
    pm = ws / "corpus" / "daizhige" / "page_map.jsonl"
    if pm.exists():
        for ln in pm.read_text(encoding="utf-8").splitlines():
            row = json.loads(ln)
            if row.get("half") is not None:
                inv[row["half"]] = (row["vol"], row["page"])
    cats = Counter(d["cat"] for d in diffs)
    chars = Counter()
    for d in diffs:
        chars[d["cat"]] += d["n"]
    rng = random.Random(195)
    samples = {}
    for c in cats:
        pool = [d for d in diffs if d["cat"] == c]
        # 优先抽落在我们十冊里的（能对刻本图核），不够再补
        ours = [d for d in pool if d["dzg_at"]["half"] in inv]
        pick = rng.sample(ours, min(n_samples, len(ours)))
        if len(pick) < n_samples:
            rest = [d for d in pool if d not in pick]
            pick += rng.sample(rest, min(n_samples - len(pick), len(rest)))
        for d in pick:
            if d["dzg_at"]["half"] in inv:
                d["our_page"] = "%s:%d" % inv[d["dzg_at"]["half"]]
        samples[c] = pick
    res = {
        "rolls_compared": len(pairs), "rolls_guangpan": len(gp), "rolls_dzg": len(dz),
        "title_mismatch": title_mismatch,
        "han": dict(lens),
        "columns": dict(cols_t),
        "column_rates": {k: round(cols_t[k] / cols_t["columns"], 4)
                         for k in ("start_hit", "end_hit", "both_hit")} if cols_t["columns"] else {},
        "diff_sites": dict(cats), "diff_chars": dict(chars),
        "per_roll": per_roll, "samples": samples,
    }
    out = ws / "corpus" / "daizhige" / "compare_guangpan.json"
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: res[k] for k in ("rolls_compared", "han", "columns", "column_rates",
                                           "diff_sites", "diff_chars")}, ensure_ascii=False, indent=1))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["download", "manifest", "convert", "map", "compare"])
    ap.add_argument("--ws", default=os.environ.get("GUJI_WORKSPACE"))
    ap.add_argument("--max", type=int, default=60)
    ap.add_argument("--vols", default=",".join(VOLS))
    ap.add_argument("--samples", type=int, default=10)
    a = ap.parse_args(argv)
    if not a.ws:
        ap.error("要 --ws 或 GUJI_WORKSPACE（四庫總目书目录）")
    ws = Path(a.ws)
    if a.cmd == "download":
        cmd_download(ws, a.max)
    elif a.cmd == "manifest":
        cmd_manifest(ws)
    elif a.cmd == "convert":
        cmd_convert(ws)
    elif a.cmd == "map":
        cmd_map(ws, [v.zfill(2) for v in a.vols.split(",")])
    else:
        cmd_compare(ws, a.samples)
    return 0


if __name__ == "__main__":
    sys.exit(main())
