"""叠图:把 column_raw(削版框前)的一端画出来,标规则的削线(trim_px)与 Step1 内框线;用于人眼复核。
用法: GUJI_WORKSPACE=... GUJI_PRODUCTS_DIR=... python3 -I overlay.py <out_dir> <id> [<id>...]   (id 形如 vol02:105:4:bot)"""
import sys, pathlib, cv2, numpy as np
import open_guji_cv.steps  # noqa: F401  注册产物种类(否则 KeyError 未注册的产物种类)
from open_guji_cv.core.spec import column_key, page_key
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext
from open_guji_cv.products.store import ProductStore
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.books.siku_zongmu.column import strip_column_rules
from open_guji_cv.seg.profile import denoise_column, column_text_band
CROP = 220
def make(ctx, book, pg, col, end):
    wins = ctx.store.read(book, "column_warp", page_key(pg), "column_windows")
    w = next(x for x in wins.columns if x.col == col)
    trim = w.trim_top if end == "top" else w.trim_bottom
    path = ctx.materialize("column_raw", column_key(pg, col))
    img = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_GRAYSCALE)
    dn = denoise_column(img); lo, hi = column_text_band(dn)
    full = dn[:, max(0, lo - 12): hi + 12]
    h = full.shape[0]
    crop = full[:CROP] if end == "top" else full[max(0, h - CROP):][::-1]
    vis = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
    vis = cv2.resize(vis, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    y = int(trim.px) * 2
    cv2.line(vis, (0, y), (vis.shape[1], y), (0, 0, 255), 2)            # 红:规则削到这里
    cv2.putText(vis, f"{trim.case} cut={trim.px}", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
    return vis
if __name__ == "__main__":
    out = pathlib.Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
    book = load_book("vol02"); ctx = RunContext(book, ProductStore(), ImageCache(), log=lambda s: None)
    for i in sys.argv[2:]:
        b, pg, col, end = i.split(":")
        try:
            cv2.imwrite(str(out / (i.replace(":", "_") + ".png")), make(ctx, b, int(pg), int(col), end))
            print("ok", i)
        except Exception as e:
            print("FAIL", i, type(e).__name__, e)
