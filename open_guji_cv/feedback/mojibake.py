"""字形字段合法性校验与乱码机械还原（H 道，2026-09-27）。

## 背景

`feedback/events/*.jsonl` 里 `confirm` 事件的 `payload.shape`／`payload.reading`／
`payload.char` 三个字段按约定应是**单个字**（或极少数合法的多码位形态，见下）。
2026-09-16 一批 `vol01-p1-30-confirm-20260916` 事件在写盘前已经乱码——UTF-8 字节
被按 cp1252／latin-1 误解成文本又存了一遍（`"内"` → `"å†…"`，3 个 code point）。
`glyphdb_admit`（字形库写入口）在 `b162e64` 已经加了同款还原 + 单字校验，但
`feedback/lookup.py::human_chars()`（Step6/Step7 文本层的人裁读出口）没有，
乱码字符串会原样流进 `AdmitRec.char`，把「一个字位 = 一个字符」的假设打破，
下游 `report/collate.py::diff_page` 逐位比对时下标错位直接崩溃（P cross 1717）。

## 本模块提供什么

- `unmojibake`：机械还原规则，从 `consumers.py` 的 `_unmojibake` 原样搬来当正本
  （`consumers.py` 改为从这里 import，不留两份实现）。
- `is_legal_shape`：字形字段合法性判据——单字，或已知的合法多码位形态：
  - **IDS 拆分串**（`⿰亻斯` 这类）：未收字用 IDS 表达身份是既定做法
    （见 `unencoded_char_sources_survey.md`），全串是表意文字描述字符
    （U+2FF0–U+2FFF）与 CJK 类字符的组合。
  - **表意文字变体序列（IVS）**：已编码 CJK 字 或 PUA 码位 + 一个变体选择符，
    `console/routers/step8.py` 的"都不对，填 X+VS17"、全字库／字统网未收字
    都是这种形态——**基字不限 PUA**，普通已编码汉字一样可以带变体选择符
    （`test_step8_routes.py::test_decide_accepts_variation_selector_fix`
    实测踩过：第一版只认 PUA 基字，把"葛+VS17"误判成不合法）。
  - **`human_stale_*` 撤下标记**：不是字形值，是 provenance 标记字符串，
    出现在这三个字段里本身就不合法（不豁免），列在这里只是文档说明不误判。
- `classify_shape_field`：普查用，`legal` / `recoverable`（乱码可还原）/
  `needs_human`（两边都够不上）。

## 谁在用

- **写入口**（`events.EventLog.append`）：不合格直接拒（`BadRequest`），
  不让新的乱码再落盘。
- **读取处**（`lookup.human_chars` / `steps.seed_admit._human_shapes`）：
  遇到不合格的跳过并记 warning，不让老数据/未来的意外数据把下游冲垮，
  但也不吞掉——warning 里带 key，方便追。
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

#: 表意文字描述字符（Ideographic Description Characters）：⿰⿱⿲⿳⿴⿵⿶⿷⿸⿹⿺⿻
_IDC_RANGE = (0x2FF0, 0x2FFF)
#: 私用区三段（BMP + 两个补充平面）
_PUA_RANGES = ((0xE000, 0xF8FF), (0xF0000, 0xFFFFD), (0x100000, 0x10FFFD))
#: 变体选择符：VS1-16（U+FE00-FE0F）＋ 表意文字变体序列用的补充变体选择符
_VS_RANGES = ((0xFE00, 0xFE0F), (0xE0100, 0xE01EF))
#: 「像 CJK」的宽松下限：`_unmojibake` 用它判断"已经是好字符，不用再解一遍"，
#: 沿用 consumers.py 原实现的口径（CJK 部首补充起，含部首/IDC/CJK 区块/假名等）。
_CJK_ISH = 0x2E80


def _in_ranges(cp: int, ranges: tuple[tuple[int, int], ...]) -> bool:
    return any(lo <= cp <= hi for lo, hi in ranges)


def is_ids_string(s: str) -> bool:
    """全串是表意文字描述字符＋部件字，且至少含一个 IDC——真正的 IDS 拆分串。"""
    if len(s) < 2:
        return False
    has_idc = any(_in_ranges(ord(ch), (_IDC_RANGE,)) for ch in s)
    return has_idc and all(ord(ch) >= _CJK_ISH or _in_ranges(ord(ch), (_IDC_RANGE,)) for ch in s)


def is_variation_sequence(s: str) -> bool:
    """基字 + 变体选择符（表意文字变体序列 IVS），长度恰好 2。

    基字可以是**已编码的 CJK 统一表意文字**（标准 Unicode IVS 机制，
    `console/routers/step8.py` 的"都不对填 X+VS17"就是这种——「一个字，两个
    码位」），也可以是 **PUA 私用区字符**（全字库/字统网未收字常见形态，见
    `unencoded_char_sources_survey.md`）。两者都合法，不能只认 PUA 那一种。"""
    if len(s) != 2:
        return False
    a, b = ord(s[0]), ord(s[1])
    base_ok = _in_ranges(a, _PUA_RANGES) or a >= _CJK_ISH
    return base_ok and _in_ranges(b, _VS_RANGES)


def is_legal_shape(s: str | None) -> bool:
    """字形字段合法：空值不管（有没有填是另一层逻辑）；单字；或已知合法多码位形态。"""
    if not s:
        return True
    if len(s) == 1:
        return True
    return is_ids_string(s) or is_variation_sequence(s)


def unmojibake(s: str | None) -> str | None:
    """UTF-8 被当 cp1252 / latin-1 解过一遍的乱码还原（「å†…」→「内」）。

    还原不了的、或原本就不像乱码的（全串已是 CJK 类字符）原样返回——这是
    `consumers.py::_unmojibake` 的正本，`consumers.py` 改为从这里 import。"""
    if not s or all(ord(ch) >= _CJK_ISH for ch in s):
        return s
    try:
        raw = b"".join(ch.encode("cp1252") if ch.encode("cp1252", "ignore") else ch.encode("latin-1")
                       for ch in s)
        fixed = raw.decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s
    return fixed if fixed and all(ord(ch) >= _CJK_ISH for ch in fixed) else s


def classify_shape_field(s: str | None) -> str:
    """普查用：`legal` / `recoverable`（乱码机械还原后合法）/ `needs_human`。"""
    if is_legal_shape(s):
        return "legal"
    fixed = unmojibake(s)
    if fixed != s and is_legal_shape(fixed):
        return "recoverable"
    return "needs_human"
