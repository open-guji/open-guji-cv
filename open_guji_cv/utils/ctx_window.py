# -*- coding: utf-8 -*-
"""方案 D 的 ctx 窗口：`group_decide` 与 `seed_admit` 共用的纯函数（overview GUJI-49 PR2，GUJI-208lf）。

窗口里的邻字**只取整理本对位字**（`align_ref` 的 `align_char`），缺则 `□`；不看 `glyph_match` 的
判决、不看放行态。所以键不随放行集合漂移，也与调用方在哪一步无关——两处都调这里，键逐位相同。

骨架（`ids`）约定：整页所有格、列号升序展平、列内按产物存储序，**不剔 `excluded` 格**
（`seed_admit` 的 `_ry_group_pass` 旧口径会剔，D 下骨架与 `group_decide` 对齐，不剔；目标格仍只取未排除的）。
页首尾自然截断；窗口至多 `CTX_WIDTH` 字，再交 `ji_yi_si_clf.ctx_key` 按 □ 收窄。

纯函数、无 IO，不依赖 `Step`；改本文件会让两处的 `code_deps` 一起过期（`seed_admit`、`group_decide`）。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence

from .ji_yi_si_clf import ctx_key

CTX_WIDTH = 30


def ref_window(ids: Sequence[str], ref: Mapping[str, str | None], i: int, step: int,
               width: int = CTX_WIDTH) -> str:
    """第 i 格前（step=-1）／后（step=1）至多 width 字，读序；邻格取对位字，缺则 □。"""
    out: list[str] = []
    j = i + step
    while 0 <= j < len(ids) and len(out) < width:
        out.append(ref.get(ids[j]) or "□")
        j += step
    return "".join(reversed(out)) if step < 0 else "".join(out)


def ref_ctx(ids: Sequence[str], ref: Mapping[str, str | None], i: int,
            width: int = CTX_WIDTH) -> tuple[str, str]:
    return ref_window(ids, ref, i, -1, width), ref_window(ids, ref, i, 1, width)


def ref_ctx_key(ids: Sequence[str], ref: Mapping[str, str | None], i: int, width: int = CTX_WIDTH) -> str:
    return ctx_key(*ref_ctx(ids, ref, i, width), width)
