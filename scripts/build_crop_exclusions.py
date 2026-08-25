# -*- coding: utf-8 -*-
"""生成图块排除名单 config/crop_exclusions.jsonl。

    PYTHONPATH=. python scripts/build_crop_exclusions.py

口径（2026-08-25 用户定，保守）：**现在的图质量低、后面会重扫，所以有问题的
一律尽量移出**。两个来源合起来：

  human  出库裁决台上人裁「出库」或「进测试集」的（实锤，39 条）
  gate   现行 `crop_quality` 旗标命中的（图块池 + 已进库实例）

gate 那批按出库裁决标定只有约 **26.5%** 是真有问题——也就是说照这个口径
排除，四条里有三条其实是好的。这是**故意付的代价**：现阶段留着一条坏图
的害处（错标进库、沿簇扩散）远大于少一条好图，何况重扫之后能按名单一条条
拿回来复核。名单里 `origin` 分得很清楚，将来复核先复核 gate 那批。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402

from open_guji_cv.clustering.crop_quality import assess_crop, detect_intrusion  # noqa: E402

PIPE_REV = "502fa04d0c"
DATE = "2026-08-25"
ROUND = "r1"


def gray_root() -> Path:
    root = Path(tempfile.gettempdir()) / f"guji-output-{PIPE_REV}"
    if not (root / ".complete").exists():
        root.mkdir(parents=True, exist_ok=True)
        paths = " ".join(f"output/{b}/phase4_chars" for b in ("vol01", "vol02"))
        subprocess.run(f"git -C {REPO} archive {PIPE_REV} {paths} | tar -x -C {root}",
                       shell=True, check=True)
        (root / ".complete").touch()
    return root / "output"


def flags_of(iid: str, root: Path) -> list[str] | None:
    b, p, c, i = iid.split(":")
    f = root / b / "phase4_chars" / "patches" / p / f"{c}_{i}.png"
    if not f.exists():
        return None
    im = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
    if im is None:
        return None
    q = assess_crop(im)
    fl = set(detect_intrusion(im))
    if q.truncated:
        fl.add("truncated")
    if q.residue:
        fl.add("residue")
    return sorted(fl)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verdicts", default="artifacts/glyph_evict_verdicts.jsonl")
    ap.add_argument("--pairs", default="../open-guji-dataset/glyph-match/pairs")
    ap.add_argument("--db", default="output/glyph.db")
    ap.add_argument("--out", default="config/crop_exclusions.jsonl")
    args = ap.parse_args()

    root = gray_root()
    rec: dict[str, dict] = {}

    def put(iid, origin, evidence, note):
        old = rec.get(iid)
        if old and old["origin"] == "human":      # 人裁优先，不被 gate 覆盖
            return
        rec[iid] = {"instance_id": iid, "reason": "crop_defect", "origin": origin,
                    "evidence": evidence, "round": ROUND, "date": DATE, "note": note}

    # ① 人裁实锤
    for line in Path(args.verdicts).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r["verdict"] in ("out", "test"):
            put(r["instance_id"], "human",
                flags_of(r["instance_id"], root) or [],
                f"出库裁决台 {ROUND}：{r['verdict']}")

    # ② 图块池里被旗标的
    ids = {r["instance_id"] for r in
           json.loads((Path(args.pairs) / "expected.json").read_text(encoding="utf-8"))["instances"]}
    # ③ 已进库的实例
    if Path(args.db).exists():
        ids |= {r[0] for r in sqlite3.connect(args.db).execute(
            "select instance_id from instances")}
    for k, iid in enumerate(sorted(ids)):
        if iid in rec:
            continue
        fl = flags_of(iid, root)
        if fl:
            put(iid, "gate", fl, "crop_quality 旗标命中")
        if k % 2000 == 0:
            print(f"  扫 {k}/{len(ids)}", flush=True)

    out = Path(args.out)
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(json.dumps(rec[k], ensure_ascii=False, sort_keys=True)
                             for k in sorted(rec)) + "\n", encoding="utf-8")
    print(f"\n排除名单 {len(rec)} 条 → {out}")
    print("  按来源:", dict(Counter(v["origin"] for v in rec.values())))
    print("  按证据:", dict(Counter(f for v in rec.values() for f in v["evidence"])))


if __name__ == "__main__":
    main()
