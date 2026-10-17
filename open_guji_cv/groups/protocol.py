"""判别输入／输出与后端协议。

**判别输入与决策输入拆开**（Ethan、Evan 评审）：后端只吃 `JudgeInput`、只出 `GroupVerdict`（pick）。
现行放行字要等 `seed_admit` 的全部通道跑完才定，`group_decide` 阶段根本没有，所以**放行字不得进 `judge`，
也不得进上下文键**；「抬／降」由 `apply_group_verdicts` 拿 pick 与放行状态比。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

#: 窗口取法：`window(width) -> (left, right)`。left 是读序前文（越靠右越近），right 是读序后文（越靠左越近），
#: 各至多 width 字，缺字用「□」。**窗口只许由统一的窗口函数产生**（PR2 的 `ctx_window`；评测时用数据集里现成的
#: left/right，见 `window_from_text`），后端内部不得自己再取一份——否则又多出一份窗口口径。
Window = Callable[[int], "tuple[str, str]"]


class PatchUnavailable(Exception):
    """图像后端读不到字块（缓存缺图）。是否跳过、是否抛出由调用方按 `patch_missing` 语义定，后端不静默弃权。"""


def window_from_text(left: str, right: str) -> Window:
    """把已经取好的前后文字符串包成窗口函数（数据集 `items.jsonl` 的 `left`/`right` 就是这种）。"""
    def window(width: int) -> tuple[str, str]:
        if width <= 0:
            return "", ""
        return left[-width:], right[:width]
    return window


@dataclass
class JudgeInput:
    """判别输入：`group_decide` 阶段就有的全部东西（只读）。"""
    id: str
    ref: str | None                       # 整理本对位字
    window: Window                        # 窗口取法，见上
    patch: Callable[[], Any] | None = None   # 惰性读字块灰度图；缺图抛 `PatchUnavailable`；文本类后端不碰它


@dataclass
class GroupVerdict:
    """判别输出（就是 `group_decision` 里的一条）。"""
    char: str | None                      # pick；弃权＝None（语义同 group_clf/1）
    conf: float | None = None
    #: 取值沿用 group_clf/1 的词汇：agree／abstain:<来源>／disagree／veto:<来源>，及 cache_miss／ctx_mismatch／ver_mismatch；
    #: 不另起一套。后端各自的原始说明放 `extra`。
    why: str = ""
    via: str = ""                         # "rule"|"table"|"image"|"ctx_table"
    extra: dict = field(default_factory=dict)   # 原样保留：votes、规则命中文本、图像四类概率、legacy 原始返回…


class GroupBackend(Protocol):
    name: str
    fingerprint: str                      # 表／模型／规则版本的内容哈希（文本规则为空串）

    def judge(self, spec: Any, cell: JudgeInput) -> GroupVerdict: ...
