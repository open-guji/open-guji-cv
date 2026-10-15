"""T9 与过切提示的纯几何重叠（只读，不写产物；Elena 208cz 条件 2）。
用法：GUJI_PRODUCTS_DIR=<沙箱根> python t11_t9_overlap.py <book> [页起 页止]
口径：hint 几何命中集（_oversplit_pairs，不看 admit）∩ T9 命中集（cells 里 高<runt_ratio×period 等，同 _runt_cell_pass）。
状态：只做过 py_compile，未在真书上跑；id→(col,slot) 按 "书:页:列:槽" 末两段解析，真书上若形式不同请先对。"""
import re
import sys

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
from open_guji_cv.steps.seed_admit import SeedAdmitParams, _oversplit_pairs


def main(book, lo=1, hi=9999):
    ctx = RunContext(load_book(book), ProductStore(), ImageCache(), log=lambda s: None)
    p = SeedAdmitParams(db_path="x", oversplit_gate="hint")
    tot = dict(pages=0, hint=0, t9=0, both=0)
    for pg in range(lo, hi + 1):
        try:
            ci = ctx.product("char_index", pg)
            cells = ctx.product("cells", pg)
        except Exception:
            continue
        tot["pages"] += 1
        hint = set()
        for cid in _oversplit_pairs(p, ci):
            col, slot = cid.split(":")[-2:]
            hint.add((int(col), int(re.sub(r"\D", "", slot))))
        t9 = set()
        for cc in cells.columns:
            if not cc.ok or not cc.period or not cc.n_body_slots:
                continue
            for x in cc.cells:
                if (x.slot > 0 and x.kind == "char" and not x.raised and not x.flags
                        and x.ink_ratio >= p.runt_min_ink and (x.y1 - x.y0) < p.runt_ratio * cc.period):
                    t9.add((cc.col, x.slot))
        tot["hint"] += len(hint)
        tot["t9"] += len(t9)
        tot["both"] += len(hint & t9)
    print(book, tot)


if __name__ == "__main__":
    main(sys.argv[1], *(int(a) for a in sys.argv[2:4]))
