"""1c 印章定位最小 benchmark（CV1，2026-11-28，四大步验收 L2／S11）。

    python -m open_guji_cv.eval.seal_bench --products <产物根> --gold <seal-box items.jsonl> [--iou 0.5] [--out report.json]

读 `<产物根>/<册>/seal_detect/pNNNN.json`（上游冻结：产物由 `seal_detect` 在固定图上跑出），与金标印章框配对，
按 IoU 量。坐标同产物，规范空间（右上原点、x 向左）；金标框同一坐标系，`[x0, y0, x1, y1]`。

条目（`seal-box/items.jsonl`）：
`{"id": "mj01:3", "anchor": {"book": "mj01", "page": 3}, "expected": {"seals": [{"kind": "crisp", "bbox": [..]}]},
  "label_origin": "human|draft", "status": "active"}`
`label_origin: draft`（拿现行预测当底稿、人还没核）不进指标，只列「待核」；`human` 才算。

主指标：印章召回@IoU、精确率@IoU、IoU 中位、类别（stain／crisp）对率。护栏（必须为 0）：**印章漏认**（金标有印、
产物没有任何配得上的框）——漏认的印会让压在下面的字被当成清晰字放行。匹配：每页金标框与预测框按 IoU 贪心一对一配。
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from .layout_bench import series_of


def iou(a, b) -> float:
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    iw = max(0.0, min(max(ax0, ax1), max(bx0, bx1)) - max(min(ax0, ax1), min(bx0, bx1)))
    ih = max(0.0, min(max(ay0, ay1), max(by0, by1)) - max(min(ay0, ay1), min(by0, by1)))
    inter = iw * ih
    ua = abs(ax1 - ax0) * abs(ay1 - ay0) + abs(bx1 - bx0) * abs(by1 - by0) - inter
    return inter / ua if ua > 0 else 0.0


def match(gold: list[dict], pred: list[dict], thr: float) -> dict:
    """金标框与预测框按 IoU 从大到小贪心配对（不同 kind 也配，类别另算）。"""
    cand = sorted(((iou(g["bbox"], p["bbox"]), gi, pi) for gi, g in enumerate(gold) for pi, p in enumerate(pred)),
                  reverse=True)
    mg, mp, pairs = set(), set(), []
    for v, gi, pi in cand:
        if v < thr:
            break
        if gi in mg or pi in mp:
            continue
        mg.add(gi)
        mp.add(pi)
        pairs.append({"gi": gi, "pi": pi, "iou": v, "kind_ok": gold[gi]["kind"] == pred[pi]["kind"]})
    return {"pairs": pairs, "missed": [i for i in range(len(gold)) if i not in mg],
            "extra": [i for i in range(len(pred)) if i not in mp]}


def _pred_seals(products: Path, book: str, page: int) -> list[dict] | None:
    p = products / book / "seal_detect" / f"p{page:04d}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text(encoding="utf-8"))
    d = d.get("seals", d)
    return [{"kind": s["kind"], "bbox": s["bbox"]} for s in d.get("seals", [])]


def run(products: Path, items: list[dict], thr: float = 0.5) -> dict:
    per: dict[str, dict] = defaultdict(lambda: {"pages": 0, "gold": 0, "pred": 0, "hit": 0, "kind_ok": 0,
                                               "ious": [], "missed": [], "extra": []})
    pending, no_product = [], []
    for it in items:
        if it.get("status", "active") != "active":
            continue
        a = it["anchor"]
        key = f"{a['book']}:{a['page']}"
        if it.get("label_origin", "human") != "human":
            pending.append(key)
            continue
        pred = _pred_seals(products, a["book"], int(a["page"]))
        if pred is None:
            no_product.append(key)
            continue
        gold = it["expected"].get("seals", [])
        m = match(gold, pred, thr)
        for ser in ("全部", series_of(a["book"]) or "其他"):
            s = per[ser]
            s["pages"] += 1
            s["gold"] += len(gold)
            s["pred"] += len(pred)
            s["hit"] += len(m["pairs"])
            s["kind_ok"] += sum(p["kind_ok"] for p in m["pairs"])
            s["ious"] += [p["iou"] for p in m["pairs"]]
            s["missed"] += [f"{key}#{i}" for i in m["missed"]]
            s["extra"] += [f"{key}#{i}" for i in m["extra"]]
    out = {}
    for ser, s in per.items():
        ious = sorted(s["ious"])
        out[ser] = {"pages": s["pages"], "gold_seals": s["gold"], "pred_seals": s["pred"], "matched": s["hit"],
                    f"recall@iou{thr}": s["hit"] / s["gold"] if s["gold"] else None,
                    f"precision@iou{thr}": s["hit"] / s["pred"] if s["pred"] else None,
                    "iou_median": ious[len(ious) // 2] if ious else None,
                    "kind_acc": s["kind_ok"] / s["hit"] if s["hit"] else None,
                    "missed_seals": s["missed"], "extra_seals": s["extra"]}
    return {"summary": out, "pending_draft": pending, "no_product": no_product}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--products", required=True)
    ap.add_argument("--gold", required=True)
    ap.add_argument("--iou", type=float, default=0.5)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    items = [json.loads(l) for l in Path(a.gold).read_text(encoding="utf-8").splitlines() if l.strip()]
    txt = json.dumps(run(Path(a.products), items, a.iou), ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).write_text(txt, encoding="utf-8")
    print(txt)


if __name__ == "__main__":
    main()
