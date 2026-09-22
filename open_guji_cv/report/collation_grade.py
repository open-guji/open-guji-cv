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

#: 整理本作这些字时，刻本多半是**避諱改字**——改法不固定，同一个「虜」在
#: 不同处被改成 金/國/今/乃/人/敵/改/因/彼/其…（bxgb 实测 10 种以上）。
#: 按**目标字**认，比穷举字对靠谱：穷举永远漏，而「整理本写虜、刻本写别的」
#: 这个模式本身就是避諱的定义。
#: ⚠️ 只在**整理本侧**匹配：刻本侧写什么都算，因为改法就是不固定的。
TABOO_TARGETS = frozenset("虜酋褎亮")

#: 固定字对（`TABOO_TARGETS` 之外的避諱，如避孔子諱）。清刻本避諱是版本学事实、
#: 不是统计推断，所以单独列表，不参与重复度判定（出现 1 次也算版本差异）。
TABOO = {
    ("金", "虜"), ("國", "虜"), ("擄", "虜"), ("今", "虜"), ("乃", "虜"),
    ("金", "褎"), ("新", "褎"),
    # 避孔子諱：刻「𠀉」代「丘」。bxgb 全书 16 处（閭𠀉、封𠀉、雍𠀉、內𠀉…），
    # 重复度够高、本来也会落进 systematic 档，但它的性质是**避諱**不是正俗字，
    # 归对档才说得清「为什么刻本要这么刻」。
    ("𠀉", "丘"),
}

GRADE_LABEL = {
    "taboo": "避諱改字",
    "systematic": "正俗·异体（系统性）",
    "variant": "异体（关系图已收）",
    "gap": "增删（脱衍）",
    "human": "人裁定字（与整理本不同）",
    "misanchor": "整段错位（锚定失败）",
    "suspect": "存疑·待覈",
}

#: 哪些层是「成果」（转写忠于刻本，不用改），哪些是「待办」。
#: `human` 进成果：人看过图、定了字，这条差异就是**人判定的版本差异**，
#: 不该再挂在待办里让人重看一遍（bxgb 实测：130 条「存疑」里 109 条是人裁过的，
#: 全是 鳥/烏、扣/叩、溪/谿、棊/棋 这类一眼可判的正俗字，只因全书恰好出现一两次
#: 没够上重复度阈值）。`misanchor` 单列：那不是字错，是整页对不上。
SETTLED = ("taboo", "systematic", "variant", "human")
TODO = ("suspect",)


def grade_pairs(entries: list[dict]) -> Counter:
    """全书字对出现次数（只数 substitution，`variant` 另有关系图判据）。"""
    return Counter((e["hyp"], e["ref"]) for e in entries
                   if e["kind"] == "substitution")


#: 一页不一致率超过这个数，就当整段错位，不当成逐字认错。
#: bxgb 实测：全书中位数 2.5%，最高的正常页 5.1%（p3，卷端题那列），
#: 而 p56 是 33.9%——卷末按语列锚错，整段跟错了位置。两者差一个数量级，
#: 20% 落在中间的空档里，不是精调出来的。
MISANCHOR_RATE = 0.20


def misanchored_pages(page_stats: dict, rate: float = MISANCHOR_RATE) -> frozenset[int]:
    """按不一致率挑出「整段错位」的页。

    锚定**失败**的页（`anchored=False`）根本不出差异条目，这里管的是另一种：
    锚上了、但锚到了错的位置，于是整页逐字比对全错。这种页的差异报成几十条
    「改」，看的人会以为识别烂掉了，其实转写一个字都没错——
    bxgb p56 实证：`飯黃碧二十八里` 被配到 `飯摩訶樣又行數里`。
    """
    out = set()
    for p, s in (page_stats or {}).items():
        n = (s.get("n_slots") or 0) - (s.get("excluded") or 0)
        if n > 0 and 1 - (s.get("equal") or 0) / n >= rate:
            out.add(int(p))
    return frozenset(out)


def _is_human(e: dict) -> bool:
    """这个字是人定的吗。

    `human` = 本次转写直接取人裁 shape；`auto:human` = Step7 因为有人裁记录才放行。
    对分层是同一件事：**人看过这张图并定了这个字**。
    """
    return str(e.get("source", "")).endswith("human")


def grade(e: dict, pairs: Counter, misanchored: frozenset[int] = frozenset()) -> str:
    """给一条差异定层。

    `pairs` 来自 `grade_pairs`（**全书**统计，不能只看本页）；
    `misanchored` 是锚定失败/整段错位的页号——那些页上的差异不是字错，是对不上号。
    """
    if e.get("page") in misanchored:
        return "misanchor"
    k = e["kind"]
    if k in ("missing", "extra"):
        return "gap"
    if k == "unreadable":
        return "suspect"
    if k == "variant":
        return "variant"
    pair = (e["hyp"], e["ref"])
    if pair in TABOO or e["ref"] in TABOO_TARGETS:
        return "taboo"
    if pairs.get(pair, 0) >= REPEAT_MIN:
        return "systematic"
    # 人裁过的排在统计判据**之后**：先认避諱与系统性（那是版本学事实，
    # 比「谁定的字」更强的判据），剩下的才按「有没有人看过」分。
    if _is_human(e):
        return "human"
    return "suspect"


def summarize(entries: list[dict], misanchored: frozenset[int] | set[int] = frozenset()) -> dict:
    """→ {grade: [entries]} + 计数。给报告顶部那段结论用。"""
    pairs = grade_pairs(entries)
    mis = frozenset(misanchored)
    by: dict[str, list] = {g: [] for g in GRADE_LABEL}
    for e in entries:
        g = grade(e, pairs, mis)
        e["grade"] = g
        by[g].append(e)
    return {
        "by_grade": by,
        "counts": {g: len(v) for g, v in by.items()},
        "n_settled": sum(len(by[g]) for g in SETTLED),
        "n_todo": sum(len(by[g]) for g in TODO),
        "pairs": pairs,
    }
