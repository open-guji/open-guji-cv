"""把进库审查涌现的坏图块回流成 char-segmentation/instances 的新分片。

    PYTHONPATH=. python scripts/build_intrusion_shard.py output/vol01 \
        --gold <目视细分 json> --dataset ../open-guji-dataset

## 为什么这批样本值钱

现有 91 条实例是**抽样**来的（38 条从历史问题位置、25 条随机），
contaminated 只有 8 条——太少，评不出自检能力在这一类上的真实水平。
这批不一样：用户逐页审查 1916 个字位时**亲手**把它们挑出来标了
「不入库」，是 100% 真实的下游危害样本，且带着为什么不入库的判断。
逐条目视细分后：41 条是版面线/邻字残余混入（contaminated），
5 条是缺笔/划痕（truncated / clean 但脏），另 32 条 not_a_char。

## 溯源纪律

`seed` 字段记 `review_label_only` / `review_not_a_char`，与既有的
`hist_contaminated` / `random_rigid` 并列——采样偏置不同的样本必须能
分开统计，否则「缺陷率」会被审查样本的富集拉高（本分片是**定向富集**
的，绝不能读作全书缺陷率）。
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(description="进库审查坏图块 → 实例质量分片")
    ap.add_argument("book_out_dir")
    ap.add_argument("--gold", required=True, help="目视细分 json（rule_bar/frame_bar/other）")
    ap.add_argument("--dataset", required=True)
    args = ap.parse_args()

    book_dir = Path(args.book_out_dir)
    book = book_dir.name
    root = book_dir / "phase4_chars"
    gold = json.loads(Path(args.gold).read_text(encoding="utf-8"))
    rows = [json.loads(l) for l in
            (book_dir / "phase9_seed" / "queue.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()]
    byid = {r["instance_id"]: r for r in rows}
    layout_of = {}
    for line in (root / "index.jsonl").read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        layout_of[d["id"]] = d

    dst = Path(args.dataset) / "char-segmentation" / "instances"
    exp_path = dst / "expected.json"
    expected = json.loads(exp_path.read_text(encoding="utf-8"))
    have = {(e["book"], e["page"], e["col"], e["idx"]) for e in expected}

    # 目视细分 → quality 标签（intrusion 子类另存 defect 字段，供细分评测）
    plan: list[tuple[str, str, str]] = []          # (instance_id, quality, defect)
    for iid in gold.get("rule_bar", []):
        plan.append((iid, "contaminated", "rule_bar"))
    for iid in gold.get("frame_bar", []):
        plan.append((iid, "contaminated", "frame_bar"))
    for iid in gold.get("other", []):
        plan.append((iid, "truncated", "stroke_loss_or_scratch"))
    for r in rows:
        if r["status"] == "not_a_char":
            plan.append((r["instance_id"], "not_text", "not_text"))

    added = skipped = missing = 0
    for iid, quality, defect in plan:
        r = byid.get(iid)
        if r is None:
            missing += 1
            continue
        key = (book, r["page"], r["col"], r["idx"])
        if key in have:
            skipped += 1
            continue
        src = root / r["patch_path"]
        if not src.exists():
            missing += 1
            continue
        name = f"{book}_{r['page']}_{r['col']}_{r['idx']}.png"
        shutil.copy2(src, dst / "patches" / name)
        expected.append({
            "book": book, "page": r["page"], "col": r["col"], "idx": r["idx"],
            "quality": quality, "defect": defect,
            "layout": layout_of.get(iid, {}).get("layout", "unknown"),
            "seed": ("review_not_a_char" if quality == "not_text"
                     else "review_label_only"),
            "label_origin": "human", "schema_version": 1,
        })
        have.add(key)
        added += 1

    expected.sort(key=lambda e: (e["book"], int(e["page"]), e["col"], e["idx"]))
    exp_path.write_text(json.dumps(expected, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    from collections import Counter
    print(json.dumps({
        "added": added, "skipped_existing": skipped, "missing": missing,
        "total": len(expected),
        "quality": dict(Counter(e["quality"] for e in expected)),
        "seed": dict(Counter(e.get("seed") for e in expected)),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
