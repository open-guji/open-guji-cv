"""多层累计探针:对规则判多层(层数≥2)的端,用 layers=(1,1) 重算单层削位 px1,看多出来的 (px1,px] 段里
有什么(行墨占比峰值/框条行数)。不改引擎,只调 column_border_trim 的现有参数。
用法: python3 -I layers_probe.py <items.jsonl> <out.json>"""
import sys, json, re, numpy as np, cv2
import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.spec import column_key, page_key
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext
from open_guji_cv.products.store import ProductStore
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.books.siku_zongmu import column as cp
from open_guji_cv.seg import profile as _pf
ctx = RunContext(load_book("vol02"), ProductStore(), ImageCache(), log=lambda s: None)
out = {}
for l in open(sys.argv[1], encoding="utf-8"):
    d = json.loads(l)
    if d["input"]["source"] != "L3-batch": continue
    e = d["expected"]; case = e["engine_trim_case"]
    if int(re.sub(r"\D", "", case) or 1) < 2: continue
    _, pg, col, end = d["id"].split(":"); pg, col = int(pg), int(col); px = int(e["engine_trim_px"])
    img = cv2.imdecode(np.fromfile(str(ctx.materialize("column_raw", column_key(pg, col))), np.uint8), cv2.IMREAD_GRAYSCALE)
    dn = _pf.denoise_column(img); band = _pf.column_text_band(dn); nr = cp.strip_column_rules(dn)
    mp = None
    lo, hi = band
    if lo + (dn.shape[1] - hi) >= cp.MARGIN_MIN_PX:
        b = dn < 128; mp = np.concatenate([b[:, :lo], b[:, hi:]], axis=1).mean(axis=1)
    (t1, tc), (b1, bc) = cp.column_border_trim(nr, band, margin_profile=mp)
    px1 = t1 if end == "top" else b1; c1 = tc if end == "top" else bc
    prof = _pf.column_row_profile(nr, band); prof = prof if end == "top" else prof[::-1]
    seg = prof[px1:px]
    out[d["id"]] = dict(label=e["class"], case=case, px=px, px1=int(px1), case1=c1, delta=px - int(px1),
                        seg_peak=round(float(seg.max()), 2) if len(seg) else 0.0,
                        seg_bar_rows=int((seg >= 0.5).sum()), tail15_peak=round(float(prof[max(0, px-15):px].max()), 2),
                        tail5_mean=round(float(prof[max(0, px-5):px].mean()), 2))
json.dump(out, open(sys.argv[2], "w"), ensure_ascii=False)
print(len(out))
for k, v in sorted(out.items(), key=lambda kv: -kv[1]["delta"]): print(k, v)
