# -*- coding: utf-8 -*-
"""字体族实测（长期规划 2.3，A23 11-05）：一本书的人裁刻例当查询，在另一本书的人裁库里做 5a，
看「借库」能借到多少。两边都高才算同族。

查询：三书人裁冻结分片（`char-clustering/samples/00{4,5,6}-*-human`），库：另一本书 glyph.db 里
`provenance='human'` 的**本书**实例（≈共享刻例库 qkp 的口径，只是没筛 ≥2 批、每字 ≤3 张）。
库要先剥干净：匹配器读的是 `exemplars ⋈ glyphs`（外加 `borrowed`、`derived` 字体域），只删 `instances`
没用——借来的刻例和字体域还在，不同库的结果会糊在一起（第一遍就栽在这）。剥法：`exemplars` 只留本书源的
人裁实例，清空 `borrowed`，`derived` 只留剩下实例的（匹配器要 `derived.norm`，全删库就是 0 条）。
对角（自己查自己，留一）当对照。

读数（只算金标字在该库里**有刻例**的格，没有的算「库缺」，借库本来就没法认）：
- 另报「共同字集」口径：只看金标字**同时**在三个库里都有刻例的格，不同库之间才可比（各书人裁格是送审挑出的难格，
  字集差得很远，不限字集时首位对率会被「库里恰好有常见字」抬高）；
- `cover`：金标字在库里有刻例的格占比；
- `top1`：这些格里库首位（己已巳、日曰折叠）就是金标字的比例；
- `pass`/`wrong`：A31 证人规则（首位、≥t、领先 ≥0.02，t 取 0.95）下，金标字拿到证的占比 / 前五里有错字也拿到证的占比；
- `mean_cov`：首位答对的格的平均 cov——同族的刻例形状近，分会高；不同族即使答对分也低。

    python scripts/eval_font_family.py \
        --shard 004-siku-v2-human --shard 005-shiji-human --shard 006-qtw-human \
        --lib siku=fam/siku_human.db --lib shiji=fam/shiji_human.db --lib qtw=fam/qtw_human.db \
        --own 004-siku-v2-human=siku,005-shiji-human=shiji,006-qtw-human=qtw --out family.json

只读评测脚本，不进包。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from calibrate_lib_witness import HARD_CHARS, fold_row, passes  # noqa: E402  (fold_row 折叠候选与金标)
from calibrate_lib_witness import replay  # noqa: E402


def lib_chars(db: str) -> set[str]:
    c = sqlite3.connect(db)
    try:
        return {r[0] for r in c.execute("SELECT DISTINCT g.char FROM exemplars e JOIN glyphs g ON g.glyph_id=e.glyph_id")}
    finally:
        c.close()


def measure(rows: list[dict], chars: set[str], t: float, lead: float, common: set[str] | None = None) -> dict:
    clean = [r for r in rows if not r["flag"] and r["gold"] not in HARD_CHARS]
    rs = [fold_row(r) for r in clean]
    have = [r for r in rs if r["gold"] in chars and (common is None or r["gold"] in common)]
    n, nh = len(rs), len(have)
    top1 = [r for r in have if r["cand"] and r["cand"][0][0] == r["gold"]]
    ok = sum(passes(r["cand"], r["gold"], t, lead, True) for r in have)
    bad = sum(any(passes(r["cand"], c, t, lead, True) for c, _ in r["cand"] if c != r["gold"]) for r in have)
    return {"n": n, "cover": nh / n if n else 0, "n_have": nh,
            "top1": len(top1) / nh if nh else None,
            "pass": ok / nh if nh else None, "wrong": bad / nh if nh else None,
            "mean_cov": sum(r["cand"][0][1] for r in top1) / len(top1) if top1 else None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", action="append", required=True)
    ap.add_argument("--lib", action="append", required=True, help="<名>=<glyph.db>，可重复")
    ap.add_argument("--own", default="", help="<分片>=<库名>,… 对角对照（留一）")
    ap.add_argument("--dataset", default="../open-guji-dataset/char-clustering")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--t", type=float, default=0.95)
    ap.add_argument("--lead", type=float, default=0.02)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    libs = dict(x.split("=", 1) for x in a.lib)
    own = dict(x.split("=", 1) for x in a.own.split(",") if x)
    chars = {k: lib_chars(v) for k, v in libs.items()}
    common = set.intersection(*chars.values())
    samples = Path(a.dataset) / "samples"
    res = {}
    for shard in a.shard:
        for name, db in libs.items():
            rows = replay(samples / shard, db, a.limit)
            m = measure(rows, chars[name], a.t, a.lead)
            m["own"] = own.get(shard) == name
            m["common"] = measure(rows, chars[name], a.t, a.lead, common)
            res[f"{shard}→{name}"] = m
            c = m["common"]
            print(f'{"":>34}共同字集 n={c["n_have"]}  首位对 {c["top1"] or 0:.3f}  得证 {c["pass"] or 0:.3f}  错放 {c["wrong"] or 0:.4f}  对时均分 {c["mean_cov"] or 0:.3f}', flush=True)
            print(f'{shard:>20} → {name:<6}{" (自库,留一)" if m["own"] else ""}  覆盖 {m["cover"]:.3f}  首位对 {m["top1"]:.3f}  '
                  f'得证 {m["pass"]:.3f}  错放 {m["wrong"]:.4f}  对时均分 {m["mean_cov"]:.3f}', flush=True)
    if a.out:
        Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
