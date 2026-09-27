# -*- coding: utf-8 -*-
"""码位习惯普查：内/內 这类「同字两码」在库、人裁、OCR、整理本里各用哪个（字形库 11，只读）。

    GUJI_WORKSPACE=<书目录> GUJI_GLYPH_DB=<glyph.db> PYTHONPATH=. python scripts/glyph_codepoint_census.py \
        --books vol01,vol02,vol03 [--ocr-products <产物目录>] [--ocr-lib] [--sheet-dir <目录>] [--out 报告.json]

- 库：`instances.label` 计数，按来路分 v1 / v2（人裁）/ 其余；
- 人裁：`feedback.lookup.human_chars(book, bind=False)`（每格最后一条定字事件，不过绑定表）；
- OCR：两种口径，给了哪个报哪个——
  - `--ocr-products`：Step5-c 产物（`ocr_candidates`）逐格 top-1（这本书开了 OCR 才有）；
  - `--ocr-lib`：拿 PP-OCRv5（Step5-c 同款引擎）对**库里标成这几对字**的刻例现算 top-1；
- 整理本：册配置 `references` 里每份语料的字频（整份语料，不限册）。
- `--sheet-dir`：每对出一张样图（每个码位最多 6 张库刻例，附实例 id）。

**只读**：不改库、不写事件。定码位是用户的事（字形库 11 草案）。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

PAIRS = [("内", "內"), ("别", "別"), ("眞", "真"), ("戸", "戶"), ("强", "強"), ("届", "屆"), ("却", "卻"),
         # 08 卡 label 对齐时碰到的几对，一并数
         ("注", "註"), ("决", "決"), ("歴", "歷"), ("竒", "奇"), ("况", "況")]


def _src_kind(iid: str) -> str:
    p = iid.split(":")
    if p[0] == "v2":
        return "v2"
    if len(p) == 4 and p[0].startswith("vol"):
        return "v1"
    return "other"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--books", required=True, help="逗号分隔的册 id（人裁、OCR 产物按它读）")
    ap.add_argument("--ocr-products", type=Path)
    ap.add_argument("--ocr-lib", action="store_true")
    ap.add_argument("--sheet-dir", type=Path)
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.workspace import corpus_path, glyph_db_path
    from open_guji_cv.feedback.lookup import human_chars

    chars = {c for p in PAIRS for c in p}
    books = a.books.split(",")
    db = sqlite3.connect(f"file:{glyph_db_path()}?mode=ro", uri=True)
    lib = defaultdict(Counter)
    lib_ids = defaultdict(list)
    for iid, lab in db.execute("SELECT instance_id, label FROM instances WHERE instance_id NOT LIKE 'font:%'"):
        if lab in chars:
            lib[lab][_src_kind(iid)] += 1
            lib_ids[lab].append(iid)

    human = Counter()
    for b in books:
        for _k, ch in human_chars(b, bind=False).items():
            if ch in chars:
                human[ch] += 1

    ocr_prod = Counter()
    if a.ocr_products:
        for b in books:
            for f in sorted((a.ocr_products / b / "ocr_candidates").glob("p*.json")):
                d = json.loads(f.read_text(encoding="utf-8")).get("ocr_candidates") or {}
                for col in d.get("columns", []):
                    for r in col.get("chars", []):
                        if r.get("topk") and r["topk"][0][0] in chars:
                            ocr_prod[r["topk"][0][0]] += 1

    ocr_lib = defaultdict(Counter)      # 库字头 → OCR top-1 计数
    if a.ocr_lib:
        from open_guji_cv.clustering.candidates import PaddleOcrSource
        import cv2
        import numpy as np
        src = PaddleOcrSource()     # 不做简繁转换：要看的正是 OCR 吐哪个码位
        for lab, ids in lib_ids.items():
            for iid in ids:
                r = db.execute("SELECT patch_png FROM instances WHERE instance_id=?", (iid,)).fetchone()
                img = cv2.imdecode(np.frombuffer(r[0], np.uint8), cv2.IMREAD_GRAYSCALE)
                top = src.rec_topk(_crop(img))
                ocr_lib[lab][top[0][0] if top else "∅"] += 1
        src.close()

    corpus = {}
    for ref in load_book(books[0]).references:
        f = corpus_path(ref["file"] if isinstance(ref, dict) else ref.file)
        txt = f.read_text(encoding="utf-8")
        corpus[f.name] = {c: txt.count(c) for c in chars}

    rep = []
    for x, y in PAIRS:
        row = {"pair": f"{x}/{y}"}
        for c in (x, y):
            row[c] = {"库": dict(lib[c]), "库计": sum(lib[c].values()), "人裁": human[c],
                      **({"OCR产物": ocr_prod[c]} if a.ocr_products else {}),
                      **({"OCR看库": dict(ocr_lib[c].most_common(4))} if a.ocr_lib else {}),
                      "整理本": {k: v[c] for k, v in corpus.items()}}
        rep.append(row)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    if a.out:
        a.out.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.sheet_dir:
        _sheets(a.sheet_dir, db, lib_ids)
    return 0


def _crop(img):
    """墨框外扩 1.3 倍居中贴白底（与 glyph_triage.crop 同口径）。"""
    import numpy as np
    ys, xs = np.where(img < 128)
    if len(ys) == 0:
        return img
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    s = int(max(y1 - y0, x1 - x0) * 1.3) + 4
    cv = np.full((s, s), 255, np.uint8)
    oy, ox = (s - (y1 - y0)) // 2, (s - (x1 - x0)) // 2
    cv[oy:oy + y1 - y0, ox:ox + x1 - x0] = img[y0:y1, x0:x1]
    return cv


def _sheets(outdir: Path, db, lib_ids) -> None:
    import cv2
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    outdir.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(str(REPO / "fonts/iming/I.Ming-8.10.ttf"), 14)
    # 字头用 Jigmo（按 Unicode 参考字形出图）：I.Ming 是传承字形，真/戶 会画成 眞/戸 的样子，两行看着一样
    big = ImageFont.truetype(str(REPO / "fonts/jigmo/Jigmo.ttf"), 40)
    T, L = 110, 120
    for x, y in PAIRS:
        rows = []
        for c in (x, y):
            ids = sorted(lib_ids.get(c, []))
            step = max(1, len(ids) // 6)
            pick = ids[::step][:6]
            tile = Image.new("L", (L + 6 * (T + 6), T + 26), 255)
            d = ImageDraw.Draw(tile)
            d.text((10, 20), c, font=big, fill=0)
            d.text((6, T + 6), f"U+{ord(c):04X} n={len(ids)}", font=font, fill=0)
            for i, iid in enumerate(pick):
                r = db.execute("SELECT patch_png FROM instances WHERE instance_id=?", (iid,)).fetchone()
                im = _crop(cv2.imdecode(np.frombuffer(r[0], np.uint8), cv2.IMREAD_GRAYSCALE))
                h, w = im.shape[:2]
                sc = min((T - 4) / w, (T - 4) / h)
                im = cv2.resize(im, (max(1, int(w * sc)), max(1, int(h * sc))), interpolation=cv2.INTER_AREA)
                tile.paste(Image.fromarray(im), (L + i * (T + 6), 2))
                d.text((L + i * (T + 6), T + 6), iid.replace("v2:", "")[:18], font=font, fill=0)
            rows.append(tile)
        sheet = Image.new("L", (rows[0].width, sum(r.height for r in rows)), 255)
        yy = 0
        for r in rows:
            sheet.paste(r, (0, yy))
            yy += r.height
        sheet.save(outdir / f"{x}{y}.png")


if __name__ == "__main__":
    raise SystemExit(main())
