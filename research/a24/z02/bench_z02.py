"""Z02 判法打架 benchmark（A24，2026-11-06）：用 Z02_seed.jsonl（殿本史記 132 格，目视真字，待 sheldon 复核）给复核／补放新规则打分。

    python research/a24/z02/bench_z02.py [--dissent-margin 1.0] [--ref-pair-margin 1.5] [--groups em,fc,...]

对每格：mode=review（降审格）用 `flow._dissent_keep`，mode=lift／joint 用 `flow._ref_pair_pick`；命中＝规则要放行的字。
输出：命中格数、命中里目视对／错／读不定、门槛（误放行 0）是否过。换一本书时先用 `scan_groups.py` 取该书全册字组格、
`rule_audit.py` 审 L1 规则，再抽 30 格（每组每书）补进种子（格式同 Z02_seed.jsonl）。"""
from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path

from open_guji_cv.groups.flow import _dissent_keep, _ref_pair_pick

NORM = {"㓂": "寇", "冦": "寇", "㑹": "會", "𧰼": "象", "岀": "出"}


def canon(c):
    return NORM.get(c, c)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default=str(Path(__file__).with_name("Z02_seed.jsonl")))
    ap.add_argument("--dissent-margin", type=float, default=1.0)
    ap.add_argument("--ref-pair-margin", type=float, default=1.5)
    ap.add_argument("--groups", default="", help="只算这些组（逗号分隔）；空＝全部")
    a = ap.parse_args()
    only = set(filter(None, a.groups.split(",")))
    res = collections.defaultdict(collections.Counter)
    wrong = []
    for line in Path(a.seed).read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if only and r["group"] not in only:
            continue
        if r["mode"] == "review":
            hit = _dissent_keep(r["group"], r["trail"], r["char"], r["ref"], canon, a.dissent_margin)
            pick, rule = r["char"], "dissent_keep"
        else:
            pick = _ref_pair_pick(r["group"], r["trail"], r["ref"], canon, a.ref_pair_margin)
            hit, rule = pick is not None, "ref_pair"
        res[rule]["格"] += 1
        if not hit:
            continue
        res[rule]["命中"] += 1
        if r["truth"] == "?":
            res[rule]["读不定"] += 1
        elif canon(pick) == canon(r["truth"]):
            res[rule]["对"] += 1
        else:
            res[rule]["错"] += 1
            wrong.append((rule, r["idx"], r["group"], pick, r["truth"], r["ctx"]))
    for rule, c in res.items():
        print(f"{rule}: 命中 {c['命中']}/{c['格']}，目视对 {c['对']}、错 {c['错']}、读不定 {c['读不定']}")
    for w in wrong:
        print("误放行：", *w)
    ok = not wrong
    print("门槛（目视误放行 0）：", "通过" if ok else "未过")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
