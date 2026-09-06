"""异体字关系层查询：懒加载 ``config/variants/variants.json``。

与 ``open_guji_cv.clustering.variants.VariantMap``（异体→本版正字的语义层
归并，供 LM）不同，这里是**关系层**：带来源标签，不做归并。
用途：候选融合时判断两个候选是否互为异体、字形库检索的同义展开、
本书用字账（``variant_ledger``）的分组与分级。

表由 ``scripts/build_variants.py`` 构建，两个部分：

- ``pairs[a][b] = [来源标签]``：**无向**，只存 ``ord(a) < ord(b)`` 一侧，本模块
  负责双向展开。管「有没有关系」。
- ``directed[异体][正字] = [来源标签]``（2026-09-05 起）：只收带方向的来源
  （twedu / hydzd / dypytz / cjkvi-simplified / unihan 简繁）。管「哪边是正字」——
  一对多的判定、跨书统一键 ``canonical`` 都靠它。旧表没有这一节时照常工作，
  只是方向类查询全空。

来源标签：``unihan:kSemanticVariant`` 等六个 Unihan 属性、``twedu``、``hydzd``、
``hydzd-borrowed``、``dypytz``、``cjkvi-simplified``、``yitizi``。

## 来源分级只是先验

``unihan:kSpoofingVariant`` 是**形近易混字，不是异体字**；``hydzd-borrowed`` 是
通假。这两个永不当异体用。但反过来，「高置信来源」也不等于「刻本异体」：
twedu 既收 㕔~廳，也收古文 上~二、人~几；kSemanticVariant 既给 䙝~褻 也给
子~只。所以本模块的 ``edge_tier()`` 只给 T1/T2/T3 的**先验**，一对字最终归哪一类
由本书用字账（整理本用形 + 人裁）定——见 ``variant_strategy.md`` §1.1、§3。
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_VARIANTS_JSON = (Path(__file__).resolve().parents[1]
                         / "config" / "variants" / "variants.json")

#: ``variant_group()`` 默认采信的高置信来源——用于**候选池展开**（字形库同义
#: 检索、生僻字大表），宁多勿少。**不是**准入桥的白名单（见 BRIDGE_SOURCES）。
#: unihan（除 kSpoofingVariant）+ twedu + yitizi；hydzd / dypytz /
#: cjkvi-simplified 噪声与桥接边偏多，要用需显式传入。
HIGH_CONFIDENCE_SOURCES = frozenset({
    "unihan:kSemanticVariant", "unihan:kSpecializedSemanticVariant",
    "unihan:kZVariant", "unihan:kSimplifiedVariant",
    "unihan:kTraditionalVariant",
    "twedu", "yitizi",
})

# ── 来源分级（variant_strategy.md §3.1）─────────────────────
#: 异体来源：这条边可以是「同词异形」。准入桥的候选（最终还要过用字账）。
BRIDGE_SOURCES = frozenset({
    "twedu", "hydzd", "unihan:kSemanticVariant", "unihan:kZVariant", "yitizi",
    # local:keben —— config/variants/local_edges.json 的手工补边。公开库一家都没收、
    # 但**本书刻本实证过**的同字异形（首例 㫖—旨，各家资料里 㫖 是孤立点）。
    # 刻例是我们能拿到的最硬的证据，所以进桥；准入照样还要过本书用字账。
    "local:keben",
})
#: 单独出现不够格：yitizi 把 ytenx + OpenCC 混在一起且不可溯源，
#: 只有它一家的边（來~勅、某~私、藝~芸）最可疑。
WEAK_ALONE_SOURCES = frozenset({"yitizi"})
#: T2 标记：Unihan 官方的「只在某些义项同」。
T2_SOURCES = frozenset({"unihan:kSpecializedSemanticVariant"})
#: 简繁 / 1955 年整理表：只作关系证据，对繁体刻本方向是反的，单独出现不当异体。
SIMPLIFIED_SOURCES = frozenset({
    "cjkvi-simplified", "unihan:kSimplifiedVariant",
    "unihan:kTraditionalVariant", "dypytz",
})
#: 永不当异体：形近易混（防钓鱼域名用的）、通假（不同的词）。
NEVER_SOURCES = frozenset({"unihan:kSpoofingVariant", "hydzd-borrowed"})


class VariantGraph:
    """异体关系图：无向邻接（``pairs``）+ 有向 正字←异体（``directed``）。"""

    def __init__(self, pairs: dict[str, dict[str, list[str]]],
                 directed: dict[str, dict[str, list[str]]] | None = None):
        adj: dict[str, dict[str, tuple[str, ...]]] = {}
        for a, bs in pairs.items():
            for b, tags in bs.items():
                t = tuple(sorted(tags))
                adj.setdefault(a, {})[b] = t
                adj.setdefault(b, {})[a] = t
        self._adj = adj
        # 异体 → {正字: 标签}，以及反向 正字 → {异体: 标签}
        reg: dict[str, dict[str, tuple[str, ...]]] = {}
        var: dict[str, dict[str, tuple[str, ...]]] = {}
        for v, rs in (directed or {}).items():
            for r, tags in rs.items():
                t = tuple(sorted(tags))
                reg.setdefault(v, {})[r] = t
                var.setdefault(r, {})[v] = t
        self._reg = reg
        self._var = var

    @classmethod
    def load(cls, path: str | Path | None = None) -> "VariantGraph":
        import json
        p = Path(path) if path else DEFAULT_VARIANTS_JSON
        if not p.exists():
            raise FileNotFoundError(
                f"找不到 {p}——先跑 python scripts/build_variants.py 构建")
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f)
        return cls(doc["pairs"], doc.get("directed"))

    # ── 无向：有没有关系 ──────────────────────────────────

    def variants_of(self, char: str) -> list[tuple[str, tuple[str, ...]]]:
        """char 的直接异体（一跳邻居）→ ``[(异体字, (来源标签…)), …]``。

        含 kSpoofingVariant 边——按标签自行过滤。结果按码位排序。
        """
        bs = self._adj.get(char, {})
        return [(b, bs[b]) for b in sorted(bs)]

    def sources_of(self, a: str, b: str) -> tuple[str, ...]:
        """a、b 之间这条边的来源标签（无边返回空元组）。方向无关。"""
        return self._adj.get(a, {}).get(b, ())

    def are_variants(self, a: str, b: str) -> bool:
        """a、b 是否有直接异体关系（任一来源收录即算）。方向无关。"""
        return b in self._adj.get(a, {})

    def variant_group(self, char: str,
                      sources: frozenset[str] | set[str] | None
                      = HIGH_CONFIDENCE_SOURCES) -> set[str]:
        """char 所在异体组（连通分量展开，含 char 自身）。

        **风险须知**：异体关系不传递——「甲~乙」「乙~丙」推不出
        「甲~丙」，多义字会把不相干的组桥接成大团（低置信来源全开时
        最大连通分量可达数百字）。所以默认只沿高置信来源
        （``HIGH_CONFIDENCE_SOURCES``：unihan 非 spoofing + twedu +
        yitizi）的边扩展；``sources=None`` 表示全部来源都走，团会
        显著变大，风险自负。即便默认档，展开结果也只该当**候选池**
        用（如字形库同义检索），不能当「这些字等价」的结论。

        :param sources: 采信的来源标签集合；边的标签与之有交集才走。
        """
        group = {char}
        stack = [char]
        while stack:
            cur = stack.pop()
            for nxt, tags in self._adj.get(cur, {}).items():
                if nxt in group:
                    continue
                if sources is not None and not (set(tags) & set(sources)):
                    continue
                group.add(nxt)
                stack.append(nxt)
        return group

    # ── 有向：哪边是正字 ──────────────────────────────────

    def regulars_of(self, char: str,
                    sources: frozenset[str] | set[str] | None = None
                    ) -> list[tuple[str, tuple[str, ...]]]:
        """char 作为异体时，各来源指认的正字 → ``[(正字, (标签…)), …]``。

        ``sources`` 非空时只留标签有交集的。不在 ``directed`` 里 → 空。
        """
        rs = self._reg.get(char, {})
        out = [(r, rs[r]) for r in sorted(rs)
               if sources is None or set(rs[r]) & set(sources)]
        return out

    def irregulars_of(self, char: str,
                      sources: frozenset[str] | set[str] | None = None
                      ) -> list[tuple[str, tuple[str, ...]]]:
        """char 作为正字时名下的异体 → ``[(异体, (标签…)), …]``。"""
        vs = self._var.get(char, {})
        return [(v, vs[v]) for v in sorted(vs)
                if sources is None or set(vs[v]) & set(sources)]

    def is_regular(self, char: str, source: str = "twedu") -> bool:
        """某来源是否把 char 当正字（名下有异体）。默认按教育部正字表。"""
        return any(source in tags for tags in self._var.get(char, {}).values())

    def is_one_to_many(self, char: str,
                       sources: frozenset[str] | set[str] | None = None) -> bool:
        """char 作为异体是否指向 ≥2 个正字（一形多正：囘→回/迴、发→發/髮）。"""
        return len(self.regulars_of(char, sources)) >= 2

    def canonical_of(self, char: str,
                     sources: frozenset[str] | set[str] | None = None) -> str | None:
        """跨书统一键：char 归到哪个正字名下。

        - 没人把它当异体 → 自身（它就是正字，或表里没它）；
        - 恰好一个正字 → 那个字；
        - 多个正字：教育部（twedu）指认的唯一那个优先；仍不唯一 → ``None``
          （一对多，要靠本书语料定，见 ``variant_ledger``）。
        """
        regs = self.regulars_of(char, sources)
        if not regs:
            return char
        if len(regs) == 1:
            return regs[0][0]
        tw = [r for r, tags in regs if "twedu" in tags]
        if len(tw) == 1:
            return tw[0]
        return None

    def edge_tier(self, a: str, b: str) -> str | None:
        """a、b 这条边的分型**先验**：``"T1"`` 纯异体 / ``"T2"`` 互通·一对多 /
        ``"T3"`` 形近·通假·仅简繁 / ``None`` 无边。

        判据（variant_strategy.md §1.1）：
        - 只有 NEVER 来源 → T3；
        - 有 kSpecializedSemanticVariant → T2；两头都是教育部正字（兩正互通，
          后/後、鍾/鐘）→ T2；任一头一形多正 → T2；
        - 有异体来源（BRIDGE）→ T1；只有 yitizi 一家 → 仍 T1，但调用方可用
          ``sources_of`` 看到它单薄；
        - 只有简繁/整理表来源、无异体来源背书 → T3（刻本不会用的关系）。
        最终归类由本书用字账定，这里只是关系层能给的最好猜测。
        """
        tags = set(self.sources_of(a, b))
        if not tags:
            return None
        live = tags - NEVER_SOURCES
        # 没有任何异体/互通来源背书（只剩简繁、整理表、或什么都不剩）→ 刻本不会用的关系。
        # 这一条要排在「一形多正」之前：发→發/髮 也是一形多正，但那是简化合并，不是互通。
        if not (live & (BRIDGE_SOURCES | T2_SOURCES)):
            return "T3"
        if live & T2_SOURCES:
            return "T2"
        if self.is_regular(a) and self.is_regular(b):
            return "T2"
        directed = BRIDGE_SOURCES | SIMPLIFIED_SOURCES
        if self.is_one_to_many(a, directed) or self.is_one_to_many(b, directed):
            return "T2"
        return "T1"

    def __len__(self) -> int:
        """收录的字数（图的节点数）。"""
        return len(self._adj)

    def __contains__(self, char: str) -> bool:
        return char in self._adj


# ── 模块级便捷接口（懒加载单例）─────────────────────────

_GRAPH: VariantGraph | None = None


def _graph() -> VariantGraph:
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = VariantGraph.load()
    return _GRAPH


def variants_of(char: str) -> list[tuple[str, tuple[str, ...]]]:
    """见 :meth:`VariantGraph.variants_of`。"""
    return _graph().variants_of(char)


def are_variants(a: str, b: str) -> bool:
    """见 :meth:`VariantGraph.are_variants`。"""
    return _graph().are_variants(a, b)


def variant_group(char: str,
                  sources: frozenset[str] | set[str] | None
                  = HIGH_CONFIDENCE_SOURCES) -> set[str]:
    """见 :meth:`VariantGraph.variant_group`（默认只走高置信来源）。"""
    return _graph().variant_group(char, sources)


def regulars_of(char: str,
                sources: frozenset[str] | set[str] | None = None
                ) -> list[tuple[str, tuple[str, ...]]]:
    """见 :meth:`VariantGraph.regulars_of`。"""
    return _graph().regulars_of(char, sources)


def canonical_of(char: str,
                 sources: frozenset[str] | set[str] | None = None) -> str | None:
    """见 :meth:`VariantGraph.canonical_of`。"""
    return _graph().canonical_of(char, sources)


def edge_tier(a: str, b: str) -> str | None:
    """见 :meth:`VariantGraph.edge_tier`。"""
    return _graph().edge_tier(a, b)
