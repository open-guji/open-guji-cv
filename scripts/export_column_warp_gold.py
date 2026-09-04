# -*- coding: utf-8 -*-
"""把「单列矫正·文字带核校」标注页里的人裁结果导成 column-warp 金标。

    # 1) 先把页面读回本地（Artifact action:"read"，大页会落成文件）
    # 2) 再喂给这个脚本
    python scripts/export_column_warp_gold.py read_back.html \\
        -o ../open-guji-dataset/char-segmentation/column-warp

**输入口径**：列图一律取 `output/<book>/step2_columns/<page>/`（由
`scripts/regen_step2_columns.py` 用 `detect_borders` + `page_column_windows`
生成），也就是**生产链路真正会喂给 Step2 的那张图**。样本里存
`input.variant = "detected_lines@per_column_window"` 把这件事写死。

早先还有一套口径不同的金标（人工金标边线 + 页级 x=0 锚点），已经归档在
`legacy-page-anchor/`，不再扩充——两套的差别不是参数而是**链路**：边线一个
来自人工金标、一个来自算法探测，实测差 0.76~27.6px，列图宽度差到 38px。
详见该子集的 README。

金标一列一个 JSON，存这几样：
  * `text_band` —— 文字带左右边界（矫正图局部 x），**真源**。它不是一个点
    而是一条**走廊**：用户明说「我标定的不一定是唯一的坐标，应该让坐标尽量
    靠近两边（保持墨量接近 0）」，所以存两组——
      `human_*`     人拖到的位置（保守端，一定在零区里）；
      `canonical_*` 从人标点**往外推到墨量还 <= `ZERO_EPS` 的最远处**（激进端）。
    算法落在 [canonical, human] 这条走廊里都算对；推过 canonical = 留残墨，
    越过 human = 吃字。
  * `verdict` —— 界行残墨跟字身墨分不分得开，**真源**；
  * `input` + `profile` —— 复现这张列图所需的全部量，以及沿竖直方向的投影
    快照。快照是给人看形状用的，不当硬金标（改一行 warp 实现就会全量出容差，
    char-normalization 那边踩过这个坑）。

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

from open_guji_cv.utils.column_projection import (  # noqa: E402
    column_profile,
    column_text_band,
    denoise_column,
)

sys.path.insert(0, str(ROOT / "scripts"))
from migrate_column_warp_gold import COL_FP_SIZE, fingerprint  # noqa: E402

STEP2_COLUMNS = ROOT / "output" / "{book}" / "step2_columns" / "{page}"
VARIANT = "detected_lines@per_column_window"

# "墨量接近 0" 的口径。人标点处的墨占比实测均值 0.0010 / 最大 0.0097，
# 而界行裙边一路从 0.4 缓降、要到 0.01 才真正归零——0.005 卡在这两者之间。
ZERO_EPS = 0.005

COORD_SPACE = (
    "input.left_line/right_line/top_y/bottom_y 都在 Step1 的新坐标系里（原点在"
    "页面右上角，x 向左递增、y 向下递增；VLine.x_at(y)=x_at_top+slope*y）。"
    "text_band 的边界则在**矫正之后那张竖直矩形图自己的局部坐标**里"
    "（左上角原点，x 向右），半开区间 [x_left, x_right)。"
)


def parse_page(html: str) -> tuple[list[dict], dict]:
    m = re.search(r'<script type="application/json" id="data">(.*?)</script>', html, re.S)
    if not m:
        raise SystemExit("这份 HTML 里没有 #data——确认读回的是标注页本身")
    d = json.loads(m.group(1).replace("<\\/", "</"))
    return d["rows"], d.get("verdicts", {})


def load_windows(book: str, page: str) -> dict[int, dict]:
    f = Path(str(STEP2_COLUMNS).format(book=book, page=page)) / "windows.json"
    if not f.exists():
        raise SystemExit(f"{f} 不存在——先跑 scripts/regen_step2_columns.py {book} {page}")
    d = json.loads(f.read_text(encoding="utf-8"))
    return {c["col"]: (d, c) for c in d["columns"]}


def export(rows: list[dict], state: dict, out_dir: Path,
            drop: set[str] | None = None) -> list[dict]:
    samples_dir = out_dir / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)
    drop = drop or set()
    cache: dict[tuple[str, str], dict] = {}
    written = []

    for r in rows:
        rec = state.get(r["id"])
        if not rec or not rec.get("v"):
            continue                      # 没裁 ≠ 默认通过，是还没看
        if r["id"] in drop:
            # 输入换过口径、人标已经不落在零区，标注失效。宁可少一列也不留
            # 一条错金标——从 samples 里删掉、等重标。
            (samples_dir / f"{r['id']}.json").unlink(missing_ok=True)
            continue
        book, page, col = r["book"], r["page"], r["col"]
        if (book, page) not in cache:
            cache[(book, page)] = load_windows(book, page)
        meta, win = cache[(book, page)][col]
        img_path = Path(str(STEP2_COLUMNS).format(book=book, page=page)) / win["file"]
        warped = denoise_column(cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE))

        band_rec = state.get(r["id"] + "#band")
        if band_rec and band_rec.get("v"):
            xl, xr = (int(v) for v in band_rec["v"].split(","))
        else:
            xl, xr = r["seed"]            # 人裁了但没动界 = 认可种子位置
        prof = column_profile(warped)
        # 从人标点往外推到墨量还接近 0 的最远处 —— 走廊的激进端
        cl = xl
        while cl - 1 >= 0 and prof[cl - 1] <= ZERO_EPS:
            cl -= 1
        cr = xr
        while cr < len(prof) and prof[cr] <= ZERO_EPS:
            cr += 1
        auto = column_text_band(warped)

        sample = {
            "book": book, "page": page, "col": col,
            "coord_space": COORD_SPACE,
            "input": {
                "variant": VARIANT,
                "producer": "open-guji-cv scripts/regen_step2_columns.py"
                            "（detect_borders + page_column_windows）",
                "column_image": f"open-guji-cv output/{book}/step2_columns/{page}/{win['file']}",
                "source_image": meta["source_image"],
                "page_size": meta["page_size"],
                "left_line": win["left_line"], "right_line": win["right_line"],
                "top_y": win["top_y"], "bottom_y": win["bottom_y"],
                "border_top_in_column": win["border_top_in_column"],
                "border_bottom_in_column": win["border_bottom_in_column"],
                "raised": win["raised"], "head_raise_inner_y": win["head_raise_inner_y"],
                "warped_size": win["warped_size"],
            },
            "text_band": {"human_left": xl, "human_right": xr,
                           "canonical_left": cl, "canonical_right": cr,
                           "zero_eps": ZERO_EPS},
            "verdict": rec["v"],
            "label_origin": "human",
            "moved_from_seed": bool(band_rec),
            "auto_band_at_export": [int(auto[0]), int(auto[1])],
            # 人当时看的那张列图的指纹。上游再改列图时
            # scripts/migrate_column_warp_gold.py 拿它当**主判据**判断"还是不是
            # 同一张图"——是就原样留用，不必回去重标。
            "column_fingerprint": fingerprint(warped, COL_FP_SIZE),
            "tags": r["tags"],
            # 快照，不是硬金标：给人看"界行是尖峰还是鼓包"用的
            "profile": [round(float(v), 4) for v in prof],
        }
        (samples_dir / f"{book}_{page}_c{col}.json").write_text(
            json.dumps(sample, ensure_ascii=False, indent=1), encoding="utf-8")
        written.append(sample)
    return written


def write_metadata(out_dir: Path, samples: list[dict],
                    pending: list[str] | None = None) -> None:
    verdicts: dict[str, int] = {}
    pages, books = set(), {}
    raised = 0
    for s in samples:
        verdicts[s["verdict"]] = verdicts.get(s["verdict"], 0) + 1
        pages.add((s["book"], s["page"]))
        books[s["book"]] = books.get(s["book"], 0) + 1
        raised += bool(s["input"]["raised"])
    meta = {
        "name": "column-warp",
        "version": "0.2.0",
        "schema_version": 2,
        "description": "Step2（单列射影变换+去噪+界行/版框清除）的金标：每列矫正后"
                       "「文字带」的左右边界、界行残墨跟字身墨分不分得开的人裁，"
                       "以及上下两端的版框残墨类别",
        "created": str(date.today()),
        "status": f"试点（{len(samples)} 列 / {len(pages)} 页）",
        "input_variant": VARIANT,
        "input_note":
            "列图取 open-guji-cv `output/<book>/step2_columns/<page>/c<N>.png`，"
            "由 `scripts/regen_step2_columns.py` 用 **detect_borders 算法探测的"
            "边线** + `page_column_windows` 逐列窗口生成——也就是生产链路真正会"
            "喂给 Step2 的那张图，Step1 的误差包含在内。另有一套口径不同的旧金标"
            "（人工金标边线 + 页级 x=0 锚点）归档在 `legacy-page-anchor/`。",
        "total_samples": len(samples),
        "sample_unit": "列（每列一个文字带边界对 + 一条裁决；上下版框类别另存）",
        "sources": ["06061300.cn（武英殿刻本《欽定四庫全書總目》卷首一~四）"],
        "label_origin_values": ["human"],
        "verdict_distribution": verdicts,
        "book_distribution": books,
        "raised_columns": raised,
        "gold_definition":
            "每列经 warp_column 矫正成竖直矩形后，在该图自身的局部 x 坐标里，"
            "「文字带」的左右边界——带外只该剩界行残墨、带内字身完整；外加一条"
            "裁决：这两件事能不能同时做到（clean=分得开 / mixed=分不开，界行"
            "残墨跟字身墨在横向糊在一起 / idk=拿不准）。边界不是唯一解而是一条"
            "**走廊**：human_* 是人拖到的保守端，canonical_* 是从人标点往外推到"
            "墨占比仍 <= zero_eps(0.005) 的最远处；落在走廊内都算对。",
        "why_gold_does_not_go_stale":
            "金标挂在人对**某一张具体列图**的判断上，样本里存了复现那张图所需的"
            "全部量（input 那一块）。**但 Step1 一改，列图就变、标注就可能失效**"
            "——已经发生过三次（head_raise 列号归属、verticals 按真墨重拟、输入"
            "换成算法边线+逐列窗口）。规矩是每次都逐条复核人标点处的墨占比，"
            "失效的删掉重标，绝不假设能迁。profile 只是快照，不当硬金标。",
        "labeling_method":
            "自研交互标注 artifact：文字带那一页给整列压扁图（横向 1:1）+ 沿竖直"
            "方向的投影曲线，拖两条竖线定边界；上下版框那一页给两端裁剪图 + 沿"
            "水平方向的投影，**只点类别不标坐标**。种子取自算法判据，人工逐列核校。",
        "pending_relabel": sorted(pending or []),
        "known_limitations": [
            "只有 vol01，且列是按「难例优先」选的（倾斜大/梯形大/抬头列各取前"
            "几名 + 少量平稳列对照），**不是随机抽样**——可以用来找失败形态，"
            "不能直接当全书比例的估计。",
            "输入用的是算法探测的边线，所以这批数字是 **Step1+Step2 端到端**的，"
            "不隔离 Step1 的误差。要单看 Step2 自己，用 legacy-page-anchor/ 那套"
            "（人工金标边线），但那套的窗口口径已经过时。",
        ],
    }
    # **保留别的工具往 metadata 里加的字段**。这个函数是整份重写的，2026-09-03
    # 因此丢过两次数据：`sampling`（分层抽样口径，没它就没法解释「全书 mixed 率」
    # 那个数是怎么来的）和 `previously_excluded`（页级排除台账 + 解除理由）。
    # 本函数只对下面这些"自己算出来的"字段有话语权，其余一律沿用旧文件。
    OWNED = {"name", "version", "schema_version", "description", "created", "status",
              "input_variant", "input_note", "total_samples", "sample_unit", "sources",
              "label_origin_values", "verdict_distribution", "book_distribution",
              "raised_columns", "gold_definition", "why_gold_does_not_go_stale",
              "labeling_method", "pending_relabel", "known_limitations"}
    path = out_dir / "metadata.json"
    if path.exists():
        prev = json.loads(path.read_text(encoding="utf-8"))
        merged = {k: v for k, v in prev.items() if k not in OWNED}
        merged.update(meta)          # 自己算的那批覆盖旧值
        meta = {**meta, **{k: v for k, v in prev.items() if k not in OWNED}}
    path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("html", help="从 Artifact 读回来的标注页 HTML")
    ap.add_argument("-o", "--out", required=True, help="金标子集目录")
    ap.add_argument("--drop", default="",
                    help="逗号分隔的列 id：输入换了口径、人标已失效，删掉等重标")
    args = ap.parse_args()

    rows, state = parse_page(Path(args.html).read_text(encoding="utf-8"))
    out_dir = Path(args.out)
    drop = {x for x in args.drop.split(",") if x}
    samples = export(rows, state, out_dir, drop)
    if not samples:
        raise SystemExit(f"0 / {len(rows)} 已裁——多半是自存没生效，"
                         "查 .claude/skills/review-artifact/references/autosave.md")
    write_metadata(out_dir, samples, sorted(drop))
    moved = sum(1 for s in samples if s["moved_from_seed"])
    print(f"导出 {len(samples)} / {len(rows)} 列 -> {out_dir/'samples'}"
          f"（其中 {moved} 列人工改过界；口径 {VARIANT}）")
    for v in sorted({s["verdict"] for s in samples}):
        print(f"  {v}: {sum(1 for s in samples if s['verdict'] == v)}")


if __name__ == "__main__":
    main()
