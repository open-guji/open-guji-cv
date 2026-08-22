"""生成行列识别（列型判别）数据集。

金标来源：**人工目视**。判别方式是把「纯刚性格线」（书级 cell_h + 页相位）
叠在列上，看红线是落在字与字之间（rigid）还是穿字而过 / 字数与格数对不上
（elastic）——见 .claude/doc 与本仓 scripts/ 的叠图工具。

自动化的只有两件客观的事，不涉及判断：
  1. 空列：整列墨量低于阈值 → blank；
  2. 列的位置：沿用 phase3 的列带（横向刚性，实测职名页与正文页列间距
     变异系数同为 1.4%~2.4%，不是本数据集要测的对象）。

页级标签写在 PAGE_LABELS 里：值为该页所有非空列的列型；individual 字典
可覆盖单列（抬头、标题等）。改标注只改这张表。
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

import cv2
import numpy as np

from open_guji_cv.clustering.layout_spec import ColumnSpec, PageLayout

BLANK_INK_RATIO = 0.004      # 列墨量占比低于此 → blank（客观判定，非人工）

# 页型 → 该页非空列的列型；[人工目视确认，2026-08]
#   body/toc : 红线干净落在字间，一格一字（目录页字少但字距仍是 1×）
#   roster   : 职名页，字距明显偏离 1×（拉开或压缩两种子型都有）
PAGE_LABELS: dict[str, dict] = {
    # ── 正文页：密排、字距 1× ──
    "vol01/23": {"cls": "body", "all": "rigid"},
    "vol01/33": {"cls": "body", "all": "rigid"},
    "vol01/34": {"cls": "body", "all": "rigid"},
    "vol01/38": {"cls": "edict", "all": "rigid"},
    "vol01/90": {"cls": "roster", "all": "elastic"},
    "vol01/93": {"cls": "roster", "all": "elastic"},
    "vol01/100": {"cls": "roster", "all": "elastic"},
    "vol01/103": {"cls": "roster", "all": "elastic"},
    "vol01/108": {"cls": "roster", "all": "elastic"},
    "vol01/113": {"cls": "roster", "all": "elastic"},
    "vol01/115": {"cls": "roster", "all": "elastic"},
    "vol01/116": {"cls": "roster", "all": "elastic"},
    "vol01/117": {"cls": "roster", "all": "elastic"},
    "vol01/121": {"cls": "roster", "all": "elastic"},
    "vol01/122": {"cls": "roster", "all": "elastic"},
    "vol01/123": {"cls": "roster", "all": "elastic"},
    "vol01/158": {"cls": "cover", "all": "blank"},
    "vol01/161": {"cls": "toc", "all": "rigid"},
    "vol01/163": {"cls": "toc", "all": "rigid"},
    "vol01/176": {"cls": "toc", "all": "rigid"},
    "vol01/179": {"cls": "toc", "all": "rigid"},
    "vol01/185": {"cls": "toc", "all": "rigid"},
    # 目视复核修正：193/196 实为目录页（「卷一百四十八 集部一」），
    # 列型仍是 rigid，但页型标错会让分层报告失真
    "vol01/193": {"cls": "toc", "all": "rigid"},
    "vol01/196": {"cls": "toc", "all": "rigid"},
    # vol02/1 是题名页（「四庫全書」大字装饰框），字距无从按 1× 判定
    "vol02/1": {"cls": "cover", "all": "uncertain"},
    "vol02/9": {"cls": "body", "all": "rigid"},
    "vol02/16": {"cls": "body", "all": "rigid"},
    "vol02/27": {"cls": "body", "all": "rigid"},
    "vol02/33": {"cls": "body", "all": "rigid"},
    "vol02/49": {"cls": "body", "all": "rigid"},
    "vol02/94": {"cls": "body", "all": "rigid"},
    "vol02/115": {"cls": "body", "all": "rigid"},
    "vol02/131": {"cls": "body", "all": "rigid"},
    "vol02/154": {"cls": "body", "all": "rigid"},
    # ── 卷端/题名页：大字标题、抬头混排，目视也难逐列定夺 ──
    "vol01/3": {"cls": "mixed", "all": "uncertain"},
    "vol01/47": {"cls": "edict", "all": "rigid",
                 # 抬头honorific列：字太少，字距无从判定
                 "individual": {8: "uncertain", 5: "uncertain",
                                4: "uncertain", 3: "uncertain"}},
}


def col_ink_ratio(col_gray: np.ndarray) -> float:
    return float((col_gray < 128).mean())


def build_page(book: str, page: str, spec: dict, out_root: Path,
               pipeline_version: str) -> PageLayout | None:
    book_out = Path("output") / book
    grid_p = book_out / "phase3_char_grid" / f"{page}_char_grid.json"
    img_p = book_out / f"{page}.png"
    if not grid_p.exists() or not img_p.exists():
        return None
    grid = json.loads(grid_p.read_text(encoding="utf-8"))
    img = cv2.imread(str(img_p), cv2.IMREAD_GRAYSCALE)

    cols: list[ColumnSpec] = []
    for c in grid.get("columns", []):
        if c.get("skipped"):
            continue
        idx = int(c["index"])
        lx, rx = int(c["left_x"]), int(c["right_x"])
        strip = img[:, max(0, lx):rx]
        layout = spec.get("individual", {}).get(idx, spec["all"])
        if layout != "blank" and col_ink_ratio(strip) < BLANK_INK_RATIO:
            layout = "blank"            # 客观覆盖：整列没墨
        cols.append(ColumnSpec(index=idx, left_x=float(c["left_x"]),
                               right_x=float(c["right_x"]), layout=layout))
    cols.sort(key=lambda c: -c.index)
    return PageLayout(
        book=book, page=page,
        image_size=grid.get("image_size", {}),
        n_cols=len(cols),
        cell_h=float(grid.get("grid", {}).get("cell_h", 0.0)),
        columns=cols, page_class=spec["cls"],
        edition_tag="wuyingdian-siku-zongmu",
        source_item={"vol01": "06061300.cn", "vol02": "06061301.cn"}.get(book),
        pipeline_version=pipeline_version, label_origin="human")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="样本输出目录")
    args = ap.parse_args()
    try:
        ver = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True).stdout.strip()
    except Exception:
        ver = ""

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    stat: dict[str, int] = {}
    for key, spec in sorted(PAGE_LABELS.items()):
        book, page = key.split("/")
        pl = build_page(book, page, spec, out, ver)
        if pl is None:
            print(f"跳过 {key}（缺少切分结果或页图）")
            continue
        d = out / f"{book}_{page}"
        d.mkdir(exist_ok=True)
        pl.save(d / "expected.json")
        img = cv2.imread(str(Path("output") / book / f"{page}.png"))
        cv2.imwrite(str(d / "image.png"), img)
        for c in pl.columns:
            stat[c.layout] = stat.get(c.layout, 0) + 1
        n += 1
    print(f"写出 {n} 页 → {out}")
    print("列型分布:", dict(sorted(stat.items())))


if __name__ == "__main__":
    main()
