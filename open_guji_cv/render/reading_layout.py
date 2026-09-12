# -*- coding: utf-8 -*-
"""Step9 结果整理 · 9.2 可阅读排版：把 9.1 产出的分行 guji-markdown 文本
（`render/guji_markdown.py::render_page`，每列一行，带 `^`/`.`/`<…>`/`[[…]]`
记号）转成横排、分段、无版式记号的可阅读文本。

设计见 `overview` 仓 `项目进展/图片初步数字化/进度/Step9-结果整理/01-结果排版.md`
§二·2 后半（README 里编号 9.2）。用户 2026-09-12 定的四条规则：

1. 取消抬头、挪抬记号，字直接拼接（敬体排版信息，阅读版不需要）。
2. 取消大部分换行——9.1 里一列一行，本模块把多行拼成连续段落。
3. 保留小注，但转行 `|` 去掉——`<a|b>` → `<ab>`，横排不需要竖排转行位置。
4. 分段：核心判据是「上一行没排满 且 下一行是本段该有的正常延续」。

## 输入两路（用户 2026-09-12 定）

主体解析 9.1 的纯文本（`render_page` 的返回值，不是重新拼一遍）；
判断「排满」这一项文本层面做不到（`<ab>` 这类夹注让「字符数」与
「格数」对不上，参见 `render_column` 的 join 逻辑），**这一项单独
回查 Step3 `n_body_slots` + Step7 `seed_admit` 最后一个正文 slot**，
不是从文本字符数近似出来的。除此之外不重新解析坐标。

## 「排满」判据

这一列全部 `AdmitRec` 里最大的正文 slot（`sub is None`）是否等于
`ColumnCells.n_body_slots`。**阙文算排满**（`[[…]]` 那一格物理上是
有字的，只是认不出，版面确实写到了那里）；`blank`/`excluded` 的格子
不算——它们本来就不产出 `AdmitRec`（`excluded` 有记录但内容不算数，
`blank` 干脆没有记录，见 `guji_markdown.py::_lead_blank_count` 的
同款教训）。

## 分段判据（用户 2026-09-12 定，第二版——第一版滑动窗口猜基线的方案
用真实数据（vol02 p11）验证是错的：抬头行天然写不满，把它的「没排满」
当分段信号会把一段连续敬语拆得七零八落，已废弃）

**基线是外部给定的已知常量**（`baseline_kg`，默认 2），不是统计出来的。
每一行的「开头点数」`kg`（`.`/`..` 的点数）与基线比较，只认三种情况，
碰到没覆盖的组合**不猜，记进 `notes` 里向上抛**：

1. `kg == baseline_kg`：正常行。若上一行没排满 → 分段；排满则接着拼。
2. `kg < baseline_kg`（含抬头 `^`，按"抬头 n 级 == 点数 -n"折算）：
   **只有开头词命中 `_TAITOU_WORDS` 词表才判定为抬头**——抬头不分段，
   直接接着拼（抬头是强制换行，不是新段落的开始，见 vol02 p11 教训）。
   `kg == 0` 时另有一条分支（见下），其余不命中词表的记进 `notes`，
   不要在没有依据的时候擅自分段。
2a. `kg == 0` 且**连续 ≥2 行**（自己已经在 0 区间里，或下一行也是 0）：
    判定为**这一段的基线本来就是 0**（如 vol02 p3 整页顶格不挪抬），
    按当前基线（0）走情况 1 的排满/分段逻辑，不是逐行标题。
    `kg == 0` 但**孤立单行**（前后都不是 0）：书目条目标题行（如
    "夏易傳十一卷<內府藏本>"），前后都强制分段、独立成段。用户
    2026-09-12 两次裁：先按"点数=0 且不在抬头词表里"识别成标题，
    后用 vol02 p3 真实数据验证"连续多行都是 0"不是标题是基线，
    补上"连续 2 行以上才算基线 0，单独 1 行才算标题"这条区分。
3. `kg > baseline_kg` 且开头命中 `_SECTION_MARKERS`（如"謹案"）：
   判定为**连续几行的基线切换**——从这一行起，后续判断改用新基线
   （新基线就是这一行的 `kg`），直到再遇到下一次切换信号。
   这不是"这一行要不要分段"的问题，是"这一段接下来该用哪个基线"。
4. 其余没覆盖的组合（`kg > baseline_kg` 但开头不是已知的按语引导词，等）：
   记进 `notes`，按当前基线不变、不分段处理，等着人核实。

分段本身只发生在情况 1（正常行 + 上一行没排满）。
"""
from __future__ import annotations

import re

