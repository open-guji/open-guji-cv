# -*- coding: utf-8 -*-
"""实验十四：视觉大模型当切点选择器——在候选池里挑「切出来上下都是完整字」的那条。

输入：每条候选渲染成「切开后的上半 / 下半」并排编号（比画几条线在同一张图上直观得多）。
两种提示：blind（不告诉字）、hint（告诉整理本上字/下字——生产上 align_ref 能给）。
评分：模型挑中的候选与金标的最大 |dy| ≤ tol 算对；与现役选法、墨闸策略并列比。
结果按 (provider, hint) 缓存到 json，重跑不重复调用。

    python exp14_vlm_pick.py --pvg pvg.json --provider qwen [--hint] [--model qwen-vl-max]
"""
import argparse
import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from vlm_call import ask_vision  # noqa: E402

from open_guji_cv.core.spec import column_key  # noqa: E402
from open_guji_cv.core.step import page_key  # noqa: E402
from open_guji_cv.eval.touching import SHARD  # noqa: E402
from open_guji_cv.feedback.consumers import verdict_store  # noqa: E402
from open_guji_cv.products import kinds as _k  # noqa: E402,F401
from open_guji_cv.products.cache import ImageCache  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402

GAP = 14          # 上下半之间留白
TILE_H = 260      # 每个选项渲染高度（窗口按比例缩放）


def split_view(win: np.ndarray, seam: np.ndarray) -> np.ndarray:
    """按缝把窗口切成上半/下半两张（另一半涂白），竖着叠起来中间留白。"""
    h, w = win.shape
    ys = np.arange(h)[:, None]
    above = ys < seam[None, :]
    top = np.where(above, win, 255).astype(np.uint8)
    bot = np.where(~above, win, 255).astype(np.uint8)
    # 各自裁到墨的范围（留 4px），让模型看到的是「一个字」而不是半张白纸
    def crop(im):
        ink = np.where((im < 128).any(axis=1))[0]
        if len(ink) == 0:
            return im[:8]
        a, b = max(0, ink[0] - 4), min(h, ink[-1] + 5)
        return im[a:b]
    t, b = crop(top), crop(bot)
    gap = np.full((GAP, w), 235, np.uint8)
    out = np.vstack([t, gap, b])
    s = TILE_H / max(out.shape[0], 1)
    return cv2.resize(out, (max(1, int(w * s)), TILE_H), interpolation=cv2.INTER_AREA)


def build_sheet(win, seams, labels):
    tiles = []
    for k, sm in enumerate(seams, start=1):
        sv = split_view(win, sm)
        pad = np.full((TILE_H + 34, sv.shape[1] + 12, 3), 255, np.uint8)
        pad[30:30 + TILE_H, 6:6 + sv.shape[1]] = cv2.cvtColor(sv, cv2.COLOR_GRAY2BGR)
        cv2.putText(pad, f"#{k}", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 200), 2)
        cv2.rectangle(pad, (0, 0), (pad.shape[1] - 1, pad.shape[0] - 1), (160, 160, 160), 1)
        tiles.append(pad)
    h = max(t.shape[0] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, h - t.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255)) for t in tiles]
    sep = np.full((h, 10, 3), 255, np.uint8)
    row = [tiles[0]]
    for t in tiles[1:]:
        row += [sep, t]
    return np.hstack(row)


PROMPT_BLIND = (
    "这是中国古籍刻本竖排文字中相邻的上下两个字，它们的笔画粘连在一起。"
    "图中有 {n} 个切分方案（#1…#{n}），每个方案显示的是按该方案切开后的**上半部分**（上）和**下半部分**（下）。"
    "请判断哪个方案切出的上下两部分都是完整、正确的汉字——上字不缺笔画、下字不多出上字的笔画。"
    "只回答一个方案编号，格式：#k"
)
PROMPT_HINT = (
    "这是中国古籍刻本竖排文字中相邻的上下两个字，它们的笔画粘连在一起。"
    "根据整理本，上面的字应为「{up}」，下面的字应为「{dn}」。"
    "图中有 {n} 个切分方案（#1…#{n}），每个方案显示的是按该方案切开后的**上半部分**（上）和**下半部分**（下）。"
    "请判断哪个方案切出的上半部分是完整的「{up}」、下半部分是完整的「{dn}」。"
    "只回答一个方案编号，格式：#k"
)


