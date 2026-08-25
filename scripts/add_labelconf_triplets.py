# -*- coding: utf-8 -*-
"""把「疑似错标裁决台」裁出来的 67 条**确认没标错**收进 triplets。

    PYTHONPATH=. python scripts/add_labelconf_triplets.py --dump /tmp/pairs.npz [--apply]

## 为什么这 67 条比那 3 条错标更值钱

挖它们的判据是「一个实例反复只跟同一个字撞、纯度还极高」。人裁下来只有 3 条
真错标，其余 67 条**标的都没错**——也就是说：这些是**人确认过的、分数极高的
异字对**。而库匹配的覆盖率天花板恰恰就是异字对分数的上尾（硬约束
precision ≥ 0.999 逼着闸站在 0.9985）。所以这 67 条正是那条尾巴的**人工标定
样本**：算法能不能把它们压下去，直接决定闸能开多低。

每条摊成一个三元组：锚点 = 这个实例，同例 = 同字里跟它最像的那个，负例 =
它撞得最凶的那个异字刻例。按当前算法排得对不对分两档：

- `hard`：现在就排反了（cov(负例) ≥ cov(同例)）——当下的失败，是靶子；
- `nearmiss`：排序对，但负例分数照样在 0.97 以上——闸开不下去就是被这些顶着。
  它们**不得回退**：哪个改动把 nearmiss 排反了，那个改动是负收益。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import numpy as np  # noqa: E402

from open_guji_cv.clustering.exclusions import excluded_ids  # noqa: E402

PIPE_REV = "502fa04d0c"
ROUND = "label_suspect_review_r1"
SRC = "https://claude.ai/code/artifact/aa816ec8-3eca-4cb8-a889-87660e92d24a"


def gray_root() -> Path:
    root = Path(tempfile.gettempdir()) / f"guji-output-{PIPE_REV}"
    if not (root / ".complete").exists():
        root.mkdir(parents=True, exist_ok=True)
        paths = " ".join(f"output/{b}/phase4_chars" for b in ("vol01", "vol02"))
        subprocess.run(f"git -C {REPO} archive {PIPE_REV} {paths} | tar -x -C {root}",
                       shell=True, check=True)
        (root / ".complete").touch()
    return root / "output"


def patch_path(iid: str, out: Path) -> Path:
    b, p, c, i = iid.split(":")
    return out / b / "phase4_chars" / "patches" / p / f"{c}_{i}.png"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dump", required=True, help="pairs 全量 cov 转储（npz）")
    ap.add_argument("--dataset", default="../open-guji-dataset/glyph-match/triplets")
    ap.add_argument("--pairs", default="../open-guji-dataset/glyph-match/pairs")
    ap.add_argument("--verdicts", default="artifacts/label_suspect_verdicts.jsonl")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    ds, ps = Path(a.dataset), Path(a.pairs)
    meta = {r["instance_id"]: r
            for r in json.loads((ps / "expected.json").read_text(encoding="utf-8"))["instances"]}
    ex = excluded_ids()
    z = np.load(a.dump, allow_pickle=True)
    pairs, cov = list(z["pairs"]), z["cov"]

    verd = [json.loads(l) for l in Path(a.verdicts).read_text(encoding="utf-8").splitlines() if l.strip()]
    subj = {v["instance_id"]: v for v in verd if v["verdict"] == "ok"}

    # 同字最像的那个 / 撞得最凶的那个异字刻例
    best_same: dict[str, tuple[float, str]] = {}
    best_other: dict[str, tuple[float, str]] = {}
    for k, p in enumerate(pairs):
        for x, y in ((p["a"], p["b"]), (p["b"], p["a"])):
            if x not in subj or y in ex or y not in meta or x not in meta:
                continue
            c = float(cov[k])
            if meta[y]["char"] == meta[x]["char"]:
                if c > best_same.get(x, (0.0, ""))[0]:
                    best_same[x] = (c, y)
            elif meta[y]["char"] == subj[x]["rival"]:
                if c > best_other.get(x, (0.0, ""))[0]:
                    best_other[x] = (c, y)

    tri = json.loads((ds / "expected.json").read_text(encoding="utf-8"))
    have = {(t["anchor"], t["same"], t["other"]) for t in tri}
    out = Path(gray_root()) if a.apply else None
    add, skip = [], Counter()
    for iid, v in subj.items():
        if iid in ex or iid not in meta:
            skip["排除名单/已剔除"] += 1
            continue
        s, o = best_same.get(iid), best_other.get(iid)
        if not s or not o:
            skip["缺同字参照或缺对手"] += 1
            continue
        key = (iid, s[1], o[1])
        if key in have:
            skip["已在集内"] += 1
            continue
        add.append({
            "subset": "hard" if o[0] >= s[0] else "nearmiss",
            "anchor": iid, "same": s[1], "other": o[1],
            "char": meta[iid]["char"], "other_char": meta[o[1]]["char"],
            "build_cov_same": round(s[0], 4), "build_cov_other": round(o[0], 4),
            "schema_version": 1, "label_origin": "human", "seed": ROUND,
        })

    tally = Counter(t["subset"] for t in add)
    print(f"新增 {len(add)} 条（" + " / ".join(f"{k} {n}" for k, n in tally.items())
          + "）；跳过 " + " / ".join(f"{k} {n}" for k, n in skip.items()))
    if not a.apply:
        print("试跑，没写。加 --apply 落盘。")
        return

    for t in add:
        for iid in (t["anchor"], t["same"], t["other"]):
            src = patch_path(iid, out)
            dst = ds / "patches" / (iid.replace(":", "_") + ".png")
            if not dst.exists():
                shutil.copy(src, dst)

    tri.extend(add)
    (ds / "expected.json").write_text(
        json.dumps(tri, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    mp = ds / "metadata.json"
    m = json.loads(mp.read_text(encoding="utf-8"))
    m["total_samples"] = len(tri)
    m["subset_distribution"] = dict(Counter(t["subset"] for t in tri))
    m.setdefault("growth_history", []).append({
        "round": ROUND, "date": str(date.today()), "added": len(add),
        "subset": " / ".join(f"{k} {n}" for k, n in tally.items()), "source": SRC,
        "criterion": "「疑似错标裁决台」71 张人裁，67 张判「标的没错」——即"
                     "**人确认过的高分异字对**。每条摊成三元组：锚点=该实例，"
                     "同例=同字最像者，负例=撞得最凶的那个异字刻例。当前排反的"
                     "入 hard，排对但负例仍 ≥0.97 的入 nearmiss。",
        "effect": "nearmiss 是覆盖率天花板的人工标定样本：闸开不下去就是被它们"
                  "顶着，且**不得回退**——把 nearmiss 排反的改动是负收益。",
    })
    mp.write_text(json.dumps(m, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"→ triplets {len(tri)} 条 {m['subset_distribution']}")


if __name__ == "__main__":
    main()
