# -*- coding: utf-8 -*-
"""证人里**根本没有**的段：校勘按语、卷端题、卷末题。

这些段不参与对勘——不是因为它们特殊，是因为「拿有按语的页去跟删了按语的证人
逐字比」这件事本身不成立。留着它们不但自己全报成差异，还会把整页的锚点带偏。

## 实证（bxgb，2026-09-22）

| 段 | 位置 | 证人（文集本）作 |
|---|---|---|
| 68 字校勘按语 | p56 第 1 列夾注 | **删了不收** |
| 撰人题「宋樓鑰𢰅」 | p3/p39 第 2 列 | 「四明樓鑰大防」+ 生平 |
| 卷末题「北行日錄下完」 | p56 第 13 列 | 「攻媿先生文集卷第一百二十」 |

不摘出去的后果：p56 整页 170 字里 160 字在证人里不存在，8-gram 锚定拿前 5 字
「接晚過黃壁」命中证人第 18251 字，整页按那个偏移对齐，报出 60+ 条「改/增删」
——**图与转写一个字都没错**。撰人题那 4 格则被配成 宋→州、樓→教、鑰→授、
𢰅→隨 四条假「改」外加一条 16 字 missing，一处体例差异报成五条。

## 判据：查证人里有没有，不认「案」「按」字头

起初想按起头字认（「案」起头的是按语），但全书四段夾注的起头字是
張 / 或 / 並 / 案，只有一段是按语——**样本太少，认字头就是过拟合**。
改成直接拿这段文字去证人里查：在就比，不在就不比。这是**可核实的事实**，
换一本书照样成立。实测三段「整理本有」的夾注照常比对，只有 p56 那段被摘。
"""

from __future__ import annotations

from collections import defaultdict

#: 夾注段短于这个字数就不查——「並六十陌」这类三五字的注落进证人正文纯属
#: 碰巧的概率不低，查了反而添乱。按语总是成段的。
JIAZHU_MIN = 12
#: 题名的字数范围。卷末题「北行日錄下完」6 字、撰人题「宋樓鑰𢰅」4 字；
#: 再短（两三字的卷次、页码）不足以断定，长于 12 字多半是正文列没写满。
TITLE_MIN, TITLE_MAX = 4, 12
#: 探针归一后至少这么长才判「证人里没有」。
PROBE_MIN = 6


def mostly_absent(probe: str, corpus_norm: str, k: int = 4, hit_max: float = 0.25) -> bool:
    """这段文字**整体**不在证人里吗。

    判据不是「这些 k-gram 出现过吗」，而是「它们**连在一处**出现吗」——
    按语恰恰会**大段引用**原文（bxgb p56 那段引了上卷「行三十里飯黃碧二十八里」），
    按「出现过」算命中率接近 1，会被当成正文放过去；但那些引文散落在证人的不同
    位置，**没有一个连续区间能同时装下它们**，正文则一定有。

    整串精确匹配也不行：**一个字对不上就全串落空**。p24 第 1 列是正文，
    只因证人作「廪」而刻本刻「廩」（异体表没收这对）就被误摘。

    短串（≤8 字）k-gram 太少，统计不出「大面积命中」——卷末题「北行日錄下完」
    只有 3 个 4-gram，而「北行日錄」在证人里是书名、必然命中。短串回到整串匹配，
    它们本来就短，一个字对不上的风险低。
    """
    if len(probe) <= 8:
        return probe not in corpus_norm
    grams = [probe[i:i + k] for i in range(len(probe) - k + 1)]
    if not grams:
        return probe not in corpus_norm
    best = 0.0
    for g0 in grams[:6]:
        at = corpus_norm.find(g0)
        while at >= 0:
            lo = max(0, at - len(probe))
            win = corpus_norm[lo:at + 2 * len(probe)]
            best = max(best, sum(1 for g in grams if g in win) / len(grams))
            if best > hit_max:
                return False
            at = corpus_norm.find(g0, at + 1)
            if at > lo + 4 * len(probe):
                break
    return best <= hit_max


def absent_runs(cells: list[dict], corpus_norm: str, normalize) -> list[dict]:
    """→ `[{ids, text, kind, col, n}]`。`kind` ∈ 夾注 / 卷端题 / 卷末题。

    `cells` 每项要有 `id` / `col` / `sub` / `char`（`SlotRec` 与脚本的字典都能喂，
    调用方各自适配成这个形状）。`normalize` 是异体归一函数（`VariantMap.normalize_text`）
    ——证人作「北行日録」而刻本刻「北行日錄」，不归一会把卷端题误判成「证人里没有」。
    """
    out: list[dict] = []

    # 1) 夾注段（连续带 sub 的格）——校勘按语多半在这里
    runs: list[list[dict]] = []
    cur: list[dict] = []
    for c in cells:
        if c["sub"]:
            cur.append(c)
        else:
            if cur:
                runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    for r in runs:
        t = "".join(x["char"] for x in r)
        if len(t) < JIAZHU_MIN:
            continue
        probe = normalize(t[:10]).replace("□", "")
        if len(probe) >= PROBE_MIN and probe not in corpus_norm:
            out.append({"ids": [x["id"] for x in r], "text": t, "kind": "夾注",
                        "col": r[0]["col"], "n": len(r)})

    # 2) 卷端题 / 卷末题——**只查页首两列与末列**。
    #
    # ⚠️ 起初对**每一列**都做这个判断，摘掉了 302 段 6,167 字的**正文**
    # （字位 18,237→12,138、「刻本多」暴涨到 930）。正文列在证人里是连续文本，
    # 但证人有分页、有异体、有个别识别错，「整列连续命中」正文本来就满足不了。
    # 题名的特征是**位置在页首/页末**且**自成一体**，不是「长得不像正文」。
    by_col: dict[int, list[dict]] = defaultdict(list)
    for c in cells:
        if not c["sub"]:
            by_col[c["col"]].append(c)
    body_cols = sorted(by_col)
    if not body_cols:
        return out
    taken = {i for a in out for i in a["ids"]}
    for col in sorted(set(body_cols[:2] + body_cols[-1:])):
        cs = by_col[col]
        if not (TITLE_MIN <= len(cs) <= TITLE_MAX) or any(x["id"] in taken for x in cs):
            continue
        t = "".join(x["char"] for x in cs)
        probe = normalize(t).replace("□", "")
        if probe and mostly_absent(probe, corpus_norm):
            out.append({"ids": [x["id"] for x in cs], "text": t,
                        "kind": "卷末题" if col == body_cols[-1] else "卷端题",
                        "col": col, "n": len(cs)})
    return out
