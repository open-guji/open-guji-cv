# -*- coding: utf-8 -*-
"""三元组集按**自带的图**重键到当前管线（不借外部映射表）。

    PYTHONPATH=. python scripts/rekey_triplets_by_patch.py [--apply]

## 为什么这一集不能用那张映射表

`config/rekey_502fa04d0c_to_current.json` 是「502fa04d0c → 当前」的表。
char-clustering / pairs 的 crop 与冻结版 phase4 逐像素一致（实测 IoU 1.000），
用那张表没问题。**三元组不是**：它的 `patches/vol01_17_6_5.png` 是「印」，而
502fa04d0c 同键的图块是「初」——这一集的图是从**另一个版本**的产物拷出来的
（分几轮加的，来源版本不一）。照那张表迁，就把 印 迁成了 初，control 子集
排序率从 1.000 掉到 0.873，7 条全是这么坏的。

教训写在这：**一个集是不是属于某个键空间，要用它自带的图去验，不能看它放在
哪个目录里。** 幸好这一集把图存在自己身上，所以能自救。

## 怎么重键

按页做匈牙利指派：这一页上三元组自带的图 × 当前管线这一页的所有图块，
用归一化后的 IoU 当代价；配上之后再用 `verify_pair_elastic` 复核，cov ≥ 0.95
才认。同一页上同一个字出现两次是常事，所以用全局指派而不是逐条取最像的。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from scipy.optimize import linear_sum_assignment  # noqa: E402

from open_guji_cv.clustering.normalize import normalize_patch  # noqa: E402
from open_guji_cv.clustering.verify import verify_pair_elastic  # noqa: E402

MIN_COV = 0.95
NEW_REV = "1158da9093"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="../open-guji-dataset/glyph-match/triplets")
    ap.add_argument("--new-root", default="output")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    ds, root = Path(a.dataset), Path(a.new_root)
    tri = json.loads((ds / "expected.json").read_text(encoding="utf-8"))
    ids = sorted({i for t in tri for i in (t["anchor"], t["same"], t["other"])})

    by_page: dict[tuple[str, str], list[str]] = defaultdict(list)
    for iid in ids:
        b, p, _, _ = iid.split(":")
        by_page[(b, p)].append(iid)

    new_of: dict[str, tuple[str, float]] = {}
    tally = Counter()
    for (book, page), page_ids in sorted(by_page.items()):
        mine = {}
        for iid in page_ids:
            f = ds / "patches" / f"{iid.replace(':', '_')}.png"
            im = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
            if im is not None:
                mine[iid] = normalize_patch(im)
        cur = {}
        for f in sorted((root / book / "phase4_chars" / "patches" / page).glob("*.png")):
            c, i = f.stem.split("_")
            im = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
            if im is not None:
                cur[f"{book}:{page}:{int(c)}:{int(i)}"] = normalize_patch(im)
        if not mine or not cur:
            tally["整页没图"] += len(page_ids)
            continue
        mk, ck = list(mine), list(cur)
        A = np.array([mine[k].astype(bool).ravel() for k in mk])
        B = np.array([cur[k].astype(bool).ravel() for k in ck])
        inter = A.astype(np.uint16) @ B.T.astype(np.uint16)
        union = A.sum(1)[:, None] + B.sum(1)[None, :] - inter
        iou = inter / np.maximum(union, 1)
        ri, ci = linear_sum_assignment(-iou)
        for i, j in zip(ri, ci):
            cov = float(verify_pair_elastic(mine[mk[i]], cur[ck[j]]).f1)
            if cov >= MIN_COV:
                new_of[mk[i]] = (ck[j], round(cov, 3))
                tally["配上" if ck[j] != mk[i] else "键没变"] += 1
            else:
                tally["配不上"] += 1

    keep, drop = [], 0
    for t in tri:
        ids3 = (t["anchor"], t["same"], t["other"])
        if not all(i in new_of for i in ids3):
            drop += 1
            continue
        t["rekey_history"] = t.get("rekey_history", []) + [{
            "from": list(ids3), "round": "rekey_triplets_by_patch_r1",
            "date": str(date.today()), "to_rev": NEW_REV,
            "method": "本集自带图 × 当前管线同页图块，匈牙利指派 + elastic cov ≥ 0.95"}]
        t["anchor"], t["same"], t["other"] = (new_of[i][0] for i in ids3)
        keep.append(t)

    print("　".join(f"{k} {v}" for k, v in tally.most_common()))
    print(f"三元组 {len(tri)} → {len(keep)}（剔 {drop}）　"
          + str(dict(Counter(t["subset"] for t in keep))))
    if not a.apply:
        print("  试跑，没写。加 --apply 落盘。")
        return

    pat = ds / "patches"
    tmp = ds / "_patches_new"
    tmp.mkdir(exist_ok=True)
    for t in keep:
        for iid in (t["anchor"], t["same"], t["other"]):
            dst = tmp / f"{iid.replace(':', '_')}.png"
            if not dst.exists():
                b, p, c, i = iid.split(":")
                shutil.copy(root / b / "phase4_chars" / "patches" / p / f"{c}_{i}.png", dst)
    shutil.rmtree(pat, ignore_errors=True)
    tmp.rename(pat)
    (ds / "expected.json").write_text(json.dumps(keep, ensure_ascii=False, indent=1) + "\n",
                                      encoding="utf-8")
    m = json.loads((ds / "metadata.json").read_text(encoding="utf-8"))
    m["total_samples"] = len(keep)
    m["subset_distribution"] = dict(Counter(t["subset"] for t in keep))
    m["rekey"] = {"round": "rekey_triplets_by_patch_r1", "date": str(date.today()),
                  "to": NEW_REV, "min_cov": MIN_COV,
                  "why": "本集的图来自与 502fa04d0c 不同的产物版本（同键 印 vs 初），"
                         "不能套 char-clustering 那张映射表；改用本集自带的图配对。"}
    (ds / "metadata.json").write_text(json.dumps(m, ensure_ascii=False, indent=1) + "\n",
                                      encoding="utf-8")
    print(f"→ {ds}")


if __name__ == "__main__":
    main()
