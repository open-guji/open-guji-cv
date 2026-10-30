"""对全部 L3-batch 端:①核对标签里的 engine_trim_px/case 与 snap 产物一致;②削线紧上方连续"笔画行"(0.08≤p<0.55)数。
输出 all_pixel.json。用法: python3 -I all_pixel.py <items.jsonl> <out.json>"""
import sys, json, numpy as np, cv2, collections
import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.spec import column_key, page_key
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext
from open_guji_cv.products.store import ProductStore
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.books.siku_zongmu.column import strip_column_rules
from open_guji_cv.seg.profile import denoise_column, column_text_band, column_row_profile
book = load_book("vol02"); ctx = RunContext(book, ProductStore(), ImageCache(), log=lambda s: None)
out = {}; mism = []
for l in open(sys.argv[1], encoding="utf-8"):
    d = json.loads(l)
    if d["input"]["source"] != "L3-batch": continue
    _, pg, col, end = d["id"].split(":"); pg, col = int(pg), int(col); e = d["expected"]
    wins = ctx.store.read("vol02", "column_warp", page_key(pg), "column_windows")
    w = next(x for x in wins.columns if x.col == col); tr = w.trim_top if end == "top" else w.trim_bottom
    if (tr.case, int(tr.px)) != (e["engine_trim_case"], int(e["engine_trim_px"])): mism.append((d["id"], (tr.case, tr.px), (e["engine_trim_case"], e["engine_trim_px"])))
    img = cv2.imdecode(np.fromfile(str(ctx.materialize("column_raw", column_key(pg, col))), np.uint8), cv2.IMREAD_GRAYSCALE)
    dn = denoise_column(img); band = column_text_band(dn); nr = strip_column_rules(dn); p = column_row_profile(nr, band)
    p = p if end == "top" else p[::-1]; px = int(tr.px)
    k = px - 1; n = 0
    while k >= 0 and 0.08 <= p[k] < 0.55: n += 1; k -= 1
    out[d["id"]] = dict(label=e["class"], case=tr.case, px=px, stroke_rows_above=n if px else 0)
json.dump(dict(items=out, mismatch=mism), open(sys.argv[2], "w"), ensure_ascii=False)
print("n", len(out), "label-vs-product 不一致:", len(mism), mism[:5])
c = collections.Counter(min(v["stroke_rows_above"], 12) for v in out.values() if v["px"]); print("cut>0 的端按'削线紧上方连续笔画行'分布:", sorted(c.items()))
print("≥8 行:", sorted([(k, v["case"], v["px"], v["stroke_rows_above"], v["label"]) for k, v in out.items() if v["stroke_rows_above"] >= 8], key=lambda x: -x[3]))
