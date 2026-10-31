"""探针(不是缺陷数):规则削线是否切在连续的墨上。取削线两侧各 K 行的文字带行墨占比,
若线上侧 K 行与下侧 K 行**都**≥T,说明墨跨过了削线(可能切进字或粗框的中间)。
用法: python3 -I cut_probe.py <items.jsonl> <out.json>"""
import sys, json, numpy as np, cv2, collections
import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.spec import column_key, page_key
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext
from open_guji_cv.products.store import ProductStore
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.books.siku_zongmu.column import strip_column_rules
from open_guji_cv.seg.profile import denoise_column, column_text_band, column_row_profile
K, T = 3, 0.10
book = load_book("vol02"); ctx = RunContext(book, ProductStore(), ImageCache(), log=lambda s: None)
res = {}
for l in open(sys.argv[1], encoding="utf-8"):
    d = json.loads(l)
    if d["input"]["source"] != "L3-batch": continue
    _, pg, col, end = d["id"].split(":"); pg, col = int(pg), int(col); e = d["expected"]
    px = int(e["engine_trim_px"])
    try:
        img = cv2.imdecode(np.fromfile(str(ctx.materialize("column_raw", column_key(pg, col))), np.uint8), cv2.IMREAD_GRAYSCALE)
        dn = denoise_column(img); band = column_text_band(dn); nr = strip_column_rules(dn)
        p = column_row_profile(nr, band)
        p = p if end == "top" else p[::-1]
        up = p[max(0, px - K):px]; dn_ = p[px:px + K]
        cross = bool(px > 0 and len(up) and len(dn_) and up.min() >= T and dn_.min() >= T)
        res[d["id"]] = dict(label=e["class"], case=e["engine_trim_case"], px=px, cross=cross,
                            up=[round(float(x), 2) for x in up], down=[round(float(x), 2) for x in dn_])
    except Exception as ex:                                       # noqa: BLE001
        res[d["id"]] = dict(error=f"{type(ex).__name__}: {ex}")
json.dump(res, open(sys.argv[2], "w"), ensure_ascii=False, indent=0)
ok = [v for v in res.values() if "error" not in v]
print("n", len(res), "error", len(res) - len(ok))
c = collections.Counter((v["label"], v["cross"]) for v in ok); print(sorted(c.items()))
print("cross 列表:", [k for k, v in res.items() if v.get("cross")])
