"""修去扫描污渍：页面上贯穿全宽的粗黑横轨（vol02 p151）。

背景
----
vol02 第 151 页正文上部有两条横贯全宽的粗黑污渍轨（y≈361-370 与 y≈401-410），
夹住一行字。肉眼看像"黑白反色"，但实测不是：在**纯纸列**（上下文都无墨的列）上
测墨占比，两条轨是 0.6 / 0.8，中间只有 0.15——所以是两条实心黑条压在纸上，
不是一整块反色。（若真是反色，整段反过来后墨占比应回到正文水平 0.2 左右，
实测反色后是 0.53，且上下接缝对不上，故排除。）

污渍来自扫描源，不是本仓管线引入：git 历史里最早的 cc8ad10cd8 版本已有。
图早已二值化（只有 0/255），没有留灰度中间态，所以只能在二值图上修。

做法
----
逐行扫轨内的水平黑游程：
  - 短游程（<30px）判为真笔画，原样保留；
  - 长游程判为污渍，逐列检查该列是否有竖笔穿过轨（轨上下各 6 行都有墨）；
    有则保留（真笔画穿过污渍），无则抹白。
  - 「穿过」的连通块若过宽（>26px）仍判为污渍——真竖笔不会那么宽。

局限（重要）
----------
污渍最浓处（页面左侧两列）笔画已被完全吞掉，二值图里没有信息可还原，
修完仍有残留黑块，那几个字要靠上下文/整理本定字，不要指望图像层修干净。
修后带内墨占比从 0.44-0.56 降到 0.18-0.42（正文正常约 0.2）。

用法
----
    python scripts/fix_page_smudge.py output/vol02/151.png
默认 --dry-run 只报告；加 --write 才落盘。改动只发生在 y361..410。
"""
import argparse
import numpy as np
from PIL import Image
from scipy import ndimage

RAILS = [(361, 370), (401, 410)]
MIN_SMUDGE_RUN = 30   # 短于此的水平游程判为真笔画
MAX_STROKE_W = 26     # 「穿轨」连通块宽于此判为污渍而非竖笔
CTX = 6               # 轨上下各取几行判断竖笔是否穿过


def repair(b, rails=RAILS):
    fixed = b.copy()
    for y0, y1 in rails:
        for y in range(y0, y1 + 1):
            row = b[y].astype(np.uint8)
            idx = np.flatnonzero(np.diff(np.r_[0, row, 0]))
            for a, c in zip(idx[::2], idx[1::2]):
                if c - a < MIN_SMUDGE_RUN:
                    continue
                up = b[y0 - CTX - 1:y0 - 1, a:c].any(axis=0)
                dn = b[y1 + 2:y1 + CTX + 2, a:c].any(axis=0)
                through = up & dn
                lab, n = ndimage.label(through)
                for k in range(1, n + 1):
                    xs = np.flatnonzero(lab == k)
                    if len(xs) > MAX_STROKE_W:
                        through[xs] = False
                fixed[y, a:c] = through
    return fixed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--write", action="store_true", help="落盘；默认只报告")
    args = ap.parse_args()

    im = Image.open(args.image).convert("L")
    b = np.array(im) < 128
    fixed = repair(b)

    changed = int((b & ~fixed).sum())
    y0, y1 = rails_span = (RAILS[0][0], RAILS[-1][1])
    print(f"抹掉像素 {changed}")
    print(f"带内墨占比 {b[y0:y1+1].mean():.3f} -> {fixed[y0:y1+1].mean():.3f}"
          f"（正文正常约 0.2）")
    if args.write:
        Image.fromarray(np.where(fixed, 0, 255).astype(np.uint8)).save(args.image)
        print(f"已写入 {args.image}")
    else:
        print("dry-run：未落盘，加 --write 才写")


if __name__ == "__main__":
    main()
