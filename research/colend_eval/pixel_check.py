"""像素核对:对指定端,打印削线前后 -14..+8 行的文字带行墨占比,并估"削线之上、条形框之下的笔画行数"。
框条行:行墨占比≥0.55(见 column_border_trim bar_coverage 口径,探针);笔画行:0.08≤p<0.55。
用法: python3 -I pixel_check.py <id> [<id>...]"""
import sys, numpy as np, cv2
import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.spec import column_key, page_key
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext
from open_guji_cv.products.store import ProductStore
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.books.siku_zongmu.column import strip_column_rules
from open_guji_cv.seg.profile import denoise_column, column_text_band, column_row_profile
book = load_book("vol02"); ctx = RunContext(book, ProductStore(), ImageCache(), log=lambda s: None)
for i in sys.argv[1:]:
    _, pg, col, end = i.split(":"); pg, col = int(pg), int(col)
    wins = ctx.store.read("vol02", "column_warp", page_key(pg), "column_windows")
    w = next(x for x in wins.columns if x.col == col); tr = w.trim_top if end == "top" else w.trim_bottom
    img = cv2.imdecode(np.fromfile(str(ctx.materialize("column_raw", column_key(pg, col))), np.uint8), cv2.IMREAD_GRAYSCALE)
    dn = denoise_column(img); band = column_text_band(dn); nr = strip_column_rules(dn); p = column_row_profile(nr, band)
    p = p if end == "top" else p[::-1]; px = int(tr.px)
    seg = p[max(0, px - 14):px + 8]
    print(i, tr.case, "cut", px)
    print("  行墨占比(cut-14..cut+7):", " ".join(f"{v:.2f}" for v in seg))
    # 削线紧上方连续的"笔画行"(0.08<=p<0.55)
    k = px - 1; n = 0
    while k >= 0 and 0.08 <= p[k] < 0.55: n += 1; k -= 1
    # 削线紧下方连续的行(字身起笔)
    m = px; d = 0
    while m < len(p) and p[m] >= 0.08: d += 1; m += 1
    print(f"  削线紧上方连续笔画行(0.08≤p<0.55): {n};紧下方连续墨行: {d}")
