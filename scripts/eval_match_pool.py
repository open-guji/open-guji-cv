"""3a 固定候选池分片的通用评测（A23，2026-11-23）：首位命中、放行、误放，按查询类别分报。

分片：open-guji-dataset `glyph-match/<名>/`（`items.jsonl`：`{query_id, gold, kind, candidates:[{id, char, same}]}`
＋自带归一图 `crops/`，由 dataset `scripts/build_glyph_poolset.py` 冻结；候选池当时按物理格留一从库里取）。
现用于 A5 退化：`damaged-siku-v2`、`damaged-shiji`（ai-team 残笔细笔真实残损集，类别 残笔／细笔／对照）。

判官同 `eval_advset.py`：生产的 `verify_pair_elastic`，给 `--sim-model` 时加 CNN 与 fuse 两路。
- 首位命中：同字候选最高分 > 所有异字候选最高分（字分取该字刻例的最高分，和生产一致）；
- 放行：首位命中且首位那对判 same（生产会自动认下）；
- 误放：有异字候选判 same 且分数不低于同字最高分（生产会认成别的字）——护栏，不许增。

    python scripts/eval_match_pool.py <分片目录> [--sim-model …] [--out r.json] [--against old.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_advset as A  # noqa: E402


def report(items, ways):
    res, flips = {}, {}
    for name, sc in ways.items():
        agg = defaultdict(lambda: dict(n=0, rank1=0, accept=0, false_same=0))
        bad = []
        for it, s in zip(items, sc):
            g = [x for c, x in zip(it["candidates"], s) if c["same"]]
            o = [(c, x) for c, x in zip(it["candidates"], s) if not c["same"]]
            gmax = max((x[1] for x in g), default=-1.0)
            omax = max((x[1] for _, x in o), default=-1.0)
            top1 = gmax > omax
            acc = top1 and any(x[0] and x[1] == gmax for x in g)
            fs = [(c, x) for c, x in o if x[0] and x[1] >= gmax]
            for k in (it["kind"], "全部"):
                a = agg[k]
                a["n"] += 1
                a["rank1"] += top1
                a["accept"] += acc
                a["false_same"] += bool(fs)
            if not top1:
                c = max(o, key=lambda t: t[1][1])[0] if o else {"char": "?", "id": "?"}
                bad.append(f'{it["query_id"]}|{it["gold"]}→{c["char"]}{"（误放）" if fs else ""}')
        res[name] = {k: dict(v, rank1_rate=v["rank1"] / v["n"], accept_rate=v["accept"] / v["n"])
                     for k, v in agg.items()}
        flips[name] = sorted(bad)
    return res, flips


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("shard")
    ap.add_argument("--sim-model", default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--out", default=None)
    ap.add_argument("--against", default=None)
    a = ap.parse_args()
    shard = Path(a.shard)
    info = json.loads((shard / "info.json").read_text(encoding="utf-8"))
    items, P = A._load(shard)
    ways = A._score(items, P, a.sim_model, a.workers)
    res, flips = report(items, ways)
    print(f"== {shard.name}（{info['book']}）：{len(items)} 格 ==")
    for name, r in res.items():
        print("  " + name + "  " + "  ".join(
            f"{k} 首位 {100 * v['rank1_rate']:.1f}% 放行 {100 * v['accept_rate']:.1f}% 误放 {v['false_same']}（n={v['n']}）"
            for k, v in sorted(r.items(), key=lambda t: t[0] != "全部")))
    way = "cnn+fuse" if "cnn+fuse" in res else "cov"
    h = res[way]
    out = dict(shard=str(shard), book=info["book"], n=len(items), crops_from=info.get("crops_from"),
               sim_model=a.sim_model, result=res, flips=flips,
               headline=dict(way=way, false_same=h["全部"]["false_same"],
                             **{f"{k}_rank1": v["rank1_rate"] for k, v in h.items()},
                             **{f"{k}_accept": v["accept_rate"] for k, v in h.items()}))
    if a.against:
        old = json.loads(Path(a.against).read_text(encoding="utf-8")).get("flips", {})
        for k, v in flips.items():
            o = set(old.get(k, []))
            add, gone = sorted(set(v) - o), sorted(o - set(v))
            if add or gone:
                print(f"  翻转 {k}：新错 {len(add)} 改对 {len(gone)}")
                for x in add[:20]:
                    print(f"    + {x}")
                for x in gone[:20]:
                    print(f"    - {x}")
    if a.out:
        Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
