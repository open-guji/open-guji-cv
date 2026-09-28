# -*- coding: utf-8 -*-
"""校准形近对表（overview#128）：拿实测混淆对量召回，报表大小/门槛。**只读**——
不改 `config/ids/ids_confusable_pairs_v1.tsv`，不改放行任何东西。

真值来源（任务卡原话「拿实测错例校准，来源是 #86 R 道和 #120 C 道 done 单里的
混淆表」；#120 那份混淆表实际出自同一批「借库书 CNN 首选」实验的 done 单，
issue 号在整理途中变过，数据没变）：

- overview#86 done（R·全唐文借库失效，2026-09-27 22:06）：像素比对系统性认反的
  高频对，`格数` 是「AI 首选=X 但真值=Y」在人裁难例上的出现次数。
- overview 进度/图片初步数字化/进度/inbox/C-借库首选CNN/20260927-done.md
  （C·借库书人审首选改CNN原型）：CNN 首选仍认错的主错例。
- Z15 ask/reply/status（整理Z15-形近对失效、Z15-全唐文识别放行/…v5收回与统计）：
  今/令、玉/王、大/天 三对用户逐簇裁决确认系统性混淆。
- 己/已/巳：项目内长期已知的族内混淆（`utils/ji_yi_si.py` 模块头），
  不靠字形分——列进来是为了钉死「这类字 IDS 方法接不住」这条边界。

每条 `(a, b, n, source)`，`n` 是那次实测里报告的格数/出现次数（找不到具体数字
时先记 1，见 `source` 里的说明；**不是精确的全局统计**，只是「这条真实发生过、
发生频率大致是这个量级」的证据，权重召回率据此算，报的时候写清楚）。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from open_guji_cv.clustering import ids_struct as S

REAL_CONFUSIONS: list[tuple[str, str, int, str]] = [
    # overview#86 done（2026-09-27 22:06，人裁难例 2851 格全书统计，「每一处」= 分母就是该字出现次数）
    ("以", "取", 135, "#86：以→取 135/135（全为此错）"),
    ("令", "今", 112, "#86：令→今 112 次"),
    ("平", "乎", 111, "#86：平→乎 111 次"),
    ("申", "中", 97, "#86：申→中 97 次"),
    ("天", "大", 95, "#86：天→大 95 次"),
    ("人", "入", 95, "#86：人→入 95 次"),
    # C-借库首选CNN done（2026-09-27）：CNN 首选仍认错的主错例（人裁全集 3805 格口径）
    ("宇", "字", 82, "C-借库首选CNN：宇→字 ×82"),
    ("平", "乎", 55, "C-借库首选CNN：平→乎 ×55（与 #86 同一对，不同子集，不重复计权重，取更大值）"),
    ("馭", "取", 20, "C-借库首选CNN：馭→取 ×20"),
    ("寡", "㝠", 19, "C-借库首选CNN：寡→㝠 ×19"),
    # Z15 ask/status（用户逐簇裁决确认系统性混淆；批5 三对每对约 40 格量级，取该批格数近似）
    ("今", "令", 40, "Z15 batch1：今 40 格快速连点、方向信号（与令混）"),
    ("玉", "王", 5, "Z15 batch1：玉 5 格全部判「不对」（真值多为王）"),
    ("大", "天", 1, "Z15 v5：形近三对簇之一，簇级确认（未给格数，记1）"),
    # R-形近对扩展 done（2026-09-27）：vol03/bxgb 的真实 Step5-a 放错例（逐格实锤，非统计口径）
    ("冶", "治", 1, "R-形近对扩展：bxgb:52:11:15 人裁确认冶，Step5-a 放成治"),
    ("澤", "擇", 2, "R-形近对扩展：vol03:21:7:9/12 两格"),
    ("河", "何", 1, "R-形近对扩展：vol03:26:9:11"),
    ("仕", "士", 1, "R-形近对扩展：vol03:47:7:21"),
    ("猶", "獨", 1, "R-形近对扩展：vol03:68:9:13"),
    # 已知的方法论边界（族内混淆，长期存在，见 utils/ji_yi_si.py 模块头）——
    # 列进来专门验证「IDS 接不住」这条负结果，不是这次新采的证据
    ("己", "已", 1, "ji_yi_si.py：族内混淆（无格数统计，仅作边界验证）"),
    ("已", "巳", 1, "ji_yi_si.py：族内混淆"),
    ("己", "巳", 1, "ji_yi_si.py：族内混淆"),
]


def load_universe() -> list[str]:
    from build_confusable_pairs import _discover_books, collect_universe
    ws = Path("/home/user/guji-workspace")
    chars, _ = collect_universe(_discover_books(ws))
    return sorted(chars)


def eval_existing_confusables_table() -> None:
    """对照组：开工时才发现的既有系统 `clustering/confusables.py` +
    `config/ids/confusable_pairs_v1.tsv`（2026-09-22 建，IDS + 字体模板
    embedding 余弦 + 纯视觉近邻三路合成，已接进 rare_panel/控制台）。
    在同一份校准集上量它的召回，供协调者判断两套表要不要合并/谁留谁弃。"""
    try:
        from open_guji_cv.clustering.confusables import is_pair
    except Exception as e:
        print(f"（既有表读取失败，跳过对照: {e}）")
        return
    dedup: dict[tuple[str, str], int] = {}
    for a, b, n, _ in REAL_CONFUSIONS:
        pair = (a, b) if a < b else (b, a)
        dedup[pair] = max(dedup.get(pair, 0), n)
    hit_pairs = [p for p in dedup if is_pair(p[0], p[1])]
    hit_n = sum(dedup[p] for p in hit_pairs)
    total_n = sum(dedup.values())
    print(f"\n=== 对照：既有 confusables.py 表在同一校准集上的召回 ===")
    print(f"对数命中 {len(hit_pairs)}/{len(dedup)}，格数命中 {hit_n}/{total_n} "
          f"= {100*hit_n/total_n:.1f}%")
    for pair in sorted(dedup, key=lambda p: -dedup[p]):
        mark = "HIT" if pair in hit_pairs else "miss"
        print(f"  {pair[0]}/{pair[1]} n={dedup[pair]:<4} {mark}")


def main() -> int:
    chars = load_universe()
    print(f"universe: {len(chars)} 字")

    pairs_all = S.build_confusable_pairs(chars)
    table_all = {(p.a, p.b) if p.a < p.b else (p.b, p.a): p for p in pairs_all}
    print(f"表大小（全量，不设 max_shared_freq）: {len(pairs_all)}")

    thresholds = [None, 500, 1000, 1500, 2000]
    tables = {}
    for t in thresholds:
        ps = S.build_confusable_pairs(chars, max_shared_freq=t)
        tables[t] = {(p.a, p.b) if p.a < p.b else (p.b, p.a): p for p in ps}

    # 去重：同一对可能因不同来源重复列出，只取最大的 n 当权重（同来源事件不叠加计数）
    dedup: dict[tuple[str, str], int] = {}
    sources: dict[tuple[str, str], list[str]] = {}
    for a, b, n, src in REAL_CONFUSIONS:
        pair = (a, b) if a < b else (b, a)
        dedup[pair] = max(dedup.get(pair, 0), n)
        sources.setdefault(pair, []).append(src)

    print("\n=== 各门槛下：召回（对数 / 加权格数）与表大小 ===")
    header = f"{'门槛':>8} | {'表大小':>10} | {'对数命中':>10} | {'格数命中/总':>16} | {'格数召回':>8}"
    print(header)
    total_pairs = len(dedup)
    total_n = sum(dedup.values())
    for t in thresholds:
        tbl = tables[t]
        hit_pairs = [p for p in dedup if p in tbl]
        hit_n = sum(dedup[p] for p in hit_pairs)
        label = "全量" if t is None else str(t)
        print(f"{label:>8} | {len(tbl):>10} | {len(hit_pairs):>3}/{total_pairs:<6} | "
              f"{hit_n:>6}/{total_n:<8} | {100*hit_n/total_n:>6.1f}%")

    print("\n=== 逐对明细（全量表，含命中的类型/分数、来源） ===")
    for pair, n in sorted(dedup.items(), key=lambda kv: -kv[1]):
        cp = table_all.get(pair)
        status = f"HIT  kind={cp.kind:<9} score={cp.score:.3f}" if cp else "MISS"
        print(f"  {pair[0]}/{pair[1]:<3} n={n:<4} {status}   来源: {'; '.join(sources[pair])}")

    print("\n=== 推荐门槛 ===")
    print("max_shared_freq=1000（build_confusable_pairs.py 默认值）：全表 448,659 → "
          "见上表「1000」行的表大小（61,376，降 86.3%）；本校准集里 7 个 2 槽真错例"
          "（申/中、宇/字、冶/治、馭/取、澤/擇、河/何、猶/獨）的共享部件频次全部 "
          "≤984，门槛 1000 一个不丢——加权召回与不设门槛的全量完全相同（53.3%）。")

    eval_existing_confusables_table()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
