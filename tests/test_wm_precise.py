"""精确线条替换 v2：分别用 closing 和 opening 检测黑线和白线。

- 黑线检测：closing(p90) - p90 > thresh （closing 填充暗特征）
- 白线检测：p90 - opening(p90) > thresh （opening 去除亮特征）
- 合并为精确掩码 → inpaint 只修复线条像素
"""

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from open_guji_cv.utils.image_io import imread, imwrite

OUT_DIR = Path("output/hanshu_yiwenzhi/_wl_test")
DATA_DIR = Path("data/hanshu_yiwenzhi")


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pages_raw = []
    for p in sorted(DATA_DIR.glob("page_*.png")):
        im = imread(str(p))
        if im is not None:
            pages_raw.append((p.stem, im))

    stack = np.array([img for _, img in pages_raw], dtype=np.float32)
    h, w = pages_raw[0][1].shape[:2]

    p90 = np.percentile(stack, 90, axis=0).astype(np.uint8)
    p90_gray = cv2.cvtColor(p90, cv2.COLOR_BGR2GRAY)

    # ── 检测黑线：closing - p90 ──
    # closing 填充比核小的暗特征 → 黑线处变亮
    k_morph = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    p90_closed = cv2.morphologyEx(p90_gray, cv2.MORPH_CLOSE, k_morph)
    black_tophat = p90_closed.astype(np.int16) - p90_gray.astype(np.int16)  # 黑线处 > 0

    # ── 检测白线：p90 - opening ──
    p90_opened = cv2.morphologyEx(p90_gray, cv2.MORPH_OPEN, k_morph)
    white_tophat = p90_gray.astype(np.int16) - p90_opened.astype(np.int16)  # 白线处 > 0

    imwrite(str(OUT_DIR / "40_black_tophat_3x.png"),
            np.clip(black_tophat * 3, 0, 255).astype(np.uint8))
    imwrite(str(OUT_DIR / "40_white_tophat_3x.png"),
            np.clip(white_tophat * 3, 0, 255).astype(np.uint8))

    for thresh in [3, 5, 8, 10, 15]:
        bm = (black_tophat > thresh).astype(np.uint8) * 255
        wm = (white_tophat > thresh).astype(np.uint8) * 255
        nb = cv2.countNonZero(bm)
        nw = cv2.countNonZero(wm)
        print(f"  thresh={thresh:2d}: black={nb:7d}({nb*100/(h*w):.1f}%) "
              f"white={nw:7d}({nw*100/(h*w):.1f}%)")

    # ── 用 thresh=8：只抓水印线条，排除文字残影 ──
    black_mask = (black_tophat > 8).astype(np.uint8) * 255
    white_mask = (white_tophat > 8).astype(np.uint8) * 255
    line_mask = cv2.bitwise_or(black_mask, white_mask)

    imwrite(str(OUT_DIR / "41_black_mask_t8.png"), black_mask)
    imwrite(str(OUT_DIR / "41_white_mask_t8.png"), white_mask)
    imwrite(str(OUT_DIR / "41_line_mask_t8.png"), line_mask)

    # 膨胀 1px 覆盖线条边缘
    line_mask_d = cv2.dilate(line_mask,
                              cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
                              iterations=1)

    rx1, ry1, rx2, ry2 = 1600, 700, 2500, 1700
    lx1, ly1, lx2, ly2 = 200, 700, 1100, 1700

    original = pages_raw[0][1]
    imwrite(str(OUT_DIR / "42_original_right.png"), original[ry1:ry2, rx1:rx2])
    imwrite(str(OUT_DIR / "42_original_left.png"), original[ly1:ly2, lx1:lx2])

    # ── inpaint 不同半径 ──
    for radius in [2, 3, 5]:
        result = cv2.inpaint(original, line_mask_d, radius, cv2.INPAINT_TELEA)
        imwrite(str(OUT_DIR / f"43_inpaint_r{radius}_right.png"),
                result[ry1:ry2, rx1:rx2])
        imwrite(str(OUT_DIR / f"43_inpaint_r{radius}_left.png"),
                result[ly1:ly2, lx1:lx2])

    # ── 不同阈值的掩码 ──
    for thresh in [5, 8, 10, 15]:
        bm = (black_tophat > thresh).astype(np.uint8) * 255
        wm = (white_tophat > thresh).astype(np.uint8) * 255
        mask = cv2.bitwise_or(bm, wm)
        mask = cv2.dilate(mask,
                           cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
                           iterations=1)
        result = cv2.inpaint(original, mask, 3, cv2.INPAINT_TELEA)
        imwrite(str(OUT_DIR / f"44_t{thresh}_right.png"), result[ry1:ry2, rx1:rx2])
        imwrite(str(OUT_DIR / f"44_t{thresh}_left.png"), result[ly1:ly2, lx1:lx2])

    # ── 全图 + 多页 ──
    for name, img in pages_raw[:5]:
        result = cv2.inpaint(img, line_mask_d, 3, cv2.INPAINT_TELEA)
        imwrite(str(OUT_DIR / f"45_{name}.png"), result)

    print(f"\n输出: {OUT_DIR}")


if __name__ == "__main__":
    main()
