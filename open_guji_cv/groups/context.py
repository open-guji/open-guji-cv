"""上下文窗口（M7 块 A4，GUJI-563）：目标字前后各 `WIDTH`（20）字，**简单上下各取 20 字，不按段截断**。

用户 10-17 定：很多字缺上下文或上下文很短，按段截取容易误判，不再分段。
- 输入是读序展平的整串字 `chars`（整理本正文；对位缺字用占位符「□」，**不跳过**，位置才对得上）。
- 输出 `(left, right)`：left 是读序前文（越靠右越近），right 是读序后文；只在**整串的头／尾**才会比 `WIDTH` 短，
  短的话记在 `Ctx.cut_left / cut_right`（True＝撞到全文首／尾；False＝窗口取满）。
- 和 `protocol.Window` 兼容：`as_window(ctx)` 返回 `width -> (left, right)`，用于 `JudgeInput.window`。
- 键：`ctx_key(left, right)`，`CTX_VER = 3`（v2 是遇段界即停的版本，v1 是 30 字窗口；三者不混）。
- 本模块不被任何 Step 引用。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

WIDTH = 20
CTX_VER = 3
MISSING = "□"


@dataclass(frozen=True)
class Ctx:
    left: str
    right: str
    cut_left: bool      # 左侧是撞到全文首（True）还是窗口取满（False）
    cut_right: bool     # 右侧同理，全文尾


def window(chars: str, index: int, width: int = WIDTH) -> Ctx:
    """`chars[index]` 的上下文：前 `width` 字、后 `width` 字，不看段界。越界下标抛 IndexError。"""
    if not 0 <= index < len(chars):
        raise IndexError(f"index {index} 不在全文（长 {len(chars)}）内")
    lo = max(0, index - width)
    hi = min(len(chars), index + 1 + width)
    return Ctx(left=chars[lo:index], right=chars[index + 1:hi],
               cut_left=(index - width) < 0, cut_right=(index + 1 + width) > len(chars))


def as_window(ctx: Ctx) -> Callable[[int], "tuple[str, str]"]:
    """包成 `protocol.Window`（`width -> (left, right)`）；`width` 小于已有窗口时再截短。"""
    def win(width: int) -> tuple[str, str]:
        if width <= 0:
            return "", ""
        return ctx.left[-width:], ctx.right[:width]
    return win


def ctx_key(left: str, right: str) -> str:
    """`ctx_ver: 3` 的键：左右上下文用 `|` 隔开（与旧版 30 字窗口、v2 段内窗口不混）。"""
    return f"v{CTX_VER}:{left}|{right}"
