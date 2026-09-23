# -*- coding: utf-8 -*-
"""差异的**三层分类**与**按字对聚合**：把 343 条压成 154 次判断。

用户 2026-09-22 定的框架：

> 首先一部分是通用的异体字，我们应该有一个通用的异体字表，根据那个就可以确定
> 它是不是只是异体字……第二层是这本书特有的一些字形转换，包括像这个父亲的父的
> 这个不同写法，以及一些特殊的避讳字，它是在这本书里常用，但在另一本书可能就
> 不常用了……第三类就是它出现的也不频繁，也不是这本书特有的，就要看到底是谁错了。

| 层 | 判据 | bxgb 实测 | 人要做什么 |
|---|---|---|---|
| `taboo` 避諱改字 | 避諱字表 / 目标字 | 40 条 / 17 对 | 什么都不用做 |
| ① `common` 通用异体 | 通用异体关系图有边 | 185 条 / 74 对 | **选做**复核，可推翻 |
| ② `book` 本书特有 | 表外 ＋ 本书反复（≥`BOOK_MIN`） | 69 条 / 11 对 | 批量确认一次 |
| ③ `dispute` 零星分歧 | 表外 ＋ 零星 | 72 条 / 64 对 | 逐对判谁错 |

避諱单列在三层之外：它是**版本学事实**，不需要人判。不先认它，
今→虜、金→褎 这些对会散落进 ③ 让人一对对地判「谁错了」——而没有一处是错的。

## 为什么按字对聚合，不按条

`𠊓→傍` 一对就占 24 条。**同一字对的判断几乎总是相同的**，逐条问等于把同一个
问题问 24 遍。bxgb 聚合后：必做 ②11 ＋ ③64 = 75 次，全查也只 155 次。

## ⚠️ ① 不是「不用看」，是「不用先看」

关系图**会错**——2026-09-22 实测查出 `治/冶`、`輨/轄` 两条错边，而它们正是被
「关系图说是异体」这一条送进成果档的，躺了三天没人看见。**自动归档必须可被
人推翻**：推翻的字对写进 `variants.deny.tsv`（跨书负样本），以后哪本书都不再
拿它当异体。

## ② 为什么落书配置而不是全局表

`完→元` 是这部书证人的编辑方针（女真姓氏「完顏」整理本作「元顏」），
**放进全局异体表会污染别的书**——别的书里「完」和「元」就是两个字。
"""

from __future__ import annotations

from collections import Counter, defaultdict

#: ② 的门槛：同一字对在本书出现几次以上，才算「本书通例」而非偶发分歧。
#: 与 `collation_grade.REPEAT_MIN` 同源同值——2 次可能是同一块坏版连错两页。
BOOK_MIN = 3

TIER_LABEL = {
    "taboo": "避諱改字",
    "common": "通用异体",
    "book": "本书特有转换",
    "dispute": "零星分歧",
}

#: ② 确认时人选的性质。用户 2026-09-22 定（「名物」拆成「人名」「物品」）。
CONVENTION_KINDS = ("人名", "物品", "通假", "避諱", "正俗")


def _same_char(a: str, b: str) -> bool:
    """通用异体关系图认不认这一对。走 `eval.round_check._same_char`——
    那里已经按**来源数**判（单一 twedu 来源不算数），别在这里另起一套。"""
    try:
        from ..eval.round_check import _same_char as sc
        return bool(sc(a, b))
    except Exception:
        return False


def tier_of(hyp: str, ref: str, n: int, *, conventions: set | None = None,
            denied: set | None = None) -> str:
    """一对字属于哪一层。`n` 是它在**全书**出现的次数。

    顺序有讲究：先看人已经裁过的（`conventions` / `denied`），再看关系图，
    最后才按重复度分。人的结论优先于任何自动判据。
    """
    pair = (hyp, ref)
    # 避諱是**版本学事实**，比任何统计判据都硬：清刻本回避「虜」，同一个字在不同处
    # 被刻成 金/國/今/乃/人/敵/改/因/彼/其… 十几种。不先认它，这些对会散落进 ③
    # 让人一对一对地判「谁错了」——而没有一处是错的。
    from .collation_grade import TABOO, TABOO_TARGETS
    if pair in TABOO or ref in TABOO_TARGETS:
        return "taboo"
    if conventions and pair in conventions:
        return "book"
    if denied and pair in denied:
        # 人推翻过的关系图边：不再算通用异体，退回逐对判
        return "dispute"
    if _same_char(hyp, ref):
        return "common"
    return "book" if n >= BOOK_MIN else "dispute"


def pair_index(diffs: list[dict], *, conventions: set | None = None,
               denied: set | None = None, kinds: tuple = ("sub.", "variant.")) -> list[dict]:
    """差异清单 → **按字对聚合**的条目，每条带层、次数、全部实例 id。

    只收替换类（`sub.*` / `variant.*`）——增删（`missing`/`extra`）没有「对应的
    另一个字」，聚合不了，它们在报告里单独一档。

    返回按「层的紧要程度 → 出现次数」排序：③ 在前（要判谁错），
    ② 次之（批量确认），① 最后（选做复核）。
    """
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for d in diffs:
        if not str(d.get("kind", "")).startswith(kinds):
            continue
        a, b = d.get("char"), d.get("ref")
        if not a or not b or a == b:
            continue
        buckets[(a, b)].append(d)

    order = {"dispute": 0, "book": 1, "common": 2, "taboo": 3}
    out = []
    for (a, b), rows in buckets.items():
        t = tier_of(a, b, len(rows), conventions=conventions, denied=denied)
        out.append({
            "pair": [a, b],
            "tier": t,
            "n": len(rows),
            "ids": [r["id"] for r in rows],
            "pages": sorted({r["page"] for r in rows}),
            # 前 3 个实例给裁决台出图与上下文，其余点开再取
            "samples": [{k: r.get(k) for k in
                         ("id", "page", "col", "slot", "sub", "hyp_ctx", "ref_ctx",
                          "channel", "human", "kind")}
                        for r in rows[:3]],
        })
    out.sort(key=lambda x: (order[x["tier"]], -x["n"], x["pair"]))
    return out


def tier_counts(index: list[dict]) -> dict:
    """→ `{层: {"pairs": 字对数, "items": 条数}}`，给看板顶部那排数用。

    **两个数都要给**：人按「对」判，但报告讲「条」——只给一个会让人算不清
    工作量（274 条听着吓人，其实只有 107 对）。
    """
    pc, ic = Counter(), Counter()
    for r in index:
        pc[r["tier"]] += 1
        ic[r["tier"]] += r["n"]
    return {t: {"pairs": pc.get(t, 0), "items": ic.get(t, 0)} for t in TIER_LABEL}
