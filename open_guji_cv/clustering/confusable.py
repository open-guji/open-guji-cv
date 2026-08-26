# -*- coding: utf-8 -*-
"""形近字对照表：匹配侧的「这两个字太像，别下断言」名单。

## 为什么要有这张表

库匹配唯一的硬约束是 `match_precision ≥ 0.999`，而覆盖率的天花板由**异字对
分数的上尾**决定：刻 + 印 + 扫 + 归一化把区分性细节抹平之后，末/未、目/自、
注/註 这类在书上能到 0.99 以上，闸只好站得比它们还高，于是真同字对也一起被
挡在外面。留出实测（`scripts/eval_guard_ceiling.py`）：闸 0.9933 时 recall
只有 0.196；把形近对从「误判」里摘出去（系统对它们不下断言，交给 OCR/语言
模型），闸能降到 0.986，recall 涨到 0.40。

## 两张表，别混

- `NEVER_MATCH_FAMILIES` —— **手工核过的**，每一对都有实审案底（见各行注释）。
  它同时供 `seeding.NEAR_FORM_CHARS` 用：那边一旦命中就**拦掉采信通道**，
  代价高，所以只放核过的。
- `FONT_TABLE` —— 字体渲染自动跑出来的形近表（`build_confusable_families.py`）。
  它只喂**匹配侧**的降档护栏：命中只是把 `same` 降成 `unsure`，还有候选+
  上下文兜底，代价低，宁可多拦。
- `HUMAN_TABLE` —— **人裁确认的**形近对（`config/confusable_human.json`，27 对）：
  「疑似错标裁决台」71 张里判「标的没错」的那 67 条，每条给出这个刻例反复
  撞上的那个字。它不是猜的形近，是**这本书上真会混**的形近，所以按对算的
  含金量比字体表高得多——留出实测见下。

两张表的门槛不同是**故意的**：一个错拦的代价是「少一次自动采信」，另一个
错拦的代价是「一个字被判死」。

## τ 怎么定的

`eval_guard_ceiling.py` 在 pairs 留出集上扫 τ，同时看两件事：recall 涨多少、
**牵连**（有多大比例的同字对，它那个字在表里有对手）涨多少——牵连就是线上
被降成 unsure 的那部分，是这张表的成本。degraded 渲染那版的拐点在 0.988：

    τ=0.995  recall 0.196 (1.0×)  牵连  2.5%
    τ=0.99   recall 0.319 (1.6×)  牵连 11.1%
    τ=0.988  recall 0.403 (2.1×)  牵连 13.7%   ← 拐点
    τ=0.98   recall 0.463 (2.4×)  牵连 20.6%
    τ=0.93   recall 0.738 (3.8×)  牵连 78.6%   ← 靠「什么都不判」换来的，不算数

干净渲染那版在同等牵连下一律更差（字体上分得开的字，书上分不开），所以
默认用 degraded。
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

_CFG = Path(__file__).resolve().parents[2] / "config"

FONT_TABLE = _CFG / "confusable_font_degraded.json"
FONT_TAU = 0.988
# 对比实验用：GUJI_CONFUSABLE=off 只留手工表（= 接字体/人裁表之前的行为），
# GUJI_CONFUSABLE=hand+human 不要字体表，或直接给个数当 τ。
_ENV = os.environ.get("GUJI_CONFUSABLE", "").strip().lower()
HUMAN_TABLE = _CFG / "confusable_human.json"

# 手工核过的形近否决家族。每一对都是实审案底，别凭感觉往里加。
NEVER_MATCH_FAMILIES: list[tuple[str, str]] = [
    ("諭", "論"), ("遺", "還"), ("圓", "圖"), ("大", "太"), ("廣", "贋"),
    ("候", "侯"), ("間", "問"), ("已", "巳"), ("曾", "會"), ("選", "過"),
    ("人", "入"), ("未", "末"), ("面", "而"), ("夬", "夫"), ("彖", "象"),
    # 匕/七：margin 标定唯一阈上错例（vol02:37:6:12，diff 分支 OCR 认错）。
    # 本表只防库匹配侧；OCR-only 路径（diff 档）管不到，属残余风险，
    # 出路是 char-ocr 集给 OCR 分支单独立门。
    ("匕", "七"),
    # 日/曰：vol01:10:9:10 实审发现（裘曰修之「曰」，库内「日」对它
    # cov 0.96 已进 unsure 带；OCR 也认成日）。同形程度全表最高。
    ("日", "曰"),
    # 揀/棟：vol01:9:4:12 实锤（match_solo 通道首个错例——揀选之「揀」
    # 对库内「棟」cov 0.9802，偏旁 扌/木 之差全落一个残差窗，wmax 13）。
    ("揀", "棟"),
    # 己/已、己/巳：vol01:21:3:19 实锤（因己身→人裁误判巳，align/图块
    # 目视核对后改判己）。与 已/巳 不同——己是**真的另一个字**
    # （自己 vs 已经/地支），不是同词异写，字形层同样要拦；但不进
    # seeding.py 的 SEMANTIC_MERGED_PAIRS（上下文通道不豁免它）。
    ("己", "已"), ("己", "巳"),
]


def _flat(p: Path) -> frozenset[tuple[str, str]]:
    """读一张只有断言、没有分数的表（人裁表）。"""
    if not p.exists():
        return frozenset()
    tab = json.loads(p.read_text(encoding="utf-8")).get("pairs", {})
    return frozenset((k[0], k[1]) if k[0] <= k[1] else (k[1], k[0])
                     for k in tab if len(k) == 2)


@lru_cache(maxsize=4)
def font_pairs(tau: float = FONT_TAU, path: str | None = None) -> frozenset[tuple[str, str]]:
    """字体形近表里 ≥ τ 的字对（无序对，两端按码点排好）。表缺失就当空表。"""
    p = Path(path) if path else FONT_TABLE
    if not p.exists():
        return frozenset()
    tab = json.loads(p.read_text(encoding="utf-8"))
    tab = tab.get("pairs", tab)
    out = set()
    for k, v in tab.items():
        if len(k) == 2 and v >= tau:
            out.add((k[0], k[1]) if k[0] <= k[1] else (k[1], k[0]))
    return frozenset(out)


@lru_cache(maxsize=8)
def partners(tau: float | None = FONT_TAU, path: str | None = None) -> dict[str, frozenset[str]]:
    """字 → 它的形近对手集合。`tau=None` 表示不要字体表。"""
    human = True
    if _ENV == "off":
        tau, human = None, False
    elif _ENV in ("hand+human", "nofont"):
        tau = None
    elif _ENV:
        tau = float(_ENV)
    acc: dict[str, set[str]] = {}
    pairs = set(NEVER_MATCH_FAMILIES) | (set(_flat(HUMAN_TABLE)) if human else set())
    if tau is not None:
        pairs |= set(font_pairs(tau, path))
    for a, b in pairs:
        acc.setdefault(a, set()).add(b)
        acc.setdefault(b, set()).add(a)
    return {k: frozenset(v) for k, v in acc.items()}


# ## 留出实测：人裁表按对算比字体表值钱，但**按书走**
#
# 表从一册的人裁学、拿另一册的对评（`eval_guard_ceiling.py --book`）：
#
#     评 vol02（基线 recall 0.4252）
#       vol01 人裁 17 对   → 0.6642 (1.6×)  牵连  9.1%
#       字体 78 对         → 0.6642 (1.6×)  牵连 14.3%
#       两张并起来 97 对   → 0.7739 (1.8×)  牵连 18.8%
#
#     评 vol01（基线 recall 0.0726）
#       vol02 人裁 18 对   → 0.0726 (1.0×)  ← **一点没帮上**
#       字体 78 对         → 0.1918 (2.6×)  牵连 14.1%
#
# 两条结论：
# 1. **人裁表按对算远比字体表值钱**——17 对做到了 78 对的效果，牵连还少三分之一；
# 2. **但它不保证跨书转移**：vol01 学的能帮 vol02，反过来完全没用。每本书的
#    上尾由那本书的刻工与刷印决定。所以形近表要**按书养**：每接一本新书，
#    出一轮「疑似错标裁决台」（71 张卡、二十分钟）把这本书的表补上；字体表
#    是不依赖书的地板，人裁表是这本书的天花板。

