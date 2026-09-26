"""字形库机器分诊（2026-09-25）：OCR + CNN 两路独立识别 + 整理本对齐字，对照库里定的字。

    GUJI_WORKSPACE=<书目录> PYTHONPATH=. python scripts/glyph_triage.py <out.jsonl> [--all]

不带 --all 只过体检（glyph-db selfcheck）标出、还没裁的卡；带 --all 过全库刻例
（噪声块常是单例、体检标不出来——北行 bxgb:6:11:4 那块污渍就是这样找到的）。
OCR 默认用 **Step5-c 同款引擎 PP-OCRv5 server**（~/paddle-venv 常驻 worker，15,907 字；
2026-09-05 横评比 RapidOCR v4 mobile 高 10 个点）；`--rapid` 退回 v4 mobile（6,278 字，快但弱，
繁体、生僻字大量不可达）。`--only <jsonl>` 只跑其中列出的 instance_id（大书先用 --rapid
全量筛，再对非 agree 的用 v5 复跑）。

分四类：agree（OCR 或 CNN ≥0.5 认定库里的字）/ mislabel（两路一致认成另一个字）/
noise（两路都 <0.3，多半是污渍、残块、切坏）/ unclear。**只是分诊，不改库**；
非 agree 的用 scripts/glyph_triage_sheet.py 出联系表看图再裁（OCR/CNN 对生僻字、
异体、繁简码位都偏，mislabel 里一大半是 内/內、别/別、巳/已 这类码位习惯）。
依赖（仅 --rapid）：rapidocr-onnxruntime（pyproject 的 cpu extra）——装它会顺带装有 GUI 的
opencv-python，与 headless 版冲突、cv2 直接起不来，装完要卸掉 opencv-python
再强装回 opencv-python-headless。
"""
import json, sqlite3, sys
import cv2, numpy as np
import opencc
from open_guji_cv.clustering.glyph_db import _unpng
from open_guji_cv.clustering.glyph_selfcheck import load_findings, decisions
from open_guji_cv.clustering.candidates import RapidOcrSource
from open_guji_cv.clustering.cnn_candidates import shared as cnn_shared
from open_guji_cv.clustering.variants import VariantMap
from open_guji_cv.core.workspace import glyph_db_path

vm = VariantMap.load()
sem = lambda c: vm.semantic(c) if c else c
cc = opencc.OpenCC("s2t")
db = glyph_db_path()
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
from open_guji_cv.clustering.glyph_ledger import _v1_sources  # noqa: E402
V1_IDS = _v1_sources(c)            # 仍是 idx 坐标的 v1 刻例（重键过的已是格号，不再 +1）
meta, rows = load_findings()
dec = decisions()
alive = {r[0] for r in c.execute("SELECT instance_id FROM exemplars")}
rows = [r for r in rows if r["instance_id"] in alive and r["key"] not in dec]
if "--all" in sys.argv:
    # 全库：没被体检标出的刻例也过一遍（噪声块常常是单例、体检标不出来）
    flagged = {r["instance_id"]: r for r in rows}
    fo = {}
    for ln in open(str(db.parent / "glyph_selfcheck" / "findings.jsonl"), encoding="utf-8"):
        pass
    allrows = []
    for iid, ch, prov in c.execute(
            "SELECT e.instance_id, g.char, a.provenance FROM exemplars e JOIN glyphs g USING(glyph_id) "
            "LEFT JOIN admissions a ON a.instance_id=e.instance_id WHERE g.edition_tag NOT LIKE 'font:%'"):
        allrows.append(flagged.get(iid) or {"instance_id": iid, "key": iid, "char": ch,
                                            "provenance": prov or "", "flags": [], "rival_char": None,
                                            "rival": 0, "xrival_char": None, "font_own": None, "score": 0})
    rows = allrows
if "--only" in sys.argv:
    want = {json.loads(l)["instance_id"] for l in open(sys.argv[sys.argv.index("--only") + 1], encoding="utf-8")}
    rows = [r for r in rows if r["instance_id"] in want]

