"""按格号清单从产物＋原图导出字块 PNG（A24 第 4 轮）。

    GUJI_WORKSPACE=… GUJI_PRODUCTS_DIR=… python dump_patches.py <ids.txt|cells.json> <输出目录>

ids 每行一个格号 volNN:页:列:slot[a|b]；cells.json 是 [{id,…}]。输出 `<id 把 : 换成 _>.png`（和 book_knn_train 对口）。
已存在的跳过；读不到的写进 <输出目录>/_missing.txt。"""
import json, sys, re
from pathlib import Path
from open_guji_cv.core.book import load_book
from open_guji_cv.core.spec import cell_key
from open_guji_cv.core.step import RunContext
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore

src, out = sys.argv[1], Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
ids = [c["id"] for c in json.load(open(src))] if src.endswith(".json") else [l.strip() for l in open(src) if l.strip()]
byvol = {}
for i in ids:
    byvol.setdefault(i.split(":")[0], []).append(i)
miss = []
st, cache = ProductStore(), ImageCache()
for vol, lst in sorted(byvol.items()):
    ctx = RunContext(load_book(vol), st, cache, log=lambda s: None)
    for i in lst:
        dst = out / (i.replace(":", "_") + ".png")
        if dst.exists():
            continue
        m = re.fullmatch(r"vol\d+:(\d+):(\d+):(-?\d+)([ab]?)", i)
        key = cell_key(int(m[1]), int(m[2]), int(m[3])) + m[4]
        try:
            f = cache.get(vol, "char_patch", key) or ctx.materialize("char_patch", key)
            dst.write_bytes(Path(f).read_bytes())
        except Exception as e:  # noqa: BLE001
            miss.append(f"{i}\t{type(e).__name__}")
    print(vol, len(lst), file=sys.stderr)
(out / "_missing.txt").write_text("\n".join(miss))
print("missing", len(miss))
