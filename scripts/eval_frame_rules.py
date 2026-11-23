"""框型规则前后对比（2026-11-23，CV1）：用标注包里的原图直接跑 detect_borders，对 layout-gold 的 frame 字段评测。
用法：python frame_eval.py [--out report.json]"""
import json, sys, glob, os, re, statistics as st
from collections import defaultdict
import numpy as np, cv2
from open_guji_cv.impl.keben.border import detect_borders
from open_guji_cv.products.kinds.borders import Borders
from open_guji_cv.eval import layout_gold as lg, layout_metrics as lm

GOLD = os.environ.get("FRAME_GOLD", "open-guji-dataset/layout/items.jsonl")          # layout-gold
PACKS = glob.glob(os.environ.get("FRAME_IMG_GLOB", "标注包_*/*.png"))                 # 金标对应的原图（标注包里的 png）
IMG = {os.path.basename(p)[:-4]: p for p in PACKS}   # qtw005_0018 -> path


def family(book):
    return re.sub(r"\d+$", "", book) if not book.startswith("vol") else "vol"


# 套书规则（实验用；落地后写进各书册配置）
RULES = {
    "vol": dict(frame_layers={"top": 2, "bottom": 2}, side_frame={"even": "left", "odd": "right"}),
    "qtw": dict(frame_layers={"top": 2, "bottom": 2}, side_frame={"even": "left", "odd": "right"}),
    "sj": dict(frame_layers={"top": 2, "bottom": 2}, side_frame={"odd": "left", "even": "right"}),
    "mj": dict(frame_layers={"top": 1, "bottom": 1}, side_frame={"even": "left"}),
}


def gaps_from_gold(items):
    """每套书 outer_gap（上/下/侧）：金标 double 页外框到内框的中位距离（标定值，换书重标）。"""
    acc = defaultdict(lambda: defaultdict(list))
    for it in items:
        e = it["expected"]; fr = e.get("frame") or {}
        fam = family(it["anchor"]["book"])
        for side in ("top", "bottom"):
            f = fr.get(side) or {}
            ln = e.get(side)
            if f.get("kind") == "double" and f.get("outer") and ln:
                y_in = np.mean([p[1] for p in ln["pts"]]); y_out = np.mean([p[1] for p in f["outer"]["pts"]])
                acc[fam][side].append(abs(y_out - y_in))
        vl = e.get("vlines") or []
        for side, idx in (("left", -1), ("right", 0)):
            f = fr.get(side) or {}
            if f.get("kind") == "double" and f.get("outer") and vl:
                x_in = np.mean([p[0] for p in vl[idx]["pts"]]); x_out = np.mean([p[0] for p in f["outer"]["pts"]])
                acc[fam]["side"].append(abs(x_out - x_in))
    return {fam: {k: float(np.median(v)) for k, v in d.items() if v} for fam, d in acc.items()}


def run(items, rule, gaps):
    recs = []
    for it in items:
        a = it["anchor"]; key = f'{a["book"]}_{a["page"]:04d}'
        if key not in IMG:
            continue
        g = dict(it["expected"], book=a["book"], stratum=it.get("stratum"))
        gray = cv2.imread(IMG[key], cv2.IMREAD_GRAYSCALE)
        ncols = g.get("n_cols") or 9
        fam = family(a["book"])
        kw = {}
        if rule and fam in RULES:
            r = RULES[fam]
            kw = dict(frame_layers=r["frame_layers"], book_outer_gap=gaps.get(fam),
                      outer_side=r["side_frame"].get("even" if a["page"] % 2 == 0 else "odd"))
        try:
            res = detect_borders(gray, expected_cols=ncols, **kw)
        except Exception as ex:
            print("FAIL", key, ex, file=sys.stderr); continue
        b = Borders.from_result(res, ncols)
        d = lg.doc_from_borders(b, None)
        m = lm.page_metrics(g, d)
        m["key"] = f'{a["book"]}/{a["page"]}'; m["family"] = fam
        m["gold_type"] = g.get("page_type")
        recs.append(m)
    return recs


def summarize(recs):
    out = {}
    for fam in sorted({r["family"] for r in recs}) + ["ALL"]:
        rs = [r for r in recs if fam == "ALL" or r["family"] == fam]
        body = [r for r in rs if r["gold_type"] == "body"]
        for name, sub in (("body", body), ("all", rs)):
            fr = [r["frame"] for r in sub if r.get("frame")]
            sides = defaultdict(lambda: [0, 0]); outer = []
            for f in fr:
                for s, x in f.items():
                    sides[s][1] += 1; sides[s][0] += int(x["ok"])
                    if x.get("outer"): outer.append(x["outer"]["med"])
            tot = [sum(v[0] for v in sides.values()), sum(v[1] for v in sides.values())]
            out[f"{fam}/{name}"] = dict(
                pages=len(fr), kind_acc=round(tot[0] / tot[1], 3) if tot[1] else None,
                by_side={s: f"{v[0]}/{v[1]}" for s, v in sorted(sides.items())},
                outer_med_px=round(st.median(outer), 1) if outer else None, outer_n=len(outer))
    return out


if __name__ == "__main__":
    items = [json.loads(l) for l in open(GOLD)]
    items = [i for i in items if i.get("status") == "active" and (i["expected"].get("frame"))]
    gaps = gaps_from_gold(items)
    print("outer_gap 标定值：", json.dumps(gaps, ensure_ascii=False))
    base = run(items, False, gaps); new = run(items, True, gaps)
    sb, sn = summarize(base), summarize(new)
    for k in sb:
        print(f"{k:12s} 前 {json.dumps(sb[k], ensure_ascii=False)}\n{'':12s} 后 {json.dumps(sn[k], ensure_ascii=False)}")
    wrong = [(r["key"], {s: (x["gold"], x["pred"]) for s, x in r["frame"].items() if not x["ok"]}) for r in new if r.get("frame") and any(not x["ok"] for x in r["frame"].values())]
    print("规则后仍错的页：")
    for w in wrong: print(" ", w)
    json.dump(dict(gaps=gaps, before=sb, after=sn, still_wrong=wrong), open(sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--out" else "frame_report.json", "w"), ensure_ascii=False, indent=1)
