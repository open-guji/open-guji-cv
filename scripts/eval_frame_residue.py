# -*- coding: utf-8 -*-
"""Step2 版框残留：按 `column_border_trim` 自己的判档（a/b/c/d/e）分桶计数，
不额外发明像素判据（char-segmentation/frame-residue）。

    python scripts/eval_frame_residue.py --book vol02 [--pages 3-186] [--json out.json]

## 为什么不量「削完还剩多少残墨」

试过在削干净后的列图上自己写一把「连续 N 行墨占比 ≥ 阈值」的像素判据去分「干净/残留」，
拿 2026-09-26 vol02 列尾抽查页的 104 张人裁卡当真值标定：**精确率长期卡在 0.24~0.39**，
不管怎么调窗口/阈值——要么把干净列的最后一个字自己的墨也算成残留（宽松判据），要么因为
「残留贴着字、中间没有真空白」而整段被判成字身一起放过（严格判据）。104 卡里「新仍残留」
一类（b/bi 档，框粘字只削 3px，见下）里有 3/3 是真残留，恰好证明这类残留物理上就**贴着
字身没有间隙**——任何要求"残留和字之间有空白"的局部像素判据结构性看不见它们（与
cv-segmentation skill 里「腰斩」结构性判不出的道理相同：可观测量里没有区分信息）。

## 改用什么

`column_border_trim` 自己已经在判「这一段该怎么削」，分档就是它的判据强度：

| 档 | 意思 | 104 卡实测（n=74，列尾+列首） |
|---|---|---|
| a / a2 / a3 | 贴边整段削掉（最有把握） | 10/12 干净、1/12 仍切字（`t073_p51c1`「甚」，老问题未改）、1/12 仍残留 |
| b / bi | 框粘字，只削 3px（宁可留一点也不切字，**设计上就不会干净**） | 3/3 残留（100%） |
| c | 判定「没有可削的东西」 | 3/5 干净、2/5 残留（不可靠，无法只凭本判据分辨） |
| d / d2 / di | 内缩剥离，靠 Step1 位置证据或边距证据认线 | 39/49 干净、10/49 残留 |
| e | 薄高墨 + 持续低平底 | 4/5 干净、1/5 仍切字（`h057_p130c6`「易」，列首老问题未改） |

`t008_p33c2`（曾判「字被切掉」）本轮已修（`line_end` 半峰误触发，见 `column_projection.py`
`LAYER2_HALF_LOOKAHEAD` 注），上表按修后的现状记（算进 a 档「干净」，不算进「切字」）。

校准细节、口径、n=74（104 卡里的列尾/列首两类，末字块另计）见
`进度/Step3-逐字切分/14-两把尺子校准.md`（overview 仓）。**这张表本身就是「护栏」**——
下次全书跑批把 b/bi 档列数报出来，那就是"设计上留着的已知残留"，不需要每次都出图核对；
c 档列数报出来是"这批还没人看过、可能有残留也可能没有"的存量。

## 末字块挂满宽横线——已验证不可靠，本脚本不提供

同一批 104 卡里「末字块」30 张的像素判据（probe 18%、cov 0.85、连续 ≥4 行）精确率只有
0.241（22/30 触发，真正「挂线」只有 7/30）——绝大多数字自己的宽横画（五/王/一类）就会
触发。人裁结论也是"这份不能当缺陷数用"。本脚本不做这项，需要时用
`.claude/skills/review-artifact` skill 出审查页让人看。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from open_guji_cv.core.book import load_book  # noqa: E402
from open_guji_cv.core.step import page_key  # noqa: E402
from open_guji_cv.products import kinds as _k  # noqa: E402,F401
from open_guji_cv.products.store import ProductStore  # noqa: E402

# 104 卡校准表（2026-09-27，vol02，n=74，见 14-两把尺子校准.md）；
# 键是 trim.case 去掉数字后缀与 "i" 的主档字母。
RESIDUAL_RATE = {
    "a": 1 / 12,
    "b": 3 / 3,
    "c": 2 / 5,
    "d": 10 / 49,
    "e": 0 / 5,
}


def _base_case(case: str) -> str:
    """`a`/`a2`/`a3`/`ai`/`a3i`… 都归到主档字母 `a`。先剥 `i`（内框位置证据）
    后缀，再剥层数后缀——顺序反了会把 `a3i` 剥成 `a3`（`bi`/`ci` 这类没有数字
    后缀的能侥幸剥对，`a3i` 这种两个后缀都有的剥不干净，2026-09-27 实测踩过）。"""
    if case.endswith("i"):
        case = case[:-1]
    return case.rstrip("0123456789")


def _expand_pages(spec: str | None, all_pages: int) -> list[int]:
    if spec is None or spec == "all":
        return list(range(1, all_pages + 1))
    out: list[int] = []
    for part in spec.split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", required=True)
    ap.add_argument("--pages", default="all", help="3-186 之类；缺省全书")
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    store = ProductStore()
    bspec = load_book(a.book)
    # `--pages all` 曾经硬编码 max_page=300——全唐文冊页数超过 300，`--pages all`
    # 会悄悄漏掉 300 页之后的部分（任务卡 #54 第15条）。改成按书实际页数（`all_pages()`
    # 为空时退回 300，兜底旧行为，免得一本连 raw_dir 都没配全的书直接报错退出）。
    max_page = max(bspec.all_pages(), default=300)
    pages = _expand_pages(a.pages, max_page)

    tab: dict[str, Counter] = {"top": Counter(), "bottom": Counter()}
    b_glued: list[tuple[int, int, str]] = []
    c_unknown: list[tuple[int, int, str]] = []
    n_cols = 0
    for pg in pages:
        win = store.read(a.book, "column_warp", page_key(pg), "column_windows")
        if win is None or not win.columns:
            continue
        for cw in win.columns:
            n_cols += 1
            for end, trim in (("top", cw.trim_top), ("bottom", cw.trim_bottom)):
                base = _base_case(trim.case)
                tab[end][base] += 1
                if base == "b":
                    b_glued.append((pg, cw.col, end))
                elif base == "c":
                    c_unknown.append((pg, cw.col, end))

    report = {"book": a.book, "pages_scanned": len(pages), "n_columns": n_cols,
              "case_distribution": {k: dict(v) for k, v in tab.items()},
              "glued_b_bi_count": len(b_glued),
              "unknown_c_count": len(c_unknown)}

    expected_residual = 0.0
    for end in ("top", "bottom"):
        for base, n in tab[end].items():
            expected_residual += n * RESIDUAL_RATE.get(base, float("nan")) if base in RESIDUAL_RATE else 0
    report["expected_residual_columns_by_calibration"] = round(expected_residual, 1)

    print(f"{a.book}：扫了 {len(pages)} 页、{n_cols} 列")
    for end in ("top", "bottom"):
        print(f"  {end}: " + ", ".join(f"{k}={v}" for k, v in sorted(tab[end].items())))
    print(f"  b/bi（框粘字，设计上就有残留）：{len(b_glued)} 端")
    print(f"  c（判定无可削，可靠性 60/40，需要时人复核）：{len(c_unknown)} 端")
    print(f"  按 104 卡校准率估算全书残留端数：约 {report['expected_residual_columns_by_calibration']}")

    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
