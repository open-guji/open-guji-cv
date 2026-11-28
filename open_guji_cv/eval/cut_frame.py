"""2e 字框压缩（`cell_shrink`）紧框评测：cut-frame（列首、列尾字与上下版框）与 shrink-ink（列中干净字的字身墨）两个分片共用。

CV2，2026-11-28 从 open-guji-dataset `char-segmentation/cut-frame/score.py` 与 ai-team `cut-bench/cutframe-1126/cf_eval.py`
合并搬进 cv（四大步验收 L4）。只读产物，不跑任何 Step、不动指纹。

    python -m open_guji_cv.eval.cut_frame --items <dataset>/char-segmentation/cut-frame/items.jsonl \
        --pred <产物根> [--against <另一产物根>] [--split tune|blind] [--tol 2] [--json out.json]

产物根下按册放 `<册>/cell_shrink/pNNNN.json`（`cut_bench run` 的结果目录给 `<结果目录>/ws/products`）。
预测框取 `char_index` 里同 (册, 页, 列, slot, sub) 的 `bbox_page`（原图坐标 raw_page_px@top-right，与金标同一空间）。

items 一行一格：`key`、`book`、`vol`、`page`、`col`、`slot`、`sub`、`status`（ok／fixed 计分，excluded 不计）、
`tight`（金标框 [x0,y0,x1,y1]）、`split`（tune／blind）、`tags`；cut-frame 另有 `end`（head／tail）。

指标（按书、按 split、按 tag 分报）：
- **IoU@0.9**：预测框与金标框 IoU ≥0.9 的格占比（主指标）；
- **切笔**（护栏，必须为 0／不增）：预测框有一边比金标往里收超过 `tol` 像素（字身墨被切掉）；
  cut-frame 里 `crosses_frame` 的格（勾越过内框）也按这条量，看越框的笔画有没有被抹；
- **带渣**：预测框有一边比金标往外扩超过 `tol` 像素（带框线、带邻字墨）；
- 缺格：产物里没有这一格；错格：item 带金标格四边形 `quad`（shrink-ink）而预测框中心不在格里——第二步格号对不上，归 2d，不判切笔／带渣。
`--against` 出翻转格：两边任一指标（IoU@0.9、切笔、带渣）结论不同的格逐格列出，「好→坏」的要出图人看。
"""
from __future__ import annotations

import argparse
import glob
import json
from collections import defaultdict
from pathlib import Path


def load_pred(root: Path) -> dict:
    """产物根 → {(册, 页, 列, slot, sub): bbox_page}。"""
    out = {}
    for f in glob.glob(str(root / "*" / "cell_shrink" / "p*.json")):
        vol = Path(f).parts[-3]
        d = json.loads(Path(f).read_text(encoding="utf-8"))["char_index"]
        for c in d["columns"]:
            for ch in c.get("chars") or []:
                if ch.get("bbox_page"):
                    out[(vol, d["page"], c["col"], ch["slot"], ch.get("sub"))] = ch["bbox_page"]
    return out


def load_cells(root: Path) -> dict:
    """产物根 → {(册, 页, 列, slot, sub): 第二步格四边形外包}（`row_segment` 的 `quad_page`）。没有就空表。"""
    out = {}
    for f in glob.glob(str(root / "*" / "row_segment" / "p*.json")):
        vol = Path(f).parts[-3]
        d = json.loads(Path(f).read_text(encoding="utf-8"))["cells"]
        for c in d["columns"]:
            for cell in c.get("cells") or []:
                q = cell.get("quad_page")
                if q:
                    xs, ys = [p[0] for p in q], [p[1] for p in q]
                    out[(vol, d["page"], c["col"], cell.get("slot"), cell.get("sub"))] = [min(xs), min(ys), max(xs), max(ys)]
    return out


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    i = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u > 0 else 0.0


def judge(pred, gold, tol: float, junk_tol: float | None = None, quad=None, cell=None) -> dict:
    """一格的结论。边序 (x0, y0, x1, y1)；「往里收」＝x0/y0 变大或 x1/y1 变小。
    给了 `quad`（金标格四边形）时先看第二步的格对不对得上：预测格外包 `cell` 与金标格 IoU <0.75，或（没有 `cell` 时）
    预测框中心不在金标格里，记错格（归 2d），不判切笔／带渣。"""
    junk_tol = tol if junk_tol is None else junk_tol
    none = {"missing": False, "misaligned": False, "iou_ok": False, "cut": False, "junk": False, "iou": 0.0, "d": None}
    if pred is None:
        return {**none, "missing": True}
    if quad:
        xs, ys = [p[0] for p in quad], [p[1] for p in quad]
        qb = [min(xs), min(ys), max(xs), max(ys)]
        cx, cy = (pred[0] + pred[2]) / 2, (pred[1] + pred[3]) / 2
        if (cell is not None and iou(cell, qb) < 0.75) or not (qb[0] <= cx <= qb[2] and qb[1] <= cy <= qb[3]):
            return {**none, "misaligned": True}
    d = [pred[i] - gold[i] for i in range(4)]
    inward = [d[0], d[1], -d[2], -d[3]]          # >0 往里收
    v = iou(pred, gold)
    return {"missing": False, "misaligned": False, "iou": round(v, 4), "iou_ok": v >= 0.9,
            "cut": any(x > tol for x in inward), "junk": any(-x > junk_tol for x in inward),
            "d": [round(x, 1) for x in d]}


