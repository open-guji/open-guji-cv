# -*- coding: utf-8 -*-
"""语义层派生：从关系层 + 本书用字账生成 ``config/dicts/variants.auto.tsv``。

    python scripts/build_semantic_variants.py [--edition wuyingdian_zongmu] [--dry-run]

产出是 ``VariantMap`` 的自动表（异体 → 代表字），手工表 ``config/dicts/variants.tsv``
仍然覆盖它（variant_strategy.md §3.4）。两条来路：

1. **用字账**（provenance ``ledger``）：整理本单形（``ref_policy=single``）的组里，
   非代表形 → 整理本用的那个形（髪→髮、卽→即、㕔→廳）。多形组（注/註、已/巳）
   **不派生**——整理本自己在区分，LM 该各算各的。
2. **关系图**（provenance ``graph``）：T1 边、来源里至少一个硬来源（twedu / hydzd /
   kSemanticVariant / kZVariant，yitizi 单独不算）、**恰好一头**在整理本里出现过 →
   没出现的那头映到出现的那头。这一条给的是"还没刻到过、但刻出来就该认"的覆盖
   （髪 在被刻到之前就能进 LM 的同义计数）。两头都在整理本 → 不派生（中/仲、穿/串、
   已/巳 这类都被这条挡住）。

派生方向永远是「整理本用形」而不是「教育部正字」——语义层的唯一用途是给 LM 做统计
与给人读，用本版最常写的形当代表，n-gram 计数才不分票（charset_and_lm.md 的旧纪律）。
永远不进表：形近家族（己已巳 等 NEVER_MATCH）、通假、形近易混。
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from open_guji_cv.clustering.confusable import NEVER_MATCH_FAMILIES  # noqa: E402
from open_guji_cv.clustering.variants import (DEFAULT_AUTO_PATH,  # noqa: E402
                                              DEFAULT_VARIANTS_PATH, VariantMap)
from open_guji_cv.variant_ledger import (DEFAULT_EDITION, BookLedger,  # noqa: E402
                                         han_counter)
from open_guji_cv.variants import (BRIDGE_SOURCES, WEAK_ALONE_SOURCES,  # noqa: E402
                                   VariantGraph)

DEFAULT_CORPUS = "corpus/zongmu_wuyingdian_reference.txt"
STRONG = BRIDGE_SOURCES - WEAK_ALONE_SOURCES
NEVER_CHARS = frozenset(c for pair in NEVER_MATCH_FAMILIES for c in pair)


def from_ledger(led: BookLedger) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for canon, grp in led.groups.items():
        if grp.get("ref_policy") != "single":
            continue
        # 整理本用形里剔掉孤例（盖 ×1 对 葢 ×791）：single 组按定义只剩一个主形
        minor = set(grp.get("ref_minor", []))
        refd = [m for m, f in grp["forms"].items() if f["ref"] > 0 and m not in minor]
        target = refd[0] if len(refd) == 1 else canon
        for m in grp["members"]:
            if m != target and m not in NEVER_CHARS and target not in NEVER_CHARS:
                out[m] = (target, "ledger")
    return out


def from_graph(g: VariantGraph, ref: Counter) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    # 只需遍历整理本用字的一跳邻居：派生方向永远指向整理本用形
    for target in ref:
        if target in NEVER_CHARS:
            continue
        for v, tags in g.variants_of(target):
            if v in ref or v in NEVER_CHARS:
                continue
            if not (set(tags) & STRONG):
                continue
            if g.edge_tier(target, v) != "T1":
                continue
            prev = out.get(v)
            # 一个形连到多个整理本用字（囘→回/迴）：一对多，不派生
            if prev is not None and prev[0] != target:
                out[v] = ("", "ambiguous")
                continue
            out[v] = (target, "graph")
    return {v: t for v, t in out.items() if t[0]}


def main() -> int:
    ap = argparse.ArgumentParser(description="派生语义层自动表 variants.auto.tsv")
    ap.add_argument("--edition", default=DEFAULT_EDITION)
    ap.add_argument("--corpus", default=DEFAULT_CORPUS)
    ap.add_argument("--out", default=str(DEFAULT_AUTO_PATH))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    g = VariantGraph.load()
    led = BookLedger.load_or_empty(a.edition)
    cp = Path(a.corpus) if Path(a.corpus).is_absolute() else REPO / a.corpus
    ref = han_counter(cp.read_text(encoding="utf-8")) if cp.exists() else Counter()

    auto = from_graph(g, ref)
    auto.update(from_ledger(led))            # 账本比字典硬，后写覆盖
    hand = VariantMap.load(DEFAULT_VARIANTS_PATH)
    n_hand_conflict = sum(1 for v, (t, _) in auto.items()
                          if v in hand._map and hand._map[v] != t)

    by_src = Counter(src for _, src in auto.values())
    print(f"自动表 {len(auto)} 条：{dict(by_src)}；与手工表冲突 {n_hand_conflict}（手工表优先）")
    for probe in ("髪", "卽", "㕔", "䙝", "厯", "彚", "皍", "无", "葢", "勅", "仲", "巳", "囘"):
        t = auto.get(probe)
        print(f"  {probe} → {t[0] + ' (' + t[1] + ')' if t else '—'}")

    if a.dry_run:
        return 0
    lines = [
        "# 语义层自动表：异体字 → 整理本用形（LM 统计 / 阅读辅助用），由 scripts/build_semantic_variants.py 派生。",
        "# 格式：异体字\t代表字\t来源(ledger|graph)。手工表 config/dicts/variants.tsv 覆盖本表。",
        "# 字形层标签永远保留精确异体字形，绝不按此表合并。",
        f"# edition={a.edition}  entries={len(auto)}",
    ]
    for v in sorted(auto, key=lambda c: (auto[c][1] != "ledger", ord(c))):
        t, src = auto[v]
        lines.append(f"{v}\t{t}\t{src}")
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
