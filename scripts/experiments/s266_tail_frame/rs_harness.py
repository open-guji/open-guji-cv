"""内存重跑 Step3（与 RowSegmentStep.run_page 同一入口），逐页写出 cells JSON，并与磁盘产物比对。
用法: rs_harness.py OUTDIR [pages...]   (无 pages = 全书)
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext, page_key
from open_guji_cv.products import kinds as _k  # noqa
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.row_segment import RowSegmentStep

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
bk = load_book("vol03"); st = ProductStore(); ic = ImageCache()
ctx = RunContext(bk, st, ic, log=lambda s: None)
pages = [int(x) for x in sys.argv[2:]] or list(range(1, 111))
step = RowSegmentStep()
mism = 0
for pg in pages:
    old = st.read("vol03", "row_segment", page_key(pg), "cells")
    if old is None:
        continue
    new = step.run_page(ctx, pg)["cells"]
    (out / f"p{pg:04d}.json").write_text(new.model_dump_json())
    def sig(pc):
        return [(c.col, c.ok, [(x.slot, x.kind, round(x.y0), round(x.y1), round(x.x0), round(x.x1)) for x in c.cells]) for c in pc.columns]
    if sig(old) != sig(new):
        mism += 1
        print("MISMATCH", pg, flush=True)
print("done pages", len(pages), "mismatch", mism)
