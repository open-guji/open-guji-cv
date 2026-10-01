"""评测侧边界行残余剥离（char-segmentation/side-rule）。

三个指标：
  残余率   带界行残余的样本里，图块中仍有「出文字带的细高连通体」的比例 → 目标 0
  误剥率   带内竖笔（忄/阝/川/而 的边竖）被剥掉墨的样本比例             → 红线 0
  字保全   全体样本里，字身（最大连通体）墨量 ≥ 金标基线的比例          → 红线 100%

用法：PYTHONPATH=. python scripts/eval_side_rule.py <数据集目录> [--source v2|v1]

## 2026-09-30（M1·A 道）：默认改读现行 v2 链

`--source v1`（旧）读 `output/<册>/phase3_char_grid` + `phase4_chars`（退役链；不存在会 FileNotFoundError
或全部「缺」）。`--source v2`（默认）读 `products/<册>/cell_shrink` + `cache/<册>/char_patch`，文字带
取 Step3 的 `content_x`（`row_segment` 产物），且**每条金标先过「人当时看的图块还在不在」闸**
（`patch_identity.locate`，见该文件文档；没存图块的不计分）。三个指标定义不变。
注意 side-rule 的金标本身是按**当时产物**算法挖出来的（正样本=图块里有出带细高连通体），
不是逐格人裁——所以图块没存下来的条目没有任何「人看过」的证据，一律不迁。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2

from scripts.build_side_rule_shard import side_candidates


def main_v2(rows: list[dict]) -> None:
    import collections
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import open_guji_cv.products.kinds  # noqa: F401
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.products.store import ProductStore
    from patch_identity import locate
    st = ProductStore()
    reasons = collections.Counter()
    n_pos = res = n_neg = strip_err = keep = scored = 0
    bad, skipped = [], []
    for e in rows:
        loc = locate(e)
        tag = f'{e["book"]}/{e["page"]}:{e["col"]}:{e["idx"]}'
        if loc["status"] != "scored":
            reasons[loc["status"]] += 1
            skipped.append((tag, loc["status"], loc["why"]))
            continue
        pc = st.read(e["book"], "row_segment", page_key(int(e["page"])), "cells")
        cc = None if pc is None else next((c for c in pc.columns if c.col == int(e["col"])), None)
        if cc is None or not cc.content_x:
            reasons["v2_missing"] += 1
            skipped.append((tag, "v2_missing", "row_segment 无此列 content_x"))
            continue
        scored += 1
        main_ink, cands = side_candidates(loc["patch"], float(loc["rec"].bbox_col[0]),
                                          float(cc.content_x[0]), float(cc.content_x[1]))
        if main_ink >= e["main_ink"]:
            keep += 1
        else:
            bad.append(f"字身少墨 {tag} {main_ink}<{e['main_ink']}（NCC {loc['ident']['ncc']}）")
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
    print(f"样本 {len(rows)}（[v2 链] 图像同一性通过并计分 {scored}；不计分 {len(skipped)}："
          f"{'、'.join(f'{k} {v}' for k, v in sorted(reasons.items())) or '—'}）")
    print(f"残余率  {res}/{n_pos}" + (f" = {res / n_pos:.1%}" if n_pos else "（计分样本里没有正样本）"))
    print(f"误剥率  {strip_err}/{n_neg}" + (f" = {strip_err / n_neg:.1%}" if n_neg else ""))
    print(f"字保全  {keep}/{scored}")
    for b in bad[:25]:
        print("  ", b)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--out", default="output")
    ap.add_argument("--source", choices=("v2", "v1"), default="v2")
    args = ap.parse_args()
    rows = json.loads(
        (Path(args.dataset) / "side-rule" / "expected.json")
        .read_text(encoding="utf-8"))
    if args.source == "v2":
        return main_v2([e for e in rows if not e.get("retired")])
    # 退役样本不计分：`retired` 字段里写着为什么这条不再对应任何图块
    # （多半是所在列被重切、基线无法核对）。留在文件里是为了留档，
    # 不是为了每轮都失败一次。
    rows = [e for e in rows if not e.get("retired")]

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
