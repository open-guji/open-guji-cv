# -*- coding: utf-8 -*-
"""自动配页的「逐列无格位」参照类型（`row_segment.page_map_ref: column_text`，2026-11-06，Sheldon 定按文本类型做）。

## 参照分几类、这一类管什么

出一张逐列格位表要回答三件事：这页对参照哪一段（配页）、哪几个字是第 k 列（分列）、字落在第几格（格位）。
参照自带到哪一步，管线就只用图像补剩下的：

- **逐列带格位**（`column_slots`，缺省）：参照每列记了哪几格有字（daizhige 逐列本），表全由参照定，管线只配页
  （`row_segment_pagemap.py` 本体）。
- **逐列无格位**（`column_text`，本模块）：参照是 `#@ 半叶头` ＋ 一行一列的逐列文本（与 align_ref 读的逐列本同一格式），
  只知道每列几个字、哪里是雙行小注，不知道从第几格起。配页比各列字数，格位用本页图像量出来。
- 不分列的参照（只有卷、篇界）先不做（Sheldon 11-06）。

框架里只认文本类型，不认书：新书的参校本先归到一类，转成该类的统一文件格式，册 yaml 只写类型和文件路径。

## 做法

- **格墨**（`ink_grid`）：列窗口（Step2）给的每列左右界行与上下版框之间等分 `n_slots`（册 `chars_per_line`）格，
  每格量墨占比（上下、左右各让出一点，避开界行与格缝），按本页底色自适应二值（`inked`）。不跑切分，一页几十毫秒。
- **配页**（`score_matrix` → `page_align.align_scores`）：每页各列「有墨格的跨度」对参照每个半叶各行的字数
  （雙行小注一对算一格，空格位不算），逐列差 ≤ `COUNT_TOL` 的比例是得分；单调 DP 与殿本配页同一套，
  关掉局部重排和前后对调（满页字数彼此一样，重排只会把次序正常的满页挪乱）。钉位表里本册已有的页当硬约束。
- **定格位**（`page_rows`）：本页有墨的列与参照各行按序 DP 配对（列可跳过：参照没录的印章列；行也可跳过），
  每列取「格数 ＝ 参照字数」的一段连续格，有墨格最多者优先、墨量和次之、偏上再次；段外的墨贴着段（< 2 格）就不出行
  （分不清是字还是框条），少数细字（一、二）量不出墨不要紧，段内允许缺 `n // 4` 格。整列没墨的列出空列 `slots: []`。
  雙行小注格（两半都有字）写进 `notes`，只有右半有字的写进 `half`。

全唐文 005–015 原型（2026-11-06，A22）：与离线表（guji-manager make_qtw_layout，Step4 产物出的表）逐列相同约 96%，
差一格的约 1%（多是低两格的篇题列，离线表按无先验切分的格号，比同页邻列的字低一格；本模块按版框等分，
与邻列对齐）；自动配页 1,800 多页正文页 0 页配错。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

#: 改本模块产出（格位表、配页）口径时加一：开着 column_text 的册 Step3 判过期
ALGO_VERSION = 1
COUNT_TOL = 1              # 配页：一列字数差这么多以内算对上
CELL_MARGIN_Y = 0.12       # 量格墨时每格上下各让出的格高比例（同 page_align）
CELL_MARGIN_X = 0.15       # 左右各让出的列宽比例
INK_THR = 0.05             # 格内墨占比过这条算有墨（纸色深的页按底色抬高）
TEXT_MIN_CELLS = 10        # 有墨格不少于这个算有字页

_LEAVES: dict[tuple, tuple] = {}


def _sig(p: Path) -> tuple:
    st = p.stat()
    return (str(p), st.st_mtime_ns, st.st_size)


def file_sha(p: Path) -> str:
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]


def leaves(path: Path) -> tuple[list[str], dict[str, list[list]]]:
    """逐列文本 → （半叶头按文件次序，{头: 各行的字位单元（不含空格位）}）。空行不算一列（同 align_ref）。
    进程内按文件签名缓存。"""
    from .align_ref_coord import parse_lines
    path = Path(path)
    key = _sig(path)
    if key not in _LEAVES:
        heads: list[str] = []
        raw: dict[str, list[str]] = {}
        cur = None
        for ln in path.read_text(encoding="utf-8").split("\n"):
            if ln.startswith("#@ "):
                cur = ln[3:].strip()
                if cur not in raw:
                    heads.append(cur)
                    raw[cur] = []
                continue
            if cur is not None and ln.strip() and not ln.startswith("#"):
                raw[cur].append(ln)
        units = {}
        for h, lines in raw.items():
            out = []
            for rl in (parse_lines("#@ x\n" + "\n".join(lines)) if lines else []):
                u = [x for x in rl.units if x.kind != "b"]
                if u:
                    out.append(u)
            units[h] = out
        _LEAVES.clear()
        _LEAVES[key] = (heads, units)
    return _LEAVES[key]


def ink_grid(gray: np.ndarray, columns: list[tuple[float, float, float, float]], n_slots: int,
             ink_threshold: int = 128) -> np.ndarray:
    """一页每列每格的墨占比 (列数, n_slots)。`columns` 从右到左每列 (x_left, x_right, 版框上, 版框下)，图像坐标。"""
    h, w = gray.shape[:2]
    b = gray < ink_threshold
    out = np.zeros((len(columns), n_slots), dtype=np.float32)
    for c, (x0, x1, top, bot) in enumerate(columns):
        pitch = (bot - top) / n_slots
        m = max(3, int((x1 - x0) * CELL_MARGIN_X))
        xa, xb = max(0, int(x0) + m), min(w, int(x1) - m)
        if xb <= xa or pitch <= 0:
            continue
        for k in range(n_slots):
            ya = int(top + k * pitch + pitch * CELL_MARGIN_Y)
            yb = int(top + (k + 1) * pitch - pitch * CELL_MARGIN_Y)
            if ya < 0 or yb > h or yb <= ya:
                continue
            out[c, k] = float(b[ya:yb, xa:xb].mean())
    return out


def inked(grid: np.ndarray) -> np.ndarray:
    """墨占比 → 有墨。门槛按本页底色自适应（同 `page_align.binarize`）。"""
    base = min(float(np.percentile(grid, 5)), 0.07) if grid.size else 0.0
    return grid > max(INK_THR, base + 0.045)


def span_counts(b: np.ndarray) -> np.ndarray:
    """各列有墨格的跨度（首末有墨格之间的格数，没墨为 0）：细字量不出墨也不少算。"""
    out = np.zeros(b.shape[0], dtype=np.int64)
    for c in range(b.shape[0]):
        idx = np.nonzero(b[c])[0]
        if len(idx):
            out[c] = idx[-1] - idx[0] + 1
    return out


def count_matrix(heads: list[str], units: dict[str, list[list]], ncol: int) -> np.ndarray:
    """(半叶数, ncol) 各半叶前 ncol 行的字数。"""
    R = np.zeros((len(heads), ncol), dtype=np.int64)
    for i, h in enumerate(heads):
        v = [len(u) for u in units.get(h, [])][:ncol]
        R[i, :len(v)] = v
    return R


def score_matrix(counts: list[np.ndarray | None], R: np.ndarray) -> np.ndarray:
    """(页数, 半叶数) 得分：逐列字数差 ≤ `COUNT_TOL` 的列占比。列数不对的页全 0。"""
    S = np.zeros((len(counts), R.shape[0]), dtype=np.float32)
    for i, c in enumerate(counts):
        if c is None or c.shape[0] != R.shape[1]:
            continue
        S[i] = (np.abs(R - c[None, :]) <= COUNT_TOL).mean(axis=1)
    return S


def choose(good: list[int], n: int, ink: np.ndarray, n_slots: int) -> list[int] | None:
    """本列参照 n 字落在哪 n 格（格号从 1）：有墨格最多、墨量和次之、偏上再次的一段连续格；配不上给 None。"""
    if n <= 0 or n > n_slots:
        return None
    gs = set(good)
    best = None
    for st in range(1, n_slots - n + 2):
        w = range(st, st + n)
        key = (sum(1 for x in w if x in gs), float(sum(ink[x - 1] for x in w)), -st)
        if best is None or key > best[0]:
            best = (key, list(w))
    (k, _, _), keep = best
    # 段内缺墨的格不能太多（细字量不出墨可以；满列或差一格满列的，字数本身就钉住了段，放宽到一半）
    if k < n - max(1, n // 4) and not (n >= n_slots - 1 and k >= n // 2):
        return None
    drop = [x for x in good if x not in keep]
    if drop and (any(min(abs(x - y) for y in keep) < 2 for x in drop)
                 or (len(drop) > 3 and any(min(abs(x - y) for y in keep) < 3 for x in drop))):
        return None
    return keep


def page_rows(book: str, page: int, grid: np.ndarray, lines: list[list], n_slots: int,
              head: str = "") -> list[dict]:
    """一页的格位表行（格式同 `layout_slots.jsonl`）。`grid` 是 `ink_grid`，`lines` 是本页半叶各行的字位单元。"""
    b = inked(grid)
    cols = [(c + 1, [k + 1 for k in np.nonzero(b[c])[0]]) for c in range(b.shape[0])]
    rows = [{"vol": book, "page": page, "col": c, "ref": head, "slots": [], "notes": [], "half": [], "raised": 0}
            for c, good in cols if not good]
    text = [(c, good) for c, good in cols if good]
    A, B = len(text), len(lines)
    INF = 10 ** 9
    cost = [[INF] * (B + 1) for _ in range(A + 1)]
    back: dict[tuple[int, int], tuple[int, int, int, int]] = {}
    cost[0][0] = 0
    ok = {}
    for i in range(A):
        for j in range(B):
            ok[i, j] = choose(text[i][1], len(lines[j]), grid[text[i][0] - 1], n_slots)
    for i in range(A + 1):
        for j in range(B + 1):
            if cost[i][j] >= INF:
                continue
            for di, dj in ((1, 1), (1, 0), (0, 1)):
                if i + di > A or j + dj > B:
                    continue
                c = (0 if ok[i, j] else 3) if di and dj else 4
                if cost[i][j] + c < cost[i + di][j + dj]:
                    cost[i + di][j + dj] = cost[i][j] + c
                    back[i + di, j + dj] = (i, j, di, dj)
    i, j = A, B
    pairs = []
    while (i, j) != (0, 0):
        pi, pj, di, dj = back[i, j]
        if di and dj and ok[pi, pj]:
            pairs.append((text[pi][0], ok[pi, pj], lines[pj]))
        i, j = pi, pj
    for col, keep, u in reversed(pairs):
        rows.append({"vol": book, "page": page, "col": col, "ref": head, "slots": keep,
                     "notes": [s for s, x in zip(keep, u) if x.kind == "n" and x.b],
                     "half": [s for s, x in zip(keep, u) if x.kind == "n" and not x.b], "raised": 0})
    return sorted(rows, key=lambda r: r["col"])


OVERRIDE_SKIP = ("vol", "page", "col", "why", "drop")


def apply_overrides(rows: list[dict], lines: list[dict]) -> list[dict]:
    """人核过的改格（`page_map_overrides`，一行 `{"vol","page","col", 要改的字段…, "why"}`）盖到推出的行上，
    表里没有的列整行补进来；`"drop": true` 删掉这一列（配不准、不要先验的列）。"""
    at = {(r["vol"], r["page"], r["col"]): r for r in rows}
    for o in lines:
        k = (o["vol"], int(o["page"]), int(o["col"]))
        if o.get("drop"):
            at.pop(k, None)
            continue
        r = at.get(k)
        if r is None:
            r = at[k] = {"vol": k[0], "page": k[1], "col": k[2], "ref": "override",
                         "slots": [], "notes": [], "half": [], "raised": 0}
        r.update({f: v for f, v in o.items() if f not in OVERRIDE_SKIP})
    return sorted(at.values(), key=lambda r: (r["page"], r["col"]))


def build(book: str, pages: list[int], grids: list[np.ndarray | None], ref_path: Path,
          pins: dict[int, str | None], strategy: str, n_slots: int, ncol: int, skip=()) -> dict:
    """本册配页＋格位表（`row_segment_pagemap.ensure` 存进 `_page_map.json`）。

    `grids` 各页 `ink_grid`（列数不对或没列窗口为 None）；`pins` 本册钉位 {页: 半叶头或 None}；
    `strategy` 为 `pins` 时只按钉位出表、不配页。`skip`：册配置 `reference_profile` 声明没有逐列参照的页，
    当钉成 null（不配、不出表），也不算进正文页；空时结果与原来逐位相同。"""
    skip = set(skip)
    if skip:
        pins = {**pins, **{p: None for p in pages if p in skip}}
    from ..utils.page_align import align_scores
    heads, units = leaves(ref_path)
    hi = {h: i for i, h in enumerate(heads)}
    rows, layout = [], []
    if strategy == "pins":
        match = {p: (pins.get(p), "pin", 1.0, True) for p in pages if pins.get(p) in hi}
        empty_h = np.array([not units.get(h) for h in heads], dtype=bool)
    else:
        R = count_matrix(heads, units, ncol)
        counts = [span_counts(inked(g)) if g is not None and g.shape[0] == ncol else None for g in grids]
        S = score_matrix(counts, R)
        empty = R.sum(axis=1) == 0
        cover = np.zeros(len(heads), dtype=bool)
        # 钉了位的页直接按钉位，不进 DP（钉位可能不按文件次序，如参照末尾补录的目录页；钉成 null 的页不配）
        free = [k for k, p in enumerate(pages) if p not in pins]
        match = {p: (h, "pin", 1.0, True) for p, h in pins.items() if p in set(pages) and h in hi}
        res = (align_scores([pages[k] for k in free], S[free], empty, cover, reorder=False, swap=False)
               if free and len(heads) else None)
        for p, mt in (res.matches.items() if res is not None else ()):
            if mt.half is not None:
                match[p] = (heads[mt.half], mt.how, float(mt.score), bool(mt.confident))
        empty_h = empty
    gi = dict(zip(pages, grids))
    for p in pages:
        g = gi.get(p)
        mt = match.get(p)
        row = {"vol": book, "page": p, "head": None, "how": "none", "score": 0.0, "confident": False}
        if mt is not None:
            h, how, sc, conf = mt
            row.update(head=h, how=how, score=round(sc, 3), confident=conf)
            if conf and g is not None and g.shape[0] == ncol:
                layout.extend(page_rows(book, p, g, units.get(h, []), n_slots, head=h))
        rows.append(row)
    text = [p for p in pages if gi.get(p) is not None and int(inked(gi[p]).sum()) >= TEXT_MIN_CELLS
            and p not in skip]
    # 没配上的有字页：前后两个配上的页之间，参照里没有空出来的有字半叶 ⇒ 参照根本没录这页（目录页、牌记、插图说明），
    # 只报不拦；中间空着有字半叶（该配却没配上）才算配不上
    seq = [(p, hi[match[p][0]]) for p in pages if p in match]
    used = {h for _p, h in seq}
    no_ref = []
    for p in text:
        if p in match:
            continue
        a = max((h for q, h in seq if q < p), default=None)
        b = min((h for q, h in seq if q > p), default=None)
        if a is None or b is None:
            no_ref.append(p) if (a is None) != (b is None) else None
            continue
        lo_, hi_ = min(a, b), max(a, b)
        if not any(not empty_h[h] and h not in used for h in range(lo_ + 1, hi_)):
            no_ref.append(p)
    bad = [p for p in text if p not in no_ref and (p not in match or not match[p][3])]
    sc = [m[2] for p, m in match.items() if units.get(m[0])]
    summary = {"ref": "column_text", "pages": len(pages), "mapped": len(match), "text_pages": len(text),
               "mean_score": round(float(np.mean(sc)), 4) if sc else 0.0, "bad_text_pages": bad,
               "unsure_pages": [p for p, m in match.items() if not m[3]],
               "unmapped_pages": [p for p in pages if p not in match], "no_ref_pages": no_ref,
               "columns": len(layout), "pages_with_layout": len({r["page"] for r in layout}),
               "half_span": [min((m[0] for m in match.values()), key=lambda h: hi[h]),
                             max((m[0] for m in match.values()), key=lambda h: hi[h])] if match else []}
    if skip:
        summary["ref_skip_pages"] = sorted(p for p in skip if p in set(pages))
    return {"rows": rows, "layout": layout, "summary": summary}
