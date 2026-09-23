# -*- coding: utf-8 -*-
"""证人（整理本）的装载与索引。

三份整理本的来历、质量分级与结构实测见 `overview` 仓
`项目进展/图片初步数字化/进度/Step9-结果整理/05-整理本清单.md`（唯一真相源）。
摘要：

| 文件 | 质量 | 结构 |
|---|---|---|
| `zongmu_wenyuange_wikisource.txt`（**实为四库光盘版**，待改名 `siku_guangpan.txt`） | **best** | **19 字一行 ＝ 我们刻本的一列**（行首两格版式留白不录） |
| `zongmu_wuyingdian_reference.txt`（朋友「杳冥」整理） | mid | 按段，长行 100~1485 字 |
| `zongmu_wikisource_reference.txt`（维基文库） | low | 整块 2 行 |

## ⭐ 光盘版的行 ＝ 我们的列（2026-09-13 实测，别当巧合）

用户订正「19 个字一行是没算两个空格」后实测 `align_ref` 全部已锚定页：

- 19 字行占全部 147,585 行的 76.4%（只看长行是 84.9%）；
- **列首落在语料行首**：vol01 94.7%（1259/1329）、vol02 98.2%（1608/1637）；
- 列长与对应行长**相等**：命中行首的 2,867 列里 2,500 相等（87.2%）；
- 不等的 367 列里 **273 列是我们少字**（差 −1 占 216 条）——正是丢格缺陷。

（以上是 2026-09-13 用本模块 ＋ `collate.py` 的生产路径全量重量的数。
更早一版档里记的「vol01 93.7% / vol02 76.2%」出自一次性草稿脚本——它用
「锚定 offset ＋ 字位序号」线性推位置，页内一有增删就整体偏掉，**已作废**。）

所以这份语料不只是字符流证人，还是**列结构证人**：不做字符比对也能查出
「这一列少了几个字」，且**独立于 difflib 怎么对齐**。`line_starts` 就是为它准备的。

`col_verdict()` 对未命中行首的列只报 `col.drift` 供人看，**不当成错误计数**
——抬头/标题行本来就不一定断行，那不是缺陷。

## 为什么要 `han_only` 与位置映射表

锚定与对齐都只吃汉字（`clustering/align_label` 的第一个坑：整理本夹着抬头码
`⏎b1`/`c3`/`a1`、全角空格、行末连字符，8-gram 投票按原文位置数偏移，页内一有
这些标记页首就锚晚几字）。但**行起点是原文的概念**，要把它换算到汉字流的坐标
系里才能跟对齐结果比——`line_starts` 存的已经是汉字流坐标，调用方直接用。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..clustering.align_eval import build_ngram_index
from ..clustering.align_label import is_han
from ..core.workspace import corpus_path

#: 质量分级（05 §一）。证人不一致时按这个加权，**不是简单多数**。
QUALITY_ORDER = {"best": 3, "mid": 2, "low": 1}

#: 没有 `references:` 配置时的默认证人——与 `align_ref`/`context_decide` 同一份语料
#: （`steps/align_ref.py` 的 DEFAULT_CORPUS），即光盘版。
DEFAULT_WITNESS = "zongmu_wenyuange_wikisource.txt"


@dataclass
class Witness:
    """一份装载好的整理本。`text` 是**只留汉字**的流，所有 offset 都在它的坐标系里。"""
    name: str
    label: str
    quality: str                       # best | mid | low
    text: str                          # 只留汉字
    line_starts: frozenset[int] = field(default_factory=frozenset)
    """每一原文行首字在 `text`（汉字流）里的 offset。光盘版靠它做列结构比对；
    段落式整理本（杳冥本）这个集合就是段首，密度低，`line_is_column` 为假时
    调用方不该拿它判列。"""
    line_is_column: bool = False       # 这份证人的「行」是否对应我们的「列」
    index: dict = field(default_factory=dict, repr=False)   # 8-gram 索引，建一次复用
    text_norm: str = field(default="", repr=False)
    """`text` 的异体归一版，建一次复用（`report/absent.py` 要按归一层查段）。
    证人作「北行日録」而刻本刻「北行日錄」，不归一会把卷端题误判成「证人里没有」。
    18k 字逐页重算等于白跑 54 遍。"""

    @property
    def rank(self) -> int:
        return QUALITY_ORDER.get(self.quality, 0)


def load_witness(name: str, label: str = "", quality: str = "mid",
                 line_is_column: bool = False, build_index: bool = True) -> Witness:
    """读一份整理本 → `Witness`。路径走 `core.workspace.corpus_path`。

    ⚠️ **不要写死 `"corpus/xxx.txt"` 相对路径**——那种写法靠进程 cwd 解析，
    曾让仓内 6000 字小样本与工作区真语料悄悄分叉 4680 行无人发现
    （见 `core/workspace.py` 与 `steps/align_ref.py` 模块头）。
    """
    p = Path(corpus_path(name))
    raw = p.read_text(encoding="utf-8")

    han: list[str] = []
    starts: set[int] = set()
    for line in raw.split("\n"):
        # `#` 开头是语料自带的来历说明（光盘版首行 1286 字，维基版两行）。
        # **必须整行剥掉**：它绝大部分是汉字，只按 is_han 过滤会把它当正文吃进流里，
        # 后面每一个 offset 都偏掉，`line_starts` 与对齐结果就对不上了。
        # （现役 align_ref/context_decide 不剥它也没事——一行在 262 万字里赢不了
        # 8-gram 投票；但本模块要拿 offset 做列结构比对，差一个字都不行。）
        if line.startswith("#"):
            continue
        at_line_start = True
        for ch in line:
            if not is_han(ch):
                # 非汉字（标点/空格/夹注尖括号/PUA 缺字符）不进流，但**不打断行首标记**
                # ——行首若是全角空格或夹注 `<`，其后的第一个汉字仍是这一行的首字。
                continue
            if at_line_start:
                starts.add(len(han))
                at_line_start = False
            han.append(ch)

    text = "".join(han)
    from ..clustering.variants import VariantMap
    return Witness(name=name, label=label or name, quality=quality, text=text,
                   line_starts=frozenset(starts), line_is_column=line_is_column,
                   index=build_ngram_index(text) if build_index else {},
                   text_norm=VariantMap.load().normalize_text(text))


def load_witnesses(specs: list[dict] | None, build_index: bool = True) -> list[Witness]:
    """书配置 `references:` → 证人列表，按质量降序（最好的在前）。

    `specs` 为空时退回默认单证人（光盘版）。每项：
    `{file, quality, label, line_is_column}`。
    """
    if not specs:
        specs = [{"file": DEFAULT_WITNESS, "quality": "best",
                  "label": "四库光盘版", "line_is_column": True}]
    out = [load_witness(s["file"], s.get("label", ""), s.get("quality", "mid"),
                        bool(s.get("line_is_column")), build_index)
           for s in specs]
    return sorted(out, key=lambda w: -w.rank)


def col_verdict(col_start: int, col_len: int, w: Witness) -> tuple[str, int]:
    """一列的结构裁定 → `(kind, delta)`，`delta` ＝ 我们的字数 − 证人的行长。

    `col_start`：这一列首字在证人汉字流里的 offset（由字符对齐给出）。

    只在 `w.line_is_column` 为真时有意义。四种裁定见 04 卡 §二·5·a：

    - `col.ok`：列首命中行首且长度相等（实测占命中行首的 87.2%）；
    - `col.short`：命中行首但我们**少**字 → Step3 丢格（不等的 367 列里 273 条）；
    - `col.long`：命中行首但我们多字 → Step3 多切，或证人漏字；
    - `col.drift`：列首没落在行首——上游累积错位，或本列是抬头/标题
      （证人对这类行不一定断行）。**这条不当错误计数**。
    """
    if col_start not in w.line_starts:
        return "col.drift", 0
    # 行长 = 到下一个行首的距离；末行到文本末尾
    nxt = _next_line_start(col_start, w)
    line_len = (nxt if nxt is not None else len(w.text)) - col_start
    delta = col_len - line_len
    if delta == 0:
        return "col.ok", 0
    return ("col.long" if delta > 0 else "col.short"), delta


def _next_line_start(pos: int, w: Witness) -> int | None:
    """`pos` 之后最近的行首。`line_starts` 是集合，这里线性往后找——
    行长上限很小（光盘版 19~21），扫几十步就停，不值得再建一个有序表。"""
    for i in range(pos + 1, min(pos + 400, len(w.text)) + 1):
        if i in w.line_starts:
            return i
    return None
