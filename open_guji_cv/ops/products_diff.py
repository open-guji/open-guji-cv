"""前后对比：两份产物（重跑前／重跑后、基线／变体）逐列比，出摘要、列清单和看图页。

`guji products diff <册> --a <产物根> [--b <产物根>] [--pages …] [--out 目录] [--images N]`

只读产物，不跑任何 Step，不进任何 Step 的 `code_deps`。和 `guji exp report` 的分工：

- `exp report` 按**格 id** 对齐，只比 seed_admit，要标签，回答「开关开不开」；
- 这里按**位置**对齐，切分变了（格号漂移）也能比，不要标签，回答「这次重跑到底改了什么、人审格多了还是少了」。

对齐口径：同一（页、列）里，两边的格按 `bbox_page`（原图规范空间）的 IoU 贪心配对，
IoU ≥ 0.5 算同一格；配不上的是「新切出」或「切没了」。格的状态取 seed_admit（没有就只比切分）：
`admit`（机器放行）、`human`（人裁）、`excluded`（排除）、`review`（送人审），口径同 `exp/compare.cell_state`。

列分类（按先后取第一个成立的）：

| 类 | 判据 |
|---|---|
| `cells` | 格数变了，或有配不上的格（切分变了） |
| `text`  | 格一一对上，有格的字变了（两边都有字） |
| `state` | 字没变，有格的状态变了（放行↔送审等） |
| `geom`  | 字、状态都没变，格框动了超过 2px |
| `same`  | 都没变（不列出） |

人审率 = review 格 / 全部格（同 close-check R3 的分子分母口径：只数 char 格）。
"""
from __future__ import annotations

import html
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ..exp.compare import cell_state

IOU_MIN = 0.5
GEOM_TOL = 2.0
KINDS = ("cells", "text", "state", "geom")


@dataclass
class Cell:
    id: str
    bbox: tuple[float, float, float, float] | None
    idx: int
    state: str = "none"          # 没有 seed_admit 产物时
    char: str = ""


@dataclass
class ColDiff:
    page: int
    col: int
    kind: str
    a: list[Cell]
    b: list[Cell]
    pairs: list[tuple[int, int]] = field(default_factory=list)   # (a 下标, b 下标)

    def text(self, side: str) -> str:
        return "".join(_show(c) for c in (self.a if side == "a" else self.b))

    def n_review(self, side: str) -> int:
        return sum(c.state == "review" for c in (self.a if side == "a" else self.b))


def _show(c: Cell) -> str:
    ch = c.char or "□"
    return f"[{ch}]" if c.state == "review" else ch


def _load(root: Path, book: str, step: str, page: int) -> dict | None:
    f = Path(root) / book / step / f"p{page:04d}.json"
    if not f.is_file():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def page_cells(root: Path, book: str, page: int) -> dict[int, list[Cell]] | None:
    """一页的格，按列：{列号: [Cell…]}（读序）。没有 cell_shrink 产物 → None。"""
    ci = _load(root, book, "cell_shrink", page)
    if ci is None:
        return None
    sa = (_load(root, book, "seed_admit", page) or {}).get("seed_admit") or {}
    rec = {r["id"]: r for col in sa.get("columns") or [] for r in col.get("chars") or []}
    out: dict[int, list[Cell]] = {}
    for col in (ci.get("char_index") or {}).get("columns") or []:
        if not col.get("ok", True):
            out.setdefault(int(col["col"]), [])
            continue
        cells = []
        for r in col.get("chars") or []:
            if r.get("cell_type", "char") != "char":
                continue
            bb = r.get("bbox_page")
            c = Cell(r["id"], tuple(float(v) for v in bb) if bb else None, int(r.get("idx", len(cells))))
            s = rec.get(r["id"])
            if s is not None:
                c.state, c.char = cell_state(s), s.get("char") or ""
            cells.append(c)
        cells.sort(key=lambda c: c.idx)
        out[int(col["col"])] = cells
    return out


