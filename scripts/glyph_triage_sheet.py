"""分诊结果出联系表：每卡一格 = 本例 | 本书对手 | 字体(定的字) | 字体(OCR1) | 字体(CNN1)，下注文字。

    GUJI_WORKSPACE=<书目录> PYTHONPATH=. python scripts/glyph_triage_sheet.py tri.jsonl out_prefix cat[,cat] [per_page]

配 scripts/glyph_triage.py 用。字体取康熙字典體（本机比对用，不进产物），缺字退 Jigmo。
"""
import io, json, sqlite3, sys
import cv2, numpy as np
from PIL import Image, ImageDraw, ImageFont
from open_guji_cv.core.workspace import glyph_db_path
from open_guji_cv.clustering.glyph_selfcheck import font_renderer

from open_guji_cv.clustering.glyph_selfcheck import _font_root
F = ImageFont.truetype(str(_font_root() / "iming/I.Ming-8.10.ttf"), 15)
FS = ImageFont.truetype(str(_font_root() / "iming/I.Ming-8.10.ttf"), 12)
c = sqlite3.connect(f"file:{glyph_db_path()}?mode=ro", uri=True)
kx = font_renderer("kangxi")
jg = font_renderer("jigmo")
T = 80


def crop(img):
    ys, xs = np.where(img < 128)
    if len(ys) == 0:
        return img
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    s = int(max(y1 - y0, x1 - x0) * 1.25) + 4
    cv = np.full((s, s), 255, np.uint8)
    oy, ox = (s - (y1 - y0)) // 2, (s - (x1 - x0)) // 2
    cv[oy:oy + y1 - y0, ox:ox + x1 - x0] = img[y0:y1, x0:x1]
    return cv


def patch(iid):
    r = c.execute("SELECT patch_png FROM instances WHERE instance_id=?", (iid,)).fetchone() if iid else None
    if not r:
        return None
    return crop(cv2.imdecode(np.frombuffer(r[0], np.uint8), cv2.IMREAD_GRAYSCALE))


def font(ch):
    if not ch:
        return None
    for r in (kx, jg):
        if r and r.has(ch):
            im = r.render(ch)
            if im is not None:
                return crop(im)
    return None


def tile(a):
    t = np.full((T, T), 235, np.uint8)
    if a is not None:
        a = cv2.resize(a, (T - 4, T - 4), interpolation=cv2.INTER_AREA)
        t[2:-2, 2:-2] = a
    return t


rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
cats = set(sys.argv[3].split(","))
per = int(sys.argv[4]) if len(sys.argv) > 4 else 24
rows = [r for r in rows if r["cat"] in cats]
rows.sort(key=lambda r: -r["score"])
rival = {}
for ln in open(str(glyph_db_path().parent / "glyph_selfcheck" / "findings.jsonl"), encoding="utf-8"):
    d = json.loads(ln)
    rival[d["key"]] = d.get("rival_peer") or ""
W = 5 * T + 10
H = T + 34
for pg in range(0, len(rows), per):
    chunk = rows[pg:pg + per]
    ncol = 2
    nrow = (len(chunk) + 1) // 2
    img = Image.new("L", (ncol * (W + 20), nrow * (H + 8)), 255)
    d = ImageDraw.Draw(img)
    for n, r in enumerate(chunk):
        x0 = (n % ncol) * (W + 20)
        y0 = (n // ncol) * (H + 8)
        o1 = r["ocr"][0][0] if r["ocr"] else ""
        k1 = r["cnn"][0][0] if r["cnn"] else ""
        tiles = [patch(r["instance_id"]), patch(rival.get(r["key"])), font(r["char"]), font(o1), font(k1)]
        for i, t in enumerate(tiles):
            img.paste(Image.fromarray(tile(t)), (x0 + i * (T + 2), y0))
        d.text((x0, y0 + T + 1), f"#{pg + n} 定{r['char']} 本{r.get('witness') or '-'} 对{r.get('rival_char') or '-'} "
               f"OCR{o1}{(r['ocr'][0][1] if r['ocr'] else 0):.2f} CNN{k1}{(r['cnn'][0][1] if r['cnn'] else 0):.2f}",
               fill=0, font=F)
        d.text((x0, y0 + T + 18), f"{r['instance_id']} {r['provenance'][:5]} {','.join(f[:5] for f in r['flags'])}",
               fill=90, font=FS)
    img.save(f"{sys.argv[2]}_{pg // per}.png")
    print(f"{sys.argv[2]}_{pg // per}.png", len(chunk))
