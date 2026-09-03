# -*- coding: utf-8 -*-
"""用 Step 1 的新结果重算 Step 2 的输入（单列矫正图）。

以前整页共用一个页级 `top_y = top.y_at(0)`，版框是斜的、越靠左的列偏得越多
（实测最大 54.4px，且一律偏下 → 首字被削）；抬头列更是整段被切（140~187px）。
现在 `page_column_windows()` 逐列算上下界，抬头列自动上探到抬头框外延。

    python scripts/regen_step2_columns.py <book> <page> [<page> ...] [--denoise]
    python scripts/regen_step2_columns.py vol01 --gold-pages
    python scripts/regen_step2_columns.py vol01 4 7 10 ... --jobs 4   # 跨页并行

输出：output/<book>/step2_columns/<page>/c<N>.png + <page>/windows.json

## 性能：99.7% 的时间在 Step1 的 `detect_borders`，Step2 自己几乎不花时间

实测单页（vol01/9，2327×3072）：`detect_borders` 22.1s，`warp_page_columns`
（9 列射影变换）0.006s，`denoise_column`×9 0.02s，`clean_column`×9
（denoise+定带+去界行+削版框）0.03s——Step2 自己的活加起来 **不到 0.1s**，
优化 Step2 本身没有意义，瓶颈是它调用的 Step1 探测。

`detect_borders` 内部再拆（cProfile，同一页）：`find_vertical_lines` 17.5s
（76%）、`find_horizontal_border`（上下各一次）3.9s（17%）、
`fit_vlines_polyline`（三段折线拟合）1.4s（6%）。`find_vertical_lines` 的
时间几乎全在 `joint_search_coarse_to_fine`——9 列页面探 16 个候选线窗口，
每个窗口粗扫 35 档角度 + 精扫 25 档角度，每一档角度都要对整页高度做一次
双线性插值投影（`sample_line_curve`，962 次调用、17.7s tottime）。这是
Step1（`peak_line_search.py`）内部的计算结构，不归 Step2 改，但记在这里
方便算总账：

- **本文件已加的优化：跨页并行**（`--jobs`）。`detect_borders` 每页完全
  独立，`ProcessPoolExecutor` 按页分给多个进程。这台容器 4 核实测（4 页，
  vol01/4·7·10·13）：`--jobs 1` 81.9s（20.5s/页）→ `--jobs 4` 24.2s
  （6.1s/页），**3.4x**，接近核数上限（`detect_borders` 是纯 CPU 计算，
  没有 IO 等待可省，多进程序列化图像数组的开销吃掉了一点理论上限）。
  两种跑法产出的 `windows.json` **逐字节相同**——并行不改变任何一页的
  结果，只是分给谁算的问题。按这个比率外推，54 页批跑大约能从 ~18 分钟
  压到 ~5.5 分钟；这台容器只有 4 核，更多核数应该还能往上摊（`detect_borders`
  之间没有共享状态，理论上 `--jobs` 可以一直加到核数）。
- **没做、留给 Step1 那边的建议**（都要改 `peak_line_search.py`，这次范围
  外）：①`joint_search_coarse_to_fine` 的粗扫/精扫是 Python 循环里逐个角度
  调 `sample_line_curve`，60 次独立 numpy 调用——合并成一次广播（加一维
  角度轴）能把 60 次调用变 1 次，省掉大部分重复的数组分配和调用开销；
  ②先在降采样图（比如 2x/4x）上粗定位候选线的大致 x/角度范围，再回原图
  精搜小窗口——`sample_line_curve` 的开销跟页高线性相关，降采样能按比例
  砍时间；③`find_horizontal_border` 的两次调用（top/bottom）互相独立，
  也能并行，但相对 `find_vertical_lines` 的 17.5s 收益有限。
"""
import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from open_guji_cv.utils.border_geometry import detect_borders
from open_guji_cv.utils.column_projection import warp_page_columns

RAW_ROOT = Path("/home/user/rebuild_src")
FALLBACK_ROOT = Path(__file__).resolve().parent.parent / "data_full" / "zongmu"
OUT_ROOT = Path(__file__).resolve().parent.parent / "output"
GOLD_PAGES = ["137", "138", "32", "33", "49", "9", "14", "142", "24", "65", "141", "26", "47", "51"]


def _find_source(book: str, page: str) -> Path:
    """`RAW_ROOT` 是那台原始容器里的路径，这台容器上不存在——退回
    `data_full/zongmu/<book>/<page>.png`，跟 14 页金标核对过是同一张源图
    （page_size 逐位对得上），只是格式从 tif 换成了 png。"""
    tif = RAW_ROOT / book / f"{page}.tif"
    if tif.exists():
        return tif
    png = FALLBACK_ROOT / book / f"{page}.png"
    if png.exists():
        return png
    raise SystemExit(f"两个候选源都没有：{tif}  /  {png}")


