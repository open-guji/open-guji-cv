"""在进程内批量重建线上字块（char_patch）：python mat.py <ids 文件，一行一个 vol:page:col:slot> <输出目录>"""
import sys, collections, shutil, re
from pathlib import Path
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext
from open_guji_cv.core.spec import cell_key
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
ids = [l.strip() for l in open(sys.argv[1]) if l.strip()]
out = Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
st, cache = ProductStore(), ImageCache()
byb = collections.defaultdict(list)
for i in ids:
    if not (out / (i.replace(":", "_") + ".png")).exists():
        byb[i.split(":")[0]].append(i)
ok = bad = 0
for b, L in sorted(byb.items()):
    try:
        ctx = RunContext(load_book(b), st, cache, log=lambda s: None)
    except Exception as e:
        print("book", b, e); bad += len(L); continue
    for i in sorted(L, key=lambda s: (int(s.split(":")[1]), int(s.split(":")[2]))):
        _, p, c, s = i.split(":")
        m = re.match(r"(-?\d+)([ab]?)", s)
        key = cell_key(int(p), int(c), int(m.group(1))) + m.group(2)
        try:
            f = ctx.materialize("char_patch", key)
            shutil.copy(f, out / (i.replace(":", "_") + ".png")); ok += 1
        except Exception as e:
            bad += 1
    print(b, "ok", ok, "bad", bad, flush=True)