def parse_pick(text: str, n: int):
    m = re.search(r"#\s*(\d+)", text or "")
    if not m:
        m = re.search(r"(\d+)", text or "")
    if not m:
        return None
    k = int(m.group(1))
    return k if 1 <= k <= n else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pvg", required=True)
    ap.add_argument("--provider", default="qwen")
    ap.add_argument("--model", default=None)
    ap.add_argument("--hint", action="store_true")
    ap.add_argument("--tol", type=float, default=6.0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--save-sheets", default=None, help="目录：存每条的清单图供人核对")
    a = ap.parse_args()

    rows = json.load(open(a.pvg, encoding="utf-8"))
    pt = {(str(i.anchor.book), int(i.anchor.page)): (i.expected or {}).get("page_type")
          for i in verdict_store().list("page-type", legacy=False) if i.anchor.page is not None}
    sel = [r for r in rows if r["n_cand"] >= 2 and r["book"] != "vol03"
           and pt.get((r["book"], int(r["id"].split(":")[1]))) == "body"]
    if a.limit:
        sel = sel[:a.limit]
    gold = {f"{i.anchor.book}:{i.anchor.page}:{i.anchor.col}:{i.anchor.slot}": (i.expected or {})
            for i in verdict_store().list(SHARD)}
    st, ic = ProductStore(), ImageCache()
    tag = f"{a.provider}_{(a.model or 'default').replace('-', '')}_{'hint' if a.hint else 'blind'}"
    cache_p = Path(a.pvg).with_name(f"exp14_{tag}.json")
    cache = json.load(open(cache_p, encoding="utf-8")) if cache_p.exists() else {}
    if a.save_sheets:
        Path(a.save_sheets).mkdir(parents=True, exist_ok=True)

    T = a.tol
    n_hit = n_cur = n_ans = 0
    n_ok_hit = n_ok_tot = n_mv_hit = n_mv_tot = 0
    for r in sel:
        cid = r["id"]
        b, pg, col, slot = cid.split(":")
        pg, col, slot = int(pg), int(col), int(slot)
        cells = st.read(b, "row_segment", page_key(pg), "cells")
        cc = next((c for c in cells.columns if c.col == col), None)
        cm = {c.slot: c for c in cc.cells if c.sub is None}
        up, dn = cm.get(slot), cm.get(slot + 1)
        cp = next((x for x in (cc.cut_candidates or []) if x.slot_above == slot), None)
        if up is None or dn is None or cp is None:
            continue
        img = cv2.imread(str(ic.get(b, "column_image", column_key(pg, col))), 0)
        x0, x1 = (int(round(v)) for v in cc.content_x)
        y0, y1 = int(max(0, up.y0)), int(min(img.shape[0], dn.y1))
        w = x1 - x0
        win = img[y0:y1, x0:x1]
        seams = []
        for c in cp.candidates:
            sm = np.full(w, float(cp.y)) if c.y is None else np.asarray(c.y, float)
            if len(sm) != w:
                sm = np.interp(np.linspace(0, len(sm) - 1, w), np.arange(len(sm)), sm)
            seams.append(sm - y0)
        n = len(seams)
        errs = [e for _, e, _ in r["cands"]]
        g = gold.get(cid, {})
        if cid not in cache:
            sheet = build_sheet(win, seams, [c.kind for c in cp.candidates])
            if a.save_sheets:
                cv2.imwrite(str(Path(a.save_sheets) / f"{cid.replace(':', '_')}.png"), sheet)
            if a.hint:
                prompt = PROMPT_HINT.format(n=n, up=g.get("char_above") or "？", dn=g.get("char_below") or "？")
            else:
                prompt = PROMPT_BLIND.format(n=n)
            res = ask_vision(a.provider, prompt, [sheet], model=a.model, max_tokens=30)
            cache[cid] = {"text": res.get("text"), "error": res.get("error"), "n": n,
                          "elapsed": res.get("elapsed"), "usage": res.get("usage")}
            json.dump(cache, open(cache_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        ans = cache[cid]
        pick = parse_pick(ans.get("text"), n)
        e_pick = errs[pick - 1] if pick else None
        hit = e_pick is not None and e_pick <= T
        cur_hit = r["chosen_err"] <= T
        n_hit += hit; n_cur += cur_hit; n_ans += pick is not None
        if r["verdict"] == "ok":
            n_ok_tot += 1; n_ok_hit += hit
        else:
            n_mv_tot += 1; n_mv_hit += hit
        kinds = [k for k, _, _ in r["cands"]]
        print(f"  {cid:18s} n={n} VLM=#{pick} ({kinds[pick-1] if pick else '-'}:{e_pick if e_pick is not None else '-'}) "
              f"cur={r['chosen_kind']}:{r['chosen_err']:.0f} best={r['best_kind']}:{r['best_err']:.0f} "
              f"{'✓' if hit else '✗'}{'(cur✓)' if cur_hit else ''} v={r['verdict']} [{(ans.get('text') or ans.get('error') or '')[:20]}]")
    N = len(sel)
    print(f"\n=== {tag} ===  n={N} 有答 {n_ans}")
    print(f"  VLM 命中 {n_hit}/{N} ({n_hit/N:.0%})   现役 {n_cur}/{N} ({n_cur/N:.0%})")
    print(f"  ok 组 {n_ok_hit}/{n_ok_tot}   moved/cand 组 {n_mv_hit}/{n_mv_tot}")


main()
