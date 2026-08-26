"""夹注段端收编回归（char-segmentation/jiazhu-tail）。

三分类：tail_a（奇数字末行单字，只发 a 半）/ row（漏拆末行，拆 a/b）/
reject（正文，不收）。判据与教训见分片 README。

现场重跑 extract_page 取判定（不读产物——replay 会把金标贴回产物，
读产物就是自考，recrop 那条闸栽过）。

回归口径（非对称）：
  - tail_a/row → reject 是**丢字**，零容忍；
  - reject → tail_a/row 是**吞正文**，零容忍；
  - tail_a ↔ row 之间的迁移打印出来人工过目（两边都保住了字，
    只是拆法不同）。

用法：PYTHONPATH=. python scripts/eval_jiazhu_tail.py <数据集目录>
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--out", default="output")
    args = ap.parse_args()
    gold = json.loads((Path(args.dataset) / "jiazhu-tail" / "expected.json")
                      .read_text(encoding="utf-8"))

    import cv2
    from open_guji_cv.clustering.extractor import CharExtractor

    ex = CharExtractor()
    pages = sorted({(e["book"], e["page"]) for e in gold})
    got: dict[tuple, str] = {}
    for book, page in pages:
        gp = (Path(args.out) / book / "phase3_char_grid"
              / f"{page}_char_grid.json")
        img = cv2.imread(f"{args.out}/{book}/{page}.png")
        if img is None or not gp.exists():
            continue
        grid = json.loads(gp.read_text(encoding="utf-8"))
        subs: dict[tuple, set] = {}
        for inst, _p in ex.extract_page(img, grid, book, page):
            subs.setdefault((inst.col, inst.idx), set()).add(inst.sub or "")
        for e in gold:
            if (e["book"], e["page"]) != (book, page):
                continue
            ss = subs.get((e["col"], e["idx"]), set())
            if "a" in ss and "b" in ss:
                got[(book, page, e["col"], e["idx"])] = "row"
            elif "a" in ss:
                got[(book, page, e["col"], e["idx"])] = "tail_a"
            else:
                got[(book, page, e["col"], e["idx"])] = "reject"

    n_lost = n_swallow = n_shift = miss = 0
    for e in gold:
        k = (e["book"], e["page"], e["col"], e["idx"])
        g = got.get(k)
        tag = f'{e["book"]}/{e["page"]}:{e["col"]}:{e["idx"]}'
        if g is None:
            miss += 1
            print(f"  ? 格位消失 {tag}（重切漂移，需重键）")
            continue
        if g == e["expect"]:
            continue
        if e["expect"] in ("tail_a", "row") and g == "reject":
            n_lost += 1
            print(f"  ✗ 丢字 {tag}：{e['expect']} → reject")
        elif e["expect"] == "reject":
            n_swallow += 1
            print(f"  ✗ 吞正文 {tag}：reject → {g}")
        else:
            n_shift += 1
            print(f"  ~ 拆法迁移 {tag}：{e['expect']} → {g}（人工过目）")
    dist = Counter(got.values())
    print(f"\njiazhu-tail {len(gold)} 条：实测 {dict(dist)}；"
          f"丢字 {n_lost}，吞正文 {n_swallow}，拆法迁移 {n_shift}，消失 {miss}")
    ok = n_lost == 0 and n_swallow == 0
    print("回归门：通过" if ok else "回归门：**失败**")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
