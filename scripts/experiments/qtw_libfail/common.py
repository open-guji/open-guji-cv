"""R 道：全唐文借四庫库失效查根因（overview#86）的公共件。沙箱用，不进管线。

路径全走环境变量，缺省是云端会话里的布局：
  QTW_WS   全唐文沙箱工作区（books/ data_full/ products/，产物来自 products-snap/qtw-v006-v010-full-20260927）
  SIKU_WS  四庫沙箱工作区（products/vol03 来自 products-snap/vol03-20260927 的 iron 包）
  QTW_TRUTH 整理 Z15 收回的人裁（overview 新书整理/书/全唐文/人裁待导入/）
"""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path

QTW_WS = Path(os.environ.get("QTW_WS", "/home/user/qtw-ws"))
SIKU_WS = Path(os.environ.get("SIKU_WS", "/home/user/siku-sb"))
QTW_TRUTH = Path(os.environ.get(
    "QTW_TRUTH", "/home/user/overview/项目进展/新书整理/书/全唐文/人裁待导入"))
QTW_BOOKS = ["v006", "v007", "v008", "v009", "v010"]


def load_qtw_truth() -> dict[str, dict]:
    """用户人裁（簇级确认 + 手打字）：{cell_id: {char, pool, src}}。blur 的不要。"""
    out: dict[str, dict] = {}
    for f in ("batch2-v2-partial.jsonl", "batch3-v3-partial.jsonl"):
        for line in open(QTW_TRUTH / f, encoding="utf-8"):
            d = json.loads(line)
            ch = d.get("accepted_char")
            if not ch:
                continue
            out[d["id"]] = {"char": ch, "pool": d.get("pool"), "src": f.split("-")[0]}
    return out


def iter_page_products(ws: Path, book: str, step: str):
    for f in sorted(glob.glob(str(ws / "products" / book / step / "p*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        yield int(Path(f).stem[1:]), d[next(iter(d))]


def match_recs(ws: Path, book: str) -> dict[str, dict]:
    out = {}
    for _pg, pm in iter_page_products(ws, book, "glyph_match"):
        for col in pm["columns"]:
            for r in col.get("chars") or []:
                out[r["id"]] = r
    return out


def align_chars(ws: Path, book: str) -> dict[str, dict]:
    """整理本对齐给的字（只取锚定页的 equal/replace）。"""
    out = {}
    for _pg, ar in iter_page_products(ws, book, "align_ref"):
        if not ar.get("anchored"):
            continue
        for c in ar.get("chars") or []:
            if c.get("align_op") in ("equal", "replace") and c.get("align_char"):
                out[c["id"]] = c
    return out


def admit_recs(ws: Path, book: str) -> dict[str, dict]:
    out = {}
    for _pg, sa in iter_page_products(ws, book, "seed_admit"):
        for col in sa["columns"]:
            for r in col.get("chars") or []:
                out[r["id"]] = r
    return out
