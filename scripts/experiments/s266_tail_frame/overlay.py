"""列图左右两半画 旧(红)/新(绿) 格线与格类型。用法: overlay.py BASE NEW OUTDIR [tail|full] [pg:col ...]"""
import sys, json, cv2, numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from open_guji_cv.core.book import load_book
from open_guji_cv.core.step import RunContext
from open_guji_cv.core.spec import column_key
from open_guji_cv.products import kinds as _k  # noqa
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
M = {'char': 'C', 'blank': '.', 'jiazhu_a': 'a', 'jiazhu_b': 'b', 'jiazhu_solo': 's'}
A, B, O = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]); O.mkdir(parents=True, exist_ok=True)
mode = sys.argv[4]
bk = load_book("vol03"); ctx = RunContext(bk, ProductStore(), ImageCache(), log=lambda s: None)
def col_of(d, col): return next(c for c in d["columns"] if c["col"] == col)
for t in sys.argv[5:]:
    pg, col = map(int, t.split(":"))
    a = col_of(json.loads((A / f"p{pg:04d}.json").read_text()), col)
    b = col_of(json.loads((B / f"p{pg:04d}.json").read_text()), col)
    img = ctx.image("column_image", column_key(pg, col))
    h, w = img.shape
    y0 = 0
    if mode == "tail":
        ba, bbn = a["boundaries"], b["boundaries"]
        diff = [i for i, (x, y) in enumerate(zip(ba, bbn)) if abs(x - y) > 2]
        first = min(diff) if diff else len(ba) - 1
        y0 = int(max(0, min(ba[max(0, first - 2)], bbn[max(0, first - 2)]) - 10))
    crop = cv2.cvtColor(img[y0:], cv2.COLOR_GRAY2BGR)
    canvas = np.full((crop.shape[0], w * 2 + 8, 3), 255, np.uint8)
    canvas[:, :w] = crop; canvas[:, w + 8:] = crop
    for side, c, color in ((0, a, (0, 0, 230)), (1, b, (0, 160, 0))):
        xo = side * (w + 8)
        for cell in c["cells"]:
            if cell["kind"].startswith("jiazhu") and cell["kind"] != "jiazhu_a":
                continue
            ya = int(round(cell["y0"])) - y0
            if ya < 0: continue
            cv2.line(canvas, (xo, ya), (xo + w - 1, ya), color, 2)
            cv2.putText(canvas, f"{cell['slot']}{M[cell['kind']]}", (xo + 2, ya + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        yl = int(round(c["cells"][-1]["y1"])) - y0
        cv2.line(canvas, (xo, yl), (xo + w - 1, yl), color, 2)
        if side == 1 and c.get("flags"):
            yb = int(round(c["border_bottom"])) - y0
            cv2.line(canvas, (xo, yb), (xo + 20, yb), (255, 0, 0), 3)
    cv2.imwrite(str(O / f"p{pg}c{col}.jpg"), canvas, [cv2.IMWRITE_JPEG_QUALITY, 80])
