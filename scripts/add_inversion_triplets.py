# -*- coding: utf-8 -*-
"""把形近误判裁决台的人裁结果并进 glyph-match/triplets 的 hard 子集。

    PYTHONPATH=. python scripts/add_inversion_triplets.py

hard 子集的收录标准（triplets README）：**用户亲眼裁定「本例标签没错」**，
也就是判据确实排反了、不是金标的锅。裁决台的四个键正好对上：

    可入集 keep  → 收进 hard
    标注有误 bad → 不收（金标本身错了，那是标注层的账）
    异体字 var   → 不收（归 P0 异体字关系层）
    拿不准 idk   → 不收

三元组存**原始灰度 patch**，不存归一图——归一化本身是匹配算法的一部分，
冻结原图才能让归一化的改进也被量到（与 build_match_triplets_shard.py 同规矩）。

排除名单里的实例一律不收：那些图块已经不参与匹配了，收进来只会在评测时
被再筛掉一遍，白占分母。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from open_guji_cv.clustering.exclusions import excluded_ids  # noqa: E402

PIPE_REV = "502fa04d0c"


def gray_root() -> Path:
    root = Path(tempfile.gettempdir()) / f"guji-output-{PIPE_REV}"
    if not (root / ".complete").exists():
        root.mkdir(parents=True, exist_ok=True)
        paths = " ".join(f"output/{b}/phase4_chars" for b in ("vol01", "vol02"))
        subprocess.run(f"git -C {REPO} archive {PIPE_REV} {paths} | tar -x -C {root}",
                       shell=True, check=True)
        (root / ".complete").touch()
    return root / "output"


def patch_src(iid: str, root: Path) -> Path | None:
    b, p, c, i = iid.split(":")
    f = root / b / "phase4_chars" / "patches" / p / f"{c}_{i}.png"
    return f if f.exists() else None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", default="artifacts/match_inversion_verdicts.jsonl")
    ap.add_argument("--triplets", default="../open-guji-dataset/glyph-match/triplets")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    root = gray_root()
    ex = excluded_ids()
    tri = Path(args.triplets)
    data = json.loads((tri / "expected.json").read_text(encoding="utf-8"))
    have = {(e["anchor"], e["same"], e["other"]) for e in data}

    added, skip = [], Counter()
    for line in Path(args.verdicts).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r["verdict"] != "keep":
            skip[r["verdict"]] += 1
            continue
        trip = (r["anchor"], r["same"], r["other"])
        if trip in have:
            skip["已在集里"] += 1
            continue
        if any(x in ex for x in trip):
            skip["在排除名单里"] += 1
            continue
        if any(patch_src(x, root) is None for x in trip):
            skip["找不到原图"] += 1
            continue
        added.append({"subset": "hard", "anchor": r["anchor"], "same": r["same"],
                      "other": r["other"], "char": r["char"],
                      "other_char": r["other_char"],
                      "build_cov_same": r["cov_same"],
                      "build_cov_other": r["cov_other"],
                      "schema_version": 1, "label_origin": "human",
                      "seed": "inversion_review_r2"})
        have.add(trip)

    print(f"可入集 {len(added)} 条  跳过 {dict(skip)}")
    if args.dry_run:
        return
    pat = tri / "patches"
    pat.mkdir(exist_ok=True)
    n = 0
    for e in added:
        for x in (e["anchor"], e["same"], e["other"]):
            dst = pat / (x.replace(":", "_") + ".png")
            if not dst.exists():
                shutil.copyfile(patch_src(x, root), dst)
                n += 1
    data.extend(added)
    (tri / "expected.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"图块拷入 {n}；集内共 {len(data)} 条 "
          f"({dict(Counter(e['subset'] for e in data))})")


if __name__ == "__main__":
    main()
