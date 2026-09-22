# -*- coding: utf-8 -*-
"""对勘差异的**定性分层**：把「我们错了」从「两个本子本来就不同」里分出来。

`build_collation_report.py` 出的是一张 545 行的平表，三分类（variant / substitution /
extra）答的是「字面一不一样」，答不了看报告的人真正要问的那一句：

> 这条差异，是**我们录错了**，还是**刻本与整理本本来就不同**？

这两件事的处置完全相反：前者是待办（要回去看图改），后者是成果（证明转写忠于刻本、
不该改）。混在一张表里，看的人只能逐条自己判，545 条谁也判不完。

## 判据：重复度 + 已知关系

分层不靠猜，靠三个**可核的**判据叠加：

1. **重复度**——同一对字（刻本 X / 整理本 Y）在全书反复出现。bxgb 实测：
   重复 ≥3 次的 30 种字对覆盖 177 处，只出现 1 次的有 108 种。
   `𠊓→傍` 出现 24 次不可能是随机识别错——识别错是散的，版本差异是系统的。
2. **避諱字表**——清刻本回避的字族（虜/褎 等），刻本改字、整理本回改原字。
   这是版本学事实，不是判断。
3. **异体关系**——`VariantMap` 已有的关系图（`_same_char`）。

三条都不命中、且只出现一两次的，才落进「存疑」。

## 为什么重复度阈值是 3

2 次可能是同一个字在相邻两页被同样地认错（同一块坏版、同一种粘连）。3 次以上跨页
反复出现，识别错误的概率就低到可以忽略了。这个阈值是**可调的**（`REPEAT_MIN`），
调它之前先看 `grade_pairs()` 出的表，别凭感觉。

⚠️ 分层是**给人看的排序**，不是闸。落进「存疑」不等于错，落进「版本差异」也不等于
一定对——只是把 545 条按「最该先看哪条」排了个序。报告里每一类都写明了判据来源，
看的人可以不同意。
"""

from __future__ import annotations

from collections import Counter

#: 重复几次以上算「系统性」。见模块头「为什么是 3」。
REPEAT_MIN = 3

#: 清刻本避諱改字：刻本用 key、整理本回改成 value。知不足齋本（乾隆—道光间）
#: 回避「虜」「褎」一族，以形近或同音字代之。这是版本学事实，不是统计推断——
#: 所以单独列表，不参与重复度判定（出现 1 次也算版本差异）。
#: 出处：本册实测字对 + 清代避諱通例；新增前先在 collation json 里核实际字对。
TABOO = {
    ("金", "虜"), ("國", "虜"), ("擄", "虜"), ("今", "虜"), ("乃", "虜"),
    ("金", "褎"), ("新", "褎"),
}

GRADE_LABEL = {
    "taboo": "避諱改字",
    "systematic": "正俗·异体（系统性）",
    "variant": "异体（关系图已收）",
    "gap": "增删（脱衍）",
    "suspect": "存疑·待覈",
}

#: 哪些层是「成果」（转写忠于刻本，不用改），哪些是「待办」。
SETTLED = ("taboo", "systematic", "variant")
TODO = ("suspect",)


def grade_pairs(entries: list[dict]) -> Counter:
    """全书字对出现次数（只数 substitution，`variant` 另有关系图判据）。"""
    return Counter((e["hyp"], e["ref"]) for e in entries
                   if e["kind"] == "substitution")


def grade(e: dict, pairs: Counter) -> str:
    """给一条差异定层。`pairs` 来自 `grade_pairs`（全书统计，不能只看本页）。"""
    k = e["kind"]
    if k in ("missing", "extra"):
        return "gap"
    if k == "unreadable":
        return "suspect"
    if k == "variant":
        return "variant"
    pair = (e["hyp"], e["ref"])
    if pair in TABOO:
        return "taboo"
    if pairs.get(pair, 0) >= REPEAT_MIN:
        return "systematic"
    return "suspect"


def summarize(entries: list[dict]) -> dict:
    """→ {grade: [entries]} + 计数。给报告顶部那段结论用。"""
    pairs = grade_pairs(entries)
    by: dict[str, list] = {g: [] for g in GRADE_LABEL}
    for e in entries:
        g = grade(e, pairs)
        e["grade"] = g
        by[g].append(e)
    return {
        "by_grade": by,
        "counts": {g: len(v) for g, v in by.items()},
        "n_settled": sum(len(by[g]) for g in SETTLED),
        "n_todo": sum(len(by[g]) for g in TODO),
        "pairs": pairs,
    }
