# -*- coding: utf-8 -*-
"""按人裁结果重冻 char-normalization 的 golden。

    PYTHONPATH=. python scripts/refreeze_norm_goldens.py --verdicts <裁决 json>

char-normalization 那层按规矩是**人工目视门**（README：「输出本身就错的
绝不冻成 golden」），所以改了 `normalize_patch` 不能直接把新输出盖上去——
得先出[复核台](https://claude.ai/code/artifact/cd2fee67-fb9d-4519-870a-41413b9c87d3)
让人过目，过了目的才重冻。

裁决 JSON 形如 `{"可以": ["001", ...], "有问题": [...], "待定": [...]}`：

- **可以** → 用当前 `normalize_patch` 的输出重冻 golden；
- **有问题** → 不动，并把样本置 `known_defect`（新输出本身就是错的）；
- **待定** → 不动，置 `status: pending_review` 并记下待定原因，
  下一轮复核台再问。**待定的样本仍按旧 golden 走回归**——它们的旧 golden
  还在，容差还在，只是不承认新输出是对的。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402

from open_guji_cv.clustering.normalize import normalize_patch  # noqa: E402
from open_guji_cv.clustering.normalize_eval import (  # noqa: E402
    binary_iou, pixel_diff_ratio, skeleton_nodes, to_binary)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="../open-guji-dataset/char-normalization")
    ap.add_argument("--verdicts", required=True)
    ap.add_argument("--note", default="", help="待定原因，写进 expected.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    v = json.loads(Path(args.verdicts).read_text(encoding="utf-8"))
    ok, bad, pend = set(v.get("可以", [])), set(v.get("有问题", [])), set(v.get("待定", []))
    root = Path(args.dataset) / "samples"
    n_re = n_same = 0
    for d in sorted(p for p in root.iterdir() if (p / "expected.json").exists()):
        spec = json.loads((d / "expected.json").read_text(encoding="utf-8"))
        gray = cv2.imread(str(d / spec["input"]), cv2.IMREAD_GRAYSCALE)
        new = normalize_patch(gray)
        gold = to_binary(cv2.imread(str(d / spec["golden"]), cv2.IMREAD_GRAYSCALE))
        changed = bool((gold != new).sum())
        if d.name in ok:
            if changed:
                n_re += 1
                if not args.dry_run:
                    cv2.imwrite(str(d / spec["golden"]), new * 255)
                    spec["golden_frozen_at"] = "2026-08-25"
                    spec.pop("pending_reason", None)
                    if spec.get("status") == "pending_review":
                        spec["status"] = "verified"
            else:
                n_same += 1
        elif d.name in bad:
            spec["status"] = "known_defect"
            spec["defect"] = (spec.get("defect") or "") + "｜人裁：新输出本身就错"
        elif d.name in pend:
            spec["status"] = "pending_review"
            if args.note:
                spec["pending_reason"] = args.note
        if not args.dry_run:
            (d / "expected.json").write_text(
                json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  {d.name} {'重冻' if (d.name in ok and changed) else ''}"
              f"{'待定' if d.name in pend else ''}"
              f"{'' if changed else '（输出未变）'}")
    print(f"\n可以 {len(ok)}（其中输出变了、已重冻 {n_re}；未变 {n_same}）"
          f"  有问题 {len(bad)}  待定 {len(pend)}")

    # 重冻之后全集必须过回归门
    fail = []
    for d in sorted(p for p in root.iterdir() if (p / "expected.json").exists()):
        spec = json.loads((d / "expected.json").read_text(encoding="utf-8"))
        gray = cv2.imread(str(d / spec["input"]), cv2.IMREAD_GRAYSCALE)
        gold = to_binary(cv2.imread(str(d / spec["golden"]), cv2.IMREAD_GRAYSCALE))
        new = normalize_patch(gray)
        t = spec["tolerance"]
        ge, _ = skeleton_nodes(gold)
        ne, _ = skeleton_nodes(new)
        if not (pixel_diff_ratio(gold, new) <= t["pixel_diff_ratio"]
                and binary_iou(gold, new) >= t["binary_iou_min"]
                and abs(ne - ge) <= t["skeleton_endpoint_delta_max"]):
            fail.append(d.name)
    print(f"回归门：{len(fail)} 张出容差 {fail if fail else ''}")


if __name__ == "__main__":
    main()
