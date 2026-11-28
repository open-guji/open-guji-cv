# -*- coding: utf-8 -*-
"""形近字对照表：匹配侧的「这两个字太像，别下断言」名单。

## 为什么要有这张表

库匹配唯一的硬约束是 `match_precision ≥ 0.999`，而覆盖率的天花板由**异字对
分数的上尾**决定：刻 + 印 + 扫 + 归一化把区分性细节抹平之后，末/未、目/自、
注/註 这类在书上能到 0.99 以上，闸只好站得比它们还高，于是真同字对也一起被
挡在外面。留出实测（`scripts/eval_guard_ceiling.py`）：闸 0.9933 时 recall
只有 0.196；把形近对从「误判」里摘出去（系统对它们不下断言，交给 OCR/语言
模型），闸能降到 0.986，recall 涨到 0.40。

## 「形近护栏」三处同名（A24 2026-11-06 理清）

①匹配层护栏 `guard=never_match／conflict`（`match.py`，用下面三表并集 `_PARTNER`）；②`near_form` 疑问
（`seeding.NEAR_FORM_CHARS`，只认手工表）；③待审原因 N01（guji-manager `reasons._near_form`，参校字与候选成手工表对）。
三者口径不同，别互相当同义词。全流程见 guji-manager doc/01-粗校/待审原因/near_form_guard/流程.md。

## 三张来源表，一个读口（2026-11-28 起读形近字组登记表）

三张表的**真源**仍各自一份，但现役代码一律从形近字组登记表 `config/near_groups/v2.json`（`near_groups/2`，
`scripts/build_near_groups_v2.py` 生成，见 `doc/3-识字/形近字组登记表.md`）里按字对的 `src` 派生，本模块不再直接读三张表
（W1 第二期；派生结果与原先逐项相同，`tests/test_near_registry_readers.py` 守着）：

- 手工表（`src=hand`）—— **手工核过的**，每一对都有实审案底（见 `config/near_groups/hand.json` 各条 `note`；
  原先是本模块里的 `NEVER_MATCH_FAMILIES` 字面量，11-28 原样搬过去）。`NEVER_MATCH_FAMILIES` 现在是登记表里
  `src` 含 hand 的对（按码位序），它同时供 `seeding.NEAR_FORM_CHARS` 用：那边一旦命中就**拦掉采信通道**，
  代价高，所以只放核过的。
- `FONT_TABLE`（`src=font`）—— 字体渲染自动跑出来的形近表（`build_confusable_families.py`）。
  它只喂**匹配侧**的降档护栏：命中只是把 `same` 降成 `unsure`，还有候选+
  上下文兜底，代价低，宁可多拦。登记表只收 τ≥`FONT_TAU` 的；`partners()` 换 τ 或换表时仍读原表。
- `HUMAN_TABLE`（`src=human`）—— **人裁确认的**形近对（`config/confusable_human.json`）：
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

HAND_TABLE = _CFG / "near_groups" / "hand.json"


def hand_pairs(path: str | Path | None = None) -> list[tuple[str, str]]:
    """手工表**真源**（`config/near_groups/hand.json`）里的对，原顺序原方向。只给生成登记表／`near_groups.json`
    的脚本读；现役代码用 `NEVER_MATCH_FAMILIES`（从登记表派生）。"""
    p = Path(path) if path else HAND_TABLE
    return [(str(e["a"]), str(e["b"])) for e in json.loads(p.read_text(encoding="utf-8"))["pairs"]]


def registry_pairs(*srcs: str, path: str | Path | None = None) -> list[tuple[str, str]]:
    """形近字组登记表里 `src` 含 `srcs` 任一个的字对（无序对，两端按码位排好，去重后按码位序）。
    一对字同在几个注册组里会在登记表里挂几次，这里只出一次。"""
    from ..groups import near_registry
    want = set(srcs)
    out: set[tuple[str, str]] = set()
    for g in near_registry.load(path).groups.values():
        for k, e in g.pairs.items():
            if len(k) == 2 and want & set(e.get("src") or ()):
                out.add((k[0], k[1]) if k[0] <= k[1] else (k[1], k[0]))
    return sorted(out)


# 手工核过的形近否决家族：登记表里 `src` 含 hand 的对（真源与各对案底在 config/near_groups/hand.json）。
NEVER_MATCH_FAMILIES: list[tuple[str, str]] = registry_pairs("hand")


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
    """字 → 它的形近对手集合。`tau=None` 表示不要字体表。

    手工、人裁两张从登记表取；字体表在 τ 等于登记表的 `font_tau`、又没另给表时也从登记表取，
    换了 τ（参数或 `GUJI_CONFUSABLE=<数>`）或给了 `path` 才读原字体表。"""
    human = True
    if _ENV == "off":
        tau, human = None, False
    elif _ENV in ("hand+human", "nofont"):
        tau = None
    elif _ENV:
        tau = float(_ENV)
    from ..groups import near_registry
    acc: dict[str, set[str]] = {}
    pairs = set(registry_pairs("hand")) | (set(registry_pairs("human")) if human else set())
    if tau is not None:
        if path is None and tau == near_registry.load().meta.get("font_tau"):
            pairs |= set(registry_pairs("font"))
        else:
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

