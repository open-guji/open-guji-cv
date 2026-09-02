# -*- coding: utf-8 -*-
"""把 Step2 已经处理好、且**过了金标**的列推给 Step3 当输入。

    python scripts/export_step3_input.py --book vol01 \\
        --gold ../open-guji-dataset/char-segmentation/column-warp \\
        -o output/vol01/step3_input [--tier gold|gate]

产物：`<out>/<page>/c<N>.png`（`clean_column` 的输出）+ `<out>/manifest.json`。

## 为什么要有这一步

Step3 那一轮实测的最大瓶颈不是 Step3 自己，是上游连坐：40 页里 13 页
Step1 没把列切对，Step3 拿到的**根本不是一列**，逐格全对率从 27/29 掉到
8/21、fp 从 2 涨到 72。把这类列混在输入里，量出来的 Step3 准确率说明不了
Step3 准不准。所以这里先立一道准入闸，只把「确实是一列、且人核校过」的
推过去。

## 准入闸：三级，逐级独立

**L1 页级 —— Step1 有没有把这一页切对列**。判据只用几何：探出 9 列、且每列
矫正图宽度都在本页中位数 ±15% 内（跟 Step3 那节做分层用的是同一条，不另立
门户）。这是**页级**的：一页里只要有一条竖直线探错，整页的列编号和窗口一起
错位，同页其它列也不能单独救。14 页里 vol01/47 被这条挡下（列宽
`[192,187,184,186,197,197,224,212,185]`，224/192=1.17 超线）。

**L2 列级自检 —— 这一列两侧有没有「墨量归零」的边界**。量的是原始（未抹侧）
投影在两侧外 25% 范围内的**最低墨占比**，门槛 `SIDE_FLOOR_MAX=0.012`。
⚠️ **2026-09-02 扩金标后已证实：这条判据分不开 clean/mixed，别当真能筛
东西**——继续留着只是因为它至少不会误杀已知的 clean 列，见下面负结果 3。

## 记下来的负结果：L2 这条自检**几乎没有独立筛选力**（现在知道是结构性的，不是样本小）

试过三条列级判据，全部不成立或不够用：

1. **「清理后带内靠边 12px 的残墨」是循环论证** —— 带边界本来就是按"墨量
   接近 0"挑的，量它必然小。实测两条 `mixed` 列 0.008/0.003，反而比一批
   `clean` 列（最高 0.088）还低。**不能用**。
2. **「带宽偏离本页中位数」区分不出来** —— 126 列的偏离 p95 只有 5.5%、
   最大 19.5%，最大的那条恰是人判 clean 的列。
3. **「两侧最低墨」（现在的 L2）曾经能分开，扩金标之后分不开了，而且是
   结构性分不开**：clean 上限 0.0111 vs mixed 下限 **0.0044**
   （vol01/151 c4）——跟一条 clean 列（vol01/141 c1，同样 0.0044）
   **分数完全一样**。根因不是阈值没调好，是这条判据**只看两侧外 25%**，
   而两种真实污染都不贴边：`vol01/151 c4` 是弯界行只探进列**中段**；
   `vol02/3 c9`（vol02 首次抽样金标测出来的）是**背景印章导致整列散布
   噪点**，同样不集中在边缘。这两种污染 `side_floor` 天生看不见——护栏
   `tests/test_export_step3_input.py::test_side_floor_cannot_see_whole_column_contamination`
   把这条焊死，`test_gate_threshold_still_separates_the_human_verdicts`
   改成了 `xfail(strict=True)`（留活证据：谁要是手滑调阈值让它"又通过了"，
   strict xfail 会立刻报警，而不是被当成判据修好了）。

**结论没变，只是证据更硬了：目前唯一经过验证的筛选力来自 L1（页级列切
分）。** L2 现在的作用只是"至少不会误杀已知 clean 列"，不是真的能拦 mixed。
要拦"背景印章"/"局部弯界行"这类不贴边的污染，得要一条**跟"两侧墨量"完全
不同维度**的判据（比如整列噪点密度、连通域碎片数），不是在现有指标上
调参或扩样本能解决的——`mixed` 样本已经从 n=2 扩到 n=11、覆盖四种不同
机制，指标依然分不开，说明问题出在指标本身的设计范围，不是标注量不够。

## 两条口径约定（Step3 侧要知道）

1. **页级共享量用该页「全部 9 列」算，不是只用准入的那几列**。
   `period`（`estimate_shared_period`）和 `ref_w`（列内容窗口宽度中位数）
   的设计前提就是"同页多列取中位数比单列自估稳"。一页只准入 2 列时，拿这
   2 列算中位数等于退回单列自估，把这两个量的意义抹掉了。页面既然过了 L1，
   9 列在几何上都是"一列"，都可以进中位数——**准入闸管的是"哪些列推过去
   切"，不是"哪些列参与算页级先验"**。
2. **`content_x` 必须随图传**。Step2 交出来的是**抹白不裁切**的图（坐标系是
   Step3/Step4 共用的锚，裁一刀所有挂在上面的坐标全漂），界行的墨已经没了；
   于是 Step3 内部的 `find_content_window` 在这张图上**一堵墙也找不到**，
   24 列无一例外返回整幅宽度——实测比 Step2 定出来的文字带宽 9.6%（最大
   17.0%）。manifest 里的 `content_x` 就是那条带，调用方应当拿它覆盖。

   影响量过了，**比预想小**：拿整幅宽跑 vs 裁到带内跑，24 列里只有 1 列
   （vol01/51 c1）的格类型分类不同，空白格 19 ↔ 20，其余 23 列逐格类型
   完全一致。而且方向跟"窗口变宽 → `blank_thresh_frac × dst_w` 抬高 →
   多判空白"这个直觉**相反**（宽窗口反而少判一格），说明它不是单调地走
   空白阈值那条路。所以这条口径**不是紧急的正确性问题**，是一条该说清楚
   的接口约定——但既然带是 Step2 定出来的，就没道理让 Step3 再猜一遍。

`border_top`/`border_bottom` 直接沿用 `windows.json` 的
`border_top_in_column`/`border_bottom_in_column`：抹白不改坐标，版框线的 y
还在原处（只是墨被抹掉了）。抬头列按 Step3 定的口径给
`top_slack = border_top`（开到列图顶端）。

`n_body_slots` 是版式常量（这两册 21）；`n_raised` **不猜**——`raised` 只是
几何标记（"这一格伸到版框线以上了"），vol01/33 col4 就是抬头但格数不变
（`n_raised=0`）。manifest 只给几何事实 `raised` / `head_raise_inner_y`，
该给几个格由调用方按版式先验或人工核校定，理由见 Step3 那节。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from open_guji_cv.utils.column_projection import (  # noqa: E402
    clean_column, column_profile, denoise_column,
)
from open_guji_cv.utils.row_boundaries import (  # noqa: E402
    estimate_shared_period, row_ink_projection,
)

EXPECTED_COLS = 9        # 版式常量（这两册）
WIDTH_TOL = 0.15         # L1：列宽偏离本页中位数的上限
SIDE_FLOOR_LOOK = 0.25   # L2：从两侧各看进去多少比例的宽度
SIDE_FLOOR_MAX = 0.012   # L2：那段里的最低墨占比上限
N_BODY_SLOTS = 21        # 版式常量（这两册）


def load_gold(gold_dir: Path | None) -> dict[tuple[str, str, int], dict]:
    if gold_dir is None:
        return {}
    out = {}
    for f in sorted((gold_dir / "samples").glob("*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        out[(d["book"], d["page"], d["col"])] = d
    return out


def gold_admits(g: dict | None) -> tuple[bool, str]:
    if g is None:
        return False, "还没标过金标"
    if not g.get("text_band"):
        return False, "金标里文字带待重标（只有 border_class）"
    if g.get("verdict") != "clean":
        return False, f"人裁 verdict={g.get('verdict')}（界行残墨与字身分不开）"
    idk = [e for e, v in (g.get("border_class") or {}).items() if v == "idk"]
    if idk:
        return False, f"人裁 border_class {'/'.join(idk)} = idk（没看清）"
    return True, ""


def side_floor(warped: np.ndarray) -> float:
    """两侧各外 25% 里的最低墨占比，取两侧较大者。原始图上量，不是清理后。"""
    prof = column_profile(warped)
    k = max(1, int(round(SIDE_FLOOR_LOOK * len(prof))))
    return max(float(prof[:k].min()), float(prof[-k:].min()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="vol01")
    ap.add_argument("--src", default=None, help="Step2 列图根目录（默认 output/<book>/step2_columns）")
    ap.add_argument("--gold", default=None, help="column-warp 金标目录")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--tier", choices=["gold", "gate"], default="gold")
    args = ap.parse_args()

    src = Path(args.src) if args.src else ROOT / "output" / args.book / "step2_columns"
    out = Path(args.out) if args.out else ROOT / "output" / args.book / "step3_input"
    gold = load_gold(Path(args.gold) if args.gold else None)
    if args.tier == "gold" and not gold:
        raise SystemExit("--tier gold 需要 --gold 指向 column-warp 金标目录")

    pages = []
    n_written = 0
    for wf in sorted(src.glob("*/windows.json"), key=lambda p: int(p.parent.name)):
        d = json.loads(wf.read_text(encoding="utf-8"))
        page = wf.parent.name
        wins = d["columns"]
        widths = [c["warped_size"]["width"] for c in wins]
        med_w = statistics.median(widths)
        bad_w = [c["col"] for c, w in zip(wins, widths)
                 if abs(w - med_w) > WIDTH_TOL * med_w]
        page_reject = []
        if len(wins) != EXPECTED_COLS:
            page_reject.append(f"L1：只探出 {len(wins)} 列（版式应为 {EXPECTED_COLS}）")
        if bad_w:
            page_reject.append(
                f"L1：列宽偏离本页中位数 {med_w:.0f}px 超过 ±{WIDTH_TOL:.0%} 的列 "
                f"{bad_w}（{[widths[c['col'] - 1] for c in wins if c['col'] in bad_w]}）")

        # 逐列清理（页级先验要用全部列，所以不管准不准入都先算）
        cols, projs, borders, dst_ws, band_ws = [], [], [], [], []
        for c in wins:
            raw = denoise_column(cv2.imread(str(wf.parent / c["file"]), cv2.IMREAD_GRAYSCALE))
            cleaned, diag = clean_column(raw)
            b0, b1 = diag["band"]
            bt = float(c["border_top_in_column"])
            bb = float(c["border_bottom_in_column"])
            projs.append(row_ink_projection(cleaned, b0, b1))
            borders.append((bt, bb))
            dst_ws.append(b1 - b0)
            band_ws.append(b1 - b0)
            cols.append(dict(win=c, img=cleaned, band=(b0, b1), diag=diag,
                             border=(bt, bb), floor=side_floor(raw)))

        # 页级共享量：用**全部 9 列**算，理由见模块头「两条口径约定」第 1 条
        period = ref_w = None
        if not page_reject:
            try:
                period = round(float(estimate_shared_period(projs, borders, dst_ws)), 2)
            except ValueError as e:
                page_reject.append(f"L1：页级周期估不出来（{e}）")
            ref_w = float(statistics.median(band_ws))

        page_ok = not page_reject
        recs = []
        for c in cols:
            w = c["win"]
            col = w["col"]
            g = gold.get((args.book, page, col))
            ok_gold, why_gold = gold_admits(g)
            ok_gate = c["floor"] <= SIDE_FLOOR_MAX
            reasons = list(page_reject)
            if not ok_gate:
                reasons.append(f"L2：两侧最低墨 {c['floor']:.4f} > {SIDE_FLOOR_MAX}"
                                "（找不到墨量归零的边界）")
            if args.tier == "gold" and not ok_gold:
                reasons.append(f"L3：{why_gold}")
            admitted = page_ok and ok_gate and (ok_gold or args.tier == "gate")
            b0, b1 = c["band"]
            bt, bb = c["border"]
            rec = dict(
                col=col, admitted=admitted, reject=reasons,
                tier=("gold" if ok_gold else ("gate" if ok_gate and page_ok else None)),
                content_x=[int(b0), int(b1)],
                border_top=bt, border_bottom=bb,
                top_slack=(bt if w["raised"] else 0.0),
                raised=bool(w["raised"]),
                head_raise_inner_y=w["head_raise_inner_y"],
                warped_size=w["warped_size"],
                border_case={"top": c["diag"]["top"]["case"],
                              "bottom": c["diag"]["bottom"]["case"]},
                border_trim_px={"top": c["diag"]["top"]["px"],
                                 "bottom": c["diag"]["bottom"]["px"]},
                side_floor=round(c["floor"], 4),
                gold=({"verdict": g.get("verdict"),
                       "border_class": g.get("border_class")} if g else None),
            )
            if admitted:
                dst = out / page
                dst.mkdir(parents=True, exist_ok=True)
                cv2.imwrite(str(dst / f"c{col}.png"), c["img"])
                rec["file"] = f"{page}/c{col}.png"
                n_written += 1
            recs.append(rec)

        pages.append(dict(page=page, admitted=page_ok, reject=page_reject,
                          period=period, ref_w=ref_w,
                          column_widths=widths, median_width=med_w,
                          columns=recs))

    out.mkdir(parents=True, exist_ok=True)
    manifest = dict(
        producer="open-guji-cv scripts/export_step3_input.py",
        source=str(src.relative_to(ROOT)),
        book=args.book, tier=args.tier,
        n_body_slots=N_BODY_SLOTS,
        gate=dict(expected_cols=EXPECTED_COLS, width_tol=WIDTH_TOL,
                  side_floor_look=SIDE_FLOOR_LOOK, side_floor_max=SIDE_FLOOR_MAX),
        contract=[
            "图是 clean_column 的输出：抹白不裁切，坐标系跟 Step2 矫正图完全一致，"
            "border_top/border_bottom 仍是版框线原来的 y（墨被抹掉了，位置没动）。",
            "content_x 是 Step2 定出来的文字带，调用方必须拿它覆盖 Step3 内部的 "
            "find_content_window——界行墨已经被抹掉，那个函数在这张图上找不到墙、"
            "会返回整幅宽度（实测宽 10%~13%）。",
            "period / ref_w 是页级共享量，用该页**全部 9 列**算的（准入闸管的是"
            "哪些列推过去切，不是哪些列参与算页级先验）。",
            "n_raised 不给：raised 只是几何标记，抬头列可能多一格也可能不多，"
            "纯信号判据不可靠（见 row_boundaries_design.md「抬头列」节），"
            "由调用方按版式先验/人工核校定。",
        ],
        pages=pages,
    )
    (out / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    n_pages_ok = sum(1 for p in pages
                     if any(c["admitted"] for c in p["columns"]))
    n_cols = sum(len(p["columns"]) for p in pages)
    print(f"tier={args.tier}  推出 {n_written} 列 / {n_pages_ok} 页（有列可推的页）"
          f"（源：{n_cols} 列 / {len(pages)} 页）→ {out}")
    for p in pages:
        adm = [c["col"] for c in p["columns"] if c["admitted"]]
        if p["admitted"]:
            print(f"  {p['page']:>4} period={p['period']:>6} ref_w={p['ref_w']:>5.0f}"
                  f"  推 {len(adm)}/{len(p['columns'])} 列 {adm}")
        else:
            print(f"  {p['page']:>4} ✗ {'; '.join(p['reject'])}")
    if args.tier == "gold":
        held = {}
        for p in pages:
            if not p["admitted"]:
                continue
            for c in p["columns"]:
                if not c["admitted"]:
                    held[c["reject"][-1].split("：", 1)[-1]] = \
                        held.get(c["reject"][-1].split("：", 1)[-1], 0) + 1
        print("\n准入页上被扣下的列，按理由：")
        for why, n in sorted(held.items(), key=lambda kv: -kv[1]):
            print(f"  {n:>3}  {why}")


if __name__ == "__main__":
    main()
