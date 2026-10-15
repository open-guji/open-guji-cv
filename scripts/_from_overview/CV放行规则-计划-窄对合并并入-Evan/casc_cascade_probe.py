"""级联实测：repo mode productsdir。mode=build|status|run"""
import sys, os, json
repo, mode, prod = sys.argv[1], sys.argv[2], sys.argv[3]
sys.path[:0] = [repo, repo + "/tests"]
os.environ["GUJI_PRODUCTS_DIR"] = prod + "/products"; os.environ["GUJI_CACHE_DIR"] = prod + "/cache"
from pathlib import Path
import open_guji_cv.steps  # noqa
from helpers import make_book, synth_page
from open_guji_cv.core.engine import Engine
from open_guji_cv.core.pipeline import load_pipeline
from open_guji_cv.products.store import ProductStore
from open_guji_cv.products.cache import ImageCache
pipe = load_pipeline("keben_body_v2")
keep = ["page_survey", "border_detect", "column_warp", "row_segment", "cell_shrink"]
pipe.steps = [s for s in pipe.steps if s in keep]
book = make_book("casc", expected_cols=9)
over = json.loads(sys.argv[4]) if len(sys.argv) > 4 else None
eng = Engine(book, pipe, ProductStore(Path(prod) / "products"), ImageCache(Path(prod) / "cache"),
             params=over, log=lambda s: None)
pages = [1, 2]
for p in pages:
    gray, _ = synth_page(n_cols=9)
    eng.ctx._raw[p] = gray
if mode in ("build", "run"):
    rep = eng.run(pages=pages)
    print(json.dumps({s: v for s, v in rep.counts().items()}, ensure_ascii=False))
else:
    st = eng.status(pages=pages)
    out = {}
    for sid, row in st["steps"].items() if "steps" in st else st.items():
        if not isinstance(row, dict): continue
        out[sid] = {"counts": row.get("counts"), "reasons": row.get("stale_reasons")}
    print(json.dumps(out, ensure_ascii=False))
