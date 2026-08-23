"""保守聚类 purity 评测（char-clustering 数据集的指标层）。

保守聚类的取向是**宁可碎，不可脏**，两个方向的代价完全不对称：

- 脏簇：错标签沿整簇批量扩散。实测过一次——glyph_store 里 94 个
  「人工」标签是簇级确认后传播给成员的，逐张复核有 11 个对不上（11.7%），
  一个脏簇就是这么把错标撒出去的。
- 碎簇：只是多花人工审查成本，标签本身不会错。

所以 `purity` 是硬约束（≥ 0.999），`fragmentation` 只在 purity 达标之后才有
意义——先报 purity，再看碎片率，顺序不能倒。

**三条报告纪律**（making-datasets.md 第六步）：

1. **分子分母一起给**。purity 从 0.98 掉到 0.95 可能不是退步，是这一批里
   多簇实例变多了（单例天然 purity=1，单例率一降 purity 就跟着降）。
   所以每个指标都带 `n_*` 计数，并单独报 `multi_instance_purity`——
   只在 size ≥ 2 的簇上算，把单例那份「白送的 1.0」摘出去。
2. **按标注来源分层**，不合成一个数字。align 标签自带噪声底噪，
   human 子集上的 purity 才是可以当硬约束卡的那个数。
3. **难例对单独报**。它们是刻意挑出来的分布外样本，混进总体 purity 会
   把真实进展盖掉。
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field


@dataclass
class PurityReport:
    n_instances: int
    n_majority: int              # 各簇内多数字的实例数之和 —— purity 的分子
    n_clusters: int
    n_gold_chars: int
    n_singletons: int
    n_multi_instances: int
    n_multi_majority: int
    impure_clusters: list[dict] = field(default_factory=list)

    @property
    def purity(self) -> float:
        return self.n_majority / self.n_instances if self.n_instances else 0.0

    @property
    def multi_instance_purity(self) -> float:
        """只算 size ≥ 2 的簇：单例的 1.0 是白送的，会把 purity 抬高。"""
        return (self.n_multi_majority / self.n_multi_instances
                if self.n_multi_instances else 0.0)

    @property
    def fragmentation(self) -> float:
        """簇数 / 金标字类数。1.0 = 恰好一字一簇；越大越碎。"""
        return self.n_clusters / self.n_gold_chars if self.n_gold_chars else 0.0

    @property
    def singleton_ratio(self) -> float:
        return self.n_singletons / self.n_clusters if self.n_clusters else 0.0

    def to_dict(self) -> dict:
        return {
            "purity": round(self.purity, 5),
            "purity_num": self.n_majority, "purity_den": self.n_instances,
            "multi_instance_purity": round(self.multi_instance_purity, 5),
            "multi_instance_num": self.n_multi_majority,
            "multi_instance_den": self.n_multi_instances,
            "fragmentation": round(self.fragmentation, 4),
            "n_clusters": self.n_clusters, "n_gold_chars": self.n_gold_chars,
            "n_singletons": self.n_singletons,
            "singleton_ratio": round(self.singleton_ratio, 4),
            "impure_clusters": self.impure_clusters,
        }


def compute_purity(assignment: dict[str, str], gold: dict[str, str],
                   subset: set[str] | None = None,
                   top_impure: int = 10) -> PurityReport:
    """assignment: 实例 → 簇 id；gold: 实例 → 金标字。

    subset 给定时只统计这些实例（分层用）：簇结构不变，只是簇内按子集
    重新数多数字——分层不是重新聚类，是换一副眼镜看同一次聚类。
    """
    members: dict[str, list[str]] = defaultdict(list)
    for iid, cid in assignment.items():
        if iid not in gold:
            continue                       # 没金标的实例不进 purity 分母
        if subset is not None and iid not in subset:
            continue
        members[cid].append(iid)

    n_inst = n_major = n_single = 0
    n_multi = n_multi_major = 0
    impure: list[dict] = []
    for cid, ids in members.items():
        counts = Counter(gold[i] for i in ids)
        major = counts.most_common(1)[0][1]
        n_inst += len(ids)
        n_major += major
        if len(ids) == 1:
            n_single += 1
        else:
            n_multi += len(ids)
            n_multi_major += major
        if len(counts) > 1:
            impure.append({"cluster_id": cid, "size": len(ids),
                           "chars": dict(counts.most_common()),
                           "n_wrong": len(ids) - major})
    impure.sort(key=lambda c: -c["n_wrong"])

    return PurityReport(
        n_instances=n_inst, n_majority=n_major, n_clusters=len(members),
        n_gold_chars=len({gold[i] for ids in members.values() for i in ids}),
        n_singletons=n_single, n_multi_instances=n_multi,
        n_multi_majority=n_multi_major, impure_clusters=impure[:top_impure])


def hard_pair_report(assignment: dict[str, str], pairs: list[dict]) -> dict:
    """难例对判定：`same` 要落进同一簇，`diff` 不得同簇。

    按 relation 与 origin 双重分组报——`same` 和 `diff` 的失败含义完全不同
    （前者是碎，后者是脏），合成一个准确率会把两件事同时盖掉。
    """
    by_key: dict[tuple[str, str], list[bool]] = defaultdict(list)
    missing = 0
    wrong: list[dict] = []
    for p in pairs:
        a, b = p["a"], p["b"]
        if a not in assignment or b not in assignment:
            missing += 1
            continue
        together = assignment[a] == assignment[b]
        ok = together if p["relation"] == "same" else not together
        by_key[(p["relation"], p.get("origin", "?"))].append(ok)
        if not ok:
            wrong.append({"a": a, "b": b, "relation": p["relation"],
                          "origin": p.get("origin"), "note": p.get("note")})

    groups = {}
    for (rel, origin), oks in sorted(by_key.items()):
        groups[f"{rel}/{origin}"] = {"n": len(oks), "correct": sum(oks),
                                     "accuracy": round(sum(oks) / len(oks), 4)}
    all_oks = [o for oks in by_key.values() for o in oks]
    return {
        "overall": {"n": len(all_oks), "correct": sum(all_oks),
                    "accuracy": round(sum(all_oks) / len(all_oks), 4) if all_oks else 0.0},
        "by_group": groups,
        "n_missing_instances": missing,
        "failures": wrong[:20],
    }


def evaluate(assignment: dict[str, str], instances: list[dict],
             pairs: list[dict]) -> dict:
    """一个分片的完整报告：总体 + 分层 purity + 难例对。"""
    gold = {i["instance_id"]: i["char"] for i in instances}
    report = {"overall": compute_purity(assignment, gold).to_dict(),
              "strata": {}, "hard_pairs": hard_pair_report(assignment, pairs)}

    strata: dict[str, set[str]] = defaultdict(set)
    for i in instances:
        strata[f"label_origin={i.get('label_origin', '?')}"].add(i["instance_id"])
        if "align_op" in i:
            strata[f"align_op={i['align_op']}"].add(i["instance_id"])
        if "tier" in i:
            # 干净/退化分层（2026-08 策略）：算法在干净图块上必须非常好，
            # 在退化图块上能不崩即可——这两层的 purity 期望完全不同，
            # 合成一个数字会互相稀释。
            strata[f"tier={i['tier']}"].add(i["instance_id"])
    for name, subset in sorted(strata.items()):
        report["strata"][name] = compute_purity(assignment, gold, subset).to_dict()
    return report


def format_report(name: str, report: dict) -> str:
    o = report["overall"]
    lines = [f"[{name}]",
             f"  purity        {o['purity']:.5f}  ({o['purity_num']}/{o['purity_den']})",
             f"  多实例簇 purity {o['multi_instance_purity']:.5f}  "
             f"({o['multi_instance_num']}/{o['multi_instance_den']})",
             f"  簇数 {o['n_clusters']}  金标字类 {o['n_gold_chars']}  "
             f"碎片率 {o['fragmentation']:.2f}  单例率 {o['singleton_ratio']:.1%}"]
    for k, s in report["strata"].items():
        lines.append(f"  分层 {k:<22} purity {s['purity']:.5f} "
                     f"({s['purity_num']}/{s['purity_den']})  碎片率 {s['fragmentation']:.2f}")
    hp = report["hard_pairs"]["overall"]
    lines.append(f"  难例对 {hp['correct']}/{hp['n']} = {hp['accuracy']:.1%}")
    for k, g in report["hard_pairs"]["by_group"].items():
        lines.append(f"    {k:<34} {g['correct']}/{g['n']} = {g['accuracy']:.1%}")
    if o["impure_clusters"]:
        lines.append("  脏簇头部：")
        for c in o["impure_clusters"][:5]:
            chars = " ".join(f"{ch}×{n}" for ch, n in c["chars"].items())
            lines.append(f"    {c['cluster_id']} size={c['size']} 错{c['n_wrong']}  {chars}")
    return "\n".join(lines)
