# -*- coding: utf-8 -*-
"""从字形库体检的人裁结果构建匹配三元组金标（glyph-match/triplets）。

    PYTHONPATH=. python scripts/build_match_triplets_shard.py \
        --db output/glyph.db --audit output/glyphdb_audit \
        --dataset ../open-guji-dataset

三元组 = (anchor 本例, same 同字刻例, other 形近异字刻例)。金标性质：
**cov(anchor, same) > cov(anchor, other)**——同字形必须比形近他字更匹配。

- **hard 子集**：体检里 rival 旗（异字反超同字）、且用户在审查页按了
  「没问题」（audit_ok.json 白名单 = 人工二次确认标签无误）的案例。
  用户实审原话：「明明我看着第一个和第二个更像，你的匹配率却说和
  第三个更匹配」——这些就是当前算法的**已知失败**，靶子。
- **control 子集**：未被打旗、同字覆盖良好但也存在有意义异字近邻的
  实例随机抽样——防止为修 hard 把正常案例改坏。

图块存**原始灰度 patch**（不存归一图）：归一化本身是匹配算法的一部分，
冻结原图才能让归一化的改进也被量到。

评测：scripts/eval_match_triplets.py。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from open_guji_cv.clustering.audit import shape_audit  # noqa: E402
from open_guji_cv.clustering.glyph_db import GlyphDB  # noqa: E402
from open_guji_cv.clustering.variants import VariantMap  # noqa: E402
from scripts.audit_glyph_db import load_entries  # noqa: E402

N_CONTROL = 60
CONTROL_SAME_MIN = 0.95   # control 的同字覆盖须良好
CONTROL_OTHER_MIN = 0.80  # 且异字近邻有意义（太低的赢了不说明什么）


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="output/glyph.db")
    ap.add_argument("--audit", default="output/glyphdb_audit")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    ok_path = Path(args.audit) / "audit_ok.json"
    whitelist = set(json.loads(ok_path.read_text(encoding="utf-8"))) \
        if ok_path.exists() else set()

    vmap = VariantMap.load()
    db = GlyphDB(args.db)
    try:
        entries, patches = load_entries(db, vmap)
    finally:
        db.close()
    findings = shape_audit(entries)
    char_of = {e.instance_id: e.char for e in entries}

    triplets = []
    for f in findings.values():
        if "rival" not in f.flags or f.instance_id not in whitelist:
            continue
        if not (f.same_peer and f.other_peer):
            continue
        triplets.append({
            "subset": "hard", "anchor": f.instance_id,
            "same": f.same_peer, "other": f.other_peer,
            "char": f.char, "other_char": f.other_char,
            "build_cov_same": round(f.best_same, 4),
            "build_cov_other": round(f.best_other, 4),
        })

    pool = [f for f in findings.values()
            if not f.flags and f.same_peer and f.other_peer
            and f.best_same >= CONTROL_SAME_MIN
            and f.best_other >= CONTROL_OTHER_MIN]
    random.Random(args.seed).shuffle(pool)
    for f in pool[:N_CONTROL]:
        triplets.append({
            "subset": "control", "anchor": f.instance_id,
            "same": f.same_peer, "other": f.other_peer,
            "char": f.char, "other_char": f.other_char,
            "build_cov_same": round(f.best_same, 4),
            "build_cov_other": round(f.best_other, 4),
        })

    dst = Path(args.dataset) / "glyph-match" / "triplets"
    (dst / "patches").mkdir(parents=True, exist_ok=True)
    need = {t[k] for t in triplets for k in ("anchor", "same", "other")}
    for iid in need:
        (dst / "patches" / (iid.replace(":", "_") + ".png")) \
            .write_bytes(patches[iid])
    for t in triplets:
        t["schema_version"] = 1
        t["label_origin"] = "human"   # anchor 标签经审查页二次人裁
    triplets.sort(key=lambda t: (t["subset"], t["anchor"]))
    (dst / "expected.json").write_text(
        json.dumps(triplets, ensure_ascii=False, indent=1), encoding="utf-8")

    n_hard = sum(1 for t in triplets if t["subset"] == "hard")
    meta = {
        "name": "glyph-match-triplets",
        "version": "0.1.0",
        "schema_version": 1,
        "description": "匹配排序三元组：同字形必须比形近异字更匹配"
                       "（cov(anchor,same) > cov(anchor,other)）",
        "created": "2026-08-24",
        "status": "可用",
        "eval_command": "cd open-guji-cv && PYTHONPATH=. python "
                        "scripts/eval_match_triplets.py "
                        "../open-guji-dataset/glyph-match/triplets",
        "total_samples": len(triplets),
        "sample_unit": "三元组",
        "subsets": {"hard": n_hard, "control": len(triplets) - n_hard},
        "label_origin_values": ["human"],
        "provenance": "字形库体检（glyphdb-audit）rival 旗 × 审查页白名单；"
                      "control 为未打旗良例抽样（seed=%d）" % args.seed,
        "notes": "图块为原始灰度 patch——归一化属于被测算法的一部分。"
                 "hard 全部是构建时算法的已知失败，基线≈0 是设计使然；"
                 "指标 = 各子集排序正确率 + 平均 margin，control 不得回退。",
    }
    (dst / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"hard": n_hard, "control": len(triplets) - n_hard,
                      "patches": len(need)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
