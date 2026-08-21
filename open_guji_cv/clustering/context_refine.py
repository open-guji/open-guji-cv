"""M5+ 上下文自动修正：簇级边缘化 + 同书自举语言模型。

单字识别后的自动纠错，不依赖外部语料、不需要人工介入。两个信号：

**1. 簇级边缘化（聚类特有的强约束）**
   同一簇的 N 个实例必是同一个字，却分布在 N 个不同上下文中。
   把各实例的上下文后验按簇聚合（对数域求和 = 联合证据），
   再把聚合结果回灌给全簇——单点歧义被 N 处证据消解。
   高频字尤其有效："之"出现 404 次，404 处上下文的联合几乎必然正确。

**2. 同书自举 n-gram（默认关闭 —— 实测净有害）**
   设想：同书内书名、人名、术语反复出现，取高置信段落训练 n-gram
   即可自举。book9 全书消融实验（黄金集 5013 实例）推翻了这个假设：

   | 配置 | 黄金集准确率 | 高置信 | 可疑 |
   |------|------------|--------|------|
   | 基线 | 100% | 29329 | 481 |
   | 仅簇级边缘化 | **100%（零劣化）** | 29422 | **457** |
   | 仅自举 LM | 99.78% | 29944 | 1002 |
   | 两者 | 99.50% | 29952 | 907 |

   自举 LM 把已知正确的字改错了（"林→你"、"編→漏"），因为语料本身
   带 ~15% 识别错误，且 2 万字训 3-gram 远不足以压过噪声。
   故 ``use_lm`` 默认 False；**有外部古文语料时**（M5 设计的正途）
   再打开才有意义。簇级边缘化则默认开启：它零劣化且降低可疑数。
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path

from .context_rank import (Slot, SlotCandidate, beam_search,
                           check_cluster_consistency)
from .extractor import load_index
from .ids import parse_id, reading_order_key
from .lm import CharNgramLM, UniformLM
from .variants import VariantMap

MIN_SEG_LEN = 3          # 自举语料的最短连续高置信段
BOOTSTRAP_CONF = 0.6     # 进入语料的最低后验
CLUSTER_PRIOR_W = 0.6    # 簇级边缘化结果回灌为先验时的权重


def cluster_marginalize(results, cluster_of: dict[str, str],
                        top_k: int = 5) -> dict[str, list[tuple[str, float]]]:
    """簇级边缘化：同簇所有实例的上下文后验 → 簇级字分布（纯函数）。

    对数域累加各实例后验（联合证据），再归一化。实例越多、
    各处上下文越一致，分布越尖锐。

    Args:
        results: SlotResult 列表（含 instance_id 与 posterior）。
        cluster_of: instance_id → cluster_id。
    Returns:
        cluster_id → [(char, p)]，降序，最多 top_k 项。
    """
    acc: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    counts: dict[str, int] = defaultdict(int)
    for r in results:
        cid = cluster_of.get(r.instance_id)
        if not cid:
            continue
        counts[cid] += 1
        for ch, p in r.posterior:
            acc[cid][ch] += math.log(max(p, 1e-6))
    out: dict[str, list[tuple[str, float]]] = {}
    for cid, logs in acc.items():
        n = max(1, counts[cid])
        # 几何平均（按实例数归一），避免大簇分数尺度失控
        scores = {ch: math.exp(lp / n) for ch, lp in logs.items()}
        total = sum(scores.values()) or 1.0
        ranked = sorted(((ch, s / total) for ch, s in scores.items()),
                        key=lambda x: -x[1])[:top_k]
        out[cid] = ranked
    return out


def bootstrap_corpus(results, variant_map: VariantMap,
                     min_conf: float = BOOTSTRAP_CONF,
                     min_seg: int = MIN_SEG_LEN) -> list[str]:
    """从识别结果提取高置信连续段作为 LM 语料（语义层，纯函数）。

    只有连续 ≥min_seg 个字后验都 ≥min_conf 的段落才入语料——
    孤立的高置信字没有上下文价值，低置信字会污染统计。
    """
    segs: list[str] = []
    cur: list[str] = []
    for r in results:
        conf = r.posterior[0][1] if r.posterior else 0.0
        if r.best != "<unk>" and conf >= min_conf:
            cur.append(r.best_semantic or r.best)
        else:
            if len(cur) >= min_seg:
                segs.append("".join(cur))
            cur = []
    if len(cur) >= min_seg:
        segs.append("".join(cur))
    return [variant_map.normalize_text(s) for s in segs]


def apply_cluster_prior(candidates: dict[str, list[dict]],
                        cluster_post: dict[str, list[tuple[str, float]]],
                        weight: float = CLUSTER_PRIOR_W
                        ) -> dict[str, list[dict]]:
    """把簇级边缘化结果按 weight 混入候选分布（纯函数）。

    新分布 = (1-w)·原候选 + w·簇级后验；字形层不变（不做任何合并）。
    """
    out: dict[str, list[dict]] = {}
    for cid, cands in candidates.items():
        post = dict(cluster_post.get(cid, []))
        if not post:
            out[cid] = cands
            continue
        base = {c["char"]: c for c in cands}
        merged: dict[str, float] = {}
        for ch, c in base.items():
            merged[ch] = (1 - weight) * c["p"]
        for ch, p in post.items():
            merged[ch] = merged.get(ch, 0.0) + weight * p
        total = sum(merged.values()) or 1.0
        ranked = sorted(merged.items(), key=lambda x: -x[1])[:5]
        out[cid] = [
            {**base.get(ch, {"char": ch, "semantic": ch,
                             "sources": ["cluster_prior"],
                             "surface_uncertain": True}),
             "char": ch, "p": round(p / total, 4)}
            for ch, p in ranked
        ]
    return out


def refine_book(book_out_dir: str | Path, rounds: int = 2,
                lm_order: int = 3, variant_map: VariantMap | None = None,
                verbose: bool = True, use_lm: bool = False,
                use_cluster_prior: bool = True, write: bool = True) -> dict:
    """自动上下文修正主流程（IO 壳）。

    每轮：训练自举 LM → 全书重解码 → 簇级边缘化 → 回灌候选。
    输出 phase6_labels/ 的更新版本 + refine_report.json。
    """
    book = Path(book_out_dir)
    phase6 = book / "phase6_labels"
    vm = variant_map or VariantMap.load()

    with open(phase6 / "candidates.json", encoding="utf-8") as f:
        cand_payload = json.load(f)
    candidates = {c["cluster_id"]: c["candidates"]
                  for c in cand_payload["clusters"]}
    with open(book / "phase5_clusters" / "clusters.json", encoding="utf-8") as f:
        clusters = json.load(f)["clusters"]
    cluster_of = {m: c["cluster_id"] for c in clusters for m in c["members"]}

    instances = load_index(book / "phase4_chars")
    by_page: dict[str, list] = defaultdict(list)
    for inst in instances:
        by_page[inst.page].append(inst)
    pages = sorted(by_page, key=lambda p: reading_order_key(
        parse_id(by_page[p][0].id))[0])

    report = {"rounds": []}
    lm = UniformLM()
    results = []
    for rnd in range(rounds + 1):
        results = []
        page_cols: dict[str, list] = {}
        for page in pages:
            insts = sorted(by_page[page], key=lambda i: (i.col, i.idx))
            slots = []
            for inst in insts:
                cid = cluster_of.get(inst.id)
                cs = [SlotCandidate(d["char"], d.get("semantic", d["char"]),
                                    d["p"])
                      for d in candidates.get(cid, [])]
                slots.append(Slot(instance_id=inst.id, cluster_id=cid,
                                  candidates=cs, flags=list(inst.flags)))
            res = beam_search(slots, lm)
            results.extend(res)
            cols: dict[int, list] = defaultdict(list)
            for inst, r in zip(insts, res):
                cols[inst.col].append(r)
            page_cols[page] = [cols[c] for c in sorted(cols)]
        check_cluster_consistency(results)

        known = sum(1 for r in results if r.best != "<unk>")
        conf = sum(1 for r in results
                   if r.posterior and r.posterior[0][1] >= 0.9)
        stats = {"round": rnd, "lm": lm.name, "known": known,
                 "high_conf": conf,
                 "suspects": sum(1 for r in results if r.suspect_reasons)}
        report["rounds"].append(stats)
        if verbose:
            print(f"  轮 {rnd} [{lm.name}]: 已识别 {known}, "
                  f"高置信 {conf}, 可疑 {stats['suspects']}")

        if rnd == rounds:
            break

        # 簇级边缘化 → 回灌候选
        if use_cluster_prior:
            cpost = cluster_marginalize(results, cluster_of)
            candidates = apply_cluster_prior(candidates, cpost)
        # 自举语料 → 训练下一轮 LM
        corpus = bootstrap_corpus(results, vm) if use_lm else []
        if corpus:
            lm = CharNgramLM(order=lm_order)
            lm.train(corpus)
            if verbose:
                print(f"    自举语料 {len(corpus)} 段 / "
                      f"{sum(len(s) for s in corpus)} 字，词表 {len(lm.vocab)}")

    report["final"] = {"results": [(r.instance_id, r.best) for r in results]} \
        if not write else None
    if not write:
        report.pop("final")
        report["_results"] = results
        return report

    # 落盘
    with open(phase6 / "ranked.json", "w", encoding="utf-8") as f:
        json.dump({"results": [
            {"id": r.instance_id, "cluster": r.cluster_id, "best": r.best,
             "semantic": r.best_semantic, "margin": r.margin,
             "posterior": r.posterior, "suspect_reasons": r.suspect_reasons}
            for r in results]}, f, ensure_ascii=False, indent=1)
    (phase6 / "text").mkdir(exist_ok=True)
    for page in pages:
        insts = sorted(by_page[page], key=lambda i: (i.col, i.idx))
        by_id = {r.instance_id: r for r in results}
        cols: dict[int, list] = defaultdict(list)
        for inst in insts:
            r = by_id.get(inst.id)
            if r:
                cols[inst.col].append(r.best)
        (phase6 / "text" / f"{page}.txt").write_text(
            "\n".join("".join(cols[c]) for c in sorted(cols)),
            encoding="utf-8")
    with open(phase6 / "refine_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    return report
