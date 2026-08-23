"""构建 context-correction 测试集：冻结候选 + 逐槽位金标，按页存、按列组织。

    PYTHONPATH=. python scripts/build_context_correction_dataset.py <book_out_dir> \
        --corpus corpus/xxx.txt --dataset ../open-guji-dataset

## 为什么候选必须冻结在样本里

上下文纠正测的是「**在给定候选分布上**，语言模型与簇级证据能把 top-1
往上抬多少」。候选要是每次现算，上游 OCR 一换，本集的数字就不可比——
分不清是纠正变好了还是候选变好了。所以 `slots[].candidates` 是从
`phase6_labels/candidates.json` 原样拷进来的快照，连同 `pipeline_version`
一起冻结。

## 上下文字段的口径

`context.prev` / `next` 取相邻列的**金标**文本，即「相邻列已经确认好了」
的理想情形。这是上界口径：真实流程里相邻列同样带错。之所以取理想值，
是因为本集要隔离的是纠正算法本身的能力；相邻列也带噪的联合情形是另一
个问题，要另建集或另加一档。这一条必须写进 `known_limitation`，别把
本集的 `top1_gain` 直接当作全书能拿到的增益。

## 主指标是净收益，不是收益

`top1_gain` 单独看会骗人：把 20 个错的改对、同时把 15 个对的改错，
净增益只有 5，但阅读体验是更乱了。故 `harmful_flip_rate`（原本正确
被改错的比例）必须与 `top1_gain` 一起报，缺一不可。
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def git_rev(path: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                              capture_output=True, text=True,
                              check=True).stdout.strip()[:12]
    except Exception:
        return "unknown"


def main() -> None:
    ap = argparse.ArgumentParser(description="构建 context-correction 测试集")
    ap.add_argument("book_out_dir")
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--split", default="test", choices=["train", "test"])
    args = ap.parse_args()

    import sys
    sys.path.insert(0, str(REPO))
    from open_guji_cv.clustering.align_gold import gold_for_book

    book_dir = Path(args.book_out_dir)
    book = book_dir.name
    phase6 = book_dir / "phase6_labels"
    cand_payload = json.loads((phase6 / "candidates.json").read_text(encoding="utf-8"))
    cand_of = {c["cluster_id"]: c["candidates"] for c in cand_payload["clusters"]}
    clusters = json.loads(
        (book_dir / "phase5_clusters" / "clusters.json").read_text(encoding="utf-8"))
    cluster_of = {m: c["cluster_id"] for c in clusters["clusters"]
                  for m in c["members"]}
    size_of = {c["cluster_id"]: c["size"] for c in clusters["clusters"]}

    pages, _ = gold_for_book(book_dir, args.corpus)

    root = Path(args.dataset) / "context-correction"
    samples_dir = root / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)

    n_cols = n_slots = n_cand0 = 0
    gold_in_cands = gold_is_top1 = 0
    written: list[str] = []

    for pg in pages:
        if not pg.items:
            continue
        by_col: dict[int, list] = defaultdict(list)
        for it in pg.items:
            by_col[it.col].append(it)

        # 各列的金标文本，供相邻列做上下文；列按编号升序 = 从右到左
        col_order = sorted(by_col)
        gold_text = {c: "".join(i.gold for i in sorted(by_col[c],
                                                       key=lambda x: x.idx))
                     for c in col_order}

        columns = []
        for k, col in enumerate(col_order):
            slots = []
            for it in sorted(by_col[col], key=lambda x: x.idx):
                cid = cluster_of.get(it.instance_id)
                cands = [{"char": d["char"], "prob": d["p"],
                          "source": "+".join(d.get("sources", [])) or "ocr",
                          "semantic": d.get("semantic", d["char"]),
                          "surface_uncertain": d.get("surface_uncertain", True)}
                         for d in cand_of.get(cid, [])]
                n_slots += 1
                n_cand0 += (not cands)
                chars = [c["char"] for c in cands]
                gold_in_cands += it.gold in chars
                gold_is_top1 += bool(chars) and chars[0] == it.gold
                slots.append({
                    "index": it.idx,
                    "instance_id": it.instance_id,
                    "cluster_id": cid,
                    "cluster_size": size_of.get(cid, 1),
                    "candidates": cands,
                    "gold": it.gold,
                    "frozen": True,
                })
            columns.append({
                "column_id": f"{book}:{pg.page}:{col}",
                "context": {
                    "prev": gold_text[col_order[k - 1]] if k > 0 else None,
                    "next": gold_text[col_order[k + 1]] if k + 1 < len(col_order) else None,
                },
                "slots": slots,
            })
            n_cols += 1

        sample = samples_dir / f"{book}_{pg.page}"
        sample.mkdir(exist_ok=True)
        (sample / "expected.json").write_text(json.dumps({
            "source_item": book,
            "pipeline_version": git_rev(REPO),
            "label_origin": "align",
            "split": args.split,
            "page": pg.page,
            "corpus": str(Path(args.corpus).as_posix()),
            "columns": columns,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        (sample / "info.json").write_text(json.dumps({
            "id": sample.name, "placeholder": False,
            "source": f"open-guji-cv {book_dir.as_posix()}",
            "source_item": book,
            "description": f"{book} 第 {pg.page} 页逐列冻结候选 + 金标",
            "tags": ["align", "frozen-candidates", book],
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        written.append(sample.name)

    summary = {
        "samples": len(written),
        "columns": n_cols,
        "slots": n_slots,
        "slots_without_candidates": n_cand0,
        "gold_in_candidates": gold_in_cands,
        "gold_in_candidates_rate": round(gold_in_cands / n_slots, 4) if n_slots else 0,
        "baseline_top1": round(gold_is_top1 / n_slots, 4) if n_slots else 0,
        "baseline_top1_n": gold_is_top1,
        "headroom": round((gold_in_cands - gold_is_top1) / n_slots, 4) if n_slots else 0,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print("\n（headroom = 金标在候选里、但不是首选的比例 —— 重排能拿到的全部空间；"
          "\n  1 - gold_in_candidates_rate 是候选召回的天花板，重排碰不到。）")


if __name__ == "__main__":
    main()
