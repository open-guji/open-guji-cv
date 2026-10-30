"""对 |dy|>3 的金标/现役不一致条:各自落在不在"零墨走廊"(文字带行墨占比≤0.02 的连续行)里、同走廊内的相对位置。
用法: python3 -I valley_probe.py <report.json> <out.json>   (report 由 eval_cutlines.py --out 产出)"""
import sys, json, collections, statistics as st, numpy as np, cv2
import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext
from open_guji_cv.products.store import ProductStore
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.core.spec import column_key
from open_guji_cv.seg.profile import column_text_band
ctx = RunContext(load_book("vol02"), ProductStore(), ImageCache(), log=lambda s: None)
rep = json.load(open(sys.argv[1])); out = []
for x in [x for x in rep if "dy" in x and abs(x["dy"]) > 3]:
    _, pg, col, slot = x["id"].split(":")
    try: raw = cv2.imdecode(np.fromfile(str(ctx.materialize("column_raw", column_key(int(pg), int(col)))), np.uint8), cv2.IMREAD_GRAYSCALE)
    except Exception as e: out.append(dict(id=x["id"], err=str(e)[:60])); continue
    lo, hi = column_text_band(raw); core = (raw[:, lo:hi] < 128).mean(axis=1)
    def valley(y):
        y = int(round(y))
        if y < 0 or y >= len(core) or core[y] > 0.02: return None
        a = y
        while a > 0 and core[a - 1] <= 0.02: a -= 1
        b = y
        while b < len(core) - 1 and core[b + 1] <= 0.02: b += 1
        return a, b
    vg, ve = valley(x["y_gold"]), valley(x["y_eng"])
    r = dict(id=x["id"], v=x["verdict"], dy=x["dy"], gold_in=vg is not None, eng_in=ve is not None, same=bool(vg and ve and vg == ve))
    if vg: r["gold_pos"] = round((x["y_gold"] - vg[0]) / max(1, vg[1] - vg[0]), 2); r["gold_w"] = vg[1] - vg[0]
    if ve: r["eng_pos"] = round((x["y_eng"] - ve[0]) / max(1, ve[1] - ve[0]), 2); r["eng_w"] = ve[1] - ve[0]
    out.append(r)
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False)
ok = [r for r in out if "err" not in r]
print("n", len(ok), "err", len(out) - len(ok))
print("(gold在走廊, engine在走廊) 计数:", dict(collections.Counter((r["gold_in"], r["eng_in"]) for r in ok)))
sv = [r for r in ok if r["same"]]
if sv: print("同一走廊 n", len(sv), "gold_pos 中位", st.median(r["gold_pos"] for r in sv), "eng_pos 中位", st.median(r["eng_pos"] for r in sv), "走廊宽中位", st.median(r["gold_w"] for r in sv))
