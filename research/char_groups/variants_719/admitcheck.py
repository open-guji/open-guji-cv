"""已放行格按同义组判法重判（GUJI-719，2026-10-25）：产物里放行字在组里的格（人裁、印章通道除外），用该组在线判法判字块，列与放行字不同的格。

用法：python admitcheck.py <原图根（<册>/<页>.png）> <产物根（<册>/seed_admit、cell_shrink）> <输出 json> --groups jiao,lv,…
字块按 cell_shrink 的 bbox_page 从原图裁（`core.anchor.crop_patch`）。只列，不改；改字随成批上线「推」。
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

import cv2

from open_guji_cv.core.anchor import crop_patch
from open_guji_cv.groups import ids_online as O, registry as R


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("imgs", type=Path)
    ap.add_argument("prod", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--groups", required=True)
    a = ap.parse_args()
    groups = a.groups.split(",")
    ch2g = {ch: g for g in groups for ch in R.FLOW_GROUPS[g].members}
    st, rows = Counter(), []
    for vd in sorted(a.prod.glob("vol*")):
        for f in sorted((vd / "seed_admit").glob("p*.json")):
            want = [r for col in json.load(open(f, encoding="utf-8"))["seed_admit"]["columns"] for r in col["chars"]
                    if r.get("admit") and r.get("char") in ch2g and r.get("channel") not in ("human", "seal")]
            if not want:
                continue
            sh = vd / "cell_shrink" / f.name
            img = cv2.imread(str(a.imgs / vd.name / f"{int(f.stem[1:])}.png"), cv2.IMREAD_GRAYSCALE)
            if not sh.exists() or img is None:
                continue
            box = {c["id"]: c["bbox_page"] for col in json.load(open(sh, encoding="utf-8"))["char_index"]["columns"] for c in col["chars"]}
            for r in want:
                g = ch2g[r["char"]]
                if r["id"] not in box:
                    st[(g, "nocrop")] += 1
                    continue
                v = O.judge(g, crop_patch(img, tuple(box[r["id"]])))
                k = "abstain" if not v.char else ("same" if v.char == r["char"] else "diff")
                st[(g, k)] += 1
                if k == "diff":
                    rows.append({"id": r["id"], "label": r["char"], "channel": r.get("channel"), "group": g, "judge": v.char, "conf": v.conf})
    a.out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    for k in sorted(st):
        print(k, st[k])


if __name__ == "__main__":
    main()
