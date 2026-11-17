# -*- coding: utf-8 -*-
"""形近字组分流：哪些格不该让「统一的字形比对」自己下断言（2026-11-16，OCR 研究 Project；Sheldon 11-16 定方向）。

## 为什么

一个统一的相似度函数（覆盖分、HOG、CNN 都一样）对极近的字组分不开：天/夭、尸/戸、大/太、千/干……
全唐文相似度基准上，「库外字被认成形近字」的门槛就是被这几对顶高的；把它们单独挑出来以后，其余格
用以 CNN 为主的分数就能在很低的误认下放行绝大多数（数字见 ai-team
`domain/CV/字形领域/5a相似度CNN深化-2026-11-15/`）。所以分两步走：

1. 维护一张**形近字组表**（`config/near_groups.json`，`scripts/build_near_groups.py` 生成）：落表的字不自动放行，
   交给字形分析（IDS 拆分、笔画、局部判别区域）和文意去分；
2. 表外的字，证据弱的也不放：**近邻一致度不满**的格送待审。

## 实测（2026-11-16，三本书；量法与全表见 ai-team `domain/CV/字形领域/5a相似度CNN深化-2026-11-15/形近字组表与分流-2026-11-16.md`）

全唐文 2762 个基准格、现役权重、整库 CNN 首位字，门槛定在「把金标字整类拿掉后最多误放 2 格（0.07%）」：

    什么都不加                 放行 73.2%（错放 1）
    只加 ②（一致度 < 1 送审）   放行 91.4%（错放 0；②拦掉 2.5% 的正常格、72% 的库外格）
    只加 ①（核心表）            放行 71%（①拦掉 23% 的格）

- **领先量没用**：Sheldon 原话是「得分较近、邻近一致性不高的都待审」。整库 CNN 上「首位比次位领先多少」分不开库外格
  （形近字顶上首位后照样领先）：和一致度取「且」只会把 ② 变弱，取「或」要多送 26% 的格而门槛一点不降。所以缺省
  `lead_min=0`（关），只看一致度；两个参数都留着，换了分数再试。
- **表管的是另一类错**：库外形近字对抗集（全唐文 1765 格，留出权重）同一门槛下误放 13 格，加核心表剩 2 格，② 一格也拦不住
  （对家是少见字时前 k 名全是它，一致度照样满）。所以两条都要。
- **表只知道库里两个字都有的对**。真正库外的字，表是从别的书、手工表、字体表知道的；拿字体渲染给库内字找库外形近字
  试过不行（要盖住一半已知对就得把 57% 的库内字拉进表）。书越整越多，表才越全。
- 史記、殿本（按本书刻例微调的权重）整库 CNN 首位只认对 93～95%，库外格能到 0.998 以上，准确率优先时几乎放不出格：
  这两本书的门槛要等权重练好再标，本模块的缺省门槛只在全唐文上标过。

## 表里有什么

每一对带来源，`core` 标「核心对」。2026-11-16 这版 572 对、920 字，核心 369 对、644 字（全唐文基准格里 23% 的格首位字落核心表）：

- `lib:<书>`   从该书字形库自身挖的：两个字的刻例互相像到分不开（近度＝校准后 CNN 分与覆盖分的平均，取第二高）。
               近度 ≥ `CORE_NEAR` 算核心，≥ `WIDE_NEAR` 进全表；
- `hand`       `confusable.NEVER_MATCH_FAMILIES`（手工核过，核心）；
- `human`      `config/confusable_human.json`（人裁确认的，核心）；
- `font`       字体形近表 τ ≥ `confusable.FONT_TAU`（全表）；
- `variant`    同形异码／异体（侯/𠋫、歳/歲 这类；Sheldon 11-15 定不算同一个字、逐码位判；核心）：语义表归到同一个字或关系层
               有高置信来源的边，且两个字在某本书库里量出来近度 ≥ `VAR_NEAR`（库里量不出像的异体对不进表）；
- `config/near_groups_drop.tsv` 是剔除名单（错标刻例造成的假字对，自动筛出待人核）。

和 `confusable.partners()` 的关系：那张表（手工＋人裁＋字体）是它的子集来源；库里挖出来的对是新增的
（天/夭、文/丈、永/氷、早/旱 原先都不在表里）。本模块**只读表、只给判断**，不改 `match.py` 的护栏。

## 和字组（`groups/`）的关系：这里是 5a.1，只认、不判

形近字组**怎么分**早就有一套，在第 7 步：`groups/registry.py` 是字组的单一真源（每组的成员＋方法数组：码位归一、字频、
文意 L1/L2/L3、整字 HOG、IDS、量笔画、书级刻形模型），`seed_admit.group_flow` 按组跑方法、放行或留审。本模块不另起一套：

- **5a.1（本模块）只认**：首位字落表、或属于某个已注册字组 → 不下 same 断言，把对家和组 id 写进证据，交给下游；
- **5a.2（`groups/shape_stage.py`）判只看字形的**：取注册表里只吃字块图的方法（量笔画、IDS、整字 HOG）判一遍；
- **第 7 步判要上下文的**：`group_flow` 里的文意、整理本互证、字频、码位归一照旧。新方法一律注册成 `groups/methods.py` 的方法，
  挂到组的 `FlowSpec.methods` 里，只吃图的 5a.2 自动带上（Sheldon 11-16 定的分段，见 doc/design/形近字组-5a分流与第7步对接.md）；
- **表是「发现名单」，注册表是「有判法的组」**。表里每一对标了 `group`（两个字已在同一个注册组里＝已有判法）；没有 `group` 的对
  是待办：要么给已有的组补成员，要么新注册一组，注册之前这些格只能留审。`RouteDecision.groups` 给首位字所属的注册组，
  `uncovered()` 列待办。表里还抄了一份 `char_groups`（注册表里每个字属哪些组），这样第 5 步查它不用 import `groups` 包（分层上 `groups` 不 import `clustering`，这边也不反过来绑死）；真源仍是注册表，`build_near_groups.py merge` 时重抄。

实测（11-16）三本书基准格里首位字落核心表的格，绝大多数字已经在某个注册组里；表主要是给已有的组补了没登记的对家
，完全没有组的只占全部格的 2～3%（数字见 doc/design/形近字组-5a分流与第7步对接.md）。

## 近邻一致度

    knn(c) = 整库 CNN 最像的 k 个刻例（不含本格）里标成 c 的个数 ÷ min(k, c 在库里的刻例数)

字分只看「最像的那一个刻例」，近邻一致度看「是不是一群这个字的刻例都认它」。库里没有这个字时，前 k 名被几个
形近字瓜分，一致度自然低；而领先量在这种情况下帮倒忙（形近字顶上首位后照样领先）。它依赖库标签，成片错标会带偏。

## 接进匹配器

本模块不在任何 Step 的 `code_deps` 里，合进来不动各书产物指纹。真正接线要在 `match.py` 按字聚合之后调
`Router.decide`（同格排除行在那里才知道），那是动指纹的改动，要走等价登记或让开着 `sim_model` 的书重算，另议。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

_CFG = Path(__file__).resolve().parents[2] / "config"
TABLE = _CFG / "near_groups.json"
CORE_NEAR = 0.985
WIDE_NEAR = 0.975
VAR_NEAR = 0.95


@lru_cache(maxsize=8)
def partners(level: str = "core", book: str | None = None, path: str | None = None) -> dict[str, frozenset[str]]:
    """字 → 表里它的对家。`level`：`core` 只要核心对，`all` 全表。

    `book`（`qtw`／`sj`／`sk`…）给了时，库里挖的对只认这本书自己的（`lib:<book>`）；手工、人裁、字体、同形异码不分书。
    不给就三本书并起来。表不存在当空表。"""
    if level not in ("core", "all"):
        raise ValueError(f"level 只认 core／all，收到 {level!r}")
    p = Path(path) if path else TABLE
    if not p.exists():
        return {}
    acc: dict[str, set[str]] = {}
    for pair, v in json.loads(p.read_text(encoding="utf-8")).get("pairs", {}).items():
        chars = list(pair)
        if len(chars) != 2:
            continue
        src = [s for s in v.get("src", ()) if book is None or not s.startswith("lib:") or s == f"lib:{book}"]
        if not src:
            continue
        if level == "core":
            near = v.get("near", {})
            lib_core = any(n >= CORE_NEAR for b, n in near.items() if book is None or b == book)
            if not (lib_core or {"hand", "human", "variant"} & set(src)):
                continue
        a, b = chars
        acc.setdefault(a, set()).add(b)
        acc.setdefault(b, set()).add(a)
    return {k: frozenset(v) for k, v in acc.items()}


@lru_cache(maxsize=4)
def registered(path: str | None = None) -> dict[str, tuple[str, ...]]:
    """字 → 它在第 7 步字组注册表里属于哪些组（表里抄的那份 `char_groups`）。表不存在当空。"""
    p = Path(path) if path else TABLE
    if not p.exists():
        return {}
    return {c: tuple(g) for c, g in json.loads(p.read_text(encoding="utf-8")).get("char_groups", {}).items()}


def uncovered(level: str = "core", path: str | None = None) -> list[tuple[str, str]]:
    """表里还没有判法的对：两个字不在同一个注册字组里（给方向 2 排待办用）。按码位排好的无序对。"""
    p = Path(path) if path else TABLE
    if not p.exists():
        return []
    out = []
    for pair, v in json.loads(p.read_text(encoding="utf-8")).get("pairs", {}).items():
        if len(pair) == 2 and not v.get("group") and (level == "all" or v.get("core")):
            out.append((pair[0], pair[1]))
    return sorted(out)


def components(level: str = "core", book: str | None = None, path: str | None = None) -> list[tuple[str, ...]]:
    """表按连通分量并起来（给人看形近关系怎么连成片；**不是字组**——字组以 `groups/registry.py` 为准），大的在前。"""
    P = partners(level, book, path)
    seen: set[str] = set()
    out = []
    for c in sorted(P):
        if c in seen:
            continue
        comp, stack = [], [c]
        seen.add(c)
        while stack:
            x = stack.pop()
            comp.append(x)
            for y in P[x]:
                if y not in seen:
                    seen.add(y)
                    stack.append(y)
        out.append(tuple(sorted(comp)))
    return sorted(out, key=lambda g: (-len(g), g))


@dataclass(frozen=True)
class RouteConfig:
    """分流门槛。缺省值是全唐文基准上按「准确率优先」取的（见模块头「实测」）。"""
    level: str = "core"
    book: str | None = None
    lead_min: float = 0.0
    """首位字分 − 次位字分（校准到 cov 尺度）低于它算「得分接近」。缺省 0＝不看（实测没用，见模块头）。"""
    knn_min: float = 1.0
    """近邻一致度低于它算「不一致」。缺省 1.0＝前 k 名里只要混进别的字就送审。"""
    registry: bool = True
    """首位字不在表里、但属于某个已注册字组，也算落表（那些格第 7 步本来就按组判）。"""
    weak: str = "either"
    """`both`＝得分接近且不一致才送审；`either`＝任一条成立就送审（更保守，多送很多）。"""
    k: int = 10
    table: str | None = None

    def __post_init__(self):
        if self.weak not in ("both", "either"):
            raise ValueError(f"weak 只认 both／either，收到 {self.weak!r}")


@dataclass(frozen=True)
class RouteDecision:
    reason: str | None
    """None＝不拦（照常走分数门槛）；`near_group`＝首位字落表；`weak`＝近邻不一致（或得分接近，看配置）；`empty`＝库里没有可比的刻例。"""
    top: str | None = None
    score: float = 0.0
    lead: float = 0.0
    knn: float = 0.0
    partners: tuple[str, ...] = ()
    groups: tuple[str, ...] = ()
    """首位字在第 7 步字组注册表里属于哪些组（空＝还没有组，下游没有专门判法）。"""


def knn_agreement(sims: np.ndarray, chars: np.ndarray, char: str, k: int = 10) -> float:
    """近邻一致度（见模块头）。`sims` 里不该参与的行（本格、别的排除行）事先置成 -inf。"""
    n = int((chars == char).sum() - np.sum((chars == char) & ~np.isfinite(sims)))
    if n <= 0:
        return 0.0
    k = min(k, int(np.isfinite(sims).sum()))
    if k <= 0:
        return 0.0
    top = np.argpartition(-sims, k - 1)[:k]
    return float((chars[top] == char).sum() / min(k, n))


def evidence(sims: np.ndarray, chars: np.ndarray, k: int = 10, calib=None) -> tuple[str | None, float, float, float]:
    """一格对整库的相似度 → (首位字, 首位字分, 领先次位字多少, 首位字的近邻一致度)。

    字分＝该字刻例的最高分；`calib`（`sim_cnn.load_calib` 的两列节点）给了就先映射到 cov 尺度。
    只有一个字可比时领先量取字分本身（没有对手）。"""
    ok = np.isfinite(sims)
    if not ok.any():
        return None, 0.0, 0.0, 0.0
    order = np.argsort(-np.where(ok, sims, -np.inf))
    top = chars[order[0]]
    s1 = float(sims[order[0]])
    rest = order[(chars[order] != top) & ok[order]]
    s2 = float(sims[rest[0]]) if len(rest) else None
    if calib is not None:
        s1 = float(np.interp(s1, *calib))
        s2 = None if s2 is None else float(np.interp(s2, *calib))
    return str(top), s1, (s1 - s2 if s2 is not None else s1), knn_agreement(sims, chars, top, k)


def route(top: str | None, lead: float, knn: float, cfg: RouteConfig = RouteConfig(), score: float = 0.0) -> RouteDecision:
    """规则本身（纯函数）：①首位字落表（或属于已注册字组）→ near_group；②领先 < lead_min 且一致度 < knn_min → weak；否则不拦。"""
    if top is None:
        return RouteDecision("empty")
    ps = partners(cfg.level, cfg.book, cfg.table).get(top)
    gs = registered(cfg.table).get(top, ())
    if ps or (cfg.registry and gs):
        return RouteDecision("near_group", top, score, lead, knn, tuple(sorted(ps or ())), gs)
    close, loose = lead < cfg.lead_min, knn < cfg.knn_min
    if (close and loose) if cfg.weak == "both" else (close or loose):
        return RouteDecision("weak", top, score, lead, knn)
    return RouteDecision(None, top, score, lead, knn)


class Router:
    """绑定一个库（整库 CNN 嵌入＋每行的字），逐格给分流判断。

    `E`：整库单位向量嵌入（`sim_cnn.embed`）；`chars`：每行的字；`calib`：权重旁的校准表（没有就用原始余弦，
    这时 `lead_min` 要按原始尺度另标）。"""

    def __init__(self, E: np.ndarray, chars, cfg: RouteConfig = RouteConfig(), calib=None):
        if len(E) != len(chars):
            raise ValueError(f"嵌入 {len(E)} 行、字 {len(chars)} 行，对不上")
        self.E = np.asarray(E, dtype=np.float32)
        self.chars = np.asarray(chars)
        self.cfg = cfg
        self.calib = calib

    def decide(self, q: np.ndarray, exclude=()) -> RouteDecision:
        """`q`：这一格的嵌入；`exclude`：不参与的库行（同一物理格的行，同 `GlyphMatcher._same_cell_rows`）。"""
        sims = self.E @ np.asarray(q, dtype=np.float32)
        ex = list(exclude)
        if ex:
            sims[ex] = -np.inf
        top, s, lead, knn = evidence(sims, self.chars, self.cfg.k, self.calib)
        return route(top, lead, knn, self.cfg, s)
