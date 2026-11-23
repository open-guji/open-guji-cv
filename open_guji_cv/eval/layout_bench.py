"""版面（第 1 大步）benchmark 入口（A21，2026-11-23）。

    python -m open_guji_cv.eval.layout_bench --products <产物根> --book vol01 \
        [--gold <layout-gold items.jsonl>] [--page-type-gold <page-type items.jsonl> --page-map map.json] \
        [--pages 1-20] [--expected-cols 9] [--out report.json]

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
    ap.add_argument("--book", required=True)
    ap.add_argument("--pages")
    ap.add_argument("--expected-cols", type=int)
    ap.add_argument("--gold")
    ap.add_argument("--page-type-gold")
    ap.add_argument("--page-map")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
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
