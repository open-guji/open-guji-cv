# -*- coding: utf-8 -*-
"""L2 图一致证人「库前五 ≥ t」按书标定（降人审迭代框架 L2，A31 11-05 口径）。

证人定义（A31 11-05）：glyph_match 产物里该格 `candidates` 前五中**该字**的 score
（cov；没有就 sim）≥ t，就算字形这一路给了证。这里在三书人裁冻结分片
（`char-clustering/samples/00{4,5,6}-*-human`，`scripts/build_book_human_shards.py` 建）上
按生产口径重放 Step5-a：同一份 glyph.db、`GlyphMatchParams` 缺省（含 font_tier 分级查库）、
`exclude_id` 留一（按物理格摘掉自己），取 `candidates[:5]`。

报三种读法（每个阈值 t 一行）：

- `top1`：前五首位字分 ≥ t 时，首位字 == 金标的比例（精度）与这样的格占比（覆盖）；
- `any`：前五里分 ≥ t 的每个**字**都当一条证词，证词 == 金标的比例——最悲观的精度，
  等于「不管提议字从哪来，只要库前五里有它且够分就放行」；
- `gold_hit`：金标字在前五里且分 ≥ t 的格占比——证人对**对的字**能给证的比例（召回）。

`any` 的精度是 L2 放行要看的数：放行条件是「提议字 X 在库前五且 ≥ t」，X 错时只要 X 也在
前五够分就会被放过，所以要拿前五里每个够分的错字都算一条假证。

另报几条候选规则（`RULES`）的「召回 / 错放率」：召回 = 金标字拿到证的格占比；错放率 = 前五里
**有错字也能拿到证**的格占比（提议字恰好是它就会被放过）。11-05 三书实测：A31 口径「前五 ≥ 0.95」
在殿本、史記错放 43%、34%，基本不分辨；「首位且领先次优异字 ≥ 0.02」才压得到 1% 上下，
数与建议见 ai-team `domain/CV/字形领域/L2图一致证人标定-2026-11-05.md`。

**局限**：重放用的是本机 glyph.db（没导字体域）；生产 font_tier 命中弱的格会再查字体域，
候选会多出 `font:` 来的字。殿本另用导了字体域的副本复跑过一次对照。

己已巳、日曰（图上分不开，Sheldon 11-05）折叠成同类：金标与候选都按组算，候选里同组的字合并取最高分、
不当彼此的竞争者。其余 hard_pair 字（`NEVER_MATCH_FAMILIES` 里剩下的成员，如千/干、十/士）仍要分开，
与体检标过的实例（`selfcheck_flag`）
各自分开报，头条数不含它们。

    python scripts/calibrate_lib_witness.py \
        --book 004-siku-v2-human:<殿本 glyph.db> --book 005-shiji-human:<史記 glyph.db> \
        --dataset ../open-guji-dataset/char-clustering --out witness.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval_fold import FOLD, fold as fold_char  # noqa: E402  己已巳、日曰图上分不开，按组折叠（2026-11-05）
from open_guji_cv.clustering.confusable import NEVER_MATCH_FAMILIES  # noqa: E402
from open_guji_cv.steps.glyph_match import (GlyphMatchParams, GlyphMatchStep,  # noqa: E402
                                            _FontTier, _keben_subset)

THRESHOLDS = (0.85, 0.90, 0.93, 0.95, 0.96, 0.97, 0.98, 0.99, 0.996)
# 其余形近护栏字（己已巳、日曰已折叠成同类，不在这里）：这些字照旧要分开，单独报
HARD_CHARS = frozenset(c for fam in NEVER_MATCH_FAMILIES for c in fam if c not in FOLD)


def replay(shard_dir: Path, db: str, limit: int | None) -> list[dict]:
    exp = json.loads((shard_dir / "expected.json").read_text(encoding="utf-8"))
    inst = exp["instances"][:limit] if limit else exp["instances"]
    p = GlyphMatchParams(db_path=db)
    step = GlyphMatchStep()
    full = step._matcher(p)
    tier = _FontTier.rule(p.font_tier)
    matcher = _FontTier(full, _keben_subset(full), tier) if tier is not None else full
    print(f"[{shard_dir.name}] 库 {len(full)} 条，查询 {len(inst)}", flush=True)
    out, t0 = [], time.time()
    for i, x in enumerate(inst):
        img = cv2.imread(str(shard_dir / x["crop"]), cv2.IMREAD_GRAYSCALE)
        norm = (img > 127).astype(np.uint8)
        m = matcher.match(norm, exclude_id=x["instance_id"])
        out.append({"id": x["instance_id"], "gold": x["char"],
                    "flag": x.get("selfcheck_flag") or "",
                    "verdict": m.verdict, "guard": m.guard,
                    "cand": [(c, round(float(v), 4)) for c, v in m.candidates[:5]]})
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{len(inst)}  {time.time() - t0:.0f}s", flush=True)
    return out


def fold_row(r: dict) -> dict:
    """金标与候选都折叠到组代表字；同组候选合并取最高分（同组的字不是彼此的竞争者）。"""
    best: dict[str, float] = {}
    for c, v in r["cand"]:
        k = fold_char(c)
        best[k] = max(best.get(k, 0.0), v)
    cand = sorted(best.items(), key=lambda kv: -kv[1])
    return {**r, "gold": fold_char(r["gold"]), "cand": cand}


def score_of(cand, ch):
    return max((v for c, v in cand if c == ch), default=None)


def table(rows: list[dict]) -> list[dict]:
    n = len(rows)
    res = []
    for t in THRESHOLDS:
        top_n = top_ok = 0
        any_n = any_ok = 0
        gold_hit = 0
        for r in rows:
            cand = r["cand"]
            if cand and cand[0][1] >= t:
                top_n += 1
                top_ok += cand[0][0] == r["gold"]
            chars = {c for c, v in cand if v >= t}
            any_n += len(chars)
            any_ok += r["gold"] in chars
            gold_hit += r["gold"] in chars
        res.append({"t": t, "n": n,
                    "top1_cov": top_n / n if n else 0, "top1_prec": top_ok / top_n if top_n else None,
                    "any_claims": any_n, "any_prec": any_ok / any_n if any_n else None,
                    "gold_hit": gold_hit / n if n else 0,
                    "false_claims": any_n - any_ok})
    return res


RULES = (  # (名, 领先次优异字的最小差, 要求首位)
    ("top5", None, False),     # A31 11-05 口径：该字在前五且分 ≥ t
    ("top1", None, True),      # 该字是首位且分 ≥ t
    ("lead01", 0.01, True),    # 首位、分 ≥ t、比次优异字高 ≥ 0.01
    ("lead02", 0.02, True),
    ("lead03", 0.03, True),
)


def passes(cand, x: str, t: float, lead: float | None, top1: bool) -> bool:
    """提议字 x 能不能拿到这条证（cand = 产物 candidates 前五）。"""
    s = score_of(cand, x)
    if s is None or s < t:
        return False
    other = max((v for c, v in cand if c != x), default=0.0)
    if top1 and other > s:
        return False
    return lead is None or s - other >= lead


def rule_table(rows: list[dict]) -> list[dict]:
    """每条规则 × 阈值：金标字拿到证的比例（召回）与「有错字也能拿到证」的格占比（错放率，
    提议字恰好是那个错字时就会被放过——不看提议从哪来的最坏读法）。"""
    n = len(rows)
    out = []
    for name, lead, top1 in RULES:
        for t in THRESHOLDS:
            rec = sum(passes(r["cand"], r["gold"], t, lead, top1) for r in rows)
            bad = sum(any(passes(r["cand"], c, t, lead, top1)
                          for c, _ in r["cand"] if c != r["gold"]) for r in rows)
            out.append({"rule": name, "t": t, "n": n,
                        "recall": rec / n if n else 0, "false_pass": bad / n if n else 0})
    return out


def wrong_examples(rows: list[dict], t: float, k: int = 40) -> list[dict]:
    bad = []
    for r in rows:
        for c, v in r["cand"]:
            if v >= t and c != r["gold"]:
                bad.append({"id": r["id"], "gold": r["gold"], "claim": c, "score": v})
                break
    return bad[:k]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", action="append", required=True, help="<分片>:<glyph.db>，可重复")
    ap.add_argument("--dataset", default="../open-guji-dataset/char-clustering")
    ap.add_argument("--limit", type=int, default=None, help="只跑前 N 个实例（试跑）")
    ap.add_argument("--rows", default=None, help="逐格前五写到这个 jsonl（复核用）")
    ap.add_argument("--no-fold", action="store_true", help="不折叠己已巳、日曰（旧口径）")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    samples = Path(a.dataset) / "samples"
    report = {}
    for spec in a.book:
        shard, db = spec.split(":", 1)
        rows = replay(samples / shard, db, a.limit)
        if not a.no_fold:
            rows = [fold_row(r) for r in rows]
        if a.rows:
            with open(f"{a.rows}.{shard}.jsonl", "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        clean = [r for r in rows if not r["flag"] and r["gold"] not in HARD_CHARS]
        hard = [r for r in rows if not r["flag"] and r["gold"] in HARD_CHARS]
        flagged = [r for r in rows if r["flag"]]
        rep = {"n": len(rows), "headline": table(clean), "rules": rule_table(clean),
               "rules_hard_pair": rule_table(hard), "hard_pair": table(hard),
               "flagged": table(flagged), "all": table(rows),
               "wrong_at_0.95": wrong_examples(clean, 0.95)}
        report[shard] = rep
        print(f"\n[{shard}] 头条（不含 hard_pair {len(hard)}、体检标记 {len(flagged)}）n={len(clean)}")
        print(f'{"t":>6} {"top1覆盖":>8} {"top1精度":>8} {"证词数":>6} {"证词精度":>8} {"错证":>5} {"金标得证":>8}')
        for x in rep["headline"]:
            tp = f'{x["top1_prec"]:.4f}' if x["top1_prec"] is not None else "-"
            ap_ = f'{x["any_prec"]:.4f}' if x["any_prec"] is not None else "-"
            print(f'{x["t"]:>6} {x["top1_cov"]:8.3f} {tp:>8} {x["any_claims"]:6d} {ap_:>8} '
                  f'{x["false_claims"]:5d} {x["gold_hit"]:8.3f}')
        print(f'\n  规则 × 阈值（召回 / 错放率）')
        for name, *_ in RULES:
            cells = [x for x in rep["rules"] if x["rule"] == name and x["t"] in (0.93, 0.95, 0.97, 0.98, 0.99)]
            print(f'  {name:<7}' + "".join(f'  t={x["t"]}: {x["recall"]:.3f}/{x["false_pass"]:.4f}' for x in cells))
    if a.out:
        Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n→ {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
