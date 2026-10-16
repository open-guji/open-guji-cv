"""多层削位 vs Step1 内框线位置:bottom 端 cut 与 (列高 - border_bottom_in_column) 比,看"以内框线为上限"能否分开伤字端。
用法: python3 -I inner_cap.py <items.jsonl>"""
import sys, json, re
import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.spec import page_key
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext
from open_guji_cv.products.store import ProductStore
from open_guji_cv.products.cache import ImageCache
ctx = RunContext(load_book("vol02"), ProductStore(), ImageCache(), log=lambda s: None)
rows = []
for l in open(sys.argv[1], encoding="utf-8"):
    d = json.loads(l)
    if d["input"]["source"] != "L3-batch": continue
    e = d["expected"]
    if e["end"] != "bot": continue
    _, pg, col, end = d["id"].split(":"); pg, col = int(pg), int(col)
    wins = ctx.store.read("vol02", "column_warp", page_key(pg), "column_windows")
    w = next(x for x in wins.columns if x.col == col)
    H = w.warped_size[1]; inner = H - w.border_bottom_in_column
    px = int(e["engine_trim_px"]); case = e["engine_trim_case"]
    rows.append((d["id"], case, e["class"], px, round(inner, 1), round(px - inner, 1)))
import collections
print("bottom 端 n=", len(rows))
for r in sorted(rows, key=lambda r: -r[5])[:25]: print(r)
print("--- 多层(层数≥2) 的 cut-inner 分布")
ml = [r for r in rows if int(re.sub(r"\D", "", r[1]) or 1) >= 2]
print(sorted(r[5] for r in ml))
print("伤字端:", [r for r in rows if r[0] in ("vol02:47:2:bot", "vol02:70:8:bot")])
