# -*- coding: utf-8 -*-
"""9.3 对勘报告的截条图：目标格前后各 ±radius 格横排一条，目标格红框。

沿用旧的单证人脚本 `scripts/build_collation_report.py::strip_b64`（`report/collation_grade.py`
模块头「为什么横排、为什么只截 ±2」讲了缘由，这里不重复）；跟旧脚本两点不同：

1. **落盘成 webp 文件**（`<out>_strips/<witness>/<id>.webp`），不再内嵌 base64——离线
   交付包要的是「深链指向包内的静态图」，不是把整包体积焊进一个 HTML 文件。生成的
   相对路径写回 `Diff.strip`，`report/html.py` 直接 `<img src>`，控制台深链关掉
   （`--console ""`）时也能看图，不依赖正在跑的控制台（任务书「离线交付包」那一条）。
2. **缓存没命中时现算**，不假设 `char_patch` 缓存已经在——云端快照不带 `cache/`
   （子会话须知 §一 表），走 `RunContext.materialize("char_patch", key)`，跟
   控制台 `routers/review.py::api_review_context_img` 缓存现算原图那条路同一个道理。

只给「替换类」（`sub.confusable`/`sub.other`/`unreadable`）出整条截图——增删
（`missing`/`extra`）没有对应的另一格，异体已有 `variant_pairs` 汇总（另配缩略图，
见 `write_variant_thumbs`），两者都不占整条截图，跟旧脚本的口径一致。
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from ..core.book import load_book
from ..core.spec import cell_key
from ..core.step import RunContext
from ..products.cache import ImageCache
from ..products.store import ProductStore
from ..utils.image_io import imread
from .slots import SlotRec, page_slots

#: 只有这几种 kind 出整条截图（替换类）；其余（missing/extra/variant.*/same）不出。
STRIP_KINDS = ("sub.confusable", "sub.other", "unreadable")


def _load_cell(ctx: RunContext, page: int, col: int, slot: int, sub: str | None, h: int
              ) -> np.ndarray | None:
    """一个字位的图，缩到高 `h`。缓存没有就走 `ctx.materialize` 现算；两边都没有 → None。"""
    key = cell_key(page, col, slot) + (sub or "")
    try:
        path = ctx.materialize("char_patch", key)
    except Exception:
        return None
    img = imread(str(path), cv2.IMREAD_GRAYSCALE)
    if img is None or img.shape[0] == 0:
        return None
    w = max(1, int(round(img.shape[1] * h / img.shape[0])))
    return cv2.resize(img, (w, h), interpolation=cv2.INTER_AREA)


def _row(ctx: RunContext, page: int, col_slots: list[SlotRec], k: int, radius: int,
        h: int) -> np.ndarray | None:
    """目标格前后各 `radius` 格横排成一条，第 `k` 格（目标）红框。"""
    lo, hi = max(0, k - radius), min(len(col_slots), k + radius + 1)
    cells = []
    for i in range(lo, hi):
        s = col_slots[i]
        img = _load_cell(ctx, page, s.col, s.slot, s.sub, h)
        if img is None:
            img = np.full((h, h), 235, np.uint8)
        cells.append((i == k, img))
    if not cells:
        return None
    gap, pad = 4, 3
    total_w = sum(c.shape[1] for _, c in cells) + gap * (len(cells) - 1) + pad * 2
    canvas = np.full((h + pad * 2, total_w, 3), 255, np.uint8)
    x = pad
    for is_target, c in cells:
        y = pad + (h - c.shape[0]) // 2
        canvas[y:y + c.shape[0], x:x + c.shape[1]] = cv2.cvtColor(c, cv2.COLOR_GRAY2BGR)
        if is_target:
            cv2.rectangle(canvas, (x - 2, y - 2), (x + c.shape[1] + 1, y + c.shape[0] + 1),
                          (30, 38, 179), 2)
        x += c.shape[1] + gap
    return canvas


def _write_webp(img: np.ndarray, path: Path, quality: int = 70) -> bool:
    """WebP q70：字块是二值图，比 PNG 小 4–5 倍——一整册几百条截图才装得进一个小目录。"""
    ok, buf = cv2.imencode(".webp", img, [cv2.IMWRITE_WEBP_QUALITY, quality])
    if not ok:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(buf.tobytes())
    return True


def write_diff_strips(doc: dict, out_dir: str | Path, store: ProductStore | None = None,
                      cache: ImageCache | None = None, radius: int = 2, h: int = 44,
                      limit: int = 1500) -> dict[str, int]:
    """给 `doc["diffs"]` 里要看图的条目生成截条文件，写回 `Diff.strip`（原地改 `doc`）。

    `out_dir`：截图落在 `<out_dir>/strips/<witness>/<id>.webp`；调用方把它建在
    HTML/JSON 输出旁边（`cli_v2.cmd_collate`），使 `strip` 存的相对路径与 HTML
    同目录起算就能直接 `<img src>`。

    按页分组重取字位流（`page_slots`），避免同一页被逐条差异重复读一次产物；
    一本书跑几十到几百条截图，这点重算不值得再往 `doc` 里塞列上下文。
    `limit`：全书截图太多时控制体积（旧脚本 `--limit-strips` 同名参数的理由）。
    """
    store = store or ProductStore()
    cache = cache or ImageCache()
    out_dir = Path(out_dir)
    book = doc["book"]
    bk = load_book(book)
    ctx = RunContext(bk, store, cache, log=lambda s: None)

    detail = [d for d in doc["diffs"] if d["kind"] in STRIP_KINDS]
    by_page: dict[int, list[dict]] = {}
    for d in detail:
        by_page.setdefault(d["page"], []).append(d)

    stats: dict[str, int] = {}
    n_done = 0
    for page in sorted(by_page):
        if n_done >= limit:
            break
        try:
            slots = page_slots(store, book, page)
        except Exception:
            # 产物缺失/过期查不到这一页的字位流：这一页的截图跳过，不拖垮整册——
            # `doc["stale"]` 已经报过这类问题，截图这层没必要重复报错中断。
            continue
        by_col: dict[int, list[SlotRec]] = {}
        for s in slots:
            by_col.setdefault(s.col, []).append(s)
        pos_in_col = {s.id: i for col in by_col.values() for i, s in enumerate(col)}
        for d in by_page[page]:
            if n_done >= limit:
                break
            col_slots = by_col.get(d["col"])
            k = pos_in_col.get(d["id"])
            if col_slots is None or k is None:
                continue
            img = _row(ctx, page, col_slots, k, radius, h)
            if img is None:
                continue
            fname = f"{d['id'].replace(':', '_')}.webp"
            rel = f"strips/{d['witness']}/{fname}"
            if not _write_webp(img, out_dir / rel):
                continue
            d["strip"] = rel
            n_done += 1
            stats[d["witness"]] = stats.get(d["witness"], 0) + 1
    return stats


def write_variant_thumbs(doc: dict, out_dir: str | Path, store: ProductStore | None = None,
                         cache: ImageCache | None = None, h: int = 48, n_examples: int = 3
                         ) -> dict[str, int]:
    """异体对的例图（单格缩略，不带邻格/红框）——`html.py` 的异体对表要它。

    每对最多 `n_examples` 张，取该对最早出现的几处；旧脚本 `variant_examples`
    同一个理由：异体是按对汇总看的，不必每一处出现都截一整条。
    """
    store = store or ProductStore()
    cache = cache or ImageCache()
    out_dir = Path(out_dir)
    book = doc["book"]
    bk = load_book(book)
    ctx = RunContext(bk, store, cache, log=lambda s: None)

    variant_diffs = [d for d in doc["diffs"] if d["kind"].startswith("variant.")]
    by_pair: dict[tuple, list[dict]] = {}
    for d in variant_diffs:
        by_pair.setdefault((d["witness"], d["char"], d["ref"]), []).append(d)

    stats: dict[str, int] = {}
    examples: dict[str, dict] = {}
    for (label, hyp, ref), ds in by_pair.items():
        out = []
        for d in sorted(ds, key=lambda x: (x["page"], x["col"], x["slot"]))[:n_examples]:
            img = _load_cell(ctx, d["page"], d["col"], d["slot"], d.get("sub"), h)
            if img is None:
                continue
            fname = f"{d['id'].replace(':', '_')}.webp"
            rel = f"strips/{label}/variant_{fname}"
            if _write_webp(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), out_dir / rel):
                out.append(rel)
                stats[label] = stats.get(label, 0) + 1
        if out:
            examples.setdefault(label, {})[f"{hyp}\t{ref}"] = out
    doc["variant_examples"] = examples
    return stats