def _vline_dict(v) -> dict:
    """`VLine` 的完整口径，含三段折线字段。以前这里只存 `x_at_top`/`slope`
    （相当于 k1），弯页（`segments==3`）的 `k2`/`k3`/`y1`/`y2` 被静静丢掉——
    `warp_column` 自己按 `win.left`/`win.right`（内存里的完整 VLine 对象）
    做分带射影，矫正图本身没受影响；但 `windows.json` 一旦被下游拿去反算
    （`column_warp_matrix` 的文档就明说了"这个矩阵只对直线边线成立"，反算
    弯页必须先知道 k2/k3/y1/y2 才找得到对应带），存的这几个字段一直是 None，
    没法用。2026-09-02 全书重跑（vol01/47、11、151 十条线全部变成三段）
    才发现——按当时的口径一次都没漏，因为之前跑过的页基本都是直线。"""
    return dict(x_at_top=v.x_at_top, slope=v.slope, k2=v.k2, k3=v.k3, y1=v.y1, y2=v.y2)


def regen(book: str, page: str, expected_cols: int, denoise: bool) -> dict:
    src = _find_source(book, page)
    gray = cv2.cvtColor(cv2.imread(str(src)), cv2.COLOR_BGR2GRAY)
    res = detect_borders(gray, expected_cols=expected_cols)
    out_dir = OUT_ROOT / book / "step2_columns" / page
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = dict(book=book, page=page, source_image=str(src),
                page_size=dict(width=int(gray.shape[1]), height=int(gray.shape[0])),
                top_inner=dict(y_at_right=res.top.y_at_right, slope=res.top.slope),
                bottom_inner=dict(y_at_right=res.bottom.y_at_right, slope=res.bottom.slope),
                denoised=denoise, columns=[])
    for win, img in warp_page_columns(gray, res, denoise=denoise):
        cv2.imwrite(str(out_dir / f"c{win.col}.png"), img)
        meta["columns"].append(dict(
            col=win.col, file=f"c{win.col}.png",
            left_line=_vline_dict(win.left),
            right_line=_vline_dict(win.right),
            top_y=win.top_y, bottom_y=win.bottom_y,
            border_top_y=win.border_top_y, border_bottom_y=win.border_bottom_y,
            border_top_in_column=win.border_top_in_column,
            border_bottom_in_column=win.border_bottom_in_column,
            raised=win.raised, head_raise_inner_y=win.head_raise_inner_y,
            warped_size=dict(width=int(img.shape[1]), height=int(img.shape[0]))))
    (out_dir / "windows.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1) + "\n")
    return meta


def _report(book: str, page: str, m: dict) -> str:
    r = [c["col"] for c in m["columns"] if c["raised"]]
    return (f"{book}/{page}: {len(m['columns'])} 列"
            + (f"，抬头列 {r}（多矫正 "
               + ", ".join(f"{c['border_top_in_column']:.0f}px" for c in m["columns"] if c["raised"])
               + "）" if r else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    ap.add_argument("pages", nargs="*")
    ap.add_argument("--gold-pages", action="store_true", help="用 border-detection 金标那 14 页")
    ap.add_argument("--cols", type=int, default=9)
    ap.add_argument("--denoise", action="store_true")
    ap.add_argument("--jobs", type=int, default=1,
                     help="跨页并行进程数——detect_borders 是纯 CPU 计算、"
                          "每页互相独立，是这个脚本唯一值得并行的地方（见"
                          "模块头「性能」一节）。默认 1（顺序，行为不变）。")
    a = ap.parse_args()
    pages = GOLD_PAGES if a.gold_pages else a.pages
    if not pages:
        ap.error("给页号，或者 --gold-pages")
    n_raised = 0
    if a.jobs <= 1:
        for pg in pages:
            m = regen(a.book, pg, a.cols, a.denoise)
            n_raised += len([c for c in m["columns"] if c["raised"]])
            print(_report(a.book, pg, m), flush=True)
    else:
        # 边跑边打印（谁先完成先报），批大的时候（比如全书几百页）能看见进度；
        # 跑完统一按传入顺序再打一遍摘要，方便复现/diff。
        with ProcessPoolExecutor(max_workers=a.jobs) as pool:
            futs = {pool.submit(regen, a.book, pg, a.cols, a.denoise): pg for pg in pages}
            done = {}
            n_done = 0
            for fut in as_completed(futs):
                pg = futs[fut]
                m = fut.result()
                done[pg] = m
                n_done += 1
                n_raised += len([c for c in m["columns"] if c["raised"]])
                print(f"[{n_done}/{len(pages)}] {_report(a.book, pg, m)}", flush=True)
        print("\n--- 按传入顺序汇总 ---")
        for pg in pages:
            print(_report(a.book, pg, done[pg]), flush=True)
    print(f"\n完成，抬头列共 {n_raised} 个")
