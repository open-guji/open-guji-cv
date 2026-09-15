# -*- coding: utf-8 -*-
"""重跑前后产物对比：Step3 切法改了多少、下游定字动了多少、金标上好了还是坏了。

    python experiments/touch_resolve/compare_rerun.py --book vol02 --pages 1-50 --before <快照目录>

`--before` 是重跑前从 workspace products 拷出来的 `<step>/pNNNN.json`（row_segment / cell_shrink / glyph_match / context_decide）。
对比项：
  1. Step3：切点按 (slot_above, slot_below) 对齐；候选池大小、过裁判（agree 非空）、chosen_by 分布、改选方向、格线（boundaries）是否一致；
  2. 下游：context_decide 每个字位的 `char` 前后是否一致，分「切法改过的切点两侧格」与「其他格」两组报；glyph_match verdict 变化；
  3. 金标：touching-cuts 里落在这些页、frame_ok 的切点，前后切法对金标缝的错归属墨像素（尺子同实验三）；
  4. 图：改选的切点前 24 条，红=旧 绿=新 蓝=金标（有则画）。
产出 out/compare_rerun/<book>_<pages>/summary.json、changed.png。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import INK_TH, OUT_ROOT, jdump  # noqa: E402
from exp3_partition_eval import err_stats  # noqa: E402
from open_guji_cv.core.spec import column_key  # noqa: E402
from open_guji_cv.core.workspace import products_root  # noqa: E402
from open_guji_cv.eval.touching import SHARD, polyline_to_seam  # noqa: E402
from open_guji_cv.feedback.consumers import verdict_store  # noqa: E402
from open_guji_cv.gold.store import GoldStore  # noqa: E402
from open_guji_cv.products.cache import ImageCache  # noqa: E402
from open_guji_cv.utils.cut_select import owner_from_seam  # noqa: E402


def parse_pages(expr: str) -> list[int]:
    out = []
    for part in expr.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def load(dirp: Path, step: str, page: int):
    f = dirp / step / f"p{page:04d}.json"
    if not f.exists():
        return None
    d = json.loads(f.read_text(encoding="utf-8"))
    return next(iter(d.values())) if len(d) == 1 else d


def seam_of(col, cp, cand):
    x_lo, x_hi = col["content_x"]
    n = int(round(x_hi - x_lo))
    if cand.get("y") is None:
        return np.full(n, int(round(cp["y"])))
    return np.asarray(cand["y"], dtype=int)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", default="vol02")
    ap.add_argument("--pages", default="1-50")
    ap.add_argument("--before", required=True)
    a = ap.parse_args()
    before = Path(a.before)
    after = products_root() / a.book
    pages = parse_pages(a.pages)
    out = OUT_ROOT / "compare_rerun" / f"{a.book}_{a.pages.replace(',', '_')}"
    out.mkdir(parents=True, exist_ok=True)
    ic = ImageCache()

    st3 = Counter()
    changed = []            # (page, col, cp_before, cp_after, col_after)
    changed_ids = set()     # 切法改过的切点两侧格 id
    for pg in pages:
        b3, a3 = load(before, "row_segment", pg), load(after, "row_segment", pg)
        if b3 is None or a3 is None:
            st3["page_missing"] += 1
            continue
        bcols = {c["col"]: c for c in b3["columns"]}
        for col in a3["columns"]:
            bc = bcols.get(col["col"])
            if bc is None or not col.get("ok") or not bc.get("ok"):
                continue
            st3["columns"] += 1
            if [round(x) for x in col["boundaries"]] != [round(x) for x in bc["boundaries"]]:
                st3["boundaries_changed"] += 1
            bcps = {(cp["slot_above"], cp["slot_below"]): cp for cp in bc.get("cut_candidates", [])}
            for cp in col.get("cut_candidates", []):
                st3["cut_points"] += 1
                n = len(cp["candidates"])
                st3[f"pool_{min(n, 3)}"] += 1
                if any(c.get("agree") is not None for c in cp["candidates"]):
                    st3["judged"] += 1
                st3[f"by_{cp.get('chosen_by')}"] += 1
                bcp = bcps.get((cp["slot_above"], cp["slot_below"]))
                if bcp is None:
                    st3["cut_point_new"] += 1
                    continue
                s_new = seam_of(col, cp, cp["candidates"][cp["chosen"]])
                s_old = seam_of(bc, bcp, bcp["candidates"][bcp["chosen"]])
                if len(s_new) != len(s_old) or not np.array_equal(s_new, s_old):
                    st3["selection_changed"] += 1
                    k_old = bcp["candidates"][bcp["chosen"]]["kind"]
                    k_new = cp["candidates"][cp["chosen"]]["kind"]
                    st3[f"dir_{k_old}->{k_new}"] += 1
                    changed.append((pg, col["col"], bcp, cp, col, bc))
                    for s in (cp["slot_above"], cp["slot_below"]):
                        changed_ids.add(f"{a.book}:{pg}:{col['col']}:{s}")
    print("== Step3 切点")
    for k in ("columns", "boundaries_changed", "cut_points", "pool_1", "pool_2", "pool_3", "judged", "by_rule", "by_unet", "by_human", "by_None", "selection_changed", "cut_point_new"):
        if k in st3:
            print(f"   {k:20s} {st3[k]}")
    print("   改选方向:", {k[4:]: v for k, v in st3.items() if k.startswith("dir_")})

    # ── 下游：定字 ──
    dec = Counter()
    ch_examples = []
    for pg in pages:
        bd, ad = load(before, "context_decide", pg), load(after, "context_decide", pg)
        if bd is None or ad is None:
            continue
        bmap = {ch["id"]: ch for c in bd["columns"] for ch in (c.get("chars") or [])}
        for c in ad["columns"]:
            for ch in c.get("chars") or []:
                b = bmap.get(ch["id"])
                grp = "adjacent" if ch["id"] in changed_ids else "other"
                dec[f"{grp}_n"] += 1
                if b is None:
                    dec[f"{grp}_new"] += 1
                    continue
                if (b.get("char") or "") != (ch.get("char") or ""):
                    dec[f"{grp}_char_changed"] += 1
                    if grp == "adjacent" and len(ch_examples) < 20:
                        ch_examples.append((ch["id"], b.get("char"), "→", ch.get("char"), round(float(ch.get("margin") or 0), 3)))
    print("== Step6 定字（context_decide.char）")
    for grp in ("adjacent", "other"):
        n = dec.get(f"{grp}_n", 0)
        print(f"   {grp:9s} 格 {n:5d}  定字变化 {dec.get(f'{grp}_char_changed', 0):4d}  ({(dec.get(f'{grp}_char_changed', 0) / max(n, 1)):.1%})  新出现 {dec.get(f'{grp}_new', 0)}")
    print("   切法改过处的定字变化样例:", ch_examples[:12])

    # ── glyph_match verdict ──
    gmc = Counter()
    for pg in pages:
        bg, ag = load(before, "glyph_match", pg), load(after, "glyph_match", pg)
        if bg is None or ag is None:
            continue
        bmap = {ch["id"]: ch for c in bg["columns"] for ch in (c.get("chars") or [])}
        for c in ag["columns"]:
            for ch in c.get("chars") or []:
                b = bmap.get(ch["id"])
                if b is None:
                    continue
                grp = "adjacent" if ch["id"] in changed_ids else "other"
                gmc[f"{grp}_n"] += 1
                if b.get("verdict") != ch.get("verdict"):
                    gmc[f"{grp}_verdict_changed"] += 1
                    gmc[f"{grp}_{b.get('verdict')}->{ch.get('verdict')}"] += 1
    print("== Step5-a 库匹配 verdict")
    for grp in ("adjacent", "other"):
        print(f"   {grp:9s} n {gmc.get(f'{grp}_n', 0):5d}  verdict 变化 {gmc.get(f'{grp}_verdict_changed', 0)}  ",
              {k.split('_', 1)[1]: v for k, v in gmc.items() if k.startswith(grp + '_') and '->' in k})

    # ── 金标 ──
    frame_ok = set(json.loads((OUT_ROOT / "frame_ok.json").read_text(encoding="utf-8"))) if (OUT_ROOT / "frame_ok.json").exists() else None
    golds = [i for i in verdict_store().list(SHARD) if i.anchor.book == a.book and i.status == "active"
             and int(i.anchor.page) in set(pages) and not i.expected.get("tags")]
    g_rows = []
    for it in golds:
        ex = it.expected
        pg, col = int(it.anchor.page), int(it.anchor.col)
        b3, a3 = load(before, "row_segment", pg), load(after, "row_segment", pg)
        if b3 is None or a3 is None:
            continue
        bc = next((c for c in b3["columns"] if c["col"] == col and c.get("ok")), None)
        ac = next((c for c in a3["columns"] if c["col"] == col and c.get("ok")), None)
        if bc is None or ac is None:
            continue
        path = ic.get(a.book, "column_image", column_key(pg, col))
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) if path else None
        if img is None or ex.get("col_h") is None or abs(int(ex["col_h"]) - img.shape[0]) > 2:
            continue                                    # 坐标系不一致的金标不比
        sa, sb = ex.get("slot_above"), ex.get("slot_below")
        cells = {c["slot"]: c for c in ac["cells"] if c.get("sub") is None}
        up, dn = cells.get(sa), cells.get(sb)
        if up is None or dn is None:
            continue
        x_lo, x_hi = [int(round(v)) for v in ac["content_x"]]
        y0, y1 = int(round(up["y0"])), int(round(dn["y1"]))
        win = img[y0:y1, x_lo:x_hi]
        W = (win < INK_TH).astype(np.uint8)
        if ex.get("polyline") and len(ex["polyline"]) >= 2:
            gs = np.asarray(polyline_to_seam(ex["polyline"], x_lo, x_hi), dtype=int)
        elif ex.get("y") is not None:
            gs = np.full(x_hi - x_lo, int(round(ex["y"])))
        else:
            continue
        if len(gs) != win.shape[1]:
            continue
        og = owner_from_seam(W, gs - y0)

        def chosen_seam(colrec):
            cp = next((cp for cp in colrec.get("cut_candidates", []) if cp["slot_above"] == sa and cp["slot_below"] == sb), None)
            if cp is None:
                upc = next((c for c in colrec["cells"] if c.get("sub") is None and c["slot"] == sa), None)
                return np.full(x_hi - x_lo, int(round(upc["y1"]))) if upc else None
            return seam_of(colrec, cp, cp["candidates"][cp["chosen"]])
        sb_, sa_ = chosen_seam(bc), chosen_seam(ac)
        if sb_ is None or sa_ is None or len(sb_) != win.shape[1] or len(sa_) != win.shape[1]:
            continue
        e0 = err_stats(owner_from_seam(W, sb_ - y0), og)
        e1 = err_stats(owner_from_seam(W, sa_ - y0), og)
        g_rows.append({"id": it.id, "verdict": ex.get("verdict"), "before": {"px": e0[0], "blob": e0[1]}, "after": {"px": e1[0], "blob": e1[1]},
                       "changed": not np.array_equal(sb_, sa_)})
    if g_rows:
        def agg(k):
            px = np.array([r[k]["px"] for r in g_rows]); bl = np.array([r[k]["blob"] for r in g_rows])
            return f"px {px.mean():5.1f} 中位 {np.median(px):3.0f} | ≤20px {np.mean(px <= 20):5.1%} | blob≥60 {np.mean(bl >= 60):5.1%} | ≥150 {np.mean(bl >= 150):5.1%}"
        ch = [r for r in g_rows if r["changed"]]
        better = sum(1 for r in ch if (r["after"]["blob"], r["after"]["px"]) < (r["before"]["blob"], r["before"]["px"]))
        worse = sum(1 for r in ch if (r["after"]["blob"], r["after"]["px"]) > (r["before"]["blob"], r["before"]["px"]))
        print(f"== 金标（这些页上坐标系一致的 touching-cuts，n={len(g_rows)}）")
        print("   重跑前:", agg("before"))
        print("   重跑后:", agg("after"))
        print(f"   切法变了的 {len(ch)} 条：变好 {better} / 变差 {worse} / 持平 {len(ch) - better - worse}")
        for r in sorted(ch, key=lambda r: -(r["after"]["px"] - r["before"]["px"]))[:6]:
            print("    变差最大:", r["id"], r["verdict"], r["before"], "→", r["after"])
    else:
        print("== 金标：这些页上没有坐标系一致的金标")

    jdump({"step3": dict(st3), "decide": dict(dec), "glyph_match": dict(gmc), "gold": g_rows}, out / "summary.json")

    # ── 图 ──
    if changed:
        gold_by = {}
        for it in golds:
            ex = it.expected
            gold_by[(int(it.anchor.page), int(it.anchor.col), ex.get("slot_above"), ex.get("slot_below"))] = ex
        tiles = []
        for pg, col, bcp, cp, ac, bc in changed[:24]:
            path = ic.get(a.book, "column_image", column_key(pg, col))
            img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE) if path else None
            if img is None:
                continue
            cells = {c["slot"]: c for c in ac["cells"] if c.get("sub") is None}
            up, dn = cells.get(cp["slot_above"]), cells.get(cp["slot_below"])
            if up is None or dn is None:
                continue
            x_lo, x_hi = [int(round(v)) for v in ac["content_x"]]
            y0, y1 = int(round(up["y0"])), int(round(dn["y1"]))
            win = img[y0:y1, x_lo:x_hi]
            vis = cv2.cvtColor(win, cv2.COLOR_GRAY2BGR)
            s_old = seam_of(bc, bcp, bcp["candidates"][bcp["chosen"]])
            s_new = seam_of(ac, cp, cp["candidates"][cp["chosen"]])
            layers = [(s_old, (0, 0, 255), 1), (s_new, (0, 190, 0), 2)]
            g = gold_by.get((pg, col, cp["slot_above"], cp["slot_below"]))
            if g and abs(int(g.get("col_h") or 0) - img.shape[0]) <= 2:
                gs = (np.asarray(polyline_to_seam(g["polyline"], x_lo, x_hi), dtype=int) if g.get("polyline") and len(g["polyline"]) >= 2
                      else np.full(x_hi - x_lo, int(round(g["y"]))) if g.get("y") is not None else None)
                if gs is not None and len(gs) == win.shape[1]:
                    layers.append((gs, (255, 0, 0), 1))
            for seam, colr, th in layers:
                pts = [(k, int(round(v - y0))) for k, v in enumerate(seam)]
                for p1, p2 in zip(pts, pts[1:]):
                    cv2.line(vis, p1, p2, colr, th)
            H = 230; s = H / vis.shape[0]; vis = cv2.resize(vis, (max(1, int(vis.shape[1] * s)), H))
            canvas = np.full((H + 16, max(vis.shape[1], 230), 3), 255, np.uint8); canvas[:H, :vis.shape[1]] = vis
            ag = [c.get("agree") for c in cp["candidates"]]
            cv2.putText(canvas, f"p{pg} c{col} s{cp['slot_above']} {bcp['candidates'][bcp['chosen']]['kind'][:6]}->{cp['candidates'][cp['chosen']]['kind'][:6]} {ag}",
                        (2, H + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.33, (0, 0, 0), 1)
            tiles.append(canvas)
        if tiles:
            Wm = max(t.shape[1] for t in tiles); rowsimg = []
            for i in range(0, len(tiles), 4):
                row = [np.pad(t, ((0, 0), (0, Wm - t.shape[1]), (0, 0)), constant_values=255) for t in tiles[i:i + 4]]
                while len(row) < 4:
                    row.append(np.full_like(row[0], 255))
                rowsimg.append(np.hstack(row))
            cv2.imwrite(str(out / "changed.png"), np.vstack(rowsimg))
            print("→", out / "changed.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
