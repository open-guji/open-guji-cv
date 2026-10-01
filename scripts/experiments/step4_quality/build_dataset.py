"""X2 道：把人裁事件绑到现行 v2 产物的格上，拼上 capture_features 抓的原始量 → dataset.parquet。

标签来源（guji-workspace feedback/events/*.jsonl，kind=confirm，target.step∈{seed_admit,cell_shrink}）：
  defect=1  : payload.v=seg_defect 且 quality∈{truncated,contaminated}（子类 truncated/contaminated）
  defect=0  : 强负 = seg_defect/quality=clean（cell_shrink 随机抽审：人明确判「干净」）
              弱负 = v=confirm 且 reading 非空（人认出了字，没标缺陷——人只是读字，浅淡残渣可能没标）
  丢弃      : not_a_char / skip / upstream_miscut（不是「这格字块缺陷」的问题）
同键多条事件取**最后一条**（ts 序）；键上同时出现缺陷与干净/确认的记「冲突」，取最后一条并计数。

绑定：键 (book,page,col,slot) 直接对现行 v2 CharRec（cell_type=char、同 slot 的 a/b 半格并集）。
对不上（该页/列/格在现行产物里不存在，或该格被判 empty/blank）→ 丢弃并计数，不手工剔。
漂移（vol02 233 条的教训）：事件里 defect/clean 没有留图块凭证，没法逐条证明「人当时看的就是现在这格」。
  能做的只有**页级格位稳定性**：vol02 的 confirm 事件有 anchors（backfill:ink 的页坐标 ink_bbox），
  拿它跟现行同键格的 bbox_page 比，页内 ≥90% 对得上才认这页「格位稳定」。vol01 没有 anchors → 标 unverified。
"""
from __future__ import annotations

import glob
import json
import os
import pickle
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "scripts"))

WS = Path(os.environ["GUJI_WORKSPACE"])


def load_labels():
    last = {}
    hist = defaultdict(list)
    drop = Counter()
    for f in sorted(glob.glob(str(WS / "feedback/events/*.jsonl"))):
        for ln in open(f, encoding="utf-8"):
            try:
                e = json.loads(ln)
            except Exception:
                continue
            if e.get("kind") != "confirm":
                continue
            t, p = e["target"], e["payload"]
            if t.get("step") not in ("seed_admit", "cell_shrink") or t.get("unit") != "cell":
                continue
            if t.get("book") not in ("vol01", "vol02"):
                continue
            v, q = p.get("v"), p.get("quality")
            if v == "seg_defect" and q in ("truncated", "contaminated"):
                lab = ("defect", q)
            elif v == "seg_defect" and q == "clean":
                lab = ("clean", "strong")
            elif v == "confirm" and p.get("reading"):
                lab = ("clean", "weak")
            else:
                drop[f"{v}/{q}"] += 1
                continue
            key = (t["book"], int(t["page"]), int(t["col"]), int(t["slot"]))
            rec = {"ts": e["ts"], "lab": lab, "batch": e.get("batch"), "step": t.get("step"), "reading": p.get("reading")}
            hist[key].append(rec)
    out, conflict = {}, 0
    for k, h in hist.items():
        h.sort(key=lambda r: r["ts"])
        if len({r["lab"][0] for r in h}) > 1:
            conflict += 1
        out[k] = h[-1]
    return out, drop, conflict, hist


def anchors_vol02():
    a = {}
    p = WS / "feedback/anchors/vol02.jsonl"
    for ln in open(p, encoding="utf-8"):
        d = json.loads(ln)
        if d.get("anchor") and d["anchor"].get("ink_bbox"):
            parts = d["key"].split(":")
            if not all(x.isdigit() for x in parts[1:4]) or len(parts) != 4:
                continue          # a/b 夹注子格键（如 6b）不参与漂移探针
            a[(parts[0], int(parts[1]), int(parts[2]), int(parts[3]))] = d["anchor"]["ink_bbox"]
    return a


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    i = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i
    return i / u if u > 0 else 0.0


def main():
    feats = {}
    for pk in sys.argv[2:]:
        feats.update(pickle.load(open(pk, "rb")))
    outp = sys.argv[1]
    from _v2_step4 import V2Book
    labels, dropped, conflict, hist = load_labels()
    anc = anchors_vol02()
    books = {b: V2Book(b) for b in ("vol01", "vol02")}
    stats = Counter()
    stats["events_dropped_" + "_".join(sorted(dropped))] = sum(dropped.values())
    rows = []
    cache_idx = {}
    for (b, pg, col, slot), r in labels.items():
        bk = books[b]
        if not bk.has_step4(pg):
            stats["no_page_product"] += 1
            continue
        pc = bk.chars(pg)
        cc = pc.column(col) if pc else None
        if cc is None or not cc.ok:
            stats["no_column"] += 1
            continue
        recs = [c for c in cc.chars if c.slot == slot]
        if not recs:
            stats["no_slot"] += 1
            continue
        recs_char = [c for c in recs if c.cell_type == "char"]
        if not recs_char:
            stats["slot_not_char"] += 1
            continue
        flags = sorted({f for c in recs_char for f in c.flags})
        c0 = recs_char[0]
        ft = feats.get((b, str(pg), col, c0.idx))
        if ft is None:
            stats["no_feature"] += 1
            continue
        # drift probe（vol02 confirm anchors）
        drift = None
        ab = anc.get((b, pg, col, slot))
        if ab is not None and c0.bbox_page is not None:
            drift = iou(ab, c0.bbox_page)
        rows.append(dict(
            book=b, page=pg, col=col, slot=slot, y=int(r["lab"][0] == "defect"), sub=r["lab"][1],
            strong=int(r["lab"] == ("clean", "strong")), ts=r["ts"], batch=r["batch"],
            flags="|".join(flags), n_flags=len(flags), **{f"flag_{f}": int(f in flags) for f in
                                                          ("rule_bar", "edge_blob", "frame_bars", "wide_gap", "off_center",
                                                           "boundary_ink", "bad_seg", "suspect_empty", "seal_region", "jiazhu")},
            ink_ratio=c0.ink_ratio, rec_h=c0.height, rec_w=c0.width, step3_kind=c0.step3_kind,
            is_sub=int(any(c.sub for c in recs_char)), anchor_iou=drift,
            **{k: v for k, v in ft.items() if k != "flags_part"}))
        stats["bound"] += 1
    df = pd.DataFrame(rows)
    # 页级格位稳定性
    g = df[df.anchor_iou.notna()].groupby(["book", "page"]).anchor_iou.apply(lambda s: float((s > 0.3).mean()))
    df["page_stab"] = [g.get((b, p), float("nan")) for b, p in zip(df.book, df.page)]
    df.to_pickle(outp)
    print(json.dumps({"labels_total": len(labels), "conflict_keys": conflict, **stats}, ensure_ascii=False, indent=1, default=int))
    print(df.groupby(["book", "y", "sub"]).size())
    print("page_stab by book (pages with anchors):", g.groupby(level=0).describe().to_string())


if __name__ == "__main__":
    main()
