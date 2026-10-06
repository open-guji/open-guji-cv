"""H 道：全唐文人审导入书级库（overview#64）的公共件。

路径走环境变量，缺省是云端会话里的布局：
  QTW_WS     全唐文沙箱工作区（产物来自 guji-workspace products-snap/qtw-v006-v010-full-20260927）
  QTW_TRUTH  整理 Z15 收回的人裁（overview 新书整理/书/全唐文/人裁待导入/）
  SIKU_STORE 四庫工作区的字形库真源（只读借用）
"""
from __future__ import annotations

import glob
import json
import os
from pathlib import Path

QTW_WS = Path(os.environ.get("QTW_WS", "/home/user/qtw-ws"))
QTW_TRUTH = Path(os.environ.get(
    "QTW_TRUTH", "/home/user/overview/项目进展/新书整理/书/全唐文/人裁待导入"))
SIKU_STORE = Path(os.environ.get(
    "SIKU_STORE", "/home/user/guji-workspace/96mid1ogzk-欽定四庫全書總目武英殿刻本/output/glyph_store"))
QTW_BOOKS = ("v006", "v007", "v008", "v009", "v010")
#: 全唐文书级库的 edition（与四庫 `siku-zongmu` 分开）
QTW_EDITION = "quantangwen"
#: 用户人裁的四个文件（ai-vision-v1.jsonl 不是真值，**不读**）
HUMAN_FILES = ("batch1-partial.jsonl", "batch2-v2-partial.jsonl",
               "batch3-v3-partial.jsonl", "batch5-v5.jsonl")
#: 形近三对：导入后每边本书刻例 ≥3（任务书 18:50 补）
TRIO = ("今", "令", "玉", "王", "大", "天")


def page_products(book: str, step: str, ws: Path = QTW_WS):
    for f in sorted(glob.glob(str(ws / "products" / book / step / "p*.json"))):
        d = json.load(open(f, encoding="utf-8"))
        yield int(Path(f).stem[1:]), d[next(iter(d))]


def cell_index(book: str, ws: Path = QTW_WS) -> dict[str, dict]:
    """cell_shrink 里的字格：{cell_id: rec}（带 patch_key、cell_type）。"""
    out = {}
    for _pg, ci in page_products(book, "cell_shrink", ws):
        for col in ci["columns"]:
            for r in col.get("chars") or []:
                out[r["id"]] = r
    return out


def admit_recs(book: str, ws: Path = QTW_WS) -> dict[str, dict]:
    out = {}
    for _pg, sa in page_products(book, "seed_admit", ws):
        for col in sa["columns"]:
            for r in col.get("chars") or []:
                out[r["id"]] = r
    return out


def match_recs(book: str, ws: Path = QTW_WS) -> dict[str, dict]:
    out = {}
    for _pg, pm in page_products(book, "glyph_match", ws):
        for col in pm["columns"]:
            for r in col.get("chars") or []:
                out[r["id"]] = r
    return out


def align_chars(book: str, ws: Path = QTW_WS) -> dict[str, dict]:
    """整理本对齐给的字（只取锚定页的 equal/replace）。"""
    out = {}
    for _pg, ar in page_products(book, "align_ref", ws):
        if not ar.get("anchored"):
            continue
        for c in ar.get("chars") or []:
            if c.get("align_op") in ("equal", "replace") and c.get("align_char"):
                out[c["id"]] = c
    return out


def ctx_for(book: str):
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.step import RunContext
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore
    return RunContext(load_book(book), ProductStore(), ImageCache(), log=lambda *_: None)
