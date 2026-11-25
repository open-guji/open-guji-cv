"""row_segment `alt_cut`：下游怎么读「改用备选切法的列」（第 7 轮，史记）。

Step3 开了 `alt_cut` 时，一页的部分列多裁一套不带版式先验的格网（`PageCells.alt_columns`），
Step4／5a 照样给它们出字块与库匹配（`PageChars.alt_columns`、`PageMatch.alt_columns`，字块键带
`ALT_TAG`，见 `core.spec.alt_cell_key`）。`align_ref` 按列挑一种切法，把改用备选切法的列号记进
`PageAlignRef.alt_cols`。

**挑中之后**，下游读这一列一律读备选那份：格号（slot/sub）不变，字块键换成备选键，
Step3/4/5a 换成 `with_alt` 视图；Step5b（生僻字候选）、Step6（上下文定字）只对主切法跑过，
这些列丢掉。**没挑中**的备选列不进任何下游（不进准入、不进字形库、不进生僻字候选）。

这里只放两样：
- `AltView`：包一层 `RunContext`，给 align_ref 之后的 Step（seed_admit）用；
- `alt_cols_of(book, page)`／`resolve_patch_key(book, key)`：离线读者（字形库入库、人裁消费、
  审查页）按格号取字块时，先过这一道换键。

align_ref 之前的 Step（cell_shrink／glyph_match／rare_candidates）**不许**调这些——它们读的是
两套切法本身，换键会读错。

**挑列挪到准入之后**（`AlignRefParams.alt_select="admit"`，2026-11-04，史记第 9 轮，A22 评审过）：align_ref
不挑，只记候选列 `alt_cand` 和备选那份坐标对位 `alt_draft`；seed_admit 准入两遍（主切法一遍、候选列全换一遍），
逐列比后把定下的列记进 `PageAdmit.alt_cols`。所以离线读者先读 seed_admit 的 `alt_cols`，读不到再退回
align_ref 的（第 7、8 轮的包照样能读）。seed_admit 跑一页时用 `alt_override` 把这一页的列钉住，
`feedback.bindings` 等在准入里被调到的离线读者也按这一遍的列读。
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from typing import Any

from ..core.spec import ALT_TAG

_PATCH_KEY_RE = re.compile(r"^p(\d{4})c(\d{2})s(-?\d+)([ab]?)$")

#: 换成 `with_alt` 视图的产物种类
VIEW_KINDS = frozenset({"glyph_match", "char_index", "cells"})
#: 只对主切法跑过、改用备选切法的列要丢掉的产物种类
DROP_KINDS = frozenset({"rare_candidates", "context_decision"})


#: seed_admit 准入一页时钉住的 (册 id, 页, 列)：`alt_cols_of`／`AltView` 对这一页一律用它
_OVERRIDE: "ContextVar[tuple[str, int, frozenset] | None]" = ContextVar("alt_cut_override", default=None)


@contextmanager
def alt_override(book: str, page: int, cols):
    token = _OVERRIDE.set((book, page, frozenset(cols)))
    try:
        yield
    finally:
        _OVERRIDE.reset(token)


def _overridden(book: str, page: int):
    o = _OVERRIDE.get()
    return o[2] if o is not None and o[0] == book and o[1] == page else None


def merge_alt(res, draft, cols) -> None:
    """`cols` 这几列改用备选切法：坐标字、退回原因、冲突格换成 `draft`（`PageAlignRef` 或 `AltDraft`）那份，
    现役 `chars` 里这几列的字删掉（格号已不对应），列号记进 `alt_cols`。就地改 `res`。"""
    ch = set(cols)

    def _col(rid):
        try:
            return int(rid.split(":")[2])
        except (IndexError, ValueError):
            return None
    res.chars = [c for c in res.chars if c.col not in ch]
    res.coord = sorted([r for r in res.coord if r.col not in ch] + [r for r in draft.coord if r.col in ch],
                       key=lambda r: (r.col, r.slot, r.sub or ""))
    res.coord_cols = sorted({c for c in res.coord_cols if c not in ch} | {c for c in draft.coord_cols if c in ch})
    for col in ch:
        res.coord_fallback.pop(str(col), None)
        if str(col) in draft.coord_fallback:
            res.coord_fallback[str(col)] = draft.coord_fallback[str(col)]
    res.coord_conflict_ids = ([i for i in res.coord_conflict_ids if _col(i) not in ch]
                              + [i for i in draft.coord_conflict_ids if _col(i) in ch])
    res.alt_cols = sorted(ch)


def with_alt_ref(ref, cols):
    """align_ref 产物 → 候选列 `cols` 换成备选那份（`alt_select="admit"`）的副本；`cols` 空或没有草稿就原样。"""
    if ref is None or not cols or getattr(ref, "alt_draft", None) is None:
        return ref
    out = ref.model_copy(deep=True)
    merge_alt(out, ref.alt_draft, [c for c in sorted(cols) if c in set(ref.alt_cand)])
    return out


def alt_patch_key(key: str, cols) -> str:
    """主切法字块键 → 这一页 `cols` 里的列换成备选键；别的键原样返回。"""
    if not cols:
        return key
    m = _PATCH_KEY_RE.match(key)
    if not m or int(m.group(2)) not in cols:
        return key
    return f"p{m.group(1)}c{m.group(2)}s{m.group(3)}{ALT_TAG}{m.group(4)}"


def view(obj: Any, kind: str, cols) -> Any:
    """产物 → 改用备选切法后的视图（`cols` 空就原样）。"""
    if obj is None or not cols:
        return obj
    if kind in VIEW_KINDS and hasattr(obj, "with_alt"):
        return obj.with_alt(cols)
    if kind in DROP_KINDS and hasattr(obj, "columns"):
        return obj.model_copy(update={"columns": [c for c in obj.columns if c.col not in cols]})
    return obj


class AltView:
    """`RunContext` 的包装：`product()` 给视图，`image()`／`materialize()` 换字块键。
    每页的 `alt_cols` 读这一页的 align_ref 产物（读不到当没有）。"""

    def __init__(self, ctx):
        self._ctx = ctx
        self._cols: dict[int, frozenset] = {}

    def alt_cols(self, page: int) -> frozenset:
        forced = _overridden(self._ctx.book.id, page) if hasattr(self._ctx, "book") else None
        if forced is not None:
            return forced
        got = self._cols.get(page)
        if got is None:
            try:
                ref = self._ctx.product("align_ref", page)
                got = frozenset(getattr(ref, "alt_cols", ()) or ())
            except Exception:                  # noqa: BLE001 —— 没有 align_ref 就是没换列
                got = frozenset()
            self._cols[page] = got
        return got

    def product(self, kind_id: str, page: int) -> Any:
        obj = self._ctx.product(kind_id, page)
        if kind_id == "align_ref" and getattr(obj, "alt_draft", None) is not None:
            return with_alt_ref(obj, self.alt_cols(page))
        if kind_id in VIEW_KINDS or kind_id in DROP_KINDS:
            return view(obj, kind_id, self.alt_cols(page))
        return obj

    def _key(self, kind_id: str, key: str) -> str:
        if kind_id != "char_patch":
            return key
        m = _PATCH_KEY_RE.match(key)
        return alt_patch_key(key, self.alt_cols(int(m.group(1)))) if m else key

    def image(self, kind_id: str, key: str):
        return self._ctx.image(kind_id, self._key(kind_id, key))

    def materialize(self, kind_id: str, key: str):
        return self._ctx.materialize(kind_id, self._key(kind_id, key))

    def cache_stamp(self, kind_id: str, key: str):
        return self._ctx.cache_stamp(kind_id, self._key(kind_id, key))

    def __getattr__(self, name):
        return getattr(self._ctx, name)


def alt_cols_of(book: str, page: int, store=None) -> frozenset:
    """离线读：这一页改用备选切法的列——先读 seed_admit 产物的 `alt_cols`（`alt_select="admit"`），
    没有再读 align_ref 的（没有产物／没换列 → 空）。seed_admit 准入时 `alt_override` 钉住的页按钉的列。
    按产物文件的修改时间缓存（控制台这种长驻进程，重跑后读到的是新的）。"""
    from ..core.spec import page_key
    forced = _overridden(book, page)
    if forced is not None:
        return forced
    if store is None:
        from .store import ProductStore
        store = ProductStore()
    for step in ("seed_admit", "align_ref"):
        try:
            path = store.path(book, step, page_key(page))
            mtime = path.stat().st_mtime_ns
        except (OSError, AttributeError):
            continue
        got = _read_cols(str(path), mtime, step)
        if got:
            return got
    return frozenset()


@lru_cache(maxsize=4096)
def _read_cols(path: str, _mtime: int, step: str = "align_ref") -> frozenset:
    import json
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return frozenset()
    d = raw.get(step, raw) if isinstance(raw, dict) else {}
    return frozenset(d.get("alt_cols") or ())


def resolve_patch_key(book: str, key: str, store=None) -> str:
    """离线读者按格号取字块前过这一道：这一列改用了备选切法就换成备选键。"""
    m = _PATCH_KEY_RE.match(key)
    if not m:
        return key
    return alt_patch_key(key, alt_cols_of(book, int(m.group(1)), store))


def read_view(store, book: str, step_id: str, key: str, kind_id: str):
    """`store.read` 之后套上 alt_cut 视图（离线读 Step3/4/5a/5b/6 产物、要的是「挑中的那套切法」时用）。
    `key` 是页键 p0012；不是页键就原样。"""
    obj = store.read(book, step_id, key, kind_id)
    if obj is None or (kind_id not in VIEW_KINDS and kind_id not in DROP_KINDS):
        return obj
    m = re.match(r"^p(\d{4})$", key)
    return view(obj, kind_id, alt_cols_of(book, int(m.group(1)), store)) if m else obj