def _iou(p, q) -> float:
    if not p or not q:
        return 0.0
    x0, y0 = max(p[0], q[0]), max(p[1], q[1])
    x1, y1 = min(p[2], q[2]), min(p[3], q[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    if inter <= 0:
        return 0.0
    area = (p[2] - p[0]) * (p[3] - p[1]) + (q[2] - q[0]) * (q[3] - q[1]) - inter
    return inter / area if area > 0 else 0.0


def match(a: list[Cell], b: list[Cell]) -> list[tuple[int, int]]:
    """IoU 贪心配对（大的先配），返回按 a 下标排序的 (i, j)。"""
    cand = sorted(((_iou(x.bbox, y.bbox), i, j) for i, x in enumerate(a) for j, y in enumerate(b)
                   if x.bbox and y.bbox and abs(x.bbox[1] - y.bbox[1]) < 4 * max(1.0, x.bbox[3] - x.bbox[1])),
                  reverse=True)
    ua, ub, out = set(), set(), []
    for v, i, j in cand:
        if v < IOU_MIN:
            break
        if i in ua or j in ub:
            continue
        ua.add(i)
        ub.add(j)
        out.append((i, j))
    return sorted(out)


def classify(a: list[Cell], b: list[Cell], pairs: list[tuple[int, int]]) -> str:
    if len(a) != len(b) or len(pairs) != len(a):
        return "cells"
    if any(a[i].char and b[j].char and a[i].char != b[j].char for i, j in pairs):
        return "text"
    if any(a[i].state != b[j].state or a[i].char != b[j].char for i, j in pairs):
        return "state"
    if any(max(abs(u - v) for u, v in zip(a[i].bbox, b[j].bbox)) > GEOM_TOL for i, j in pairs):
        return "geom"
    return "same"


def diff_book(a_root: Path, b_root: Path, book: str, pages: list[int]) -> dict:
    """→ {summary, columns: [ColDiff…]（不含 same）, missing: {a: [页], b: [页]}}。"""
    tot = {s: Counter() for s in ("a", "b")}
    flips: Counter = Counter()
    kinds: Counter = Counter()
    cols: list[ColDiff] = []
    missing = {"a": [], "b": []}
    n_pages = 0
    for pg in pages:
        pa, pb = page_cells(a_root, book, pg), page_cells(b_root, book, pg)
        if pa is None or pb is None:
            if pa is None:
                missing["a"].append(pg)
            if pb is None:
                missing["b"].append(pg)
            continue
        n_pages += 1
        for c in sorted(set(pa) | set(pb)):
            a, b = pa.get(c, []), pb.get(c, [])
            for side, cs in (("a", a), ("b", b)):
                tot[side]["cells"] += len(cs)
                tot[side].update(x.state for x in cs)
            pairs = match(a, b)
            for i, j in pairs:
                sa, sb = a[i].state, b[j].state
                if sa != sb:
                    flips[f"{sa}→{sb}"] += 1
                elif sa in ("admit", "human") and a[i].char and b[j].char and a[i].char != b[j].char:
                    flips["放行字变"] += 1
            pa_set, pb_set = {i for i, _ in pairs}, {j for _, j in pairs}
            flips["切没了"] += len(a) - len(pa_set)
            flips["新切出"] += len(b) - len(pb_set)
            flips["切没了·原是送审"] += sum(1 for i, x in enumerate(a) if i not in pa_set and x.state == "review")
            flips["新切出·送审"] += sum(1 for j, x in enumerate(b) if j not in pb_set and x.state == "review")
            k = classify(a, b, pairs)
            kinds[k] += 1
            if k != "same":
                cols.append(ColDiff(pg, c, k, a, b, pairs))
    summ = {"book": book, "pages": n_pages, "columns": dict(kinds),
            "a": _rates(tot["a"]), "b": _rates(tot["b"]), "flips": {k: v for k, v in flips.items() if v}}
    return {"summary": summ, "columns": cols, "missing": missing}


def _rates(c: Counter) -> dict:
    n = c["cells"]
    return {"cells": n, "review": c["review"], "admit": c["admit"], "human": c["human"],
            "excluded": c["excluded"], "no_seed_admit": c["none"],
            "review_rate": round(c["review"] / n, 5) if n and c["none"] < n else None}


def _impact(cd: ColDiff) -> tuple:
    return (KINDS.index(cd.kind), -abs(cd.n_review("b") - cd.n_review("a")), cd.page, cd.col)


def write_report(res: dict, out: Path, a_label: str, b_label: str) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    s = res["summary"]
    cols = sorted(res["columns"], key=_impact)
    (out / "summary.json").write_text(json.dumps({**s, "missing": res["missing"],
                                                  "a_root": a_label, "b_root": b_label},
                                                 ensure_ascii=False, indent=1), encoding="utf-8")
    with open(out / "columns.tsv", "w", encoding="utf-8") as f:
        f.write("page\tcol\tkind\tn_a\tn_b\treview_a\treview_b\ttext_a\ttext_b\n")
        for cd in cols:
            f.write(f"{cd.page}\t{cd.col}\t{cd.kind}\t{len(cd.a)}\t{len(cd.b)}\t{cd.n_review('a')}\t"
                    f"{cd.n_review('b')}\t{cd.text('a')}\t{cd.text('b')}\n")
    a, b = s["a"], s["b"]

    def pct(x):
        return "—" if x is None else f"{x * 100:.2f}%"
    lines = [f"# 前后对比 {s['book']}", "",
             f"- A（前）：`{a_label}`", f"- B（后）：`{b_label}`",
             f"- 两边都有的页：{s['pages']}" + (f"；只有一边有的页 A 缺 {len(res['missing']['a'])}、B 缺 {len(res['missing']['b'])}"
                                         if res["missing"]["a"] or res["missing"]["b"] else ""), "",
             "| | 格 | 送审 | 人审率 | 机器放行 | 人裁 | 排除 |", "|---|---|---|---|---|---|---|",
             f"| A | {a['cells']} | {a['review']} | {pct(a['review_rate'])} | {a['admit']} | {a['human']} | {a['excluded']} |",
             f"| B | {b['cells']} | {b['review']} | {pct(b['review_rate'])} | {b['admit']} | {b['human']} | {b['excluded']} |",
             *([""] + ["（有一边没有 seed_admit 产物：人审率不可比，只比切分。）"]
               if a["review_rate"] is None or b["review_rate"] is None else []),
             "", "**变了的列**：" + ("、".join(f"{k} {s['columns'].get(k, 0)}" for k in KINDS)) +
             f"（没变 {s['columns'].get('same', 0)}）", "",
             "**逐格**：" + ("、".join(f"{k} {v}" for k, v in sorted(s["flips"].items())) or "无"), "",
             "「放行字变」是两边都放行、字不同的格：重跑最要看的风险，逐个看图。",
             "列清单见 `columns.tsv`（送审格写成 [字]，□ 是没有拟定字）。"]
    if (out / "index.html").exists():
        lines.append("看图：`index.html`。")
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out / "report.md"


def render_images(res: dict, out: Path, raw_page, n: int, a_label: str, b_label: str) -> int:
    """前 n 个变了的列：原图上 A 红框、B 绿框并排，送审格虚线加粗；出 PNG 和 index.html。"""
    import cv2
    import numpy as np
    cols = sorted(res["columns"], key=_impact)[:n]
    img_dir = out / "cols"
    img_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    cache: dict[int, np.ndarray] = {}
    for cd in cols:
        if cd.page not in cache:
            cache.clear()
            cache[cd.page] = raw_page(cd.page)
        im = cache[cd.page]
        boxes = [c.bbox for c in cd.a + cd.b if c.bbox]
        if im is None or not boxes:
            continue
        x0 = max(0, int(min(bb[0] for bb in boxes)) - 12)
        x1 = min(im.shape[1], int(max(bb[2] for bb in boxes)) + 12)
        y0 = max(0, int(min(bb[1] for bb in boxes)) - 12)
        y1 = min(im.shape[0], int(max(bb[3] for bb in boxes)) + 12)
        crop = im[y0:y1, x0:x1]
        crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR) if crop.ndim == 2 else crop.copy()
        tiles = []
        for cells, colr in ((cd.a, (40, 40, 220)), (cd.b, (30, 150, 30))):
            t = crop.copy()
            for c in cells:
                if not c.bbox:
                    continue
                p0 = (int(c.bbox[0]) - x0, int(c.bbox[1]) - y0)
                p1 = (int(c.bbox[2]) - x0, int(c.bbox[3]) - y0)
                cv2.rectangle(t, p0, p1, colr, 4 if c.state == "review" else 2)
            tiles.append(t)
        gap = np.full((crop.shape[0], 10, 3), 255, np.uint8)
        name = f"p{cd.page:04d}c{cd.col:02d}.png"
        cv2.imwrite(str(img_dir / name), np.hstack([tiles[0], gap, tiles[1]]))
        rows.append(f"<tr><td>{cd.page}:{cd.col}<br>{cd.kind}<br>送审 {cd.n_review('a')}→{cd.n_review('b')}</td>"
                    f"<td><img src='cols/{name}'></td><td class=t>A {html.escape(cd.text('a'))}<br><br>"
                    f"B {html.escape(cd.text('b'))}</td></tr>")
    page = ("<!doctype html><meta charset=utf-8><title>前后对比</title><style>"
            "body{font-family:sans-serif;margin:16px}td{vertical-align:top;padding:6px;border-bottom:1px solid #ccc}"
            "img{max-height:900px}.t{writing-mode:vertical-rl;font-size:18px;max-height:900px}</style>"
            f"<p>左 A（红）<code>{html.escape(a_label)}</code>，右 B（绿）<code>{html.escape(b_label)}</code>；"
            "粗框是送审格，文字里 [字] 是送审。</p><table>" + "".join(rows) + "</table>")
    (out / "index.html").write_text(page, encoding="utf-8")
    return len(rows)
