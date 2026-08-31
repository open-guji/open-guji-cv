# -*- coding: utf-8 -*-
"""把「单列矫正·文字带核校」标注页里的人裁结果导成 column-warp 金标。

    # 1) 先把页面读回本地（Artifact action:"read"，大页会落成文件）
    # 2) 再喂给这个脚本
    python scripts/export_column_warp_gold.py read_back.html \\
        -o ../open-guji-dataset/char-segmentation/column-warp

金标一列一个 JSON，存三样东西：
  * `text_band` —— 人工拖出来的文字带左右边界（矫正图局部 x），**真源**；
  * `verdict` —— 界行残墨跟字身墨分不分得开，**真源**；
  * `geometry` + `profile` —— 复现这次矫正所需的全部量，以及沿竖直方向的
    投影快照。快照是给人看形状用的，不当硬金标（改一行 warp 实现就会全量
    出容差，char-normalization 那边踩过这个坑）。

只导**裁过**的列——没裁的不是"默认通过"，是还没看。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from open_guji_cv.utils.border_geometry import HLine, VLine  # noqa: E402
from open_guji_cv.utils.column_projection import (  # noqa: E402
    column_bounds,
    column_profile,
    column_text_band,
    denoise_column,
    warp_column,
)

sys.path.insert(0, str(ROOT / "scripts"))
from build_column_warp_review import SRC, page_geometry  # noqa: E402

COORD_SPACE = (
    "left_line/right_line/top_y/bottom_y 都在 Step1 的新坐标系里（原点在页面"
    "右上角，x 向左递增、y 向下递增；VLine.x_at(y)=x_at_top+slope*y）。"
    "text_band 的 x_left/x_right 则在**矫正之后那张竖直矩形图自己的局部坐标**"
    "里（左上角原点，x 向右），半开区间 [x_left, x_right)。"
)


def parse_page(html: str) -> tuple[list[dict], dict]:
    m = re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S)
    if not m:
        raise SystemExit("这份 HTML 里没有 #data——确认读回的是标注页本身")
    d = json.loads(m.group(1).replace("<\\/", "</"))
    return d["rows"], d.get("verdicts", {})


def export(rows: list[dict], state: dict, out_dir: Path) -> list[dict]:
    samples_dir = out_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    cache: dict[str, object] = {}
    written = []

    for r in rows:
        rec = state.get(r["id"])
        if not rec or not rec.get("v"):
            continue                      # 没裁 ≠ 默认通过，是还没看
        book, page, col = r["book"], r["page"], r["col"]
        key = f"{book}/{page}"
        if key not in cache:
            cache[key] = cv2.imread(str(SRC).format(book=book, page=page),
                                     cv2.IMREAD_GRAYSCALE)
        gray = cache[key]
        _, top, bottom, vs, raise_y, _ = page_geometry(book, page)
        left, right = vs[col], vs[col - 1]
        head_y = raise_y.get(col)
        top_y, bottom_y = column_bounds(top, bottom, head_y)
        warped = denoise_column(warp_column(gray, left, right, top_y, bottom_y))

        band_rec = state.get(r["id"] + "#band")
        if band_rec and band_rec.get("v"):
            xl, xr = (int(v) for v in band_rec["v"].split(","))
        else:
            xl, xr = r["seed"]            # 人裁了但没动界 = 认可种子位置
        auto = column_text_band(warped)

        sample = {
            "book": book, "page": page, "col": col,
            "source_image": f"rebuild_src/{book}/{page}.tif"
                            f"（== open-guji-cv `data_full/zongmu/{book}/{page}.png`，"
                            "原始扫描，未裁剪未做直线增强）",
            "page_size": {"width": int(gray.shape[1]), "height": int(gray.shape[0])},
            "coord_space": COORD_SPACE,
            "geometry": {
                "left_line": {"x_at_top": left.x_at_top, "slope": left.slope},
                "right_line": {"x_at_top": right.x_at_top, "slope": right.slope},
                "top_y": round(top_y, 3), "bottom_y": round(bottom_y, 3),
                "top_y_source": "head_raise_inner_y" if head_y is not None else "page_top_border",
                "warped_size": {"width": int(warped.shape[1]), "height": int(warped.shape[0])},
            },
            "text_band": {"x_left": xl, "x_right": xr},
            "verdict": rec["v"],
            "label_origin": "human",
            "moved_from_seed": bool(band_rec),
            "auto_band_at_export": [int(auto[0]), int(auto[1])],
            "tags": r["tags"],
            "column_metrics": {"drift_px": r["drift"], "trapezoid_px": r["dgap"],
                                "anchor_offset_px": r["anchor"]},
            # 快照，不是硬金标：给人看"界行是尖峰还是鼓包"用的
            "profile": [round(float(v), 4) for v in column_profile(warped)],
        }
        (samples_dir / f"{book}_{page}_c{col}.json").write_text(
            json.dumps(sample, ensure_ascii=False, indent=1), encoding="utf-8")
        written.append(sample)
    return written


def write_metadata(out_dir: Path, samples: list[dict]) -> None:
    verdicts: dict[str, int] = {}
    pages, books = set(), {}
    for s in samples:
        verdicts[s["verdict"]] = verdicts.get(s["verdict"], 0) + 1
        pages.add((s["book"], s["page"]))
        books[s["book"]] = books.get(s["book"], 0) + 1
    meta = {
        "name": "column-warp",
        "version": "0.1.0",
        "schema_version": 1,
        "description": "Step2（单列射影变换+去噪+界行清除）的金标：每列矫正后"
                       "「文字带」的左右边界，以及界行残墨跟字身墨分不分得开的人裁",
        "created": str(date.today()),
        "status": f"试点（{len(samples)} 列 / {len(pages)} 页）",
        "total_samples": len(samples),
        "sample_unit": "列（每列一个文字带边界对 + 一条裁决）",
        "sources": ["06061300.cn（武英殿刻本《欽定四庫全書總目》卷首一~四）"],
        "label_origin_values": ["human"],
        "verdict_distribution": verdicts,
        "book_distribution": books,
        "gold_definition":
            "每列经 warp_column 矫正成竖直矩形后，在该图自身的局部 x 坐标里，"
            "「文字带」的左右边界 [x_left, x_right)——带外只该剩界行残墨、带内"
            "字身完整；外加一条裁决：这两件事能不能同时做到（clean=分得开 / "
            "mixed=分不开，界行残墨跟字身墨在横向糊在一起 / idk=拿不准）。",
        "why_gold_does_not_go_stale":
            "金标挂在人对矫正图的判断上，样本里一并存了复现矫正所需的全部几何量"
            "（左右边线 + top_y/bottom_y + 采用的上下界口径）。只要 Step1 那两条"
            "线的金标不变，任何新的矫正/清界行实现都能重算出同一张图，拿这两个 x "
            "直接算误差。profile 只是快照，**不当硬金标**——改一行重采样实现就会"
            "全量出容差，char-normalization 踩过这个坑。",
        "labeling_method":
            "自研交互标注 artifact（整列压扁图横向 1:1 + 沿竖直方向的投影曲线，"
            "拖两条竖线定边界、可逐像素微调），种子取自 column_text_band() 自动"
            "判据，人工逐列核校；页面自存，裁决读回后导出。",
        "known_limitations": [
            "只有 vol01，且列是按「难例优先」选的（倾斜大/梯形大/锚点偏差大/"
            "抬头列各取前几名 + 少量平稳列对照），**不是随机抽样**——可以用来"
            "找失败形态，不能直接当全书比例的估计。",
            "上下界用的是定版约定 top_y=页面右端 x=0 锚点；越靠左的列这个锚点"
            "离该列真实版框越远（实测最大 60.5px），个别列首字会被切掉一截，"
            "这些列的 verdict 可能记的是 idk 而不是矫正本身的问题。",
        ],
    }
    (out_dir / "metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("html", help="从 Artifact 读回来的标注页 HTML")
    ap.add_argument("-o", "--out", required=True, help="金标子集目录")
    args = ap.parse_args()

    rows, state = parse_page(Path(args.html).read_text(encoding="utf-8"))
    out_dir = Path(args.out)
    samples = export(rows, state, out_dir)
    if not samples:
        raise SystemExit(f"0 / {len(rows)} 已裁——多半是自存没生效，"
                         "查 .claude/skills/review-artifact/references/autosave.md")
    write_metadata(out_dir, samples)
    moved = sum(1 for s in samples if s["moved_from_seed"])
    print(f"导出 {len(samples)} / {len(rows)} 列 -> {out_dir/'samples'}"
          f"（其中 {moved} 列人工改过界）")
    for v in sorted({s["verdict"] for s in samples}):
        print(f"  {v}: {sum(1 for s in samples if s['verdict'] == v)}")


if __name__ == "__main__":
    main()
