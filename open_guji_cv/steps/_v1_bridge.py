"""v2 产物 → v1 `CharInstance` 的桥（阶段 B0）。

Step5/6 那一整套（`clustering/seeding.py`、`glyph_db.py`、`match.py`、
`recognize_flow.py`、`context_step.py`）都建立在 v1 的
`output/<book>/phase4_chars/index.jsonl` + 磁盘 patch 之上。v2 链到 Step4
产出的是 `char_index`（numeric）+ `char_patch`（缓存），到这里就断了。

这个模块**只做搬运，不改算法**：把 v2 的 `PageChars` 翻成 v1 的
`list[CharInstance]`，图块从 `ImageCache` 物化到一个 v1 布局的目录。
`seeding` 等模块因此可以原样跑在 v2 产物上，不必逐个改写。

## 两处口径差，这里显式处理

| | v1 | v2 | 桥怎么办 |
|---|---|---|---|
| 格号 | `idx` 从 **0** 起，含 margin 格 | `slot` 从 **1** 起，抬头格用**负数**，夹注 a/b 共用 slot | `CharInstance.idx` 用 v2 的 `pos - 1`（物理位置，永远连续），`id` 仍用 v2 的 `book:page:col:slot[a|b]` |
| bbox | 页面坐标（含 padding） | `bbox_col` 列图坐标 + `bbox_page` 规范空间 | 优先 `bbox_page`，缺了退回 `bbox_col` 并在 `flags` 里记 `bbox_is_column` |

**`id` 不翻译成 v1 口径**是有意的：v1 的 `page:col:idx` 键空间跟 v2 的
`page:col:slot` 不是双射（v2 有负数 slot 和 a/b 后缀），硬翻会把两个不同的
字位映到同一个 id。所有挂 v1 id 的旧金标（`char-ocr`、`context-correction`、
`glyph-match`）都要另行重键，见 `doc/pipeline_review_2026-09-03.md` 阶段 B2。

## 用法

```python
from open_guji_cv.steps._v1_bridge import export_v1_view
out = export_v1_view("vol01", pages=[24, 137], root=Path("output/vol01_v2view"))
# out / "index.jsonl" + out / "patches" / *.png —— 目录布局与 phase4_chars 一致
```
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Iterable

from ..core.book import load_book
from ..core.pipeline import load_pipeline
from ..core.spec import page_key
from ..products.cache import ImageCache
from ..products.store import ProductStore

__all__ = ["to_char_instances", "export_v1_view", "V1View"]


class V1View:
    """一个 v1 布局的只读视图目录：`index.jsonl` + `patches/`。"""

    def __init__(self, root: Path):
        self.root = Path(root)

    @property
    def index_path(self) -> Path:
        return self.root / "index.jsonl"

    def load(self):
        from ..clustering.extractor import load_index
        return load_index(self.root)


def _patch_rel(rec_id: str) -> str:
    """图块的相对路径。用 id 里的分隔符换成下划线，跟 v1 的 `<book>_<page>_<col>_<idx>.png`
    同构，只是格号换成了 v2 的 slot（可能带负号和 a/b 后缀）。"""
    return f"patches/{rec_id.replace(':', '_')}.png"


def to_char_instances(book: str, page: int, store: ProductStore,
                      cache: ImageCache | None = None,
                      patch_dir: Path | None = None) -> list:
    """一页的 v2 `char_index` → `list[CharInstance]`。

    `patch_dir` 给了就把图块从缓存物化到那里（`patches/` 子目录），
    `CharInstance.patch_path` 指向它；不给则 `patch_path` 仍按约定填，
    但文件可能不存在（只要元数据的调用方用得上）。
    """
    from ..clustering.extractor import CharInstance

    pc = store.read(book, "cell_shrink", page_key(page), "char_index")
    if pc is None:
        return []
    cache = cache or ImageCache()
    out: list[CharInstance] = []
    for cc in pc.columns:
        if not cc.ok:
            continue
        for r in cc.chars:
            flags = list(r.flags)
            bbox = r.bbox_page
            if bbox is None:
                bbox = r.bbox_col
                flags.append("bbox_is_column")
            rel = _patch_rel(r.id)
            if patch_dir is not None and r.patch_key:
                src = cache.get(book, "char_patch", r.patch_key)
                if src is not None:
                    dst = Path(patch_dir) / rel
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(src.read_bytes())
            out.append(CharInstance(
                id=r.id, book=book, page=str(page), col=cc.col,
                # v1 的 idx 是「物理位置，0 起」。`CharRec.idx` 已经是这个口径
                # （Step4 喂给 CharExtractor 的 0 起格号），直接用。
                # **不要用 slot**：抬头格的 slot 是负数（实测 vol01/26c5 首格
                # slot=-1、idx=0），夹注 a/b 又共用同一个 slot 值，拿它当 idx
                # 会让下游按 `page:col:idx` 建的索引撞车或出负键。
                # 也不要用 `pos - 1`：pos 是 1 起的物理位置，抬头格 pos=1，
                # 减 1 得 0 看着对，但那只是碰巧——idx 才是这一步的既定口径。
                idx=int(r.idx),
                bbox=tuple(float(v) for v in bbox),
                cell_type=r.cell_type,
                ocr_text=None, ocr_confidence=0.0,
                patch_path=rel,
                ink_ratio=float(r.ink_ratio),
                height=float(r.height), width=float(r.width),
                flags=flags, sub=r.sub,
            ))
    return out


def export_v1_view(book: str, pages: Iterable[int] | None = None,
                   root: Path | None = None,
                   store: ProductStore | None = None,
                   cache: ImageCache | None = None) -> V1View:
    """把 v2 产物导成一个 v1 布局的目录，供 Step5/6 原样消费。

    `pages` 默认取该册 `dev_set`；`root` 默认 `output/<book>_v2view`。
    整目录重写（不做增量）——v1 的 `load_index` 是整读，留下孤儿行会让
    下游对着过期图块干活（手册「重跑要清理旧产物」那条）。
    """
    store = store or ProductStore()
    cache = cache or ImageCache()
    bk = load_book(book)
    pages = list(pages) if pages is not None else list(bk.dev_set)
    root = Path(root) if root else Path("output") / f"{book}_v2view"
    if root.exists():
        import shutil
        shutil.rmtree(root)
    (root / "patches").mkdir(parents=True, exist_ok=True)

    import json
    n = 0
    with open(root / "index.jsonl", "w", encoding="utf-8") as f:
        for pg in pages:
            for inst in to_char_instances(book, pg, store, cache, patch_dir=root):
                f.write(json.dumps(asdict(inst), ensure_ascii=False) + "\n")
                n += 1
    (root / "_bridge.json").write_text(json.dumps({
        "book": book, "pages": pages, "n_instances": n,
        "note": "由 open_guji_cv.steps._v1_bridge.export_v1_view 生成；"
                "id 是 v2 口径 book:page:col:slot[a|b]，与挂 v1 id 的旧金标不通用",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return V1View(root)
