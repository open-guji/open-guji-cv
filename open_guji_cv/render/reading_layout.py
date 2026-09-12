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

## 分段判据（用户 2026-09-12 定，第四版）

- **第一版**（滑动窗口猜基线）用 vol02 p11 验证是错的：抬头行天然
  写不满，拿它的「没排满」当分段信号会把连续敬语拆得七零八落。
- **第二版**（固定基线 + `_SECTION_MARKERS` 引导词表如"謹按"）用
  vol02 p6/p7 验证又不够：「經部／易類」这类分类标题后接一段稳定在
  新点数（如 3）的正文，开头不是"謹按"而是随文而异的内容首字——
  四库分类名有几十个，逐个加进词表不是办法。
- **第三版**把"基线切换"的判据从"词表命中"改成"连续 ≥`_SECTION_RUN`
  行稳定在同一新点数"，不再需要维护 `_SECTION_MARKERS`；"謹按/謹案"
  那一行本身点数已经等于后续正文的点数（实测 vol02 p10 尾行"謹按
  唐徐堅初學記"就是 4 点，跟后面 p11 c1~c3 同值），天然被这条通用
  规则覆盖，不用再单列引导词。
- **第四版**（当前）把"标题行"判据从"只认 `eff==0`"放宽成"任何
  不命中抬头词表、不满足连续切换的孤立单行"——vol02 p6"經部"点数
  是 1、"易類"点数是 2，跟"夏易傳十一卷"那种 `eff==0` 的标题同性质，
  只是点数不是 0，没有理由只认 0 这一个值。

**基线是外部给定的已知常量**（`baseline_kg`，默认 2）。每一行的
「开头点数」`eff`（`.` 折成正数、`^` 折成负数，同一数轴）跟当前基线
比较，判断顺序固定（互斥，先命中的分支生效）：

1. `eff == baseline`：正常行。若上一条正常行没排满 → 分段；排满则
   接着拼。
2. 开头词命中 `_TAITOU_WORDS`（不论 `eff` 比基线大还是小）：抬头，
   强制换行、不分段——**优先级高于"连续同值"**，即使碰巧连续多行
   都是同一个抬头点数，只要命中词表就认抬头，不认基线切换。
3. 不命中抬头词表，且 `eff`（不论正负、不论跟基线比大小）**连续
   ≥`_SECTION_RUN` 行稳定在同一个值**：基线切换到这个新值，从这一行
   起按新基线走情况 1 的排满/分段逻辑。这条判在"孤立单行"之前——
   先排除"是切换的一部分"，才轮到下面的兜底猜测。
4. 都不是（孤立单行，前后都跟当前状态对不上）：**当标题行处理**
   （前后强制分段、独立成段），仍记一条轻量的 `notes`（"按标题行
   处理，供复核"，不是"需要人核实的疑问"）——这条比真正不确定的
   情况语气弱，是"已按规则处理，标注供检查"。
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

#: 连续几行稳定在同一新点数才认定"基线切换"，见模块头情况 4。
_SECTION_RUN = 2

#: 抬头常见开头词——初始小表，用户 2026-09-12 定："先用一个小初始表
#: （如御、聳、指示、欽定、朝廷类），不够用时问你"。碰到不在表里的
#: 抬头候选，`reflow_page` 记进 `notes` 而不是自己瞎猜要不要认。
_TAITOU_WORDS = (
    "御", "聖", "欽定", "欽奉", "朝廷", "指示", "命", "詔", "勅", "旨",
    "皇上", "皇帝", "天", "祖宗", "本朝",
)

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
    的），默认 2。**基线可以跨页延续**——调用方处理连续页时，把上一页
    返回后的当前基线传给下一页的 `baseline_kg`（本函数不自动记忆跨页
    状态，也不主动查页码是否连续，交给调用方决定要不要延续）。

    `notes`：遇到规则覆盖不到的组合（抬头候选不在词表里、点数异常但
    连续行数不够、等）时，追加一条人类可读的说明到这里——**不要在没有
    依据的时候擅自判定**，交给调用方汇总、必要时提交给人核实。
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
    prev_full: bool | None = None  # 上一条"正常行"是否排满；抬头/切换/标题行不更新这个
    in_run = False  # 是否已经处于"连续同值基线切换"区间内，见情况 4

    def is_stable_run(idx: int, value: int) -> bool:
        """从 idx 起（含）连续 `_SECTION_RUN` 行是否都等于 value——
        用来判断"新点数是不是稳定出现"，不是偶然一行。"""
        window = effs[idx:idx + _SECTION_RUN]
        return len(window) >= _SECTION_RUN and all(v == value for v in window)

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
            in_run = False
            if prev_full is False:
                paragraphs.append("".join(current))
                current = [text]
            else:
                current.append(text)
            prev_full = is_column_full(store, book, page, col)
            continue

        if any(rest.startswith(w) for w in _TAITOU_WORDS):
            # 情况 2：确认是抬头——优先级高于"连续同值"，强制换行、
            # 不是新段落开始，不分段（vol02 p11 教训：抬头行天然写
            # 不满，不能拿来判断要不要分段）。
            in_run = False
            current.append(text)
            continue  # 不更新 prev_full

        if in_run or is_stable_run(i, eff):
            # 情况 3：连续同值——基线真的切换了（含 eff=0 连续多行的
            # 情形，如 vol02 p3 整页顶格不挪抬），走正常行的排满/分段
            # 逻辑。判在"孤立单行=标题"之前——先确认不是切换，才轮到
            # 兜底的标题猜测。
            baseline = eff
            in_run = True
            if prev_full is False:
                paragraphs.append("".join(current))
                current = [text]
            else:
                current.append(text)
            prev_full = is_column_full(store, book, page, col)
            continue

        # 情况 4：既不命中抬头词表、也不满足连续切换——孤立单行。
        # 用户 2026-09-12 定（第二次放宽）：不再限定 eff==0，任何孤立
        # 单行都当标题处理（vol02 p6"經部"点数是 1、"易類"点数是 2 但
        # 前后不连续，跟"夏易傳十一卷"那种 eff=0 的标题同性质，只是
        # 点数不是 0）。仍记一条轻量记录供复核，不是"需要人核实的疑问"
        # ——这条比 notes 的疑问性质弱，是"已按规则处理，标注供检查"。
        in_run = False
        notes.append(
            f"col{col}: 开头点数 {eff}（当前基线 {baseline}），孤立单行、"
            f"不命中抬头词表，按标题行处理（独立成段），供复核："
            f"「{rest[:6]}」")
        if current:
            paragraphs.append("".join(current))
        paragraphs.append(text)
        current = []
        prev_full = None  # 标题行前后都分段，不参与"排满"判据

    if current:
        paragraphs.append("".join(current))

    return "\n\n".join(paragraphs)
