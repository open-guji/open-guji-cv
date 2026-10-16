"""抽评测集字块（归一 64²）+ 两路证据，存 pickle。沙箱用，不写任何产物。

  GUJI_WORKSPACE=$QTW_WS python extract.py human  out.pkl   # 用户人裁（只 source=human 系：batch2/3 簇级确认、batch5 human；ai-vision 不用）
  GUJI_WORKSPACE=$QTW_WS python extract.py corpus out.pkl   # 维基锚定格，每册均匀抽 600（同 R 的 a2，seed 0）

归一口径与线上 `review/borrow_first._card_patch` 相同（`normalize_patch` 缺省参数），
字块走 `RunContext.image("char_patch", cell_key+sub)`，与审卡 patch URL 同一个键。
"""
from __future__ import annotations

import glob
import json
import os
import pickle
import random
import sys
from pathlib import Path

QTW_WS = Path(os.environ.get("QTW_WS", os.environ.get("GUJI_WORKSPACE", "/home/user/qtw-ws")))
QTW_TRUTH = Path(os.environ.get(
    "QTW_TRUTH", "/home/user/overview/项目进展/新书整理/书/全唐文/人裁待导入"))
BOOKS = ["v006", "v007", "v008", "v009", "v010"]


def load_human() -> dict[str, dict]:
    """{cell_id: {char, src}}。batch1 只有好坏标记没有字，不收；blur/无字的不收；
    ai-vision-v1 **不当真值**（任务书）。后到的批次覆盖先到的。"""
    out: dict[str, dict] = {}
    for f, idk, chk, ok in (
        ("batch2-v2-partial.jsonl", "id", "accepted_char", lambda d: True),
        ("batch3-v3-partial.jsonl", "id", "accepted_char", lambda d: True),
        ("batch5-v5.jsonl", "key", "char", lambda d: d.get("source") == "human"),
    ):
        for line in open(QTW_TRUTH / f, encoding="utf-8"):
            d = json.loads(line)
            ch = d.get(chk)
            if not ch or not ok(d):
                continue
            out[d[idk]] = {"char": ch, "src": f.split("-")[0]}
    return out


def page_recs(book: str, step: str, kind: str | None = None):
    for f in sorted(glob.glob(str(QTW_WS / "products" / book / step / "p*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        yield d[kind or next(iter(d))]


def by_id(book, step):
    out = {}
    for pm in page_recs(book, step):
        for col in pm.get("columns") or []:
            for r in col.get("chars") or []:
                out[r["id"]] = r
    return out


def align_chars(book):
    out = {}
    for ar in page_recs(book, "align_ref"):
        if not ar.get("anchored"):
            continue
        for c in ar.get("chars") or []:
            if c.get("align_op") in ("equal", "replace") and c.get("align_char"):
                out[c["id"]] = c["align_char"]
    return out


def main():
    which, out = sys.argv[1], sys.argv[2]
    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.spec import cell_key
    from open_guji_cv.core.step import RunContext
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore

    jobs: dict[str, list] = {}
    if which == "human":
        for k, v in load_human().items():
            jobs.setdefault(k.split(":")[0], []).append((k, v["char"], v["src"]))
    else:
        rnd = random.Random(0)
        for b in BOOKS:
            a = align_chars(b)
            ks = sorted(a); rnd.shuffle(ks)
            jobs[b] = [(k, a[k], "wiki") for k in ks[:600]]
    recs = []
    for b in sorted(jobs):
        ctx = RunContext(load_book(b), ProductStore(), ImageCache(), log=lambda *_: None)
        gm, cd, sa = by_id(b, "glyph_match"), by_id(b, "context_decide"), by_id(b, "seed_admit")
        n0 = len(recs)
        for k, t, src in jobs[b]:
            _, pg, col, rest = k.split(":", 3)
            slot = "".join(ch for ch in rest if ch.isdigit()); sub = rest[len(slot):]
            try:
                img = ctx.image("char_patch", cell_key(int(pg), int(col), int(slot)) + sub)
            except Exception:
                continue
            m, d, a = gm.get(k) or {}, cd.get(k) or {}, sa.get(k) or {}
            recs.append({"id": k, "book": b, "truth": t, "src": src,
                         "norm": normalize_patch(img),
                         "pixel": [tuple(x) for x in (m.get("candidates") or [])],
                         "ctx": d.get("char"), "admit": a.get("admit"),
                         "ocr": [tuple(x) for x in ((a.get("evidence") or {}).get("ocr") or [])]})
        print(b, len(jobs[b]), "->", len(recs) - n0, flush=True)
    pickle.dump(recs, open(out, "wb"))


if __name__ == "__main__":
    main()
