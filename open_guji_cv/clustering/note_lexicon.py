# -*- coding: utf-8 -*-
"""版本注闭集通道：把一段夹注整体对着词表定字。

## 为什么要段级

夹注的难处不是切分（四张样张逐格核对全对、段端金标 56/57），是**小字样本少**
——字形库 16,019 例里小字只有 59 例 / 52 字种，而版本注词表 183 字种里有小字
刻例的仅 11 个。逐字硬认，库 cov 落在 0.93~0.99 这个「谁也说不准」的带里，
`match_solo` 的 0.99 闸够不着，只能落人审。

但《四庫全書總目》的版本注是**闭集**：全书 1,023 行、去重 78 个短语
（`config/jiazhu/version_notes.json`，`scripts/build_note_lexicon.py` 派生）。
既然整段的候选只有 78 种，就不必逐字认——**认整段**。这是文本先验，与库/OCR
的形状证据**来源独立**，可以当双信号的一路，与 `match_ref`「文本 × 形状
同源性为零」是同一个论证。

## 判据（三条硬约束，缺一不可）

1. **段格数 == 短语长度**。丢一格就整段拒——「差不多」在这里是有害的：
   段格数不对说明切分出了问题（漏拆末行 / 多切一格），这时候硬套短语等于
   把切分错误洗成识别正确，账就再也对不上了。
2. **相似度 ≥ `MIN_SIM`**。按位比：这一位的库候选（或 OCR 候选）里出现过
   短语的这个字就算对上。用候选集合而不是 top1，因为小字的 top1 本来就不稳。
3. **唯一最佳**，且**差距按最佳成绩缩放**。词表里满是一字之差的孪生短语
   （浙江巡撫／浙江廵撫、江蘇／江西／江南巡撫、副都御史／左都御史黃登賢），
   7 字的段里差一个字就是 0.857——拿固定的 `MIN_MARGIN` 卡，**完美命中也会被
   自己的孪生兄弟拖下水**（实测 28 段只认出 4 段，认不出的全是转写本来就对的）。
   所以要求的差距是 `MIN_MARGIN × (1 - sim)`：
   - `sim == 1.0` → 只需严格大于第二名（完美命中不该被否）；
   - `sim == 0.7` → 需领先 0.045（勉强及格时要多要一点把握）。
   相似度带来的证据强度本来就该体现在门槛上，一刀切是错的。

三条都过，整段按短语逐位定字；否则整段回落，逐位走原有通道。

## 不做的事

- **不引入候选外的字**（`context_step` 铁律 1）：短语给的是**读法**，进库的
  字形仍要过账本的 preferred/组内定形。这里只产出 `(id, char)` 建议，
  写不写库由 `seed_admit` 按原有规则决定。
- **不猜段界**：段由 `jiazhu_order.segments` 给（slot 连续 + 有 sub），
  与 `row_boundaries.reading_order` 同源。
- **不管 T2 案語**：那是开放文本，词表里没有，`match(...)` 自然返回 None。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_LEXICON = REPO / "config" / "jiazhu" / "version_notes.json"

#: 按位命中率下限。0.70 = 10 格的段允许 3 格对不上（小字 + 生僻人名地名很常见）。
MIN_SIM = 0.70
#: 最佳与次佳的差**系数**（按 `1 - sim` 缩放，见模块头判据 3）。
#: 完美命中只需严格胜出；越不完美要求的领先越多。
MIN_MARGIN = 0.15
#: 段长超出这个范围不试（词表最长 13，留点余量；太短的段信息量不足以定段）。
MIN_CELLS, MAX_CELLS = 3, 20


@lru_cache(maxsize=4)
def load_lexicon(path: str | None = None) -> tuple[str, ...]:
    """词表短语（按语料频次降序）。缺文件返回空 —— 通道自动失效，不炸。"""
    p = Path(path) if path else DEFAULT_LEXICON
    if not p.exists():
        return ()
    doc = json.loads(p.read_text(encoding="utf-8"))
    return tuple(x["text"] for x in doc.get("phrases", []))


def _similarity(cands: list[set[str]], phrase: str,
                semantic=None) -> float:
    """按位比：第 i 格的候选集合里有没有 phrase[i]。长度不等直接 0。

    `semantic` 给了就按**语义**比（异体算同字）：刻本刻 直𨽾總督採進本，
    词表（整理本派生）写的是 直隸總督採進本——𨽾 是 隸 的刻本异体，不认它
    就永远差一个字，还会和孪生短语 直隷 打平而双双出局。这与
    `seeding.admission_decision` 全程用 `vmap.semantic(...)` 比字是同一口径。
    """
    if len(cands) != len(phrase):
        return 0.0
    if semantic is None:
        hit = sum(1 for i, ch in enumerate(phrase) if ch in cands[i])
    else:
        hit = 0
        for i, ch in enumerate(phrase):
            if ch in cands[i]:
                hit += 1
                continue
            t = semantic(ch)
            if any(semantic(c) == t for c in cands[i]):
                hit += 1
    return hit / len(phrase)


def match_segment(cands: list[set[str]], lexicon: tuple[str, ...] | None = None,
                  min_sim: float = MIN_SIM, min_margin: float = MIN_MARGIN,
                  semantic=None) -> tuple[str, float] | None:
    """一段夹注的逐格候选集合 → `(短语, 相似度)`，定不下来返回 None。

    `cands` 已按**阅读顺序**排好（a 全部再 b 全部），每格一个候选字集合。
    `semantic` 是异体归一函数（`VariantMap.semantic`），见 `_similarity`。
    """
    n = len(cands)
    if not (MIN_CELLS <= n <= MAX_CELLS):
        return None
    lex = lexicon if lexicon is not None else load_lexicon()
    scored = [(p, _similarity(cands, p, semantic)) for p in lex if len(p) == n]
    if not scored:
        return None
    scored.sort(key=lambda t: -t[1])
    best, sim = scored[0]
    if sim < min_sim:
        return None
    if len(scored) > 1:
        gap = sim - scored[1][1]
        need = min_margin * (1.0 - sim)     # 完美命中 → 只需严格胜出
        if gap <= 0 or gap < need:
            return None
    return best, sim
