#!/usr/bin/env python3
"""vol03 p105（4198x5848 双联叶摞扫）→ 4 张半叶，**版心一切为二**（v2，2026-09-29，overview#266）。

v1（overview 项目进展/新书整理/书/四庫vol03/p105拆分成果/crop_recipe.py）的毛病：按窗口 x0=2225 / x1=1975
取墨迹外接框后四周各留 280px，只在横裁线（Y_SPLIT）那一侧卡死，**竖裁那一侧没卡**，280px 留白正好越过
整条版心（版心两侧线 x≈2005/2188），于是四张半叶**每张都带着一整条版心**（书名、魚尾、卷次、叶码、两侧线），
Step1 把它当成一列：版心进字位被识别，另一头真的一列正文被挤掉（105/106 丢页边列、107 两列并一列、108 版心
与正文并列被拒）。

v2：竖向也按版心中线卡死——X_SPLIT 取版心两侧线的中点（上块 2096、下块 2101，实测列墨峰），
右半叶留白不许越过 X_SPLIT 往左、左半叶不许越过往右。其余与 v1 相同（横裁 Y_SPLIT=2913、留白 280）。
用法：python3 crop_recipe_v2.py <原图路径> <输出目录>
"""
import sys
from PIL import Image
import numpy as np

def tight_crop(src, ink, x0, x1, y0, y1, margin=280, cap_top=None, cap_bot=None, cap_left=None, cap_right=None):
    W, H = src.size
    sub = ink[y0:y1, x0:x1]
    rows = np.where(sub.any(axis=1))[0]; cols = np.where(sub.any(axis=0))[0]
    px0, px1 = max(0, x0 + cols.min() - margin), min(W, x0 + cols.max() + 1 + margin)
    py0, py1 = max(0, y0 + rows.min() - margin), min(H, y0 + rows.max() + 1 + margin)
    if cap_top is not None: py0 = max(py0, cap_top)
    if cap_bot is not None: py1 = min(py1, cap_bot)
    if cap_left is not None: px0 = max(px0, cap_left)
    if cap_right is not None: px1 = min(px1, cap_right)
    return src.crop((px0, py0, px1, py1))

def main(src_path, out_dir):
    src = Image.open(src_path); W, H = src.size
    assert (W, H) == (4198, 5848), f"预期原图 4198x5848，实际 {W}x{H}"
    ink = np.array(src.convert("L")) < 150
    Y_SPLIT, XU, XL = 2913, 2096, 2101
    units = [  # name, x0, x1, y0, y1, cap_top, cap_bot, cap_left, cap_right
        ("105", XU, W, 0, Y_SPLIT, None, Y_SPLIT, XU, None),   # 右上
        ("106", 0, XU, 0, Y_SPLIT, None, Y_SPLIT, None, XU),   # 左上
        ("107", XL, W, Y_SPLIT, H, Y_SPLIT, None, XL, None),   # 右下
        ("108", 0, XL, Y_SPLIT, H, Y_SPLIT, None, None, XL),   # 左下
    ]
    for name, x0, x1, y0, y1, ct, cb, cl, cr in units:
        crop = tight_crop(src, ink, x0, x1, y0, y1, cap_top=ct, cap_bot=cb, cap_left=cl, cap_right=cr)
        crop.save(f"{out_dir}/{name}.png"); print(name, crop.size)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
