import sys, json
sys.path.insert(0, "/home/user/open-guji-cv")
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext, page_key
from open_guji_cv.products import kinds as _k  # noqa
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.border_detect import BorderDetectStep
from pathlib import Path
out = Path(sys.argv[1]); out.mkdir(exist_ok=True, parents=True)
bk = load_book("vol03"); st = ProductStore(); ctx = RunContext(bk, st, ImageCache(), log=lambda s: None)
step = BorderDetectStep()
for pg in range(1, 111):
    old = st.read("vol03", "border_detect", page_key(pg), "borders")
    r = step.run_page(ctx, pg)
    (out / f"p{pg:04d}.json").write_text(json.dumps({k: v.model_dump() for k, v in r.items()}))
    xo = [round(v.x_at_top) for v in old.verticals]; xn = [round(v.x_at_top) for v in r["borders"].verticals]
    if len(xo) != len(xn) or any(abs(a - b) > 2 for a, b in zip(xo, xn)):
        print(pg, "old", xo, "\n    new", xn, flush=True)
print("done")
