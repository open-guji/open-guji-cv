"""版面（第 1 大步）benchmark 入口（A21，2026-11-23）。

    python -m open_guji_cv.eval.layout_bench --products <产物根> --book vol01 \
        [--gold <layout-gold items.jsonl>] [--page-type-gold <page-type items.jsonl> --page-map map.json] \
        [--pages 1-20] [--expected-cols 9] [--out report.json]

    # 按书分表的基线报告（四大步验收 L2／B4）：金标里每册都跑，按套书汇总成一张 markdown 表
    python -m open_guji_cv.eval.layout_bench --products <产物根> --gold <layout-gold items.jsonl> \\
        --series-report [--md 基线报告.md] [--out report.json]

读 `<产物根>/<册>/border_detect/pNNNN.json`（＋ `border_detect_gate/`）→ 版面文档 → 指标。
三层都报，各自独立：

0. **体检**（无需金标）：列数对不对、列距均匀度、框是否在图内——对所有跑过的页；
1. **页型**（`--page-type-gold`，可配 `--page-map {"册/旧页": {"new": 新页号}}` 把换图源前
   的页号换成现页号）：策略准确率、漏切率；
2. **几何**（`--gold` layout-gold）：线检出 P/R、偏差、破损线、框、列数／行数。

只读产物，不跑任何 Step、不动指纹。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import layout_gold as lg
from . import layout_metrics as lm


def _read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def pred_doc(products: Path, book: str, page: int, expected_cols: int | None = None):
    bp = products / book / "border_detect" / f"p{page:04d}.json"
    if not bp.exists():
        return None
    b = _read_json(bp)["borders"]
    gp = products / book / "border_detect_gate" / f"p{page:04d}.json"
    gate = _read_json(gp).get("border_detect_gate_manifest") if gp.exists() else None
    return lg.doc_from_borders(b, gate)


def parse_pages(expr: str | None) -> set[int] | None:
    if not expr:
        return None
    s: set[int] = set()
    for part in expr.split(","):
        if "-" in part:
            a, b = part.split("-")
            s.update(range(int(a), int(b) + 1))
        elif part:
            s.add(int(part))
    return s


def run(products: Path, book: str, pages: set[int] | None = None, expected_cols: int | None = None,
        gold_items: list[dict] | None = None, pt_items: list[dict] | None = None,
        page_map: dict | None = None) -> dict:
    """返回 {"health", "page_type", "geometry", "worst"}。"""
    bdir = products / book / "border_detect"
    have = sorted(int(p.stem[1:]) for p in bdir.glob("p*.json")) if bdir.exists() else []
    if pages is not None:
        have = [p for p in have if p in pages]
    preds = {p: pred_doc(products, book, p, expected_cols) for p in have}
    rep: dict = {"book": book, "pages_run": len(have)}
    rep["health"] = lm.summarize_health([lm.health(d, expected_cols) for d in preds.values() if d])

    if pt_items:
        gdocs = lg.docs_from_page_type(pt_items)
        recs = []
        for key, g in gdocs.items():
            b, op = key.split("/")
            if b != book:
                continue
            if page_map is not None:
                if key not in page_map:
                    continue                       # 换图源后没有对应页（封面、书签等）
                page = int(page_map[key]["new"])
            else:
                page = int(op)
            d = preds.get(page)
            if d is None:
                continue
            r = lm.page_metrics(g, d)
            r["key"] = f"{book}/{page}"
            recs.append(r)
        rep["page_type"] = {"all": lm.aggregate(recs)["all"]["policy"],
                            "by_type": _by_type(recs), "pages": len(recs),
                            "wrong_skip": [r["key"] for r in recs if r["policy"]["wrong_skip"]],
                            "wrong_keep": [r["key"] for r in recs if r["policy"]["wrong_keep"]]}
    if gold_items:
        per, recs = [], []
        for it in gold_items:
            if it.get("status") != "active":
                continue
            a = it["anchor"]
            if a.get("book") != book:
                continue
            d = preds.get(int(a["page"]))
            if d is None:
                continue
            g = dict(it["expected"], book=book, stratum=it.get("stratum"))
            r = lm.page_metrics(g, d)
            recs.append(r)
            per.append((f"{book}/{a['page']}", r))
        rep["geometry"] = {"all": lm.aggregate(recs).get("all"), "by_tag": lm.aggregate(recs, key="tags"),
                           "pages": len(recs)}
        rep["worst"] = lm.worst_pages(per, 10)
    return rep


#: 金标册名前缀 → 套书（按书分表用）。册名取金标 `anchor.book`，产物根下同名目录。
SERIES = (("殿本", "vol"), ("史記", "sj"), ("全唐文", "qtw"), ("脈經", "mj"))
PX_BUCKETS = (5, 10, 20)   # 界行偏差分档（像素，p95 沿线）：≤5px 算准，只报 >5／>10／>20 的条数


def series_of(book: str) -> str | None:
    for name, pre in SERIES:
        if book.startswith(pre):
            return name
    return None


def run_series(products: Path, gold_items: list[dict]) -> dict:
    """金标里每册各跑一遍 `run`，按套书汇总。返回 {"series": {套书: 汇总}, "books": {册: 页数}}。

    汇总口径：线 P/R 用 recall@0.05（列距 5%）；界行偏差用「每条配上的线沿线 p95」分档 >5／>10／>20 px
    （用户 2026-11-25 定：≤5px 算准确）；框看上下框 p95 的页中位、框型认对率；页型看策略准确与两类错。
    """
    books = sorted({it["anchor"]["book"] for it in gold_items if it.get("status") == "active"})
    recs: dict[str, list[tuple[str, dict]]] = {}
    pages_missing: dict[str, list[int]] = {}
    for b in books:
        ser = series_of(b)
        if ser is None:
            continue
        for it in gold_items:
            a = it["anchor"]
            if it.get("status") != "active" or a.get("book") != b:
                continue
            d = pred_doc(products, b, int(a["page"]))
            if d is None:
                pages_missing.setdefault(b, []).append(int(a["page"]))
                continue
            g = dict(it["expected"], book=b, stratum=it.get("stratum"))
            recs.setdefault(ser, []).append((f"{b}:{a['page']}", lm.page_metrics(g, d)))
    out: dict = {"series": {}, "missing": pages_missing}
    for ser, per in recs.items():
        out["series"][ser] = summarize_recs(per)
    return out


def summarize_recs(per: list[tuple[str, dict]]) -> dict:
    """一组页的 `(页键, page_metrics)` 汇成一行：`aggregate` 的汇总＋界行偏差分档＋最差页＋册清单。"""
    rs = [r for _, r in per]
    agg = lm.aggregate(rs)["all"]
    p95 = [x for r in rs if r.get("vlines") for x in r["vlines"]["line_p95"]]
    agg["line_gt_px"] = {f">{t}": sum(1 for x in p95 if x > t) for t in PX_BUCKETS}
    agg["worst"] = lm.worst_pages(per, 5)
    agg["books"] = sorted({r["book"] for r in rs})
    return agg


def series_markdown(rep: dict, meta: dict | None = None) -> str:
    cols = ["套书", "页", "金标线", "漏线", "多线", "线召回@5%", ">5px", ">10px", ">20px",
            "上框 p95 px", "下框 p95 px", "框型认对", "列数对", "页型对", "该切判跳过", "该跳过判切"]
    f = lambda v, d=3: "–" if v is None else (f"{v:.{d}f}" if isinstance(v, float) else str(v))
    lines = []
    if meta:
        lines += [f"- {k}：{v}" for k, v in meta.items()] + [""]
    lines += ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for name, _ in SERIES:
        a = rep["series"].get(name)
        if not a:
            lines.append(f"| {name} |" + " 无金标页 |" + " – |" * (len(cols) - 2))
            continue
        pol = a.get("policy") or {}
        fr = a.get("frame") or {}
        lines.append("| " + " | ".join([
            name, str(a["pages"]), str(a["lines_gold"]),
            str(a["lines_gold"] - a["lines_matched"]), str(a["lines_pred"] - a["lines_matched"]),
            f(a.get("recall@0.05")), str(a["line_gt_px"][">5"]), str(a["line_gt_px"][">10"]),
            str(a["line_gt_px"][">20"]),
            f((a.get("top_frame_px") or {}).get("p95"), 1), f((a.get("bottom_frame_px") or {}).get("p95"), 1),
            f(fr.get("kind_acc")), f(a.get("n_cols_acc")), f(pol.get("acc")),
            str(pol.get("wrong_skip", "–")), str(pol.get("wrong_keep", "–"))]) + " |")
    return "\n".join(lines) + "\n"


def _by_type(recs: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for r in recs:
        t = r["policy"]["gold_type"]
        o = out.setdefault(t, {"n": 0, "ok": 0, "pred": {}})
        o["n"] += 1
        o["ok"] += int(r["policy"]["ok"])
        k = f'{r["policy"]["pred_type"]}/{r["policy"]["pred"]}'
        o["pred"][k] = o["pred"].get(k, 0) + 1
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--products", required=True)
    ap.add_argument("--book")
    ap.add_argument("--series-report", action="store_true", help="金标里每册都跑，按套书分表（L2／B4）")
    ap.add_argument("--md", help="--series-report 时另存 markdown 表")
    ap.add_argument("--pages")
    ap.add_argument("--expected-cols", type=int)
    ap.add_argument("--gold")
    ap.add_argument("--page-type-gold")
    ap.add_argument("--page-map")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    if a.series_report:
        if not a.gold:
            ap.error("--series-report 要 --gold")
        gold = [json.loads(l) for l in Path(a.gold).read_text(encoding="utf-8").splitlines() if l.strip()]
        rep = run_series(Path(a.products), gold)
        if a.md:
            Path(a.md).write_text(series_markdown(rep), encoding="utf-8")
        txt = json.dumps(rep, ensure_ascii=False, indent=1, default=float)
        if a.out:
            Path(a.out).write_text(txt, encoding="utf-8")
        print(series_markdown(rep))
        return
    if not a.book:
        ap.error("要 --book（或 --series-report）")
    rd = lambda p: [json.loads(l) for l in Path(p).read_text(encoding="utf-8").splitlines() if l.strip()]
    rep = run(Path(a.products), a.book, parse_pages(a.pages), a.expected_cols,
              gold_items=rd(a.gold) if a.gold else None,
              pt_items=rd(a.page_type_gold) if a.page_type_gold else None,
              page_map=_read_json(Path(a.page_map)) if a.page_map else None)
    txt = json.dumps(rep, ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
