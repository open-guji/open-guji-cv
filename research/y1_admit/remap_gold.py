# -*- coding: utf-8 -*-
"""金标重映射：整册重跑后格几何变了（cell_shrink 框与旧快照不同、格号错位），按格框 IoU 把金标搬到新格号。

只读：金标 jsonl、旧快照与新产物两份 products 根；不改任何产物、阈值、开关。

    python remap_gold.py --book vol05 --gold gold2_vol05.jsonl \\
        --old-products <旧快照 products 根> --new-products <新产物 products 根> \\
        --out gold2_vol05.remapped.jsonl [--report remap_report.json] [--iou 0.5]

判法（逐页）：
1. 金标格在旧 `cell_shrink` 里取 `bbox_page`；新 `cell_shrink` 同页所有字位取 `bbox_page`；
2. 候选对 = IoU ≥ 阈值（缺省 0.5）；按 IoU 从大到小一对一认领（一个新格只认一个金标格，
   同分时同号优先）；
3. 认上的写进输出（`cell` 换成新格号，`cell_old` 记旧格号，`remap_iou` 记 IoU）；认不上的记原因：
   `no_old_box`（旧产物里没有这格/没有框）、`no_new_page`（新产物没有这页）、
   `no_overlap`（同页没有 IoU ≥ 阈值的新格）、`lost_to_other`（候选被 IoU 更大的金标格占了）。
4. 误放行 = 映射成功、金标 v 是 ok/wrong（有明确字）、新 `seed_admit` 该格 `admit=True` 且 char ≠ 金标字
   （ok → 金标字 = shown；wrong → 金标字 = char）。`unsure` 不计。新 seed_admit 缺这页/这格记 `no_seed_record`。
5. 同号同框（IoU ≥ 阈值）的格原样保留，报告里单列「未变」。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_boxes(prod: str | Path, book: str, step: str = "cell_shrink") -> dict[int, dict[str, list[float]]]:
    """{页号: {字位 id: bbox_page}}。"""
    out: dict[int, dict[str, list[float]]] = {}
    for f in sorted(Path(prod, book, step).glob("p*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        d = next(iter(d.values()))
        pg = int(f.stem[1:])
        boxes = out.setdefault(pg, {})
        for col in d.get("columns", []):
            for r in col.get("chars") or []:
                b = r.get("bbox_page")
                if b and len(b) == 4:
                    boxes[r["id"]] = [float(x) for x in b]
    return out


def load_admit(prod: str | Path, book: str) -> dict[str, dict]:
    """{字位 id: seed_admit 记录}。"""
    out: dict[str, dict] = {}
    for f in sorted(Path(prod, book, "seed_admit").glob("p*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        d = next(iter(d.values()))
        for col in d.get("columns", []):
            for r in col.get("chars") or []:
                out[r["id"]] = r
    return out


def iou(a, b) -> float:
    x0, y0 = max(a[0], b[0]), max(a[1], b[1])
    x1, y1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    if inter <= 0:
        return 0.0
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def gold_char(g: dict) -> str | None:
    """金标认定的字：ok → shown；wrong → char；unsure/认不出 → None。"""
    if g.get("v") == "ok":
        return g.get("shown")
    if g.get("v") == "wrong":
        return g.get("char")
    return None


def page_of(cell: str) -> int:
    return int(cell.split(":")[1])


def remap(gold: list[dict], old_boxes: dict, new_boxes: dict, thr: float = 0.5):
    """→ (映射后的金标行, 失败清单 [(格, 原因)], 同号未变的格数)。"""
    by_page: dict[int, list[dict]] = {}
    for g in gold:
        by_page.setdefault(page_of(g["cell"]), []).append(g)
    mapped: list[dict] = []
    failed: list[tuple[str, str]] = []
    unchanged = 0
    for pg, rows in sorted(by_page.items()):
        ob, nb = old_boxes.get(pg, {}), new_boxes.get(pg)
        pairs = []
        for g in rows:
            if g["cell"] not in ob:
                failed.append((g["cell"], "no_old_box"))
                continue
            if nb is None:
                failed.append((g["cell"], "no_new_page"))
                continue
            for nid, box in nb.items():
                v = iou(ob[g["cell"]], box)
                if v >= thr:
                    pairs.append((v, nid == g["cell"], g["cell"], nid))
        pairs.sort(key=lambda t: (-t[0], not t[1], t[2], t[3]))
        gold_by = {g["cell"]: g for g in rows}
        got_old, used_new = set(), set()
        for v, _same, oc, nid in pairs:
            if oc in got_old or nid in used_new:
                continue
            got_old.add(oc)
            used_new.add(nid)
            row = dict(gold_by[oc])
            if nid == oc:
                unchanged += 1
            else:
                row["cell_old"], row["cell"] = oc, nid
            row["remap_iou"] = round(v, 4)
            mapped.append(row)
        for g in rows:
            c = g["cell"]
            if c in got_old or c not in ob or nb is None:
                continue
            has = any(p[2] == c for p in pairs)
            failed.append((c, "lost_to_other" if has else "no_overlap"))
    return mapped, failed, unchanged


def report(mapped: list[dict], failed: list[tuple[str, str]], unchanged: int, admit: dict[str, dict] | None) -> dict:
    reasons: dict[str, int] = {}
    for _c, why in failed:
        reasons[why] = reasons.get(why, 0) + 1
    rep = {
        "gold_total": len(mapped) + len(failed),
        "mapped": len(mapped),
        "unchanged_id": unchanged,
        "remapped_to_new_id": len(mapped) - unchanged,
        "unmapped": len(failed),
        "unmapped_reasons": reasons,
        "unmapped_cells": sorted(c for c, _ in failed),
    }
    if admit is not None:
        mis, nrec, ok_admit = [], 0, 0
        for g in mapped:
            want = gold_char(g)
            if want is None:
                continue
            r = admit.get(g["cell"])
            if r is None:
                nrec += 1
                continue
            if r.get("admit"):
                if r.get("char") == want:
                    ok_admit += 1
                else:
                    mis.append({"cell": g["cell"], "cell_old": g.get("cell_old"), "gold": want,
                                "admitted": r.get("char"), "v": g.get("v")})
        rep["checked_admit"] = {"admitted_right": ok_admit, "false_admit": len(mis),
                                "no_seed_record": nrec, "false_admit_cells": mis}
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--book", required=True)
    ap.add_argument("--gold", required=True, help="金标 jsonl（cell/v/shown/char）")
    ap.add_argument("--old-products", required=True, help="旧快照 products 根（含 <book>/cell_shrink）")
    ap.add_argument("--new-products", required=True, help="新产物 products 根（含 cell_shrink 与 seed_admit）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", default=None, help="报告 json；缺省只打印")
    ap.add_argument("--iou", type=float, default=0.5)
    a = ap.parse_args(argv)
    gold = [json.loads(l) for l in open(a.gold, encoding="utf-8") if l.strip()]
    old = load_boxes(a.old_products, a.book)
    new = load_boxes(a.new_products, a.book)
    mapped, failed, unchanged = remap(gold, old, new, a.iou)
    admit = load_admit(a.new_products, a.book)
    rep = report(mapped, failed, unchanged, admit or None)
    Path(a.out).write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in mapped), encoding="utf-8")
    if a.report:
        Path(a.report).write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    ca = rep.get("checked_admit")
    print(f"{a.book}｜金标 {rep['gold_total']}｜映射成功 {rep['mapped']}（未变 {unchanged}、改号 {rep['remapped_to_new_id']}）"
          f"｜无法映射 {rep['unmapped']} {rep['unmapped_reasons']}"
          + (f"｜新产物放行且与金标字不同 {ca['false_admit']}（放对 {ca['admitted_right']}）" if ca else ""))
    return rep


if __name__ == "__main__":
    main()