from ..core.spec import page_key
from ..errors import ProductMissing
from ..products.kinds.cells import PageCells
from ..products.kinds.recog import PageAdmit
from ..products.store import ProductStore

CELLS_STEP = "row_segment"
CELLS_KIND = "cells"
ADMIT_STEP = "seed_admit"
ADMIT_KIND = "seed_admit"

DEFAULT_BASELINE_KG = 2

#: 抬头常见开头词——初始小表，用户 2026-09-12 定："先用一个小初始表
#: （如御、聳、指示、欽定、朝廷类），不够用时问你"。碰到不在表里的
#: 抬头候选，`reflow_page` 记进 `notes` 而不是自己瞎猜要不要认。
_TAITOU_WORDS = (
    "御", "聖", "欽定", "欽奉", "朝廷", "指示", "命", "詔", "勅", "旨",
    "皇上", "皇帝", "天", "祖宗", "本朝",
)

#: 基线切换引导词——命中即认为从这一行起，连续几行换成新基线（用新的
#: `kg` 值本身作为新基线）。目前只有"謹案"（谨案）这一条，用户原话
#: "碰到'谨案'基线变成4"，其余引导词未验证，先不猜。
_SECTION_MARKERS = ("謹按", "謹案")

_PREFIX_RE = re.compile(r"^(\^*)(\.*)")
_JIAZHU_RE = re.compile(r"<([^<>|]*)\|([^<>]*)>")


def _parse_line(line: str) -> tuple[int, int, str]:
    """拆一行的前缀：`(抬头级数, 挪抬点数, 去掉前缀记号后的正文)`。

    guji-markdown 规范里 `^` 在前 `.` 在后（见 guji-markdown spec §11.4），
    `render_column` 输出顺序也是如此，这里按同一顺序解析。
    """
    m = _PREFIX_RE.match(line)
    raised = len(m.group(1)) if m else 0
    kg = len(m.group(2)) if m else 0
    rest = line[m.end():] if m else line
    return raised, kg, rest


def _effective_kg(raised: int, kg: int) -> int:
    """把 `^`（抬头）与 `.`（挪抬）折算成同一个数轴上的"开头点数"：
    抬头 n 级 == 点数 -n，跟 `.` 的点数可以直接比大小。
    一行不会同时有抬头又有挪抬（guji-markdown `^.文` 是"先抬头再挪抬"
    的另一种写法，这版数据里没见过，真遇到再补）。
    """
    return kg - raised


def _strip_jiazhu_break(text: str) -> str:
    """`<a|b>` → `<ab>`：横排阅读版不需要竖排双行小注的转行位置，
    用户 2026-09-12 裁：去掉 `|`，直接拼接。"""
    return _JIAZHU_RE.sub(lambda m: "<" + m.group(1) + m.group(2) + ">", text)


def _column_last_slot(store: ProductStore, book: str, page: int, col: int) -> int | None:
    """这一列全部 `AdmitRec` 里最大的正文 slot（`sub is None`）。
    没有任何正文记录（比如整列都是抬头/夹注，或没跑到）时返回 None。
    """
    admit: PageAdmit | None = store.read(book, ADMIT_STEP, page_key(page), ADMIT_KIND)  # type: ignore[assignment]
    if admit is None:
        raise ProductMissing(f"{book} 第 {page} 页没有 {ADMIT_STEP} 产物（先跑到 Step7）")
    col_admit = next((c for c in admit.columns if c.col == col), None)
    if col_admit is None or not col_admit.chars:
        return None
    body_slots = [r.slot for r in col_admit.chars if r.sub is None and r.slot > 0]
    return max(body_slots) if body_slots else None


def _column_body_slots(store: ProductStore, book: str, page: int, col: int) -> int | None:
    """这一列的正文格总数（`ColumnCells.n_body_slots`）。"""
    cells: PageCells | None = store.read(book, CELLS_STEP, page_key(page), CELLS_KIND)  # type: ignore[assignment]
    if cells is None:
        raise ProductMissing(f"{book} 第 {page} 页没有 {CELLS_STEP} 产物（先跑到 Step3）")
    col_cells = next((c for c in cells.columns if c.col == col), None)
    return col_cells.n_body_slots if col_cells is not None else None


def is_column_full(store: ProductStore, book: str, page: int, col: int) -> bool:
    """这一列是否「排满」：最大正文 slot 是否等于这一列的格数容量。

    两边任一查不到（列没跑通、或者压根没有这一列）时保守判**没排满**——
    宁可多分一次段，也不要在数据缺失时假装"排满"从而漏掉该分的段。
    """
    last = _column_last_slot(store, book, page, col)
    total = _column_body_slots(store, book, page, col)
    if last is None or total is None:
        return False
    return last >= total


