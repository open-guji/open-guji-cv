# -*- coding: utf-8 -*-
"""产物 → 待审格（纯函数入口，给 guji-manager 的 pipeline 收尾调；GM4 换包按条目对账细则 2026-11-24）。

边界（sheldon 11-23 定）：cv 只出产物；对账、推库、传图、发站、book-text 都归 guji-manager。本模块只**读**本机产物
（`<产物根>/<册>/seed_admit/p*.json`）和字块图缓存，**不碰**中心库、R2、网站、book-text、事件，也不需要单子的 rev。

给出的东西就是 `review/pending_items.reconcile` 要的输入：

- `cells`：产物里没放行的格（口径同 `scripts/zhengli/pending_list.py`：排除名单上人已定过的不算），每格
  `{"cell": "页:列:格[ab]", "review": "pending"}`；`extra=` 给的复审格等也并进来（现行切分里没有的列进 `missing`）。
- `fps`：格号 → 图块指纹（字块图 `char_patch` 缓存文件的 sha1，同人裁锚 `content_sha`、同 republish `cell_fingerprints`）。
- `images=True` 时每格再给一张**按内容寻址**的单格字块图（`c<sha256 前 16 位>.webp`，同 `republish add-cell`），
  卡片字段 `img={s,x:0,y:0,w,h}`，单头 `sprites=[{name,sha256,md5,bytes}]`；`out_dir` 给了就把图写进去。
  不用整页雪碧图：雪碧图里每格的坐标随同页其他格增删而挪，reconcile 会把没变的格也判成「改」。
- `digest`：全册（格号, 指纹）的 sha256。manager 可记下上次落定时的 digest，相同就整册跳过对账。

相似字 `alt`、待审原因、卡片字段（`guji audit alt`、`review/reasons`、`review/proof_fields`）在 manager，不在这里。
"""
from __future__ import annotations

import hashlib
import io
import json
import re
from pathlib import Path
from typing import Callable, Iterable

SCHEMA = "guji-pending-cells/0.1"
PATCH_KIND = "char_patch"
_CELL = re.compile(r"(\d+):(\d+):(-?\d+)([ab]?)")


def _human_settled_excluded(ch: dict) -> bool:
    """排除名单上的格：人已定过（给字／判残／非字／图）的不上单；管线 gate:crop_defect 等没人看过的照样待审。
    口径同 guji-manager `pack_stats.is_pending`（2026-11-09 A31）。"""
    if "excluded" not in (ch.get("doubts") or []):
        return False
    ev = ch.get("evidence") or {}
    why = str(ev.get("excluded") or "")
    return bool(ev.get("human_char") or ev.get("damaged") or why.startswith("human:"))


def cell_sort_key(cell: str) -> list:
    return [int(x) if x.lstrip("-").isdigit() else x for x in re.split(r"(-?\d+)", cell) if x != ""]


def _iter_chars(seed_dir: Path):
    for f in sorted(Path(seed_dir).glob("p*.json")):
        s = json.loads(f.read_text(encoding="utf-8"))["seed_admit"]
        yield s, [ch for col in s["columns"] for ch in col["chars"]]


def machine_pending(products: Path, book: str) -> tuple[list[dict], int, set[str]]:
    """产物里机器没放行的格。返回 (待审格, 应有格数, 全册格号)。应有格数＝页头 `n_review` 之和＋排除名单上
    没人定过而照样上单的格；与待审格数不等说明产物不一致，调用方应停。格号不以 `<册>:` 开头 → ValueError。"""
    seed_dir = Path(products) / book / "seed_admit"
    if not seed_dir.is_dir():
        raise FileNotFoundError(f"没有 {seed_dir}")
    prefix = f"{book}:"
    cells: list[dict] = []
    n_review = 0
    every: set[str] = set()
    for s, chars in _iter_chars(seed_dir):
        n_review += s.get("n_review", 0)
        for ch in chars:
            cid = ch["id"]
            if not cid.startswith(prefix):
                raise ValueError(f"格号 {cid} 不以 {prefix} 开头")
            every.add(cid[len(prefix):])
            if ch["admit"] or _human_settled_excluded(ch):
                continue
            if "excluded" in (ch.get("doubts") or []):
                n_review += 1
            cells.append({"cell": cid[len(prefix):], "review": "pending"})
    return cells, n_review, every


def patch_reader(book: str, products: Path | None = None, *, render: bool = True) -> Callable[[str], Path | None]:
    """格号 → 现行字块图文件（缓存）。`render=True` 时缓存里没有或戳过期就现切（经 `RunContext.materialize`，
    与跑批同一条路、同一个戳；要原图）；`render=False` 只读缓存。取不到返回 None。"""
    from ..feedback.anchor import _resolved, patch_key
    from ..products.cache import ImageCache
    from ..products.store import ProductStore
    cache = ImageCache()
    state: dict = {}

    def ctx():
        if "ctx" not in state:
            try:
                from .. import steps as _s  # noqa: F401  注册各步（producer 要用）
                from ..core.book import load_book
                from ..core.pipeline import default_pipeline_id, load_pipeline
                from ..core.step import RunContext
                b = load_book(book)
                state["ctx"] = RunContext(b, ProductStore(products) if products else ProductStore(), cache,
                                          log=lambda _: None, pipeline=load_pipeline(default_pipeline_id(b)))
            except Exception:  # noqa: BLE001 — 册配置／管线读不出：退回只读缓存
                state["ctx"] = None
        return state["ctx"]

    def read(cell: str) -> Path | None:
        m = _CELL.fullmatch(cell)
        if not m:
            return None
        key = _resolved(book, patch_key(int(m[1]), int(m[2]), int(m[3]), m[4]))
        c = ctx() if render else None
        if c is not None:
            try:
                return Path(c.materialize(PATCH_KIND, key))
            except Exception:  # noqa: BLE001
                return None
        return cache.get(book, PATCH_KIND, key)
    return read


