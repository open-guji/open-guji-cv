"""切分层重建后的金标重键（(col,idx) 按格位面积重叠映射到新网格）。

切分算法改动会移动格键——网格修对时尤甚（2026-08-24 逐页格高 + s3 救援
重建轮：p13/14 全页行号位移、救援页整列插入使列号位移）。直接对比裸
指标会把「修对了」读成「崩了」；协议是按**几何对齐**重键：

  旧键 → 旧网格格位矩形（救援页先加裁切平移）→ 新网格里面积重叠最大
  的格位 → 新键。重叠 < MIN_OVERLAP 的条目标记 needs_review（格局重排，
  语义已不可迁移，留给人工重标轮）。

  条目里如果带 old_bbox/corrected_bbox（review_recrop 的人工重切金标，
  存的是旧页绝对像素坐标），--apply 时会用同一个 (dx,dy) 一并平移——
  这与 col/idx 重键是两件独立的事，只要 --shift 给了非零平移就会做，
  不受重叠置信度影响（2026-08-28 裁边失手修复专项加）。

用法（在 open-guji-cv 根目录）：
  PYTHONPATH=. python scripts/rekey_instances.py \
      --old-root output --new-root /home/user/rebuild_out \
      --dataset ../open-guji-dataset/char-segmentation/instances \
      [--shift vol02:12:148:0 ...]   # 救援页的 (dx,dy) 平移
      [--apply]                       # 不加只打报告
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

MIN_OVERLAP = 0.40


def load_cells(root: Path, book: str, page: str) -> dict:
    p = root / book / "phase3_char_grid" / f"{page}_char_grid.json"
    if not p.exists():
        return {}
    d = json.loads(p.read_text(encoding="utf-8"))
    out = {}
    for c in d.get("columns", []):
        lx = c.get("cell_left_x", c.get("left_x"))
        rx = c.get("cell_right_x", c.get("right_x"))
        if lx is None:
            continue
        for cell in c.get("cells", []):
            if "index" in cell:
                out[(c["index"], cell["index"])] = (
                    float(lx), float(cell["y_top"]),
                    float(rx), float(cell["y_bottom"]))
    return out


def overlap(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    area = max(1e-6, (a[2] - a[0]) * (a[3] - a[1]))
    return ix * iy / area


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-root", default="output")
    ap.add_argument("--new-root", required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--shift", action="append", default=[],
                    help="book:page:dx:dy 旧页坐标 → 新页坐标的平移")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    shifts = {}
    for s in args.shift:
        book, page, dx, dy = s.split(":")
        shifts[(book, page)] = (float(dx), float(dy))

    old_root, new_root = Path(args.old_root), Path(args.new_root)
    ds = Path(args.dataset)
    cache_old: dict = {}
    cache_new: dict = {}

    def rekey(e: dict) -> tuple:
        bp = (e["book"], str(e["page"]))
        if bp not in cache_old:
            cache_old[bp] = load_cells(old_root, *bp)
            cache_new[bp] = load_cells(new_root, *bp)
        old_rect = cache_old[bp].get((e["col"], e["idx"]))
        if old_rect is None or not cache_new[bp]:
            return None, 0.0
        dx, dy = shifts.get(bp, (0.0, 0.0))
        rect = (old_rect[0] + dx, old_rect[1] + dy,
                old_rect[2] + dx, old_rect[3] + dy)
        best, bov = None, 0.0
        for key, nrect in cache_new[bp].items():
            ov = overlap(rect, nrect)
            if ov > bov:
                bov, best = ov, key
        return best, bov

    # 除了 col/idx 这个键本身，条目里还可能存着**旧页绝对像素坐标**
    # （corrected_bbox/old_bbox）——键重叠再准，坐标值不跟着平移，
    # eval_recrop.py 照样拿旧坐标去切新图，量错地方。同一个 (dx,dy)
    # 直接套在这些坐标字段上即可：两张图是同一次扫描按不同裁剪边界
    # 切出来的，裁剪偏移就是坐标系之间唯一的差。
    BBOX_FIELDS = ("old_bbox", "corrected_bbox")

    def shift_bbox_fields(e: dict) -> bool:
        bp = (e["book"], str(e["page"]))
        dx, dy = shifts.get(bp, (0.0, 0.0))
        if dx == 0.0 and dy == 0.0:
            return False
        moved = False
        for field in BBOX_FIELDS:
            v = e.get(field)
            if not v or len(v) != 4:
                continue
            e[field] = [v[0] + dx, v[1] + dy, v[2] + dx, v[3] + dy]
            moved = True
        return moved

    for fname in ("expected.json", "self_assess_r1.json"):
        fp = ds / fname
        if not fp.exists():
            continue
        entries = json.loads(fp.read_text(encoding="utf-8"))
        n_same = n_moved = n_review = n_nogrid = n_bbox = 0
        for e in entries:
            # 坐标平移与 col/idx 重键是两件独立的事——旧坐标只要 (dx,dy)
            # 非零就该平移，跟这条格位的重叠匹配置不置信无关
            if args.apply and shift_bbox_fields(e):
                n_bbox += 1
            best, ov = rekey(e)
            if best is None:
                n_nogrid += 1
                continue
            if ov < MIN_OVERLAP:
                n_review += 1
                e["needs_review"] = "rekey_low_overlap"
                continue
            if (e["col"], e["idx"]) != best:
                n_moved += 1
                if args.apply:
                    e["col"], e["idx"] = best
            else:
                n_same += 1
        print(f"{fname}: 不动 {n_same}，移键 {n_moved}，"
              f"重叠<{MIN_OVERLAP} 标 needs_review {n_review}，"
              f"无旧格位 {n_nogrid}，坐标字段平移 {n_bbox}")
        if args.apply:
            fp.write_text(json.dumps(entries, ensure_ascii=False, indent=1),
                          encoding="utf-8")
            print(f"  已写回 {fp}")


if __name__ == "__main__":
    main()