def reflow_page(store: ProductStore, book: str, page: int, page_text: str,
                 baseline_kg: int = DEFAULT_BASELINE_KG,
                 notes: list[str] | None = None) -> str:
    """把 9.1 的一页分行文本（`render_page` 的返回值）转成可阅读排版文本。

    `page_text`：**不带** `#第N页` 页眉的那一部分，一行对应一列，来自
    `guji_markdown.render_page()` 的直接返回值。

    `baseline_kg`：这一页/这一段正常行的挪抬点数（已知常量，不是统计出来
    的），默认 2。

    `notes`：遇到规则覆盖不到的组合（抬头候选不在词表里、或点数异常但
    不是已知的基线切换引导词）时，追加一条人类可读的说明到这里——
    **不要在没有依据的时候擅自判定**，交给调用方汇总、必要时提交给人核实。
    """
    if notes is None:
        notes = []

    lines = [ln for ln in page_text.split("\n") if ln != ""]
    if not lines:
        return ""

    parsed = [_parse_line(ln) for ln in lines]
    effs = [_effective_kg(raised, kg) for raised, kg, _ in parsed]

    paragraphs: list[str] = []
    current: list[str] = []
    baseline = baseline_kg
    prev_full: bool | None = None  # 上一条"正常行"是否排满；抬头/基线切换行不更新这个
    in_zero_run = False  # 是否已经处于"连续 kg=0 的段落基线"区间内，见下

    for i, (raised, kg, rest) in enumerate(parsed):
        text = _strip_jiazhu_break(rest)
        eff = effs[i]
        col = i + 1  # col 从 1 起

        if i == 0:
            current.append(text)
            if eff == baseline:
                prev_full = is_column_full(store, book, page, col)
            continue

        if eff == baseline:
            # 情况 1：正常行。上一条正常行没排满就分段。
            in_zero_run = False
            if prev_full is False:
                paragraphs.append("".join(current))
                current = [text]
            else:
                current.append(text)
            prev_full = is_column_full(store, book, page, col)
            continue

        if eff < baseline:
            if any(rest.startswith(w) for w in _TAITOU_WORDS):
                # 情况 2：确认是抬头——强制换行，不是新段落开始，不分段
                # （vol02 p11 教训：抬头行天然写不满，不能拿来判断要不要分段）。
                in_zero_run = False
                current.append(text)
                continue  # 不更新 prev_full

            if eff == 0:
                # 情况 3a：连续 ≥2 行都是 kg=0——这一段的基线本来就是 0
                # （如 vol02 p3 整页顶格不挪抬），**不是**逐行标题。
                # 用户 2026-09-12 裁："连续2行以上kg=0才算基线0，单独1行
                # 才算标题"——先看"已经在 0 基线区间里"或"下一行也是 0"。
                next_is_zero = i + 1 < len(effs) and effs[i + 1] == 0
                if in_zero_run or next_is_zero:
                    in_zero_run = True
                    if prev_full is False:
                        paragraphs.append("".join(current))
                        current = [text]
                    else:
                        current.append(text)
                    prev_full = is_column_full(store, book, page, col)
                    continue

                # 情况 3b：孤立的单行 kg=0——书目条目标题行
                # （如"夏易傳十一卷<內府藏本>"），前后都强制分段。
                if current:
                    paragraphs.append("".join(current))
                paragraphs.append(text)
                current = []
                prev_full = None  # 标题行前后都分段，不参与"排满"判据
                continue

            in_zero_run = False
            notes.append(
                f"col{col}: 开头点数 {eff}（基线 {baseline}）但开头词"
                f"「{rest[:4]}」不在抬头词表 _TAITOU_WORDS 里，也不是"
                f"点数=0 的标题/连续基线0情形，按不分段处理，需要人核实")
            current.append(text)
            continue  # 不更新 prev_full：这一行状态不明

        # eff > baseline：可能是基线切换（如"謹案"），也可能是没见过的情况。
        in_zero_run = False
        if any(rest.startswith(w) for w in _SECTION_MARKERS):
            baseline = eff  # 切换基线，后续行按新基线判断
            current.append(text)
            prev_full = is_column_full(store, book, page, col)
            continue

        notes.append(
            f"col{col}: 开头点数 {eff}（当前基线 {baseline}）比基线多，"
            f"但开头词「{rest[:4]}」不在基线切换词表 _SECTION_MARKERS 里，"
            f"按不分段、基线不变处理，需要人核实")
        current.append(text)
        # 不更新 prev_full——这一行本身状态不明，不能拿来做分段判据

    if current:
        paragraphs.append("".join(current))

    return "\n\n".join(paragraphs)
