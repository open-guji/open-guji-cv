"""s3 裁边残留：裁剪之后图像四边还剩多少空白纸边（char-segmentation/crop-margin）。

「浓墨粘连」截断专题查出来的新根因：`content_bounds._find_h_frame` 找
版框外框线靠「这一行边缘密度 ≥20%」，边框磨损重的页（vol02/133、135、
107）密度从没到过这个门槛，函数退化成「没找到就当图像边缘是边框」，
于是那一侧完全不裁，残留几百像素的扫描空白纸边——不是切分层的问题，
是上游 s3 裁剪本身失手。

这条尺子**不需要人工标注**：残留是图像里客观可数的东西——裁剪之后，
从图像边缘向内数，墨密度一直低于阈值的连续行/列有多长。金标只记
「当前每一页残留多少」，回归看的是干净页不许变脏、脏页必须变干净。

用法：PYTHONPATH=. python scripts/eval_crop_margin.py <数据集目录> [--update]
      PYTHONPATH=. python scripts/eval_crop_margin.py <数据集目录> --intermediate-dir <s3_crop 所在目录>
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np

INK_ROW_RATIO = 0.005   # 该行/列墨像素占比超此才算「有墨」
FLAG_T = 50             # 残留超过这么多 px 才算裁边失手（干净页噪声 0~25px，留 2 倍余量）


def page_margins(img_path: Path) -> dict | None:
    im = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
    if im is None:
        return None
    h, w = im.shape
    b = (im < 128).astype(np.uint8)
    rows = b.sum(axis=1)
    cols = b.sum(axis=0)
    ink_rows = np.where(rows > INK_ROW_RATIO * w)[0]
    ink_cols = np.where(cols > INK_ROW_RATIO * h)[0]
    if len(ink_rows) == 0 or len(ink_cols) == 0:
        return None
    return {
        "w": int(w), "h": int(h),
        "top": int(ink_rows[0]), "bottom": int(h - 1 - ink_rows[-1]),
        "left": int(ink_cols[0]), "right": int(w - 1 - ink_cols[-1]),
    }


def scan(intermediate_dir: str) -> dict[str, dict]:
    """扫 <intermediate_dir>/vol*/s3_crop/*.{tif,png,jpg} 或已重建产物根目录 vol*/*.png。"""
    root = Path(intermediate_dir)
    res: dict[str, dict] = {}
    for book_dir in sorted(root.glob("vol*")):
        s3 = book_dir / "s3_crop"
        src = s3 if s3.is_dir() else book_dir
        for f in sorted(src.iterdir()):
            if f.suffix.lower() not in (".tif", ".tiff", ".png", ".jpg", ".jpeg"):
                continue
            m = page_margins(f)
            if m is None:
                continue
            res[f"{book_dir.name}/{f.stem}"] = m
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--intermediate-dir", default=None,
                    help="s3_crop 中间产物所在目录（含 vol01/s3_crop、vol02/s3_crop 子目录）")
    ap.add_argument("--update", action="store_true",
                    help="把当前实测写回金标（只在确认是改进时用）")
    args = ap.parse_args()
    shard = Path(args.dataset) / "crop-margin" / "expected.json"

    if args.intermediate_dir:
        got = scan(args.intermediate_dir)
    else:
        if not shard.exists():
            print("没给 --intermediate-dir，也没有既存金标，无法比较")
            return
        gold_doc = json.loads(shard.read_text(encoding="utf-8"))
        print(f"未指定 --intermediate-dir：仅回显既存金标（{len(gold_doc['pages'])} 页）")
        return

    if args.update or not shard.exists():
        shard.parent.mkdir(parents=True, exist_ok=True)
        shard.write_text(json.dumps({
            "flag_threshold_px": FLAG_T,
            "ink_row_ratio": INK_ROW_RATIO,
            "pipeline_version": "s3_crop@content_bounds",
            "label_origin": "align",
            "pages": got,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        n_flag = sum(1 for m in got.values()
                     if max(m["top"], m["bottom"], m["left"], m["right"]) >= FLAG_T)
        print(f"写入金标 {len(got)} 页 → {shard}（其中 {n_flag} 页残留 ≥{FLAG_T}px）")
        return

    gold = json.loads(shard.read_text(encoding="utf-8"))["pages"]
    keys = sorted(set(gold) & set(got))
    regressed = []
    fixed = []
    still_bad = []
    for k in keys:
        g, c = gold[k], got[k]
        g_max = max(g["top"], g["bottom"], g["left"], g["right"])
        c_max = max(c["top"], c["bottom"], c["left"], c["right"])
        g_bad = g_max >= FLAG_T
        c_bad = c_max >= FLAG_T
        if not g_bad and c_bad:
            regressed.append((k, g_max, c_max))
        elif g_bad and not c_bad:
            fixed.append((k, g_max, c_max))
        elif g_bad and c_bad:
            still_bad.append((k, g_max, c_max))
    print(f"对比页数 {len(keys)}（金标缺 {len(set(got) - set(gold))}，实测缺 {len(set(gold) - set(got))}）")
    print(f"修好 {len(fixed)}；仍未修 {len(still_bad)}；新退步 {len(regressed)}")
    for k, g, c in regressed:
        print(f"  ✗ 新退步 {k}: {g}px → {c}px")
    for k, g, c in fixed[:10]:
        print(f"  ✔ 修好 {k}: {g}px → {c}px")
    if regressed:
        print("回归门：失败")
    else:
        print("回归门：通过")


if __name__ == "__main__":
    main()
