"""S 类待审成因归因（只读产物包，A22-3，2026-11-04）。

切分领域长期计划（ai-team `domain/CV/A22/切分领域长期计划与总览.md`）第四节第 2 步：S 类待审
（`seg_page_unaligned` S01／`seg_col_unaligned` S02／`col_width_out_of_band` S03／`seg_defect` S04）是按数量判的，
大半不是切分错。本工具把每格 S 类待审按**包里已有的事实**拆开，告诉各书项目先往哪个方向查，不用每次找 A22 代查。

**只读、不改任何东西**：不写待审单、不改 `pending_reason`（统计口径仍是 `pending_reason`，这里只是它下面的
「成因旗」，不是新的待审原因）、不在任何 Step 的 `code_deps` 里。

每格按下表**从上往下取第一条命中的**作主成因（页上的事实先于列上的事实）；其余命中的也列在「全部旗」里：

| 成因 | 从哪读 | 先怎么办 |
|---|---|---|
| known 已答复页 | `--known` 给的页表 | 照已有结论处理，不再派 |
| pinned 钉页 | align_ref `note` 含「钉页」 | 人审（整理本错页），派单扣掉 |
| page_kind 特殊页型 | border_detect_gate `page_type` 不是 body | 人标页型（册 yaml `page_kinds`），整页人审／跳过 |
| ref_none 整理本∅ | align_ref 没有一个字对上（chars、coord 都空） | 对位，不是切分；抽看一页确认切得对 |
| grid_ok 格位对得上 | 每列都做成了坐标对位、没有退回的列、有字的格 ≥95% 配上整理本字 | 格数格位与整理本一致，多半不是切分：认字／字形库／图源断烂，转 A23／A24；抽看一页（切线偏半字这种看不出） |
| seal_stain 疑假大印 | seal_detect 有 `stain`／`frame` 印 | 调参 `seal_detect.stain_pages`，从 seal_detect 重跑 |
| seal 印章页 | seal_detect 有别的印 | 看图（印章页切分） |
| invert 反色带 | invert_detect 有 band | 控制台反色带送审 |
| page_gate 页未过闸 | border_detect_gate／row_segment_gate 未放行 | 看图：Step1/3 整页失败 |
| col_grid 列网异常 | border_detect_gate 旗 `col_width_out_of_band`、列数≠版式列数 | 看图；单页 `vline_overrides`，成批找 A22 |
| col_gate 列未过闸 | row_segment_gate 列 `reject`、row_segment 列 `error` | 看图：Step3 这列失败 |
| slot_short 格少于整理本 | align_ref `coord_fallback` 「格数少于整理本字数」 | 挤格（人标 22 格）或漏切，看图 |
| slot_shift 错位一格 | `coord_fallback`「错位」 | 看图：多半首字漏切／多切一格 |
| slot_count 格数离群 | 本列 `n_body_slots` ≠ 本页众数 | 看图 |
| row_height 格高离群 | 本列有格高 < 0.6 或 > 1.5 倍 `period` | 看图（写本字大小不一常见，殿本少见） |
| seg_defect 切坏格 | 本格 `pending_reason`＝seg_defect | 细分见 `pending_reason_detail` |
| coord_other 对位冲突 | `coord_fallback` 其他原因 | 对位，不是切分 |
| none 包里看不出 | 以上都没中 | **要看图**：真切分错多在这里，也可能是认字／对位 |

用法::

    python -m open_guji_cv.review.seg_causes vol44 vol56 --products <产物根> [--out 目录]
    python -m open_guji_cv.review.seg_causes 02 03 --products <史記产物根> --pending 02.pending.json …
    python -m open_guji_cv.review.seg_causes 07 --products <全唐文产物根> --known 已答复.tsv --all

- 不给 `--pending`：按出单同一套判法（`review/reasons.py`）从包里现算每格的 `pending_reason`；
  复审格等只在单上的格算不到，数会比单上略少。给了就用单上的 `pending_reason`（格号对不上包的照样计数，旗为空）。
- `--known`：TSV，每行「页号<TAB>结论」，页号写 `vol44:236` 或 `236`（单册时）。
- `--all`：不只 S 类，所有待审格都归因（看非切分原因的格里有没有藏着切分问题）。
- `--out`：写 `汇总.md`、`逐页.tsv`、`逐格.tsv`；不给只在屏幕上打汇总。
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

#: S 类待审原因（pending_reason 值）
S_REASONS = ("seg_page_unaligned", "seg_col_unaligned", "col_width_out_of_band", "seg_defect")

#: 成因 → (显示名, 先怎么办)。顺序即判定优先级。
CAUSES: dict[str, tuple[str, str]] = {
    "known": ("已答复页", "照已有结论处理，不再派"),
    "pinned": ("钉页", "人审（整理本错页），派单扣掉"),
    "page_kind": ("特殊页型", "人标页型 page_kinds，整页人审／跳过"),
    "ref_none": ("整理本∅", "对位，不是切分；抽看一页确认切得对"),
    "grid_ok": ("格位对得上", "格数格位与整理本一致，多半不是切分：认字／字形库／图源，转 A23／A24；抽看一页"),
    "seal_stain": ("疑假大印", "调参 seal_detect.stain_pages，从 seal_detect 重跑"),
    "seal": ("印章页", "看图（印章页切分）"),
    "invert": ("反色带", "控制台反色带送审"),
    "page_gate": ("页未过闸", "看图：Step1/3 整页失败"),
    "col_grid": ("列网异常", "看图；单页 vline_overrides，成批找 A22"),
    "col_gate": ("列未过闸", "看图：Step3 这列失败"),
    "slot_short": ("格少于整理本", "挤格（人标 22 格）或漏切，看图"),
    "slot_shift": ("错位一格", "看图：首字漏切／多切一格"),
    "slot_count": ("格数离群", "看图"),
    "row_height": ("格高离群", "看图（写本常见）"),
    "seg_defect": ("切坏格", "细分见 pending_reason_detail"),
    "coord_other": ("对位冲突", "对位，不是切分"),
    "none": ("包里看不出", "要看图：真切分错多在这里"),
}
PAGE_CAUSES = ("known", "pinned", "page_kind", "ref_none", "grid_ok", "seal_stain", "seal", "invert", "page_gate", "col_grid")
COL_CAUSES = ("col_gate", "slot_short", "slot_shift", "slot_count", "row_height")

#: 格位对得上：有字的格里配上整理本字（坐标对位）的比例
GRID_OK_FRAC = 0.95
#: 格高离群：本列内部格（去掉首末格）高 < ROW_LOW 或 > ROW_HIGH 倍本列 period
ROW_LOW, ROW_HIGH = 0.6, 1.5


@dataclass
class PageFacts:
    flags: dict[str, str] = field(default_factory=dict)              # 页级成因 → 细节
    cols: dict[int, dict[str, str]] = field(default_factory=dict)     # 列号 → {成因: 细节}


def _layer(root: Path, step: str, page: int, key: str) -> dict | None:
    try:
        return json.loads((root / step / f"p{page:04d}.json").read_text(encoding="utf-8"))[key]
    except (OSError, KeyError, ValueError):
        return None


def page_facts(root: Path, page: int, known: str | None = None) -> PageFacts:
    """一页的成因旗。`root` 是一册的产物目录（<产物根>/<册>）。读不到的步就当没有这条事实。"""
    pf = PageFacts()
    f = pf.flags
    if known:
        f["known"] = known
    ar = _layer(root, "align_ref", page, "align_ref") or {}
    if "钉页" in (ar.get("note") or ""):
        f["pinned"] = ar["note"][ar["note"].find("钉页"):][:30]
    bg = _layer(root, "border_detect_gate", page, "border_detect_gate_manifest") or {}
    if bg.get("page_type") and bg["page_type"] != "body":
        f["page_kind"] = f"{bg['page_type']}/{bg.get('page_type_policy') or ''}"
    if ar and not ar.get("chars") and not ar.get("coord"):
        f["ref_none"] = (ar.get("note") or "")[:30]
    coord_cols = {int(x) for x in ar.get("coord_cols") or []}
    n_ref = sum(1 for x in ar.get("coord") or [] if x.get("ref_char"))
    ci = (_layer(root, "cell_shrink", page, "char_index") or {}).get("columns") or []
    used = {int(c["col"]) for c in ci if any(r.get("patch_key") and r.get("cell_type") != "empty" for r in c.get("chars") or [])}
    n_ink = sum(1 for c in ci for r in c.get("chars") or [] if r.get("patch_key") and r.get("cell_type") != "empty")
    if used and used <= coord_cols and not ar.get("coord_fallback") and n_ref >= GRID_OK_FRAC * n_ink:
        f["grid_ok"] = f"{n_ref}/{n_ink} 格配上整理本字"
    seals = (_layer(root, "seal_detect", page, "seals") or {}).get("seals") or []
    stain = [s for s in seals if s.get("kind") == "stain" and s.get("source") == "frame"]
    if stain:
        f["seal_stain"] = f"{len(stain)} 处 stain/frame"
    other = [s for s in seals if s not in stain]
    if other:
        f["seal"] = "、".join(sorted({f"{s.get('kind')}/{s.get('source')}" for s in other}))
    bands = (_layer(root, "invert_detect", page, "inverted") or {}).get("bands") or []
    if bands:
        f["invert"] = f"{len(bands)} 条"
    rg = _layer(root, "row_segment_gate", page, "row_segment_gate_manifest") or {}
    rej = [str(x) for x in (bg.get("reject") or []) + (rg.get("reject") or [])]
    if (bg and not bg.get("admitted", True)) or (rg and not rg.get("admitted", True)) or rej:
        f["page_gate"] = (rej[0] if rej else "未放行")[:40]
    grid = []
    if any(str(x).startswith("col_width_out_of_band") for x in bg.get("flags") or []):
        grid.append("列宽出带")
    if bg.get("n_cols") and bg.get("expected_cols") and bg["n_cols"] != bg["expected_cols"]:
        grid.append(f"{bg['n_cols']} 列≠版式 {bg['expected_cols']}")
    if grid:
        f["col_grid"] = "、".join(grid)

    cols: dict[int, dict[str, str]] = defaultdict(dict)
    for c in rg.get("columns") or []:
        if c.get("reject"):
            cols[int(c["col"])]["col_gate"] = str(c["reject"][0])[:30]
    for k, why in (ar.get("coord_fallback") or {}).items():
        why = str(why)
        key = "slot_short" if why.startswith("格数少于整理本字数") else "slot_shift" if why.startswith("错位") else "coord_other"
        cols[int(k)][key] = why[:30]
    rs = (_layer(root, "row_segment", page, "cells") or {}).get("columns") or []
    mode = Counter(c.get("n_body_slots") for c in rs if c.get("n_body_slots")).most_common(1)
    for c in rs:
        col = int(c["col"])
        if c.get("error"):
            cols[col].setdefault("col_gate", str(c["error"])[:30])
        n = c.get("n_body_slots")
        if mode and n and n != mode[0][0]:
            cols[col]["slot_count"] = f"{n} 格（本页多为 {mode[0][0]}）"
        b, p = c.get("boundaries") or [], c.get("period") or 0
        hs = [(y2 - y1) / p for y1, y2 in pairwise(b)][1:-1] if p and len(b) > 3 else []
        odd = [h for h in hs if h < ROW_LOW or h > ROW_HIGH]
        if odd:
            cols[col]["row_height"] = f"{len(odd)} 格 {min(odd):.2f}–{max(odd):.2f}×"
    pf.cols = dict(cols)
    return pf


def split_cell(cid: str) -> tuple[str | None, int, int]:
    """格号 → (册或 None, 页, 列)。认 `vol44:236:1:3`、`236:1:3a`。"""
    parts = cid.split(":")
    book = parts[0] if len(parts) >= 4 else None
    p, c = parts[-3], parts[-2]
    return book, int(p), int(c)


def attribute(pf: PageFacts, col: int, reason: str) -> tuple[str, list[str]]:
    """一格 → (主成因, 全部旗)。"""
    hits = [k for k in PAGE_CAUSES if k in pf.flags]
    cf = pf.cols.get(col, {})
    hits += [k for k in COL_CAUSES if k in cf]
    if reason == "seg_defect":
        hits.append("seg_defect")
    if "coord_other" in cf:
        hits.append("coord_other")
    return (hits[0] if hits else "none"), hits


def _detail(pf: PageFacts, col: int, k: str) -> str:
    return pf.flags.get(k) or pf.cols.get(col, {}).get(k, "")


def pending_from_pack(products: Path, book: str) -> list[tuple[str, str, str]]:
    """从包现算待审格的 pending_reason（同出单判法）→ [(格号, 原因, 细节)]。"""
    from . import reasons as R
    cells = list(R.book_cells(products, book).values())
    ctx = R.build_context(cells)
    out = []
    for c in cells:
        r = R.classify(c, ctx)
        out.append((c.id, r.value, R.detail_of(r, c)))
    return out


def pending_from_lists(paths: list[Path], book: str | None) -> list[tuple[str, str, str]]:
    out = []
    for p in paths:
        doc = json.loads(Path(p).read_text(encoding="utf-8"))
        for x in doc.get("cells", []):
            cid = x["cell"]
            if cid.count(":") < 3 and book:
                cid = f"{book}:{cid}"
            out.append((cid, x.get("pending_reason") or "unknown", x.get("pending_reason_detail") or ""))
    return out


def load_known(path: Path | None, books: list[str]) -> dict[tuple[str, int], str]:
    if not path:
        return {}
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        k, _, why = line.partition("\t")
        k = k.strip()
        if ":" in k:
            b, p = k.rsplit(":", 1)
        elif len(books) == 1:
            b, p = books[0], k
        else:
            raise SystemExit(f"--known 多册时页号要带册：{k!r}")
        out[(b, int(p))] = why.strip() or "已答复"
    return out


def run(books: list[str], products: Path, pending: list[Path] | None = None,
        known: dict | None = None, all_reasons: bool = False) -> list[dict]:
    """返回逐格归因行。"""
    known = known or {}
    rows: list[dict] = []
    for book in books:
        cells = pending_from_lists(pending, book if len(books) == 1 else None) if pending else pending_from_pack(products, book)
        cache: dict[int, PageFacts] = {}
        for cid, reason, rdetail in cells:
            b, page, col = split_cell(cid)
            if (b or book) != book or (not all_reasons and reason not in S_REASONS):
                continue
            if page not in cache:
                cache[page] = page_facts(products / book, page, known.get((book, page)))
            pf = cache[page]
            cause, hits = attribute(pf, col, reason)
            rows.append({"册": book, "格号": cid if cid.startswith(book + ":") else f"{book}:{cid}",
                         "页": page, "列": col, "pending_reason": reason, "pending_reason_detail": rdetail,
                         "成因": cause, "成因名": CAUSES[cause][0], "细节": _detail(pf, col, cause),
                         "全部旗": ",".join(hits)})
    return rows


def by_page(rows: list[dict]) -> list[dict]:
    g: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        g[(r["册"], r["页"])].append(r)
    out = []
    for (b, p), rs in sorted(g.items()):
        rc = Counter(r["pending_reason"] for r in rs)
        cc = Counter(r["成因"] for r in rs)
        flags = sorted({f for r in rs for f in r["全部旗"].split(",") if f}, key=list(CAUSES).index)
        out.append({"册": b, "页": p, "格数": len(rs),
                    "pending_reason": " ".join(f"{k}={n}" for k, n in rc.most_common()),
                    "主成因": " ".join(f"{k}={n}" for k, n in cc.most_common()),
                    "全部旗": ",".join(flags),
                    "细节": "；".join(sorted({f"{r['成因名']}:{r['细节']}" for r in rs if r["细节"]}))[:200]})
    return out


def summary_md(rows: list[dict], books: list[str], source: str) -> str:
    pages = by_page(rows)
    lines = [f"# S 类待审成因归因（{'、'.join(books)}）", "",
             f"- 待审来源：{source}；共 {len(rows)} 格、{len(pages)} 页。",
             "- 统计口径是 `pending_reason`；「成因」是从包里读的事实，按优先级取第一条（见 `review/seg_causes.py`）。", "",
             "## 按 pending_reason", "", "| pending_reason | 格数 | 页数 |", "|---|---|---|"]
    rc = Counter(r["pending_reason"] for r in rows)
    for k, n in rc.most_common():
        lines.append(f"| {k} | {n} | {len({(r['册'], r['页']) for r in rows if r['pending_reason'] == k})} |")
    lines += ["", "## 按成因", "", "| 成因 | 格数 | 页数 | 其中 S01/S02/S03/S04 | 先怎么办 | 例页 |", "|---|---|---|---|---|---|"]
    by = defaultdict(list)
    for r in rows:
        by[r["成因"]].append(r)
    for k in CAUSES:
        rs = by.get(k)
        if not rs:
            continue
        pc = Counter((r["册"], r["页"]) for r in rs)
        sx = "/".join(str(sum(1 for r in rs if r["pending_reason"] == s)) for s in S_REASONS)
        eg = "、".join(f"{b}:{p}({n})" for (b, p), n in pc.most_common(5))
        lines.append(f"| {k} {CAUSES[k][0]} | {len(rs)} | {len(pc)} | {sx} | {CAUSES[k][1]} | {eg} |")
    return "\n".join(lines) + "\n"


def _write_tsv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        if not rows:
            return
        w = csv.DictWriter(f, fieldnames=list(rows[0]), delimiter="\t")
        w.writeheader()
        w.writerows(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("books", nargs="+", help="册 id（同产物根下的子目录名）")
    ap.add_argument("--products", default="", help="产物根（<根>/<册>/<步>/pNNNN.json）；缺省本机产物根")
    ap.add_argument("--pending", nargs="*", default=None, help="待审单 *.pending.json；不给就从包现算")
    ap.add_argument("--known", default="", help="已答复页 TSV：页号<TAB>结论")
    ap.add_argument("--all", action="store_true", help="所有待审格都归因，不只 S 类")
    ap.add_argument("--out", default="", help="输出目录：汇总.md、逐页.tsv、逐格.tsv")
    a = ap.parse_args(argv)
    if a.products:
        products = Path(a.products)
    else:
        from ..products.store import default_products_root
        products = default_products_root()
    for b in a.books:
        if not (products / b).is_dir():
            print(f"产物根 {products} 下没有册 {b}（先 guji products pack fetch {b} --to {products}）", file=sys.stderr)
            return 2
    pend = [Path(p) for p in a.pending] if a.pending else None
    rows = run(a.books, products, pend, load_known(Path(a.known) if a.known else None, a.books), a.all)
    md = summary_md(rows, a.books, "待审单 " + "、".join(p.name for p in pend) if pend else "包现算（同出单判法）")
    if a.out:
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "汇总.md").write_text(md, encoding="utf-8")
        _write_tsv(out / "逐页.tsv", by_page(rows))
        _write_tsv(out / "逐格.tsv", rows)
        print(f"已写 {out}/汇总.md、逐页.tsv、逐格.tsv", file=sys.stderr)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
