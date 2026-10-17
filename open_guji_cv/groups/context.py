"""上下文窗口（M7 块 A4，GUJI-563）：目标字前后各 `WIDTH`（20）字，**遇段首、段尾就停，不跨段补字**。

- 输入是「段落序列」：每段是读序整理本字的字符串（段怎么切由调用方给，如 `render/reflow_text.py` 的 `Para.text`
  去掉标记后；整理本本身分段的书以它的段为准）。对位缺字用占位符（缺省「□」），**不跳过**，位置才对得上。
- 输出 `(left, right)`：left 是读序前文（越靠右越近），right 是读序后文；可比 `WIDTH` 短，短的原因记在
  `Ctx.cut_left / cut_right`（True＝被段界截断；False＝窗口取满）。评测按「截断／未截断」分开报。
- 和 `protocol.Window` 兼容：`as_window(ctx)` 返回 `width -> (left, right)`，用于 `JudgeInput.window`。
- 键：`ctx_key(left, right)` 与旧表区分，`CTX_VER = 2`（旧表按 30 字窗口，`ctx_ver` 缺省为 1，两者不混）。
- 本模块不被任何 Step 引用。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

WIDTH = 20
CTX_VER = 2
MISSING = "□"


@dataclass(frozen=True)
class Ctx:
    left: str
    right: str
    cut_left: bool      # 左侧是被段首截断的（True）还是窗口取满（False）
    cut_right: bool     # 右侧同理，段尾


def para_window(paras: Sequence[str], para_index: int, char_index: int, width: int = WIDTH) -> Ctx:
    """第 `para_index` 段第 `char_index` 个字的上下文。越界下标抛 IndexError。"""
    para = paras[para_index]
    if not 0 <= char_index < len(para):
        raise IndexError(f"char_index {char_index} 不在第 {para_index} 段（长 {len(para)}）内")
    lo = max(0, char_index - width)
    hi = min(len(para), char_index + 1 + width)
    return Ctx(
        left=para[lo:char_index], right=para[char_index + 1:hi],
        cut_left=(char_index - width) < 0, cut_right=(char_index + 1 + width) > len(para),
    )


def flat_window(chars: str, starts: Sequence[int], index: int, width: int = WIDTH) -> Ctx:
    """整页展平成一串字 `chars`，`starts` 是各段首字的下标（升序，含 0）。取 `index` 所在段内的窗口。"""
    s = max(i for i in starts if i <= index)
    later = [i for i in starts if i > index]
    e = min(later) if later else len(chars)
    return para_window([chars[s:e]], 0, index - s, width)


def as_window(ctx: Ctx) -> Callable[[int], "tuple[str, str]"]:
    """包成 `protocol.Window`（`width -> (left, right)`）；`width` 小于已有窗口时再截短。"""
    def window(width: int) -> tuple[str, str]:
        if width <= 0:
            return "", ""
        return ctx.left[-width:], ctx.right[:width]
    return window


def ctx_key(left: str, right: str) -> str:
    """`ctx_ver: 2` 的键：左右上下文用 `|` 隔开（与旧 `ctx_key` 的 30 字窗口不混）。"""
    return f"v{CTX_VER}:{left}|{right}"
