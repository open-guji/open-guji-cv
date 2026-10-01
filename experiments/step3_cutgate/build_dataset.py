# -*- coding: utf-8 -*-
"""X3：把「金标/人裁事件 × 现役 Step3 产物」对成一张特征表（每行一个粘连切点）。

标签来源：测试集 touching-cuts（active 1599）∪ guji-workspace feedback/events 里 cutline 事件
（金标没有的键，取最新一条）。键 = book:page:col:slot_above。
对不上现行产物的丢弃并计数：无产物 / 该列无此切点 / 金标锚点漂移（|当前格线 − y_old| > ANCHOR_TOL）/ 人裁里被
当前缝直接采用的（chosen_by=human，会泄漏标签）/ 带干扰 tag / idk。
产物在沙箱（GUJI_PRODUCTS_DIR），由 gen_products.py 跑出（PROBE_DEV=-1：所有切点都过 U-Net，信号全采，
现行「要不要探针」的门槛在 eval 里离线模拟）。

用法：GUJI_WORKSPACE=… GUJI_PRODUCTS_DIR=… python build_dataset.py --out out/table.csv
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from open_guji_cv.core.step import page_key  # noqa: E402
from open_guji_cv.eval.touching import ANCHOR_TOL, gold_anchor_shift  # noqa: E402
from open_guji_cv.products import kinds as _k  # noqa: E402,F401
from open_guji_cv.products.store import ProductStore  # noqa: E402

DATASET = Path("/home/user/open-guji-dataset/char-segmentation/touching-cuts/items.jsonl")
EVENTS_DIR = sorted(Path("/home/user/guji-workspace").glob("96mid1ogzk-*/feedback/events"))[0]
CLASSIF = REPO / "artifacts/m1_gold/touching_cuts/classification.json"
GEO = ("straight", "seam_narrow", "seam_wide")
KINDS = ("straight", "seam_narrow", "seam_wide", "unet_seam", "period_up", "period_dn")


def load_labels() -> dict[str, dict]:
    tier = {c["id"]: c["tier"] for c in json.loads(CLASSIF.read_text(encoding="utf-8"))}
    lab: dict[str, dict] = {}
    gold_ids = set()
    for l in DATASET.read_text(encoding="utf-8").splitlines():
        d = json.loads(l)
        gold_ids.add(d["id"])
        if d["status"] != "active":
            continue
        a = d["anchor"]
        lab[d["id"]] = dict(key=d["id"], book=a["book"], page=a["page"], col=a["col"], ex=d["expected"],
                            src="gold_" + tier.get(d["id"], "legacy"))
    ev: dict[str, dict] = {}
    for f in sorted(EVENTS_DIR.glob("*.jsonl")):
        for l in f.read_text(encoding="utf-8").splitlines():
            try:
                e = json.loads(l)
            except ValueError:
                continue
            if e.get("kind") != "cutline":
                continue
            k = e["target"]["key"]
            if k not in ev or e["ts"] >= ev[k]["ts"]:
                ev[k] = e
    for k, e in ev.items():
        if k in gold_ids:
            continue
        t = e["target"]
        lab[k] = dict(key=k, book=t["book"], page=t["page"], col=t["col"], ex=e["payload"], src="event_only")
    return lab


def seam_mean(c, y_line: float) -> float:
    return float(np.mean(c.y)) if c.y else float(y_line)


def build(lab: dict[str, dict], st: ProductStore):
    geoms: dict = {}
    rows, drops = [], collections.Counter()
    cache: dict = {}
    for r in lab.values():
        ex, book, pg, col = r["ex"], r["book"], r["page"], r["col"]
        v = ex.get("verdict")
        if v not in ("ok", "moved", "overlap", "seam_ok", "cand"):
            drops["verdict_" + str(v)] += 1
            continue
        if ex.get("tags"):
            drops["tags"] += 1
            continue
        k = (book, pg)
        if k not in cache:
            cache[k] = st.read(book, "row_segment", page_key(pg), "cells")
        cells = cache[k]
        cc = next((c for c in (cells.columns if cells else []) if c.col == col and c.ok), None) if cells else None
        if cc is None:
            drops["no_product"] += 1
            continue
        if r["src"] == "gold_page":
            # page 档：金标锚在原图页面坐标上，按当前列窗几何换算（M1 口径）；换算不了的（mode=drift）丢
            from open_guji_cv.eval.colgeom import current_geom, gold_rows_now
            gk = (book, pg, col)
            if gk not in geoms:
                geoms[gk] = current_geom(st, *gk)
            mode, y_now, _ = gold_rows_now(ex, geoms[gk])
            if mode == "drift" or y_now is None:
                drops["page_geom_drift"] += 1
                continue
            sh = float(y_now) - float(ex["y"])
        else:
            sh = gold_anchor_shift(cc, ex)       # 老条目：按原格线锚点复核（ANCHOR_TOL=3px）
            if sh is None or abs(sh) > ANCHOR_TOL:
                drops["anchor_drift"] += 1
                continue
        sa = ex.get("slot_above")
        cp = next((c for c in cc.cut_candidates if c.slot_above == sa), None)
        if cp is None or cp.chosen is None or not cp.candidates:
            drops["no_cutpoint_now"] += 1
            continue
        ch = cp.candidates[cp.chosen]
        if cp.chosen_by == "human":
            drops["chosen_by_human"] += 1
            continue
        if ch.dis_unet is None:
            drops["no_unet_signal"] += 1
            continue
        up = next((c for c in cc.cells if c.slot == cp.slot_above), None)
        dn = next((c for c in cc.cells if c.slot == cp.slot_below), None)
        if up is None or dn is None or not cc.period:
            drops["no_cells"] += 1
            continue
        P = float(cc.period)
        geo = [c for c in cp.candidates if c.kind in GEO]
        others = [c for c in geo if c is not ch]
        oth_ag = [c.agree for c in others if c.agree is not None]
        ag = ch.agree if ch.agree is not None else np.nan
        y_gold = ex.get("y")
        if y_gold is None and ex.get("polyline"):
            y_gold = float(np.mean([p[1] for p in ex["polyline"]]))
        y_gold = float(y_gold) + sh
        err = abs(seam_mean(ch, cp.y) - y_gold)
        hu, hd = (up.y1 - up.y0) / P, (dn.y1 - dn.y0) / P
        n_geo = len(geo)
        dev_h = max(abs(hu - 1), abs(hd - 1))
        probed_now = bool(n_geo >= 2 or dev_h > 0.10)       # 现行 PROBE_DEV 逻辑（单候选且格高正常就不探）
        slots = [c.slot for c in cc.cells if c.kind == "char"]
        row = dict(
            key=r["key"], book=book, page=pg, col=col, src=r["src"], verdict=v, y_gold=y_gold,
            err_cur=err,
            # ---- 标签
            lab_verdict=int(v in ("moved", "overlap", "cand")),
            lab_cur=int(v == "overlap" or err > 5.0),
            # ---- 现行门槛的决策（离线模拟）
            probed_now=int(probed_now), send_now=int(probed_now and ch.dis_unet >= 60),
            esc_now=int(probed_now and ch.dis_unet >= 100),
            judge_changed=int(cp.chosen_by == "unet"),
            # ---- 信号：U-Net 类
            dis=ch.dis_unet, agree=ag,
            agree_margin=(ag - max(oth_ag)) if oth_ag and not np.isnan(ag) else np.nan,
            agree_best_other=max(oth_ag) if oth_ag else np.nan,
            dis_min=min(c.dis_unet for c in cp.candidates if c.dis_unet is not None),
            dis_straight=next((c.dis_unet for c in cp.candidates if c.kind == "straight"), np.nan),
            # ---- 信号：几何/候选（不要 U-Net）
            n_geo=n_geo, n_total=len(cp.candidates), kind=ch.kind, chosen_by=cp.chosen_by or "rule",
            seam_ink=ch.seam_ink, dev_max=ch.dev_max,
            seam_ink_max=max(c.seam_ink for c in geo) if geo else 0,
            dev_max_any=max(c.dev_max for c in geo) if geo else 0,
            hu=hu, hd=hd, dev_h=dev_h, h_min=min(hu, hd), h_max=max(hu, hd),
            ink_up=up.ink_ratio, ink_dn=dn.ink_ratio, ink_min=min(up.ink_ratio, dn.ink_ratio),
            kind_up=up.kind, kind_dn=dn.kind, sub_up=int(up.sub is not None), sub_dn=int(dn.sub is not None),
            raised_up=int(up.raised), raised_dn=int(dn.raised),
            suspect_up=int(up.suspect_jiazhu_body), suspect_dn=int(dn.suspect_jiazhu_body),
            origin=cp.origin, pos_rel=cp.k / max(1, cc.n_body_slots), is_tail=int(dn.slot == max(slots)),
            n_cuts_col=len(cc.cut_candidates), period=P, col_h=float(cc.boundaries[-1]),
            width_rel=(up.x1 - up.x0) / max(1.0, float(cc.ref_w or (up.x1 - up.x0))),
        )
        rows.append(row)
    return pd.DataFrame(rows), drops


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "experiments/step3_cutgate/out/table.csv"))
    a = ap.parse_args()
    lab = load_labels()
    print("标签条数:", len(lab), collections.Counter(r["src"] for r in lab.values()))
    df, drops = build(lab, ProductStore())
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(a.out, index=False)
    print("入表:", len(df), df.groupby("src").size().to_dict())
    print("丢弃:", dict(drops))
    print("lab_verdict 阳性率", df.lab_verdict.mean().round(3), "lab_cur 阳性率", df.lab_cur.mean().round(3))
    print("chosen_by:", df.chosen_by.value_counts().to_dict())


if __name__ == "__main__":
    main()
