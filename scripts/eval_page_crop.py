"""上游裁切吃掉最外列：列窗越出页图多少（char-segmentation/page-crop）。

「中间的文字被错误截断」这句话里，切分层修不了的那一半就在这儿：s3 把
页面裁窄了，最外一列的字**根本不在页图里**（vol01/18 col1 的墨一路顶到
页图右缘 x=1607、页宽 1608）。网格照书级列距把列窗算到 1629，越出页图
21px —— 越出多少，就是那一列被吃掉多少。

这个量**不需要人工标注**：越界是网格模型与页图尺寸的直接比较。金标只
记「当前哪些页越界、越了多少」，回归看的是别越界的页不许新越界、已越界
的页不许越得更多。

用法：PYTHONPATH=. python scripts/eval_page_crop.py <数据集目录> [--update]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

OVER_T = 8.0        # 越出页图这么多像素才算（<8px 是网格拟合的正常毛刺）


def scan(out_root: str = "output") -> dict[str, dict]:
    res: dict[str, dict] = {}
    for book_dir in sorted(Path(out_root).glob("vol*")):
        for gp in sorted((book_dir / "phase3_char_grid").glob("*_char_grid.json")):
            page = gp.stem.replace("_char_grid", "")
            grid = json.loads(gp.read_text(encoding="utf-8"))
            cols = [c for c in grid.get("columns") or []
                    if c.get("cell_left_x") is not None
                    and any(x.get("type") == "char" for x in c.get("cells", []))]
            width = (grid.get("image_size") or {}).get("width")
            if not cols or not width:
                continue
            over_l = max(0.0, -min(c["cell_left_x"] for c in cols))
            over_r = max(0.0, max(c["cell_right_x"] for c in cols) - width)
            if max(over_l, over_r) >= OVER_T:
                res[f"{book_dir.name}/{page}"] = {"left": round(over_l, 1),
                                                  "right": round(over_r, 1)}
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--out", default="output")
    ap.add_argument("--update", action="store_true",
                    help="把当前实测写回金标（只在确认是改进时用）")
    args = ap.parse_args()
    shard = Path(args.dataset) / "page-crop" / "expected.json"
    got = scan(args.out)
    if args.update or not shard.exists():
        shard.parent.mkdir(parents=True, exist_ok=True)
        shard.write_text(json.dumps({"over_threshold_px": OVER_T, "pages": got},
                                    ensure_ascii=False, indent=1),
                         encoding="utf-8")
        print(f"写入金标 {len(got)} 页 → {shard}")
        return
    gold = json.loads(shard.read_text(encoding="utf-8"))["pages"]
    new = sorted(set(got) - set(gold))
    gone = sorted(set(gold) - set(got))
    worse = [(k, gold[k], got[k]) for k in sorted(set(got) & set(gold))
             if max(got[k].values()) > max(gold[k].values()) + 0.5]
    print(f"越界页：金标 {len(gold)} → 实测 {len(got)}")
    for k in gone:
        print(f"  ✔ 修好 {k} （金标 {gold[k]}）")
    for k in new:
        print(f"  ✗ 新越界 {k} {got[k]}")
    for k, a, b in worse:
        print(f"  ✗ 越得更多 {k} {a} → {b}")
    ok = not new and not worse
    print("回归门：通过" if ok else "回归门：**失败**")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
