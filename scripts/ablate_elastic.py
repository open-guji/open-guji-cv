# -*- coding: utf-8 -*-
"""弹性判据的旋钮消融：在 triplets 上扫 block / local / max_shift / scales / tau。

    PYTHONPATH=. python scripts/ablate_elastic.py ../open-guji-dataset/glyph-match/triplets

## 看哪个数

三元组的口径是**排序**：同字必须比形近异字更匹配。但排序率本身不够用——
`nearmiss` 那一档现在排序全对，margin 却只有 control 的五分之一，闸开不下去
就是被它们顶着。所以真正要看的是 **margin**：

- `hard`：现在排反的，margin 是负的——要它往上走；
- `nearmiss`：排对但贴着，要它**变厚**；
- `control`：良例，**不得回退**。

一个旋钮如果只把 hard 的 margin 拉上来、却把 control 的压薄了，那是把两个
分布一起抬，净收益是零甚至负——上一轮①（位移场平滑约束）就是这么空的。
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from open_guji_cv.clustering.exclusions import excluded_ids  # noqa: E402
from open_guji_cv.clustering.normalize import normalize_patch  # noqa: E402
from open_guji_cv.clustering.verify import verify_pair_elastic  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--grid", default="block,local,shift,tau",
                    help="扫哪几组：block/local/shift/scales/tau，逗号分隔")
    a = ap.parse_args()

    ds = Path(a.dataset)
    tri = json.loads((ds / "expected.json").read_text(encoding="utf-8"))
    ex = excluded_ids()
    tri = [t for t in tri if not ({t["anchor"], t["same"], t["other"]} & ex)]

    cache: dict[str, np.ndarray] = {}
    def norm(iid: str) -> np.ndarray:
        if iid not in cache:
            f = ds / "patches" / (iid.replace(":", "_") + ".png")
            cache[iid] = normalize_patch(cv2.imread(str(f), cv2.IMREAD_GRAYSCALE))
        return cache[iid]

    for t in tri:
        for k in ("anchor", "same", "other"):
            norm(t[k])
    print(f"三元组 {len(tri)} 组（排除名单已剔）")

    grids = {
        "block": [{"block": b} for b in (8, 16, 32)],
        "local": [{"local": l} for l in (1, 2, 3)],
        "shift": [{"max_shift": s} for s in (2, 3, 5)],
        "scales": [{"scales": s} for s in ((1.0,), (0.95, 1.0, 1.05),
                                           (0.92, 0.96, 1.0, 1.04, 1.08))],
        "tau": [{"tau": x} for x in (1.0, 1.5, 2.0)],
    }
    want = [g for g in a.grid.split(",") if g in grids]

    def run(kw: dict) -> dict:
        acc = defaultdict(lambda: {"n": 0, "ok": 0, "m": []})
        for t in tri:
            cs = verify_pair_elastic(norm(t["anchor"]), norm(t["same"]), **kw).f1
            co = verify_pair_elastic(norm(t["anchor"]), norm(t["other"]), **kw).f1
            s = acc[t["subset"]]
            s["n"] += 1
            s["ok"] += cs > co
            s["m"].append(cs - co)
        return {k: {"n": v["n"], "acc": round(v["ok"] / v["n"], 3),
                    "margin": round(float(np.mean(v["m"])), 4)}
                for k, v in sorted(acc.items())}

    base = run({})
    subs = list(base)
    head = "".join(f"{s + ' acc':>13}{s + ' mgn':>13}" for s in subs)
    print(f"\n{'设置':<28}{head}")

    def show(name: str, r: dict) -> None:
        row = "".join(f"{r[s]['acc']:>13}{r[s]['margin']:>13}" for s in subs)
        print(f"{name:<28}{row}")

    show("默认（block16 local1 s3）", base)
    for g in want:
        for kw in grids[g]:
            k, v = next(iter(kw.items()))
            if run.__doc__ is None and False:
                pass
            show(f"{k}={v}", run(kw))


if __name__ == "__main__":
    main()
