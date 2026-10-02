"""Y1：用生产代码（`cell_shrink._YoloPage/_yolo_ratio`）逐格量 YOLO 框比 CV 紧框多出的墨占比。

    GUJI_WORKSPACE=<工作区> GUJI_PRODUCTS_DIR=<快照 products 的上级> \
    python y1_calibrate.py <book> <页号,页号|all> <out.jsonl> [slide权重 [type权重]]

输出每页一行 JSON：{page, seal(seal_region 格数), rows:[{id, ratio|null, yolo, cv, flags…}]}；可续跑。
权重默认 /home/user/yolo_tool/model/{slide,type}/best.onnx。
"""
import sys, json, time, os
import numpy as np
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext
from open_guji_cv.products.store import ProductStore
from open_guji_cv.products.cache import ImageCache
from open_guji_cv import steps  # noqa
from open_guji_cv.steps import cell_shrink as cs
from open_guji_cv.steps._warpmap import ColumnMapper
book, pages, out = sys.argv[1], sys.argv[2], sys.argv[3]
SL = sys.argv[4] if len(sys.argv) > 4 else "/home/user/yolo_tool/model/slide/best.onnx"
LY = sys.argv[5] if len(sys.argv) > 5 else "/home/user/yolo_tool/model/type/best.onnx"
ctx = RunContext(load_book(book), ProductStore(), ImageCache(), log=lambda *_: None)
P = os.environ["GUJI_PRODUCTS_DIR"]
pl = sorted(int(f[1:5]) for f in os.listdir(f"{P}/{book}/cell_shrink") if f.startswith("p") and f.endswith(".json")) if pages == "all" else [int(x) for x in pages.split(",")]
done = set()
if os.path.exists(out):
    done = {json.loads(l)["page"] for l in open(out)}
fo = open(out, "a")
for pg in pl:
    if pg in done: continue
    t0 = time.time()
    try:
        ci = ctx.product("char_index", pg); cells = ctx.product("cells", pg); wins = ctx.product("column_windows", pg)
    except Exception as e:
        print("skip", pg, e, file=sys.stderr); continue
    from open_guji_cv.steps.occlusion import page_occluded
    from open_guji_cv.steps.seed_admit import SeedAdmitParams
    seal_n = len(page_occluded(ctx, pg, SeedAdmitParams()))    # 与 cell_shrink.run_page 同一入口
    raw = ctx.raw_page(pg)
    t1 = time.time(); yp = cs._YoloPage.of((SL, LY), raw); tdet = time.time() - t1
    rows = []
    for col in ci.columns:
        if not col.ok: continue
        cc = cells.column(col.col); wrec = wins.column(col.col)
        if wrec is None: continue
        mapper = ColumnMapper(wins.page_size[0], wrec.left_line.to_vline(), wrec.right_line.to_vline(), wrec.top_y, wrec.bottom_y)
        x_lo, x_hi = cc.content_x or (0.0, 200.0)
        rect = {c.pos: (float(x_lo), float(c.y0), float(x_hi), float(c.y1)) for c in cc.cells}
        first_pos, last_pos = min(c.pos for c in cc.cells), max(c.pos for c in cc.cells)
        for r in col.chars:
            if r.sub or r.cell_type != "char" or r.pos not in rect: continue
            ratio0, y = cs._yolo_ratio(yp, mapper, r.bbox_col, rect[r.pos])
            ratio, _ = cs._yolo_ratio(yp, mapper, r.bbox_col, rect[r.pos], r.pos == first_pos, r.pos == last_pos)
            rows.append(dict(id=r.id, page=pg, col=col.col, slot=r.slot, ratio=ratio, ratio0=ratio0, edge="first" if r.pos == first_pos else ("last" if r.pos == last_pos else ""), yolo=y, flags=r.flags, step3=r.step3_kind,
                             cv=list(r.bbox_col)))
    fo.write(json.dumps(dict(page=pg, seal=seal_n, tdet=round(tdet, 2), t=round(time.time() - t0, 2), rows=rows), ensure_ascii=False) + "\n"); fo.flush()
    print(pg, len(rows), seal_n, round(tdet, 2), round(time.time() - t0, 2), file=sys.stderr)
