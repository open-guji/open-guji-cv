"""异体字关系层查询：懒加载 ``config/variants/variants.json``。

与 ``open_guji_cv.clustering.variants.VariantMap``（异体→本版正字的语义层
归并，供 LM）不同，这里是**关系层**：无向、带来源标签、不选正字。
用途：候选融合时判断两个候选是否互为异体、字形库检索的同义展开。

表由 ``scripts/build_variants.py`` 构建，格式 ``pairs[a][b] = [来源标签]``
（只存 ``ord(a) < ord(b)`` 一侧，本模块负责双向展开）。来源标签：
``unihan:kSemanticVariant`` 等六个 Unihan 属性、``twedu``、``hydzd``、
``dypytz``、``cjkvi-simplified``、``yitizi``。

注意 ``unihan:kSpoofingVariant`` 是**形近易混字，不是异体字**（防钓鱼
域名用的），构建时保留是为了做 OCR 混淆集合；任何「异体归并」语义的
消费者都必须把它滤掉——本模块的默认高置信来源集不含它。
"""

from __future__ import annotations

from pathlib import Path

DEFAULT_VARIANTS_JSON = (Path(__file__).resolve().parents[1]
                         / "config" / "variants" / "variants.json")

#: ``variant_group()`` 默认采信的高置信来源。
#: unihan（除 kSpoofingVariant）+ twedu + yitizi；hydzd / dypytz /
#: cjkvi-simplified 噪声与桥接边偏多，要用需显式传入。
HIGH_CONFIDENCE_SOURCES = frozenset({
    "unihan:kSemanticVariant", "unihan:kSpecializedSemanticVariant",
    "unihan:kZVariant", "unihan:kSimplifiedVariant",
    "unihan:kTraditionalVariant",
    "twedu", "yitizi",
})


class VariantGraph:
    """无向异体关系图。``pairs[a][b] = [tags]``（单侧）→ 双向邻接表。"""

    def __init__(self, pairs: dict[str, dict[str, list[str]]]):
        adj: dict[str, dict[str, tuple[str, ...]]] = {}
        for a, bs in pairs.items():
            for b, tags in bs.items():
                t = tuple(sorted(tags))
                adj.setdefault(a, {})[b] = t
                adj.setdefault(b, {})[a] = t
        self._adj = adj

    @classmethod
    def load(cls, path: str | Path | None = None) -> "VariantGraph":
        import json
        p = Path(path) if path else DEFAULT_VARIANTS_JSON
        if not p.exists():
            raise FileNotFoundError(
                f"找不到 {p}——先跑 python scripts/build_variants.py 构建")
        with open(p, "r", encoding="utf-8") as f:
            doc = json.load(f)
        return cls(doc["pairs"])

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
