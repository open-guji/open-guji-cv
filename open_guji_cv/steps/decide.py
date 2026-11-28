"""第四步「定字」的公共读口（CV4 整理 P1a，2026-11-28）。

`seed_admit` 以前在两处各自读 `align_ref` 产物：`_align`（8-gram 文本对位 `chars`）、`_coord_refs`（坐标对位 `coord`），
读法与「缺了怎么办」各写一遍。这里收成一处：

- `text_refs(ref)`  → `{字位: (整理本字, equal|replace)}`（只认锚定了的页；产物缺失或未锚定 → 空表，所有整理本通道自动失效）；
- `coord_refs(ref)` → `{字位: 整理本字}`（空串＝坐标对位说是空格位；缅甸字母占位按缺字〓看，见 `_ref_placeholder_norm`）；
- `ref_of(ctx, page)` → `{字位: {ref, via: text|coord|pin, op, coord?}}`：对外的合并读口（不改落盘，decide-bench、gate、manager 读它）。

`seed_admit._align`／`_coord_refs` 仍在原处（测试靠 `seed_admit._opt` 换产物），只是不再自己解析 `PageAlignRef`。
"""

from __future__ import annotations

from ..core.step import RunContext
from ..utils.gap import GAP_IMAGE
from ..products.kinds.recog import PageAlignRef


def _opt(ctx: RunContext, kind: str, page: int):
    """可选上游：缺了就 None，不炸——OCR 要引擎、上下文要语料，都可能没有。"""
    try:
        return ctx.product(kind, page)
    except Exception:
        return None


def _ref_placeholder_norm(ch: str | None) -> str | None:
    """整理本「以图代字」的缅甸字母占位（U+1000–109F，史記整理本直接留着）当缺字〓看：
    不然 `ctx_guard_ref` 会把占位符当整理本字设成默认字，出单、导出露出 ခ（A24 R01 深挖，
    史記 03:114:2:20、08:122:2:16、10:3:6:7b；sheldon 11-07 同意）。"""
    if ch and len(ch) == 1 and 0x1000 <= ord(ch) <= 0x109F:
        return GAP_IMAGE
    return ch


def text_refs(ref: PageAlignRef | None) -> dict[str, tuple[str, str]]:
    """`align_ref` 的产物 → {字位: (整理本字, equal|replace)}。未锚定或没有产物 → 空表。"""
    if ref is None or not ref.anchored:
        return {}
    return {c.id: (c.align_char, c.align_op) for c in ref.chars}


def coord_refs(ref: PageAlignRef | None) -> dict[str, str | None]:
    """`align_ref.coord` → {字位 id: 整理本字（空串 = 坐标对位说是空格位）}。没有产物 → 空表。"""
    return {c.id: _ref_placeholder_norm(c.ref_char) for c in (ref.coord if ref else [])}


def ref_view(ref: PageAlignRef | None) -> dict[str, dict]:
    """两路对位合并成一张表：`{字位: {ref, via, op[, coord]}}`。

    `via`：`text`（8-gram 文本对位）、`pin`（同上，但整页是人钉的）、`coord`（只有坐标对位）；
    `op`：`equal`／`replace`（坐标对位没有，给 None）；有坐标对位的格另带 `coord`（整理本字，可为空串）。
    文本对位与坐标对位都有的格，`ref` 取文本对位的字。
    """
    out: dict[str, dict] = {}
    via = "pin" if (ref is not None and ref.anchor_via == "pin") else "text"
    for i, (ch, op) in text_refs(ref).items():
        out[i] = {"ref": ch, "via": via, "op": op}
    for i, ch in coord_refs(ref).items():
        out.setdefault(i, {"ref": ch, "via": "coord", "op": None})["coord"] = ch
    return out


def ref_of(ctx: RunContext, page: int) -> dict[str, dict]:
    """本页每个字位的整理本字（读 `align_ref` 产物）；见 `ref_view`。产物缺失 → 空表。"""
    return ref_view(_opt(ctx, "align_ref", page))