from open_guji_cv.clustering.candidates import PaddleOcrSource
ocr = PaddleOcrSource(topk=5) if "--rapid" not in sys.argv else RapidOcrSource(topk=5)
ocr._ensure()
cnn = cnn_shared()
cnn._ensure()
classes = list(cnn._classes) if cnn.available else []
from open_guji_cv.core.workspace import products_root
PR = products_root()
_al = {}


def witness(iid):
    """整理本对齐字（align_ref）。v1（idx 坐标）刻例的 idx 从 0 → slot = idx+1。"""
    parts = iid.split(":")
    if parts[0] == "v1":                       # 重键后留在 idx 坐标的 v1：v1:<book>:p:c:idx
        book, pg, col, slot = parts[1], parts[2], parts[3], parts[4]
        slot = str(int(slot) + 1) if slot.isdigit() else slot
    elif parts[0] == "v2":
        book, pg, col, slot = parts[1], parts[2], parts[3], parts[4]
    else:
        book, pg, col, slot = parts[0], parts[1], parts[2], parts[3]
        if iid in V1_IDS and slot.isdigit():
            slot = str(int(slot) + 1)
    key = (book, int(pg))
    if key not in _al:
        f = PR / book / "align_ref" / f"p{int(pg):04d}.json"
        m = {}
        if f.exists():
            for ch in json.load(open(f, encoding="utf-8"))["align_ref"].get("chars", []):
                m[ch["id"]] = (ch.get("align_char"), ch.get("align_op"))
        _al[key] = m
    return _al[key].get(f"{book}:{int(pg)}:{col}:{slot}", (None, None))


def crop(img):
    ys, xs = np.where(img < 128)
    if len(ys) == 0:
        return img
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    s = int(max(y1 - y0, x1 - x0) * 1.3) + 4
    cv = np.full((s, s), 255, np.uint8)
    oy, ox = (s - (y1 - y0)) // 2, (s - (x1 - x0)) // 2
    cv[oy:oy + y1 - y0, ox:ox + x1 - x0] = img[y0:y1, x0:x1]
    return cv


out = []
for r in rows:
    iid = r["instance_id"]
    png, norm = c.execute(
        "SELECT i.patch_png, d.data FROM instances i JOIN derived d ON d.instance_id=i.instance_id "
        "AND d.kind='norm' WHERE i.instance_id=?", (iid,)).fetchone()
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    ink = float((img < 128).mean())
    n_cc = cv2.connectedComponents((img < 128).astype(np.uint8))[0] - 1
    o = [(cc.convert(ch)[:1] or ch, p) for ch, p in ocr.rec_topk(crop(img))]
    k = cnn.topk(_unpng(norm), classes, k=5) if classes else []
    a = r["char"]
    w, wop = witness(iid)
    o1, op = (o[0] if o else ("", 0.0))
    k1, kp = (k[0] if k else ("", 0.0))
    ocr_ok = sem(o1) == sem(a)
    cnn_ok = sem(k1) == sem(a)
    alt = None
    if o1 and k1 and sem(o1) == sem(k1) and sem(o1) != sem(a):
        alt = o1
    if (ocr_ok and op >= 0.5) or (cnn_ok and kp >= 0.5):
        cat = "agree"
    elif alt and op >= 0.5 and kp >= 0.5:
        cat = "mislabel"
    elif op < 0.3 and kp < 0.3:
        cat = "noise"
    else:
        cat = "unclear"
    out.append({**{k2: r[k2] for k2 in ("instance_id", "key", "char", "provenance", "flags",
                                          "rival_char", "rival", "xrival_char", "font_own", "score")},
                "ocr": o[:3], "cnn": k[:3], "witness": w, "wop": wop, "alt": alt, "cat": cat, "ink": round(ink, 4), "n_cc": n_cc})

with open(sys.argv[1], "w", encoding="utf-8") as f:
    for x in out:
        f.write(json.dumps(x, ensure_ascii=False) + "\n")
from collections import Counter
print(len(out), Counter(x["cat"] for x in out))
