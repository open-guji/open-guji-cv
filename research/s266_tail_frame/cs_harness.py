"""Step4 内存重跑：cells 取自 CELLDIR（rs_harness 的输出），图块写进 GUJI_CACHE_DIR。输出 char_index JSON。
用法: cs_harness.py CELLDIR OUTDIR pages..."""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext
from open_guji_cv.products import kinds as _k  # noqa
from open_guji_cv.products.kinds.cells import PageCells
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.cell_shrink import CellShrinkStep
C, O = Path(sys.argv[1]), Path(sys.argv[2]); O.mkdir(parents=True, exist_ok=True)
class Ctx(RunContext):
    def product(self, kind_id, page):
        if kind_id == "cells":
            return PageCells.model_validate_json((C / f"p{page:04d}.json").read_text())
        return super().product(kind_id, page)
ctx = Ctx(load_book("vol03"), ProductStore(), ImageCache(), log=lambda s: None)
step = CellShrinkStep()
for pg in map(int, sys.argv[3:]):
    out = step.run_page(ctx, pg)["char_index"]
    (O / f"p{pg:04d}.json").write_text(out.model_dump_json())
print("ok")
