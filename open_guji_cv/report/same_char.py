"""同字判定（对勘、Step9 汇总用）：刻本字与整理本字互为异体就当同一个字。

拆分 P5（2026-11-04）从 `eval/round_check.py` 原样挪来：`report.collate`／`report.tiers`（pipeline）要用，
`eval.round_check`（manager）也用，放在 pipeline 一侧，manager 从这里取。逻辑一字未改。
"""
from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def _variant_graph():
    """关系图加载一次。⚠️ 原先 `_edge_sources` 每次调用都 `VariantGraph.load()`
    ——读一个几 MB 的 json 再建图。对勘按字对查几百次，实测 `pair_index` 要 31 s，
    控制台一开 Step8 页面接口就挂住。"""
    from ..variants import VariantGraph
    return VariantGraph.load()


@lru_cache(maxsize=1)
def _variant_map():
    """同上，`VariantMap` 也别逐次 load。"""
    from ..clustering.variants import VariantMap
    return VariantMap.load()


@lru_cache(maxsize=None)
def _edge_sources(a: str, b: str) -> tuple[str, ...]:
    """关系图里 a—b 这条边的来源标签（查不到返回空）。两个方向都试。"""
    try:
        g = _variant_graph()
        for x, y in ((b, a), (a, b)):
            tags = dict(g.variants_of(x)).get(y)
            if tags:
                return tuple(tags)
    except Exception:
        pass
    return ()


def _same_char(a: str | None, b: str | None) -> bool:
    """互为异体就当同一个字——刻本刻「卽」而整理本作「即」，字形层照录是对的。"""
    if not a or not b:
        return False
    # 关系图的边分层（2026-09-06 改）：T1 纯异体直接算同字；T2「互通·一对多」只有本书用字账
    # 记过这对（人裁或自动转换）才算——大/太、淮/准 都是 T2，整理本与刻本都分得清清楚楚，
    # 拿它们当同字，判据 A 与对勘报告会把认错的 大 记成「异体」（vol02 预跑 大→太 ×12 就是）。
    # T3（形近·通假·仅简繁）从不算。
    try:
        from ..variants import edge_tier
        t = edge_tier(a, b)
        if t == "T1":
            # ⚠️ T1 也要看来源数（2026-09-22）。`build_semantic_variants.from_graph`
            # 只要求「≥1 个硬来源 + T1」，而 twedu 在硬来源里——于是**单凭 twedu
            # 一条就能判 T1**。实测 auto.tsv 的 9,031 条 graph 派生里，
            # 唯一来源是 twedu 的有 1,125 条（12.5%），抽样即见 㐌→色、㐪→亥、
            # 治→冶 这类根本不是异体的对。bxgb 因此把 `治`（识别错，整理本作
            # `冶`）记进「异体·成果」档，对勘报告说它没问题。
            # 单一来源降级走 T2 的来源数判据，其余 T1 照旧直接算同字。
            srcs = set(_edge_sources(a, b))
            if len(srcs) > 1 or not srcs:
                return True
            return False
        if t == "T2":
            from ..variant_ledger import BookLedger
            led = BookLedger.load_or_empty()
            if led.pair(a, b) or led.pair(b, a):
                return True
            # 账本没记过时看**这条边有几个独立来源**。账本只记这本书实际用过的
            # 转换，一本新书的账本几乎是空的——只认账本会把 㓂/寇、卽/即、啟/啓
            # 这些公认异体一律判成「不同字」。实测 auto.tsv 里判 T2 的 20 条：
            # 多来源（≥3）15 条全是真异体，单一来源 twedu 的 3 条（卞/其、皍/即、
            # 轄/輨）全是错的。来源数把两者分得干净，比账本有无更可靠。
            #
            # twedu（教育部異體字字典）收的是「历史上曾被当作某字使用过的字形」，
            # 口径比「同一个字的不同写法」宽——**适合做候选来源，不适合单独做判定**。
            return len(set(_edge_sources(a, b))) >= 3
        if t:
            # T3（形近·通假·仅简繁）从不算，也不许兜底翻盘。
            return False
    except Exception:
        pass
    # 兜底**只对关系图里根本没有这条边的字对**生效——㫖/旨 这类 UCV 认同形，
    # 关系图没收、VariantMap 的语义归并收了。
    #
    # ⚠️ 2026-09-22 修：原先 T2 没过账本时**不 return**，径直落到这里，而
    # `variants.auto.tsv` 正是从同一张关系图派生的，于是「劫→刦 / 刼→刦」
    # 「轄→輨」这类条目让语义归并相等，T2 那道闸被**自己的派生物架空**。
    # 实测 bxgb：劫/刼、輨/轄 两对 T2 且账本无记录，却双双判成异体，
    # 对勘报告因此把 `輨`（识别错，整理本作 `轄`）记进「异体·成果」档，
    # 报告说它没问题。上面那段注释本就写明 T2 要账本才算——兜底把自己的防线拆了。
    try:
        vm = _variant_map()
        return vm.semantic(a) == vm.semantic(b)
    except Exception:
        return False

