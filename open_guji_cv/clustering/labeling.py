"""Phase 6 IO 编排：候选(M4) + 上下文排序(M5) → ranked.json / suspects.json / text/

CLI `label` 命令的实现层。纯算法在 candidates.py / context_rank.py，
这里只做装配与落盘。
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from .context_rank import (Slot, SlotCandidate, SlotResult, beam_search,
                           check_cluster_consistency)
from .extractor import CharInstance, load_index
from .ids import parse_id, reading_order_key
from .lm import BaseLM, CharNgramLM, UniformLM
from .variants import VariantMap


def build_lm(lm_model: str | None, corpus_dir: str | None,
             variant_map: VariantMap) -> BaseLM:
    """LM 装配：已训模型 > 语料现训 > uniform 兜底。语料先正字化再训练。"""
    if lm_model:
        return CharNgramLM.load(lm_model)
    if corpus_dir:
        texts = []
        for p in sorted(Path(corpus_dir).glob("**/*.txt")):
            texts.append(variant_map.normalize_text(
                p.read_text(encoding="utf-8")))
        lm = CharNgramLM()
        lm.train(texts)
        return lm
    return UniformLM()


def rank_book(book_out_dir: Path, lm: BaseLM,
              variant_map: VariantMap | None = None) -> dict:
    """读 candidates.json + phase4 index + clusters.json → 写 phase6 全部输出。"""
    book_out_dir = Path(book_out_dir)
    phase6 = book_out_dir / "phase6_labels"
    variant_map = variant_map or VariantMap.load()

    with open(phase6 / "candidates.json", encoding="utf-8") as f:
        cand_payload = json.load(f)
    cand_by_cluster = {c["cluster_id"]: c["candidates"]
                       for c in cand_payload["clusters"]}
    with open(book_out_dir / "phase5_clusters" / "clusters.json",
              encoding="utf-8") as f:
        clusters = json.load(f)
    cluster_of: dict[str, str] = {}
    size_of: dict[str, int] = {}
    for c in clusters["clusters"]:
        size_of[c["cluster_id"]] = c["size"]
        for m in c["members"]:
            cluster_of[m] = c["cluster_id"]

    instances = load_index(book_out_dir / "phase4_chars")

    # 按页组织，页内按阅读顺序（列升序=从右到左，列内从上到下）
    by_page: dict[str, list[CharInstance]] = defaultdict(list)
    for inst in instances:
        by_page[inst.page].append(inst)

    all_results: list[SlotResult] = []
    page_columns: dict[str, list[list[SlotResult]]] = {}
    for page in sorted(by_page, key=lambda p: reading_order_key(
            parse_id(by_page[p][0].id))[0]):
        insts = sorted(by_page[page], key=lambda i: (i.col, i.idx))
        slots: list[Slot] = []
        for inst in insts:
            cid = cluster_of.get(inst.id)
            cands = [SlotCandidate(d["char"], d["semantic"], d["p"])
                     for d in cand_by_cluster.get(cid, [])]
            flags = list(inst.flags)
            if cid and size_of.get(cid, 0) == 1:
                flags.append("singleton")
            slots.append(Slot(instance_id=inst.id, cluster_id=cid,
                              candidates=cands, flags=flags))
        results = beam_search(slots, lm)   # 同页跨列滚动解码
        all_results.extend(results)
        # 还原列结构供转写
        cols: dict[int, list[SlotResult]] = defaultdict(list)
        for inst, r in zip(insts, results):
            cols[inst.col].append(r)
        page_columns[page] = [cols[c] for c in sorted(cols)]

    check_cluster_consistency(all_results)   # 跨页的簇一致性检查

    # ── ranked.json ──
    ranked = [{"id": r.instance_id, "cluster": r.cluster_id,
               "best": r.best, "semantic": r.best_semantic,
               "margin": r.margin, "posterior": r.posterior,
               "suspect_reasons": r.suspect_reasons}
              for r in all_results]
    with open(phase6 / "ranked.json", "w", encoding="utf-8") as f:
        json.dump({"results": ranked}, f, ensure_ascii=False, indent=2)

    # ── suspects.json：预期收益 = 簇大小 × 不确定度，降序 ──
    suspects = []
    for r in all_results:
        if not r.suspect_reasons:
            continue
        size = size_of.get(r.cluster_id, 1) if r.cluster_id else 1
        gain = size * (1.0 - r.margin)
        suspects.append({"id": r.instance_id, "cluster": r.cluster_id,
                         "best": r.best, "margin": r.margin,
                         "reasons": r.suspect_reasons,
                         "expected_gain": round(gain, 2)})
    suspects.sort(key=lambda s: -s["expected_gain"])
    with open(phase6 / "suspects.json", "w", encoding="utf-8") as f:
        json.dump({"suspects": suspects}, f, ensure_ascii=False, indent=2)

    # ── 转写：字形层原文 text/ + 语义层辅助 text_semantic/ ──
    (phase6 / "text").mkdir(exist_ok=True)
    (phase6 / "text_semantic").mkdir(exist_ok=True)
    for page, columns in page_columns.items():
        surface = "\n".join("".join(r.best for r in col) for col in columns)
        semantic = "\n".join("".join(r.best_semantic for r in col)
                             for col in columns)
        (phase6 / "text" / f"{page}.txt").write_text(surface, encoding="utf-8")
        (phase6 / "text_semantic" / f"{page}.txt").write_text(
            semantic, encoding="utf-8")

    stats = {"instances": len(all_results), "suspects": len(suspects)}
    with open(phase6 / "meta.json", "w", encoding="utf-8") as f:
        json.dump({"lm": lm.name, "stats": stats}, f,
                  ensure_ascii=False, indent=2)
    return stats