def load_items(path: Path, split: str | None = None, vols: set | None = None) -> list[dict]:
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = [r for r in rows if r.get("status", "ok") in ("ok", "fixed") and r.get("tight")]
    if split:
        rows = [r for r in rows if r.get("split") == split]
    if vols is not None:
        rows = [r for r in rows if str(r["vol"]) in vols]
    return rows


def score(items: list[dict], pred: dict, tol: float = 2.0, junk_tol: float | None = None, cells_map: dict | None = None) -> dict:
    agg = defaultdict(lambda: {"cells": 0, "iou_ok": 0, "cut": 0, "junk": 0, "missing": 0, "misaligned": 0, "iou_sum": 0.0})
    cells = {}
    for r in items:
        k = (str(r["vol"]), r["page"], r["col"], r["slot"], r.get("sub"))
        j = judge(pred.get(k), r["tight"], tol, junk_tol, r.get("quad"), (cells_map or {}).get(k))
        cells[r["key"]] = j
        groups = [r["book"], "all", f"split:{r.get('split', '-')}", f"status:{r.get('status', 'ok')}"]
        groups += [f"tag:{t}" for t in r.get("tags", [])]
        if r.get("end"):
            groups.append(f"end:{r['end']}")
        for k in groups:
            a = agg[k]
            a["cells"] += 1
            a["iou_ok"] += j["iou_ok"]; a["cut"] += j["cut"]; a["junk"] += j["junk"]; a["missing"] += j["missing"]
            a["misaligned"] += j["misaligned"]
            a["iou_sum"] += j["iou"]
    return {"tol": tol, "junk_tol": tol if junk_tol is None else junk_tol, "groups": {k: dict(v) for k, v in agg.items()}, "cells": cells}


def flips(a: dict, b: dict) -> list[dict]:
    """a（基线）→ b（新）结论不同的格。worse＝b 更坏（IoU@0.9 丢了、新切笔、新带渣、新缺格）。"""
    out = []
    for k, jb in b["cells"].items():
        ja = a["cells"].get(k)
        if ja is None:
            continue
        diff = {x: (ja[x], jb[x]) for x in ("iou_ok", "cut", "junk", "missing", "misaligned") if ja[x] != jb[x]}
        if diff:
            worse = (ja["iou_ok"] and not jb["iou_ok"]) or any(not ja[x] and jb[x] for x in ("cut", "junk", "missing", "misaligned"))
            out.append({"key": k, "worse": bool(worse), "diff": diff, "a": ja["d"], "b": jb["d"]})
    return out


def _print(r: dict, title: str) -> None:
    print(title)
    for k, v in sorted(r["groups"].items(), key=lambda kv: (kv[0] != "all", kv[0])):
        n = v["cells"]
        print(f"  {k:24s} 格 {n:4d}  IoU@0.9 {v['iou_ok'] / n:.3f}  切笔 {v['cut']}  带渣 {v['junk']}  缺格 {v['missing']}  错格 {v['misaligned']}"
              f"  平均IoU {v['iou_sum'] / n:.3f}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--items", required=True, help="分片 items.jsonl（cut-frame、shrink-ink）")
    ap.add_argument("--pred", required=True, help="产物根（含 <册>/cell_shrink/pNNNN.json）")
    ap.add_argument("--against", help="对照产物根：出翻转格")
    ap.add_argument("--split", choices=["tune", "blind"])
    ap.add_argument("--tol", type=float, default=2.0, help="切笔的像素容差（原图像素）")
    ap.add_argument("--junk-tol", dest="junk_tol", type=float, help="带渣的像素容差，缺省同 --tol；shrink-ink 金标是墨的外包、紧框本来留几像素边，用 6")
    ap.add_argument("--json")
    a = ap.parse_args(argv)
    pred = load_pred(Path(a.pred))
    vols = {k[0] for k in pred}
    items = load_items(Path(a.items), a.split, vols)        # 只评产物根里有的册
    r = score(items, pred, a.tol, a.junk_tol, load_cells(Path(a.pred)))
    _print(r, f"{a.items}：{len(items)} 格（册 {', '.join(sorted(vols))}；切笔容差 {a.tol}px、带渣容差 {r['junk_tol']}px）")
    out = {"pred": r}
    if a.against:
        base = score(items, load_pred(Path(a.against)), a.tol, a.junk_tol, load_cells(Path(a.against)))
        _print(base, f"对照 {a.against}")
        fl = flips(base, r)
        out.update(against=base, flips=fl)
        bad = [f for f in fl if f["worse"]]
        print(f"翻转 {len(fl)} 格，其中变坏 {len(bad)} 格（护栏：变坏的逐格出图人看）")
        for f in fl:
            print(f"  {'坏' if f['worse'] else '好'} {f['key']}: {f['diff']}  边偏差 {f['a']} → {f['b']}")
    if a.json:
        Path(a.json).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
