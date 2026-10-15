#!/usr/bin/env python3
"""GUJI-208jn：把 Ezio 的 208io（取不到候选 38 格）与 208is（切分坏 366 抽 60 + 非字 123 抽 50）
逐格分类合并成一张表，供 Ezio 208ji 框问题聚类用。只读：不碰 products／事件／字形库。

用法（默认路径即可）：
  python3 框问题148格合并表-208jn.py [--ezio-dir ../scripts-Ezio] [--ct-dir <cell_table 目录>] [--out-dir .]

--ct-dir 放 vol01–07_base.jsonl.gz（来自 guji-workspace 分支 claude/hint-ignore-dash-newadmit-1012 的
exports/cell_table/）；用来补「基线表有无这格」和每页总格数。
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_EZIO = HERE.parent / "scripts-Ezio"
PAGE_TYPE_TODO = "待证据"  # pages.json／row_segment 产物不在本机，判不了，不猜
ASPECT_TODO = "待证据"     # 基线 cell_table 无 bbox；bbox 只在 cell_shrink 产物里，本机没有

# Ezio 的类 -> 合并表的统一类
CLASS_MAP = {
    "完整": "完整",
    "完整单字": "完整",
    "半字": "框截半字",
    "两字并框": "并框",
    "多字": "并框",
    "非字": "非字",
    "无法对应": "出不了图",
    "出不了图": "出不了图",
}


RECEIPT = (
    "GUJI-46 回执（GUJI-208jn，Emi）：148 格已合并，Ezio 直接用 "
    "`项目进展/图片初步数字化/进度/scripts-Emi/框问题148格合并表-208jn.tsv`（148 行；"
    "列：格号｜来源批｜Ezio分类｜原始类｜读到的字｜把握｜册｜页｜列｜格序｜页型｜格框宽高比｜基线表有无｜基线放行｜备注）。"
    "页型、格框宽高比两列写「待证据」：基线 cell_table 无 bbox，pages.json／row_segment 不在本机，未猜；148 格基线表全部找到。"
)


def read_tsv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def parse_id(cell: str) -> tuple[str, str, str, str]:
    vol, page, col, slot = cell.split(":")
    return vol, page, col, slot


def load_rows(ezio: Path) -> list[dict]:
    rows = []
    for r in read_tsv(ezio / "取不到候选38格-208io.tsv"):
        rows.append({
            "格": r["格"], "来源批": "208io", "原始类": r["类"],
            "字": r["我读到的字"], "把握": r["把握"], "备注": r["备注"],
        })
    for r in read_tsv(ezio / "未抽样切分坏与非字-208is.tsv"):
        src = r["来源表"]  # 切分坏 / 非字
        rows.append({
            "格": r["格"], "来源批": f"208is-{src}", "原始类": r["类"],
            "字": r["我读到的字"], "把握": r["把握"], "备注": r["备注"],
        })
    for r in rows:
        r["统一类"] = CLASS_MAP.get(r["原始类"], "未知:" + r["原始类"])
        r["册"], r["页"], r["列"], r["格序"] = parse_id(r["格"])
    return rows


def load_baseline(ct_dir: Path) -> dict[str, dict]:
    """格 id -> 基线行（放行、通道）；同时返回每页总格数。"""
    cells, page_total = {}, Counter()
    for vol in ("01", "02", "03", "04", "05", "06", "07"):
        p = ct_dir / f"vol{vol}_base.jsonl.gz"
        if not p.exists():
            continue
        with gzip.open(p, "rt", encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                if d.get("header"):
                    continue
                cells[d["id"]] = d
                vol, page, _, _ = parse_id(d["id"])
                page_total[(vol, page)] += 1
    return {"cells": cells, "page_total": page_total}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ezio-dir", type=Path, default=DEFAULT_EZIO)
    ap.add_argument("--ct-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, default=HERE)
    args = ap.parse_args()

    rows = load_rows(args.ezio_dir)
    base = load_baseline(args.ct_dir)
    ids = [r["格"] for r in rows]
    dup = [k for k, v in Counter(ids).items() if v > 1]
    if dup:
        raise SystemExit(f"重复格号：{dup}")

    # 按册、页、列、格序排
    rows.sort(key=lambda r: (r["册"], int(r["页"]), int(r["列"]), r["格序"]))

    tsv_head = ["格号", "来源批", "Ezio分类", "Ezio原始类", "读到的字", "把握",
                "册", "页", "列", "格序", "页型", "格框宽高比", "基线表有无", "基线放行", "备注"]
    out_tsv = args.out_dir / "框问题148格合并表-208jn.tsv"
    with out_tsv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(tsv_head)
        for r in rows:
            b = base["cells"].get(r["格"])
            w.writerow([
                r["格"], r["来源批"], r["统一类"], r["原始类"], r["字"], r["把握"],
                r["册"], r["页"], r["列"], r["格序"], PAGE_TYPE_TODO, ASPECT_TODO,
                "有" if b else "无", ("放行" if b["admit"] else "待审") if b else "—",
                r["备注"],
            ])

    # 每页汇总
    per_page = defaultdict(lambda: Counter())
    for r in rows:
        per_page[(r["册"], r["页"])]["框问题"] += 1
        per_page[(r["册"], r["页"])][r["统一类"]] += 1
    page_rows = []
    for (vol, page), c in sorted(per_page.items(), key=lambda kv: (kv[0][0], int(kv[0][1]))):
        total = base["page_total"].get((vol, page), 0)
        n = c["框问题"]
        ratio = f"{n / total:.1%}" if total else "基线无此页"
        page_rows.append((vol, page, n, total, ratio, c["完整"], c["框截半字"], c["并框"], c["非字"], c["出不了图"]))

    cls_counts = Counter(r["统一类"] for r in rows)
    src_counts = Counter(r["来源批"] for r in rows)
    book_counts = Counter(r["册"] for r in rows)
    base_missing = [r["格"] for r in rows if r["格"] not in base["cells"]]

    out_md = args.out_dir / "框问题148格合并表-208jn.md"
    lines = [
        RECEIPT,
        "",
        "# 框问题 148 格合并表（GUJI-208jn，Emi，10-14 PDT）",
        "",
        "给 Ezio 208ji 框问题聚类用。来源：Ezio 的 `208io`（取不到候选 38 格）与 `208is`（切分坏 60＋非字 50 抽样）逐格分类，合并成一张表；每格补册／页／列／格序（由格号拆出）和基线表有无、放行。页型与格框宽高比**本次判不了，写「待证据」**（见下）。",
        "",
        "> 落盘：`框问题148格合并表-208jn.tsv`（逐格，148 行）；本 md 为汇总与说明。",
        "> 只读：不碰 products／事件／字形库；分类沿用 Ezio 的看图结果，不下结论、不判册字表。",
        "",
        "命令（同目录，只读）：",
        "```",
        "python3 框问题148格合并表-208jn.py --ct-dir <含 vol01–07_base.jsonl.gz 的目录>",
        "# cell_table 来自 guji-workspace 分支 claude/hint-ignore-dash-newadmit-1012 的 exports/cell_table/",
        "```",
        "",
        "## 一、待证据的两列（为什么）",
        "- **页型**：要看该页 `pages.json`／`row_segment` 产物里的夹注双行标记；这些产物不在本机（只在 Ethan 沙箱和正式工作区），本次无法判，全部写「待证据」，没有按 Ezio 的备注猜页型。",
        "- **格框宽高比**：用基线 cell_table 的 bbox，但 `cell_table` 里**没有 bbox 字段**（字段只有 id／admit／channel／char／iron／doubts／verdict／cov／provenance／step3_kind／sub；Ezio 的 `overlay_review.py` 注释也写明了这一点）。bbox 只在 cell_shrink 产物里，本机没有。Ezio 的 `图-208io`、`图-208is` 是拼图，也不能量出宽高。全部写「待证据」。",
        "- 要补这两列，需要 vol01–07 的 cell_shrink 产物（或其 bbox 导出）和各页 pages.json／row_segment；拿到后在脚本里把 `PAGE_TYPE_TODO`、`ASPECT_TODO` 换成读取即可。",
        "",
        "## 二、来源与分类计数",
        "| 来源批 | 格数 |",
        "|---|---|",
    ]
    for k in ("208io", "208is-切分坏", "208is-非字"):
        lines.append(f"| {k} | {src_counts.get(k, 0)} |")
    lines += [
        f"| **合计** | **{len(rows)}** |",
        "",
        "| 统一类 | 格数 | 说明 |",
        "|---|---|---|",
        f"| 完整 | {cls_counts.get('完整', 0)} | Ezio 判为完整单字 |",
        f"| 框截半字 | {cls_counts.get('框截半字', 0)} | 原「半字」 |",
        f"| 并框 | {cls_counts.get('并框', 0)} | 原「两字并框」「多字」（208io 的 #5 vol01:90:2:6 是「多字」） |",
        f"| 非字 | {cls_counts.get('非字', 0)} | |",
        f"| 出不了图 | {cls_counts.get('出不了图', 0)} | 原「无法对应」（几何与基线对不上，Ezio 没出图） |",
        "",
        f"基线 cell_table 里找不到的格：{len(base_missing)} 个 {base_missing if base_missing else ''}",
        "",
        "## 三、按册＋页汇总（框问题格数／该页总格数）",
        "该页总格数＝基线 cell_table 该页的格数（沙箱基线副本，非交付基线）；框问题格数＝本表该页行数（148 抽样池内）。比例是「抽样池格数／该页基线格数」，不是框问题率估计。",
        "",
        "| 册 | 页 | 框问题格 | 该页总格 | 比例 | 完整 | 框截半字 | 并框 | 非字 | 出不了图 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for vol, page, n, total, ratio, c1, c2, c3, c4, c5 in page_rows:
        lines.append(f"| {vol} | {page} | {n} | {total} | {ratio} | {c1} | {c2} | {c3} | {c4} | {c5} |")
    lines += [
        "",
        "各册框问题格数：" + "、".join(f"{k} {v}" for k, v in sorted(book_counts.items())),
        "",
        "## 四、说明",
        "- 格号格式 `vol:页:列:格序`；带 a／b 后缀的格（如 `vol01:89:9:20a`）原样保留。",
        "- 208io 的 `vol01:90:3:22`、`vol01:90:3:25` 在 Ezio 的几何里对不上基线（Ezio 原文），统一类为「出不了图」，基线表有无如实列出。",
        "- 同一个字被切成两个框的（如 vol01:131:6:2／131:6:3「品」，vol01:105:1:6a／7a「臣」）各是一行，不合并。",
        "",
    ]
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_tsv} ({len(rows)} rows)")
    print(f"wrote {out_md}")


if __name__ == "__main__":
    main()
