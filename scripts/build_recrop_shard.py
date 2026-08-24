"""把审查页的人工重切回流成 char-segmentation/instances 的切分金标。

    PYTHONPATH=. python scripts/build_recrop_shard.py output/vol01 \
        --dataset ../open-guji-dataset [--base HEAD]

## 这批样本是什么

用户在进库审查页上对切错位的图块亲手拖框重切（GUJI-SEED-EVENT 的
recrop 事件，纯几何、不定字）。每条重切都是一对金标：

- **旧框**（--base 版式下 index.jsonl 里的 bbox + 旧图块）= 切分的
  实际输出，坏例；
- **新框**（用户拖的 corrected_bbox）= 该字位的正确外接框，金标。

首批 9 条（14/15 页）的模式统计见
`.claude/doc/segmentation_border_feedback.md`：列尾格框整体偏高
35~55px（grid_shift）、最左列吃进断续内边框、最右列同理。

## 溯源纪律

`seed="review_recrop"`，与 hist_contaminated / random_rigid /
review_label_only / review_not_a_char 并列。本分片同样是**定向富集**
（只有切错的才会被重切），不能读作全书切分错误率。

旧图块从 git（--base，缺省 HEAD）取——apply_recrop 已经把工作区的
patch 文件覆盖成新框了，坏例原件只在版本库里。
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# 判定阈（px）：框整体位移超此算 grid_shift；单边收缩超此算边框混入
SHIFT_T = 15.0
TRIM_T = 8.0


def classify(old: list, new: list, is_head: bool, is_tail: bool,
             is_leftcol: bool, is_rightcol: bool) -> tuple[str, str]:
    """旧框→新框的几何差 → (quality, defect)。

    - 框整体竖移（列尾实测 35~55px）：本字的墨被切掉一截，还吃进
      邻格/版框 → truncated + grid_shift；
    - 单边向内收：收掉的是版面线的墨 → contaminated，defect 按
      位置定（最左/最右列=界行竖线 rule_bar，列首/列尾=横版框
      frame_bar）。
    """
    dx0, dy0 = new[0] - old[0], new[1] - old[1]
    dx1, dy1 = new[2] - old[2], new[3] - old[3]
    # 真平移 = 上下两边**同向**都动了（列尾实测 dy0+50~63 / dy1+29~37）；
    # 只动一边的是单边收缩（切掉混入的墨），不算平移
    if (min(abs(dy0), abs(dy1)) >= TRIM_T and dy0 * dy1 > 0
            and abs(dy0 + dy1) / 2 >= SHIFT_T):
        return "truncated", "grid_shift"
    if (dx0 >= TRIM_T or dx1 <= -TRIM_T) and (is_leftcol or is_rightcol):
        return "contaminated", "rule_bar"
    if (dy0 >= TRIM_T and is_head) or (dy1 <= -TRIM_T and is_tail):
        return "contaminated", "frame_bar"
    if dy0 >= TRIM_T or dy1 <= -TRIM_T:
        # 列中段的单边竖向收缩：切掉的是上/下邻字的残余
        return "contaminated", "neighbor_residue"
    if dx0 >= TRIM_T or dx1 <= -TRIM_T:
        return "contaminated", "rule_bar"
    return "contaminated", "misc_trim"


def main() -> None:
    ap = argparse.ArgumentParser(description="人工重切 → 切分金标分片")
    ap.add_argument("book_out_dir")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--base", default="HEAD",
                    help="旧框/旧图块所在的 git 版本（重切提交之前）")
    args = ap.parse_args()

    book_dir = Path(args.book_out_dir).resolve()
    book = book_dir.name
    root = book_dir / "phase4_chars"

    def git_show(rel: str, binary: bool = False) -> bytes | str | None:
        p = subprocess.run(["git", "show", f"{args.base}:{rel}"],
                           capture_output=True, cwd=REPO)
        if p.returncode != 0:
            return None
        return p.stdout if binary else p.stdout.decode("utf-8")

    idx_rel = (root / "index.jsonl").relative_to(REPO).as_posix()
    old_text = git_show(idx_rel)
    if old_text is None:
        raise SystemExit(f"git 里取不到旧 index：{args.base}:{idx_rel}")
    old = {d["id"]: d for d in map(json.loads,
                                   filter(str.strip, old_text.splitlines()))}
    new = {d["id"]: d for d in map(json.loads, filter(str.strip,
           (root / "index.jsonl").read_text(encoding="utf-8").splitlines()))}

    colmax: dict[tuple, int] = {}
    pagecols: dict[str, set] = defaultdict(set)
    for d in new.values():
        k = (d["page"], d["col"])
        colmax[k] = max(colmax.get(k, -1), d["idx"])
        pagecols[d["page"]].add(d["col"])

    dst = Path(args.dataset) / "char-segmentation" / "instances"
    exp_path = dst / "expected.json"
    expected = json.loads(exp_path.read_text(encoding="utf-8"))
    have = {(e["book"], e["page"], e["col"], e["idx"]) for e in expected
            if e.get("seed") == "review_recrop"}

    added = skipped = missing = 0
    for iid, d in sorted(new.items()):
        if "recropped" not in (d.get("flags") or []):
            continue
        od = old.get(iid)
        if od is None or list(od["bbox"]) == list(d["bbox"]):
            continue                      # base 里已是新框（重切早于 base）
        key = (book, d["page"], d["col"], d["idx"])
        if key in have:
            skipped += 1
            continue
        patch_rel = (root / od["patch_path"]).relative_to(REPO).as_posix()
        png = git_show(patch_rel, binary=True)
        if not png:
            missing += 1
            continue
        cols = sorted(pagecols[d["page"]])
        quality, defect = classify(
            od["bbox"], d["bbox"],
            is_head=(d["idx"] == 0),
            is_tail=(d["idx"] == colmax[(d["page"], d["col"])]),
            is_leftcol=(d["col"] == cols[-1]),      # 竖排右起，col 大=左
            is_rightcol=(d["col"] == cols[0]))
        name = f"{book}_{d['page']}_{d['col']}_{d['idx']}.png"
        (dst / "patches" / name).write_bytes(png)
        expected.append({
            "book": book, "page": d["page"], "col": d["col"], "idx": d["idx"],
            "quality": quality, "defect": defect,
            "old_bbox": [round(float(v), 1) for v in od["bbox"]],
            "corrected_bbox": [round(float(v), 1) for v in d["bbox"]],
            "layout": "unknown",
            "seed": "review_recrop", "label_origin": "human",
            "schema_version": 1,
        })
        have.add(key)
        added += 1

    expected.sort(key=lambda e: (e["book"], int(e["page"]), e["col"], e["idx"]))
    exp_path.write_text(json.dumps(expected, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(json.dumps({
        "added": added, "skipped_existing": skipped, "missing_patch": missing,
        "total": len(expected),
        "quality": dict(Counter(e["quality"] for e in expected)),
        "seed": dict(Counter(e.get("seed") for e in expected)),
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