def cell_image(raw: bytes, max_side: int = 96) -> tuple[bytes, int, int]:
    """字块图原文件 → (webp 字节, 宽, 高)，同 `republish add-cell`。"""
    from PIL import Image
    im = Image.open(io.BytesIO(raw)).convert("L")
    im.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=80)
    return buf.getvalue(), im.width, im.height


def digest_of(cells: Iterable[dict], fps: dict[str, str]) -> str:
    rows = sorted((c["cell"], fps.get(c["cell"], "")) for c in cells)
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


def pending_cells(products: Path, book: str, *, extra: Iterable[str] = (), images: bool = True,
                  out_dir: Path | None = None, render: bool = True, max_side: int = 96,
                  read_patch: Callable[[str], Path | None] | None = None, strict: bool = True) -> dict:
    """本机产物 → 新待审格（见模块头）。只读产物与字块图缓存；只往 `out_dir` 写图。

    - `extra`：额外要上单的格号（复审、撤库重审、同字对照自检等，由 manager 给），带不带 `<册>:` 前缀都行；
      现行切分里没有的进 `missing`，不上单。
    - `strict`：待审格数与页头 `n_review` 不等就抛 ValueError（同 pending_list 退出）。
    - `read_patch`：格号 → 字块图文件，缺省 `patch_reader(book, products, render=render)`（测试可换）。
    返回 `{schema, book, source_rev, n_review, cells, fps, sprites, missing, no_image, digest}`。"""
    from ..products.store import ProductStore
    products = Path(products)
    cells, n_review, every = machine_pending(products, book)
    if strict and len(cells) != n_review:
        raise ValueError(f"{book} 待审格数不符：产物未放行 {len(cells)}，seed_admit 页头 n_review 合计 {n_review}")
    have = {c["cell"] for c in cells}
    missing: list[str] = []
    read = read_patch or patch_reader(book, products, render=render)
    for x in extra:
        cell = x.split(":", 1)[1] if x.startswith(f"{book}:") else x
        if cell in have:
            continue
        if cell not in every:
            # seed_admit 里没有这一格（如夹注异体格），但字块图在、复审清单点名要它：照样上单，不能悄悄漏掉
            # （GM4 11-24：008:59:6:19）。图也取不到才进 missing。
            p = read(cell)
            if p is None or not Path(p).exists():
                missing.append(cell)
                continue
        have.add(cell)
        cells.append({"cell": cell, "review": "pending"})
    cells.sort(key=lambda c: cell_sort_key(c["cell"]))
    fps: dict[str, str] = {}
    sprites: dict[str, dict] = {}
    no_image: list[str] = []
    if out_dir is not None:
        Path(out_dir).mkdir(parents=True, exist_ok=True)
    for c in cells:
        p = read(c["cell"])
        if p is None or not Path(p).exists():
            no_image.append(c["cell"])
            continue
        raw = Path(p).read_bytes()
        fps[c["cell"]] = hashlib.sha1(raw).hexdigest()
        if not images:
            continue
        data, w, h = cell_image(raw, max_side)
        sha = hashlib.sha256(data).hexdigest()
        name = f"c{sha[:16]}.webp"
        if out_dir is not None:
            (Path(out_dir) / name).write_bytes(data)
        sprites[name] = {"name": name, "sha256": sha, "md5": hashlib.md5(data).hexdigest(), "bytes": len(data)}
        c["img"] = {"s": name, "x": 0, "y": 0, "w": w, "h": h}
    return {"schema": SCHEMA, "book": book, "source_rev": ProductStore(products).source_rev(book),
            "n_review": n_review, "cells": cells, "fps": fps,
            "sprites": sorted(sprites.values(), key=lambda e: e["name"]),
            "missing": sorted(missing, key=cell_sort_key), "no_image": no_image,
            "digest": digest_of(cells, fps)}


def main(argv: list[str] | None = None) -> int:
    """`python -m open_guji_cv.feedback.pending_cells <册> --products <产物根> [--out <目录>] [--no-images]`：
    结果 JSON 打到 stdout（或 `--out/pending_cells.json`），图写进 `--out`。调试与计时用。"""
    import argparse
    import sys
    import time
    from ..core.workspace import products_root
    ap = argparse.ArgumentParser(description="产物 → 待审格（只读，不碰中心库／网站）")
    ap.add_argument("book")
    ap.add_argument("--products", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--extra", default=None, help="额外上单的格号文件（一行一个，可带 <册>: 前缀）")
    ap.add_argument("--no-images", action="store_true")
    ap.add_argument("--no-render", action="store_true", help="只读字块图缓存，不现切")
    a = ap.parse_args(argv)
    extra = [ln.split("\t")[0].strip() for ln in a.extra.read_text(encoding="utf-8").splitlines()] if a.extra else []
    t = time.time()
    r = pending_cells(a.products or products_root(), a.book, extra=[x for x in extra if x], images=not a.no_images,
                      out_dir=a.out, render=not a.no_render)
    body = json.dumps(r, ensure_ascii=False, indent=1)
    if a.out:
        (a.out / "pending_cells.json").write_text(body + "\n", encoding="utf-8")
    else:
        print(body)
    print(f"{a.book}：待审 {len(r['cells'])} 格，指纹 {len(r['fps'])}，图 {len(r['sprites'])}，"
          f"取不到图 {len(r['no_image'])}，复审格不在切分里 {len(r['missing'])}；{time.time() - t:.1f}s", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
