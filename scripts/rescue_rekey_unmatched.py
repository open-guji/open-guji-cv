# -*- coding: utf-8 -*-
"""重键映射的第二遍：拿弹性判据把「配不上」的那批捞回来（带就近约束）。

    PYTHONPATH=. python scripts/rescue_rekey_unmatched.py [--apply]

第一遍用归一化 IoU + 匈牙利指派，阈值 0.55。剩下配不上的 459 条里，多数并不是
「这一格没了」，而是重切把裁切松紧改了、IoU 掉到 0.2~0.5——用 `verify_pair_elastic`
（本来就是为「同字不同裁切」设计的判据）再看一眼，能捞回大半。

**但光看内容不够。** 实测里有 `vol01:13:8:18 → vol01:13:9:10` 这种 cov 0.942 的
配对：跨了一列、格号差 8，两块图确实像——因为**同一页上同一个字出现了两次**。
内容判据回答的是「是不是同一个字」，不是「是不是同一个格位」。所以救援必须
再加一条**就近约束**：同列、格号差 ≤2。两个信号都点头才算。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402

from open_guji_cv.clustering.normalize import normalize_patch  # noqa: E402
from open_guji_cv.clustering.verify import verify_pair_elastic  # noqa: E402

MIN_COV = 0.90
MAX_DIDX = 2


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default="config/rekey_502fa04d0c_to_current.json")
    ap.add_argument("--old-root", default="/tmp/guji-output-502fa04d0c/output")
    ap.add_argument("--new-root", default="output")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    doc = json.loads(Path(a.map).read_text(encoding="utf-8"))
    M = doc["map"]
    taken = {v["new_id"] for v in M.values() if v.get("new_id")}
    OLD, NEW = Path(a.old_root), Path(a.new_root)
    cache: dict = {}

    def page(root: Path, book: str, pg: str) -> dict:
        k = (str(root), book, pg)
        if k not in cache:
            out = {}
            for f in sorted((root / book / "phase4_chars" / "patches" / pg).glob("*.png")):
                c, i = f.stem.split("_")
                im = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
                if im is not None:
                    out[(int(c), int(i))] = normalize_patch(im)
            cache[k] = out
        return cache[k]

    un = [k for k, v in M.items() if v["status"] == "unmatched"]
    tally = Counter()
    for iid in un:
        b, pg, c, i = iid.split(":")
        c, i = int(c), int(i)
        o = page(OLD, b, pg).get((c, i))
        if o is None:
            tally["旧图缺失"] += 1
            continue
        best = (0.0, None)
        for (nc, ni), v in page(NEW, b, pg).items():
            if nc != c or abs(ni - i) > MAX_DIDX:      # 就近约束
                continue
            nid = f"{b}:{pg}:{nc}:{ni}"
            if nid in taken:
                continue
            cov = float(verify_pair_elastic(o, v).f1)
            if cov > best[0]:
                best = (cov, nid)
        if best[1] and best[0] >= MIN_COV:
            tally["救回"] += 1
            M[iid] = {"status": "moved", "new_id": best[1], "iou": None,
                      "rescue_cov": round(best[0], 3)}
            taken.add(best[1])
        else:
            tally["仍配不上"] += 1

    doc["tally"] = dict(Counter(v["status"] for v in M.values()))
    doc["rescue"] = {"min_cov": MIN_COV, "max_didx": MAX_DIDX, **tally}
    print("　".join(f"{k} {v}" for k, v in tally.most_common()))
    print("  最终：" + "　".join(f"{k} {v}" for k, v in doc["tally"].items()))
    if a.apply:
        Path(a.map).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n",
                               encoding="utf-8")
        print(f"→ {a.map}")
    else:
        print("  试跑，没写。加 --apply 落盘。")


if __name__ == "__main__":
    main()
