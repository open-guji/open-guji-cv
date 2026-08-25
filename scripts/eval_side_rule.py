"""评测侧边界行残余剥离（char-segmentation/side-rule）。

三个指标：
  残余率   带界行残余的样本里，图块中仍有「出文字带的细高连通体」的比例 → 目标 0
  误剥率   带内竖笔（忄/阝/川/而 的边竖）被剥掉墨的样本比例             → 红线 0
  字保全   全体样本里，字身（最大连通体）墨量 ≥ 金标基线的比例          → 红线 100%

用法：PYTHONPATH=. python scripts/eval_side_rule.py <数据集目录>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2

from scripts.build_side_rule_shard import side_candidates


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--out", default="output")
    args = ap.parse_args()
    rows = json.loads(
        (Path(args.dataset) / "side-rule" / "expected.json")
        .read_text(encoding="utf-8"))

    bands: dict[tuple[str, str], dict] = {}
    index: dict[tuple[str, str], dict] = {}

    def load(book: str, page: str):
        k = (book, page)
        if k not in bands:
            gp = (Path(args.out) / book / "phase3_char_grid"
                  / f"{page}_char_grid.json")
            g = json.loads(gp.read_text(encoding="utf-8"))
            bands[k] = {int(c["index"]): (float(c["left_x"]),
                                          float(c["right_x"]))
                        for c in g.get("columns", [])}
        if book not in index:
            m = {}
            ip = Path(args.out) / book / "phase4_chars" / "index.jsonl"
            for line in ip.read_text(encoding="utf-8").splitlines():
                r = json.loads(line)
                if not r.get("sub"):
                    m[(r["page"], r["col"], r["idx"])] = r
            index[book] = m
        return bands[k], index[book]

    n_pos = res = n_neg = strip_err = keep = miss = 0
    bad = []
    for e in rows:
        band, idx = load(e["book"], e["page"])
        r = idx.get((e["page"], e["col"], e["idx"]))
        if r is None:
            miss += 1
            continue
        img = cv2.imread(str(Path(args.out) / e["book"] / "phase4_chars"
                             / r["patch_path"]), cv2.IMREAD_GRAYSCALE)
        if img is None:
            miss += 1
            continue
        tl, tr = band[e["col"]]
        main_ink, cands = side_candidates(img, float(r["bbox"][0]), tl, tr)
        tag = f'{e["book"]}/{e["page"]}:{e["col"]}:{e["idx"]}'
        if main_ink >= e["main_ink"]:
            keep += 1
        else:
            bad.append(f"字身少墨 {tag} {main_ink}<{e['main_ink']}")
        if e["side_rule"]:
            n_pos += 1
            if any(c["out"] for c in cands):
                res += 1
                bad.append(f"残余 {tag}")
        if e["keep_ink"]:
            n_neg += 1
            got = sum(c["area"] for c in cands if not c["out"])
            if got < e["keep_ink"]:
                strip_err += 1
                bad.append(f"误剥带内竖笔 {tag} {got}<{e['keep_ink']}")

    print(f"样本 {len(rows)}（缺 {miss}）")
    print(f"残余率  {res}/{n_pos}" + (f" = {res / n_pos:.1%}" if n_pos else ""))
    print(f"误剥率  {strip_err}/{n_neg}"
          + (f" = {strip_err / n_neg:.1%}" if n_neg else ""))
    print(f"字保全  {keep}/{len(rows) - miss}")
    for b in bad[:25]:
        print("  ", b)
    if len(bad) > 25:
        print(f"   …共 {len(bad)} 条")


if __name__ == "__main__":
    main()
