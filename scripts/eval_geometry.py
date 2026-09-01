"""版面几何 benchmark：界行有没有被列框圈进去 + 形变矫正干净了没有。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2

from open_guji_cv.clustering.geometry_eval import evaluate, format_report
from open_guji_cv.clustering.page_geometry import PageGeometry


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--grid-root", default="output",
                    help="phase3_char_grid 所在根目录")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    pairs = []
    missing = 0
    for f in sorted(Path(args.dataset, "samples").glob("*.json")):
        g = PageGeometry.load(f)
        gp = Path(args.grid_root) / g.book / "phase3_char_grid" \
            / f"{g.page}_char_grid.json"
        if not gp.exists():
            missing += 1
            continue
        grid = json.loads(gp.read_text(encoding="utf-8"))
        cols = [(float(c["left_x"]), float(c["right_x"]))
                for c in grid.get("columns", []) if not c.get("skipped")]
        gray = cv2.imread(f"output/{g.book}/{g.page}.png",
                          cv2.IMREAD_GRAYSCALE)
        pairs.append((g, cols,
                      float(grid.get("grid", {}).get("shear", 0.0) or 0.0),
                      gray))
    if missing:
        print(f"（{missing} 页缺切分结果，跳过）")
    report = evaluate(pairs)
    print(format_report(report))
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
