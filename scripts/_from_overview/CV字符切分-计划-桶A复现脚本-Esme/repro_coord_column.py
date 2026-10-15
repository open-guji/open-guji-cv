#!/usr/bin/env python3
"""桶 A 只读复现：给定一册一页一列，重现 align_ref_coord.coord_column 的配位过程，
逐个候选起点报「被哪条闸拒」及数值。

只读：不写 products、不改 cv 代码；cv 代码 import 后以参数喂入。

输入
  --products ROOT   products 根（含 <book>/glyph_match 与 <book>/row_segment 等）
  --book vol04  --page 130  --col 5
  整理本这一行（三选一）：
    --ref-file F      文件里的第一行（光盘版写法，<右行|左行> 或 <整段> 表示夹注）
    --ref-text S      同上，直接给字符串
    --ref-pattern P   占位：只给「字位单元的类型序列」，如 "5c3n11c"＝5 个正文、3 个夹注单元、11 个正文。
                      占位只能诊断几何／类型，不能诊断载体吻合（吻合数一律 0）。
  --cells-step      cells 产物所在步目录，缺省依次试 row_segment_runs、row_segment
  --selftest        自测：用 --products/--book 下一列已 coord 成功的列，造整理本，期望不被任何闸拒
输出  单元表、逐起点拒因表、拒因计数、真实 coord_column 的返回。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def _imports():
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.steps import align_ref_coord as C
    from open_guji_cv.steps.align_ref import carrier_fn
    return ProductStore, C, carrier_fn


def load_units(root: str, book: str, page: int, col: int, cells_step: str | None,
               cells_only: bool = False):
    ProductStore, C, carrier_fn = _imports()
    st = ProductStore(Path(root))
    key = f"p{page:04d}"
    match = st.read(book, "glyph_match", key, "glyph_match")
    if match is None and not cells_only:
        sys.exit(f"读不到 {book}/glyph_match/{key}.json（本册该页没有 glyph_match 产物；"
                 f"只想看几何／类型可加 --cells-only）")
    cells = None
    for sd in ([cells_step] if cells_step else ["row_segment_runs", "row_segment"]):
        cells = st.read(book, sd, key, "cells")
        if cells is not None:
            break
    if cells is None:
        sys.exit(f"读不到 {book}/{cells_step or 'row_segment(_runs)'}/{key}.json（cells）")
    cc = cells.column(col)
    if cc is None:
        sys.exit(f"cells 里没有第 {col} 列")
    if cells_only:
        return C, _units_from_cells(C, book, page, col, cc), None, cc
    mc = match.column(col)
    if mc is None or not mc.chars:
        sys.exit(f"glyph_match 里没有第 {col} 列的格（col 不存在或整列无字格）")
    carrier = carrier_fn(match, None, None)
    units = C.column_units(book, page, col, mc, cc, carrier)
    return C, units, mc, cc


def _units_from_cells(C, book, page, col, cc):
    """只有 cells（Step3）时的近似：照 column_units 的几何口径，但格取 cells 里除 blank 外的全部格
    （按 column_units 文档「Step3 判 blank 的格不进 glyph_match」；glyph_match 若还有别的丢格规则，这里没有），
    载体字为空。只用来看几何／类型。"""
    per, top = float(cc.period), float(cc.border_top or 0.0)
    by, order = {}, []
    for c in cc.cells:
        if c.kind == "blank":          # glyph_match 不收 Step3 判 blank 的格（column_units 文档）
            continue
        g = ((c.y0 + c.y1) / 2.0 - top) / per + 0.5
        sub = c.sub or ""
        if sub:
            u = by.get(c.slot)
            if u is None:
                u = C.CellUnit("n", c.slot, g, {}, {})
                by[c.slot] = u
                order.append(c.slot)
            u.ids[sub] = f"{book}:{page}:{col}:{c.slot}{sub}"
            u.carrier[sub] = ""
        else:
            by[c.slot] = C.CellUnit("c", c.slot, g, {"": f"{book}:{page}:{col}:{c.slot}"}, {"": ""})
            order.append(c.slot)
    units = [by[s] for s in order]
    units.sort(key=lambda u: u.g)
    return units


def parse_pattern(pat: str):
    C = _imports()[1]
    units = []
    for n, k in re.findall(r"(\d+)([cn])", pat):
        for _ in range(int(n)):
            units.append(C.Unit(k, "〇", "〇" if k == "n" else ""))
    return C.RefLine(idx=0, units=units, han_start=0, text="〇" * len(units))


def fit_free(pos, g):
    """与 C._fit 同式，但不卡斜率范围，用来报原始斜率。"""
    n = len(pos)
    if n < C_SLOPE_MIN_N or max(pos) == min(pos):
        r = sorted(gi - p for gi, p in zip(g, pos))
        return 1.0, r[n // 2], True
    mp, mg = sum(pos) / n, sum(g) / n
    a = sum((p - mp) * (gi - mg) for p, gi in zip(pos, g)) / sum((p - mp) ** 2 for p in pos)
    return a, mg - a * mp, True


C_SLOPE_MIN_N = 5


def diagnose(C, units, line):
    global C_SLOPE_MIN_N
    C_SLOPE_MIN_N = C.COORD_SLOPE_MIN_N
    text = line.text_units()
    L = len(text)
    kinds = [u.kind for _p, u in text]
    pos = [p for p, _u in text]
    out = []
    print(f"\n整理本字位单元 L={L}（正文 {kinds.count('c')}／夹注 {kinds.count('n')}）；格单元 {len(units)}")
    if len(units) < L:
        print(f"→ 格数少于整理本字数（{len(units)} < {L}），coord_column 在此直接退回（另一条串）")
        return out
    cnt = {"类型对不上": 0, "斜率越界": 0, "残差超限": 0, "段外格太近": 0, "通过": 0}
    print(f"\n{'起点j':>4} {'结果':<8} 说明")
    for j in range(0, len(units) - L + 1):
        run = units[j:j + L]
        rk = [u.kind for u in run]
        if rk != kinds:
            first = next(i for i in range(L) if rk[i] != kinds[i])
            cnt["类型对不上"] += 1
            print(f"{j:>4} {'类型':<8} 第 {first} 位：格 {rk[first]}(slot {run[first].slot}) ≠ 整理本 {kinds[first]}")
            out.append((j, "类型", first))
            continue
        a, b, _ = fit_free(pos, [u.g for u in run])
        if not C.COORD_SLOPE[0] <= a <= C.COORD_SLOPE[1]:
            cnt["斜率越界"] += 1
            print(f"{j:>4} {'斜率':<8} a={a:.3f} 不在 {C.COORD_SLOPE}")
            out.append((j, "斜率", a))
            continue
        res = [(abs(u.g - (a * p + b)), u.slot) for u, p in zip(run, pos)]
        mr, ms = max(res)
        if mr > C.COORD_MAX_RESID:
            cnt["残差超限"] += 1
            print(f"{j:>4} {'残差':<8} 最大 {mr:.2f} 行（slot {ms}）> {C.COORD_MAX_RESID}；a={a:.3f} b={b:.2f}")
            out.append((j, "残差", mr))
            continue
        extras = units[:j] + units[j + L:]
        near = [(min(abs(u.g - (a * p + b)) for p in pos), u.slot) for u in extras]
        bad = [(d, s) for d, s in near if d <= C.COORD_OUTSIDE_MARGIN * a]
        if bad:
            cnt["段外格太近"] += 1
            d, s = min(bad)
            print(f"{j:>4} {'段外':<8} 多出的格 {len(extras)} 个，其中 {len(bad)} 个离字位 ≤{C.COORD_OUTSIDE_MARGIN*a:.2f} 行（最近 slot {s}：{d:.2f} 行）")
            out.append((j, "段外", d))
            continue
        cnt["通过"] += 1
        print(f"{j:>4} {'通过':<8} 残差 {mr:.2f}，多出格 {len(extras)} 个，最近 {min((d for d,_ in near), default=float('nan')):.2f} 行；a={a:.3f}")
        out.append((j, "通过", mr))
    print("\n拒因计数：" + "，".join(f"{k} {v}" for k, v in cnt.items()))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--products", required=True)
    ap.add_argument("--book", required=True)
    ap.add_argument("--page", type=int, required=True)
    ap.add_argument("--col", type=int, required=True)
    ap.add_argument("--cells-step")
    ap.add_argument("--cells-only", action="store_true",
                    help="没有 glyph_match 产物时只用 cells（Step3）：近似，blank 格也算单元，无载体")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--ref-file")
    g.add_argument("--ref-text")
    g.add_argument("--ref-pattern")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    C, units, mc, cc = load_units(a.products, a.book, a.page, a.col, a.cells_step, a.cells_only)
    print(f"{a.book} p{a.page} 第{a.col}列：Step3 cells {len(cc.cells)} 个（正文槽位 n_body_slots={cc.n_body_slots}，period={cc.period}）；"
          + (f"glyph_match 字格 {len(mc.chars)} 个 → 格单元 {len(units)} 个（Step3 判 blank 的格不在 glyph_match，不进单元）"
             if mc is not None else f"[--cells-only 近似] 格单元 {len(units)} 个（已去 blank 格，无载体）"))
    print(f"{'#':>3} {'kind':<4} {'slot':>4} {'g(行)':>7}  载体")
    for i, u in enumerate(units):
        print(f"{i:>3} {u.kind:<4} {u.slot:>4} {u.g:>7.2f}  {dict(u.carrier)}")

    if a.selftest:
        # 造整理本：按本列单元的类型与载体字，应当至少一个起点通过
        ref = []
        for u in units:
            if u.kind == "c":
                ref.append(C.Unit("c", u.carrier.get("", "〇") or "〇"))
            else:
                ref.append(C.Unit("n", u.carrier.get("a", "〇") or "〇", u.carrier.get("b", "〇") or "〇"))
        line = C.RefLine(idx=0, units=ref, han_start=0, text="".join(x.a + x.b for x in ref))
        print("\n[自测] 整理本＝本列载体自身；期望：通过")
    elif a.ref_pattern:
        line = parse_pattern(a.ref_pattern)
        print(f"\n[占位] 整理本类型序列 {a.ref_pattern}：只诊断类型／几何，载体吻合不可用")
    else:
        raw = a.ref_text if a.ref_text is not None else (
            Path(a.ref_file).read_text(encoding="utf-8").splitlines()[0] if a.ref_file else None)
        if raw is None:
            sys.exit("请给 --ref-file／--ref-text／--ref-pattern 之一")
        lines = C.parse_lines(raw)
        if not lines:
            sys.exit("整理本行解析为空")
        line = lines[0]

    diagnose(C, units, line)
    res = C.coord_column(units, line)
    print(f"\n真实 coord_column 返回：ok={res.ok}，note={res.note!r}，吻合={res.agree}，合并救援={res.merged}")
    if a.selftest and not res.ok:
        print("[自测] 未通过：本列载体自身都配不上，脚本或数据有问题", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
