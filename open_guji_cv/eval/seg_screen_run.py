"""切分筛查的跑法（A22，2026-11-12 从 `scripts/seg_screen.py` 搬进包里，`guji seg check` 与脚本共用）。

只读本机产物与列图／字块缓存，各书通用；判据都在 `eval/seg_screen.py`。不改产物、不进指纹。

`screen_book` 一册出一组 {检查名: [(book, page, col, value, note)]}：
- 页／列级（F4、F7、F8，2026-11-10）：edge_ink、orphan、edge_frame_only、colnet_page、frame_margin、layout_col_shift、
  layout_fallback、pitch_free_ignored、seal_blank；
- 格级（SJ 史記快筛，2026-11-12 并进来）：cell_flags（FOR／Lh／Lv／Fend／Fpatch／JZW，一格一行，value＝flags）；
- 列级对格号：pin_slots（钉子列 cell_shrink 格号≠钉子）、layout_slots（非钉子列对格位表：「同数」判过只计数，异数要看）；
- cell_size：一列里格高离群（≥1.7 倍中位多半两字并一格、≤0.5 倍多半一字拆两格），按列一行；
- page_pitch（2026-11-12）：正文格高对本页中位（整列偏 >10%，或单格 ≥1.5／≤0.6 倍），职名列不查；value＝列中位比；
- half_width（2026-11-12）：夹注半格宽对本册半格宽中位出 0.7–1.4 倍，或同号 a/b 宽差 >30%；
- cut_through（F6，2026-11-13）：格线劈字，相邻两格分界按连通块量切割量、±0.4 格内挪得开且 U-Net 裁判认挪后更对才报（没 torch 不跑，summary 注明），一条线一行，value＝强｜中｜弱（弱＝挪不到 1/3 格高，manager 当提示）；
- geo_ref_ok（2026-11-13，史記 R011／R013）：cell_size／page_pitch／half_width 离群、但参校字落在字形匹配前 3 名且上下邻格无反证的格
  （整列偏则本列有参校字的格 ≥85% 证实），不进上面三张表，只记在这里备查——写本扁字、大字、夹注一行偏宽是字形本来如此；
  `ref_check=False` 关掉豁免（照旧全报）；
- block_tall（2026-11-13）：cell_shrink 字块高 ≥ 本格 row_segment 格高 1.35 倍（且多 24px 以上），字块连上了格外的墨（长竖线、印章、邻字）；
  列末格不查，一格一行，value＝倍数；
- align_drift（2026-11-14，史記 R017；当天按 SJ 抽看收紧）：对位串错·疑整列错位——没配到参校字的格挨着没放行的对不上格（劈）、
  连续 ≥2 格没放行且对不上、或连续 ≥5 格对不上；考證列不查；一页报出 ≥3 列的 value 加 `page`（整页的事，降成提示）；
  value＝split／pair／run（＋page），note＝格态串（O 对上、B 对不上、R 生僻字通道、N 没配到参校字，小写＝没放行）；钉子列不查；
- pin_stale：中心库有 active 钉子、本页产物却没用上（产物早于钉子，要从 row_segment 重跑）。

钉子列（产物带 `manual_cells` 旗）只比格号、不跑墨账与端外墨（SJ 第 5 条）；有钉子而产物没用上的列照普通列查；职名列不跑端外墨。`skip` 点名的页整页不查（书配置
`seg_check.skip_pages`，由 `guji seg check` 读）。
"""
from __future__ import annotations

import functools
import sys

CHECKS = ("edge_ink", "orphan", "edge_frame_only", "colnet_page", "frame_margin", "layout_col_shift", "layout_fallback",
          "pitch_free_ignored", "cell_flags", "cell_size", "page_pitch", "half_width", "pin_slots", "pin_stale", "layout_slots", "seal_blank",
          "cut_through", "geo_ref_ok", "block_tall", "align_drift")


def _engine(book: str):
    from ..core.book import load_book
    from ..core.engine import Engine
    from ..core.pipeline import default_pipeline_id, load_pipeline
    bk = load_book(book)
    return Engine(bk, load_pipeline(default_pipeline_id(bk)), log=lambda s: None)


def _pins(book: str) -> dict[tuple[int, int], list]:
    from ..feedback.lookup import resolved_manual_cells
    try:
        return {(int(p), int(c)): v for (p, c), v in resolved_manual_cells(book).items()}
    except Exception as e:  # noqa: BLE001
        print(f"⚠️ {book}：读 manual-cells 失败（{e}），钉子列按普通列查", file=sys.stderr)
        return {}


def _img(ctx, book: str, kind: str, key: str):
    """缓存图（灰度）：缓存里没有就现算（同 `guji cache get`），算不出返回 None。"""
    import cv2
    p = ctx.cache.get(book, kind, key)
    if p is None:
        try:
            p = ctx.materialize(kind, key)
        except Exception:  # noqa: BLE001
            return None
    return None if p is None else cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)


def screen_book(book: str, pages: set[int] | None, seal_blank: bool, rows: dict[str, list], counts: dict,
                skip: set[int] | None = None, cell_checks: bool = True, ref_check: bool = True) -> None:
    import open_guji_cv.products.kinds  # noqa: F401
    from ..core.spec import column_key, page_key
    from ..steps.row_segment import RowSegmentStep, load_layout
    from . import seg_screen as ss

    for k in CHECKS:
        rows.setdefault(k, [])
    eng = _engine(book)
    ctx, store = eng.ctx, eng.store
    rs = ctx.params_for(RowSegmentStep())
    layout = {}
    if getattr(rs, "layout_prior", ""):
        try:
            layout = load_layout(rs.layout_prior, book)
        except FileNotFoundError as e:
            print(f"⚠️ {book}：{e}，跳过 ②b／F7／版式对格号", file=sys.stderr)
    pins = _pins(book)
    skip = skip or set()
    keys = sorted(p.stem for p in store.step_dir(book, "row_segment").glob("p[0-9]*.json"))
    c = counts.setdefault(book, {k: 0 for k in CHECKS} | {"pages": 0, "layout_same_count": 0})
    from ..seg.cut_select import get_judge
    judge = get_judge()                                            # cut_through 要 U-Net 归属裁判，没装 torch／权重就不跑这项
    if judge is None:
        c["cut_through_off"] = 1
        print(f"⚠️ {book}：没有 U-Net 归属裁判（torch／权重），cut_through 不跑", file=sys.stderr)
    margins = {}
    halves = []                                                    # 本册夹注半格宽中位要全册算，先过一遍
    for key in keys:
        pc = store.read(book, "row_segment", key, "cells")
        if pc is not None and int(key[1:]) not in skip:
            halves += [w for cc in pc.columns if cc.ok and "roster" not in cc.flags for _s, _b, w in ss.half_widths(cc)]
    half_med = sorted(halves)[len(halves) // 2] if len(halves) >= 10 else None
    for key in keys:
        page = int(key[1:])
        b = store.read(book, "border_detect", key, "borders")      # 中位要全册算，先于 --pages 过滤
        if b is not None:
            margins[page] = ss.frame_margins(b)
        if (pages and page not in pages) or page in skip:
            continue
        cells = store.read(book, "row_segment", key, "cells")
        if cells is None:
            continue
        c["pages"] += 1
        gate = store.read(book, "column_gate", page_key(page), "gate_manifest")
        if gate is not None:
            for hit in ss.colnet_page(gate):
                rows["colnet_page"].append((book, page, hit["col"], hit["ratio"], f"带宽 {hit['width']}px"))
            c["colnet_page"] += bool(ss.colnet_page(gate))
        fb = ss.layout_fallback_cols(cells)
        if fb:
            rows["layout_fallback"].append((book, page, ",".join(map(str, fb)), len(fb), "格位表回退几何切的列"))
            c["layout_fallback"] += 1
        # edge_frame_only 只报 cell_shrink 后还判字（cell_type != empty）的格：判 empty 的下游无害（QTW 11-10 验收）
        ci = store.read(book, "cell_shrink", key, "char_index")
        shrink_char = None if ci is None else {(cc_.col, ch.slot) for cc_ in ci.columns for ch in cc_.chars
                                               if ch.cell_type != "empty"}
        chars_by_col = {} if ci is None else {cc_.col: [ch for ch in cc_.chars if ch.cell_type == "char"]
                                              for cc_ in ci.columns if cc_.ok}
        wins = store.read(book, "column_warp", key, "column_windows") if cell_checks else None
        win_by_col = {} if wins is None else {w.col: w for w in wins.columns}
        lay_page = {col: r for (pg, col), r in layout.items() if pg == page}
        pitch = ss.page_pitch(cells)
        glyph_p, aref_p = store.read(book, "glyph_match", key, "glyph_match"), store.read(book, "align_ref", key, "align_ref")
        conf = ss.ref_confirmed(glyph_p, aref_p) if ref_check else {}
        adm_p = store.read(book, "seed_admit", key, "seed_admit")
        adm_by_col = {} if adm_p is None or aref_p is None else {a.col: a for a in adm_p.columns}
        ref_p, glyph_top = ss.page_ref_glyph(aref_p, glyph_p) if adm_by_col else ({}, {})
        no_coord = not ss.drift_applicable(aref_p)

        shifted = {cc.col for cc in cells.columns if any(str(f).startswith("layout_shift") for f in cc.flags)}
        _ref_ok = functools.partial(_geo_ref_ok, conf, shifted)
        _exempt = functools.partial(_geo_exempt, rows, c, book, page)
        sh = ss.layout_col_shift(cells, lay_page)
        if sh:
            rows["layout_col_shift"].append((book, page, "", sh["shift"],
                                             f"不挪对上 {sh['match0']}/{sh['cols']}，挪后 {sh['match']}"))
            c["layout_col_shift"] += 1
        drift_page: list[list] = []
        for cc in cells.columns:
            if not cc.ok:
                continue
            chars = chars_by_col.get(cc.col) or []
            have = {ch.id.split(":")[3] for ch in chars}
            pinned = "manual_cells" in cc.flags
            if (page, cc.col) in pins and not pinned:
                rows["pin_stale"].append((book, page, cc.col, "", "有钉子、产物没用上：从 row_segment 重跑本页"))
                c["pin_stale"] += 1
            if ci is not None and pinned and (page, cc.col) in pins:
                msg = ss.pin_slots_diff(have, pins[(page, cc.col)])
                if msg:
                    rows["pin_slots"].append((book, page, cc.col, "", msg))
                    c["pin_slots"] += 1
            elif ci is not None and cc.col in lay_page and have:
                d = ss.layout_slots_diff(have, lay_page[cc.col])
                if d == "同数":
                    c["layout_same_count"] += 1
                elif d:
                    rows["layout_slots"].append((book, page, cc.col, "", d))
                    c["layout_slots"] += 1
            if ss.pitch_free_ignored(cc, lay_page.get(cc.col)):
                rows["pitch_free_ignored"].append((book, page, cc.col, "", "表写 pitch: free，选中挤格补线格网"))
                c["pitch_free_ignored"] += 1
            # 对位串错只读产物，不要列图；钉子列只比格号。册配置声明本页参校本 text（不分列、不做坐标对位）或 none（无参照）
            # 的不查：格态全是 N／n，pair 只是在数待审格，量不出错位（全唐文 s1 闸，2026-11-14）。整页没锚上的照查（可能是切坏了）
            if not pinned and cc.col in adm_by_col and not no_coord:
                st = ss.cell_states(adm_by_col[cc.col], ref_p, glyph_top)
                dr = ss.align_drift(st, "".join(x.char or "" for x in adm_by_col[cc.col].chars))
                if dr:
                    drift_page.append([book, page, cc.col, ",".join(dr), st])
            gray = _img(ctx, book, "column_image", column_key(page, cc.col))
            if gray is None:
                continue
            boxes = [ch.bbox_col for ch in chars]
            if boxes:                     # 漏切块：人定字框、职名列也查（墨不在任何字格里与怎么切无关）
                for o in ss.orphan_ink(gray, boxes):
                    rows["orphan"].append((book, page, cc.col, o["ratio"],
                                           f"{o['where']} 墨 {o['ink']}px bbox {o['bbox']}"))
                    c["orphan"] += 1
            if pinned:
                continue                  # 钉子列只比格号（SJ 第 5 条）
            last = max(cc.cells, key=lambda x: (x.slot, x.sub or ""), default=None)
            hmap = {(x.slot, x.sub): x.y1 - x.y0 for x in cc.cells}
            for ch in chars:
                if last is not None and (ch.slot, ch.sub) == (last.slot, last.sub):
                    continue              # 列末字格吃下面的空格位，字块照样收墨
                r = ss.block_tall(ch.height, hmap.get((ch.slot, ch.sub), 0.0))
                if r:
                    rows["block_tall"].append((book, page, cc.col, r,
                                               f"{ch.slot}{ch.sub or ''} 字块高 {ch.height:.0f}px 格高 "
                                               f"{hmap[(ch.slot, ch.sub)]:.0f}px {','.join(ch.flags)}".strip()))
                    c["block_tall"] += 1
            odd = ss.odd_cell_heights(cc)
            _exempt(cc.col, "cell_size", [o for o in odd if _ref_ok(cc.col, o)])
            odd = [o for o in odd if not _ref_ok(cc.col, o)]
            if odd:
                rows["cell_size"].append((book, page, cc.col, ",".join(sorted({o["kind"] for o in odd})),
                                          " ".join(f"{o['slot']}{o['sub'] or ''}×{o['ratio']}" for o in odd)))
                c["cell_size"] += 1
            if pitch and "roster" not in cc.flags:
                po = ss.pitch_outliers(cc, pitch)
                if po and conf:
                    _exempt(cc.col, "page_pitch", [o for o in po["cells"] if _ref_ok(cc.col, o)])
                    po["cells"] = [o for o in po["cells"] if not _ref_ok(cc.col, o)]
                    if not po["cells"] and (abs(po["col_ratio"] - 1) <= ss.PITCH_COL_DEV
                                             or (cc.col not in shifted and ss.ref_ok_col(conf, cc.col))):
                        if abs(po["col_ratio"] - 1) > ss.PITCH_COL_DEV:
                            _exempt(cc.col, "page_pitch", [{"slot": "列", "sub": "", "ratio": po["col_ratio"]}])
                        po = None
                if po:
                    rows["page_pitch"].append((book, page, cc.col, po["col_ratio"],
                                               " ".join(f"{o['slot']}{o['sub'] or ''}×{o['ratio']}" for o in po["cells"])
                                               + f" 本页格高 {pitch:.0f}px"))
                    c["page_pitch"] += 1
            if half_med and "roster" not in cc.flags:
                ho = ss.half_width_outliers(cc, half_med)
                _exempt(cc.col, "half_width", [o for o in ho if _ref_ok(cc.col, o)])
                ho = [o for o in ho if not _ref_ok(cc.col, o)]
                if ho:
                    rows["half_width"].append((book, page, cc.col, len(ho), " ".join(
                        f"{o['slot']}{o['sub']}" + (f"×{o['ratio']}" if "ratio" in o else f" 差{o['asym']}") for o in ho)
                        + f" 本册半格宽 {half_med:.0f}px"))
                    c["half_width"] += 1
            if judge is not None and "roster" not in cc.flags:
                for t in ss.cut_through(gray, cc, judge=judge):
                    rows["cut_through"].append((book, page, cc.col, t["level"],
                                                f"{t['slot_above']}|{t['slot_below']} 切割量 {t['cost']}px，挪 {t['move']:+d}px 可降到 {t['best']}px"
                                                + (f"，裁判 {t['agree'][0]:.2f}→{t['agree'][1]:.2f} 分歧 {t['agree'][2]}→{t['agree'][3]}px" if t["agree"] else "")))
                    c["cut_through"] += 1
            if cell_checks and chars:
                _cell_flags(book, page, cc.col, gray, chars, win_by_col.get(cc.col), ctx, rows, c)
            if "roster" in cc.flags:
                continue                  # 职名列不按格网查端外墨
            for slot in ss.edge_frame_only(gray, cc):
                if shrink_char is not None and (cc.col, slot) not in shrink_char:
                    continue
                rows["edge_frame_only"].append((book, page, cc.col, slot, "端格里只有版框线"))
                c["edge_frame_only"] += 1
            e = ss.edge_ink(gray, cc)
            if e:
                rows["edge_ink"].append((book, page, cc.col, max(e["top"], e["bottom"]),
                                         f"上 {e['top']} 行、下 {e['bottom']} 行有墨（格高 {e['period']}）"))
                c["edge_ink"] += 1
        for r in drift_page:              # 一页报出好几列＝整页的事（透印、版式、整页没对上），降成提示
            if len(drift_page) >= ss.DRIFT_PAGE:
                r[3] += ",page"
            rows["align_drift"].append(tuple(r))
            c["align_drift"] += 1
        if seal_blank:
            from ..steps.occlusion import page_seal_blank
            from ..steps.seed_admit import SeedAdmitStep
            for (col, slot, sub), info in sorted(page_seal_blank(ctx, page, ctx.params_for(SeedAdmitStep())).items()):
                rows["seal_blank"].append((book, page, col, f"{slot}{sub}", str(info)[:80]))
                c["seal_blank"] += 1
    for h in ss.margin_outliers(margins):
        if (pages and h["page"] not in pages) or h["page"] in skip:
            continue
        rows["frame_margin"].append((book, h["page"], h["side"], h["dev"],
                                     f"外框到页边 {h['dist']}px，同奇偶页中位 {h['median']}px"))
        c["frame_margin"] += 1


def _geo_ref_ok(conf: dict, shifted: set, col: int, o: dict) -> bool:
    """格高／半格宽离群的一格能不能按参校字豁免。Step3 挪过格位表的列（layout_shift）不豁免：卷首题署列这类（史記 37:2:6 人钉过）。"""
    from . import seg_screen as ss
    return bool(conf) and col not in shifted and ss.ref_ok_cell(conf, col, int(o["slot"]), o["sub"])


def _geo_exempt(rows, c, book, page, col, kind, hits) -> None:
    for o in hits:
        rows["geo_ref_ok"].append((book, page, col, kind, f"{o['slot']}{o['sub'] or ''}×{o.get('ratio', o.get('asym'))}"))
        c["geo_ref_ok"] += 1


def _cell_flags(book, page, col, gray, chars, win, ctx, rows, c) -> None:
    """格级 flags（SJ `seg_detect`）：FOR／Lh／Lv（墨账）、Fend（列端版框）、Fpatch／Lv（字块边线）、JZW（夹注并格）。"""
    from . import seg_screen as ss
    led = ss.ink_ledger(gray, [(ch.id, ch.bbox_col, ch.slot, ch.sub) for ch in chars])
    h = gray.shape[0]
    fe = {}
    if win is not None:
        fe = ss.end_frame_hits(gray, [ch.bbox_col for ch in chars], win.border_top_in_column or 0.0,
                               h if win.border_bottom_in_column is None else win.border_bottom_in_column)
    col_w = float(win.warped_size[0]) if win is not None else float(gray.shape[1])
    for k, ch in enumerate(chars):
        fl: list[str] = []
        if ch.patch_key:
            patch = _img(ctx, book, "char_patch", ch.patch_key)
            if patch is not None:
                el = ss.patch_edge_lines(patch)
                if "top" in el or "bot" in el:
                    fl.append("Fpatch")
                if "left" in el or "right" in el:
                    fl.append("Lv")
        if k in fe:
            fl.append("Fend")
        r = led.get(ch.id)
        if r is not None:
            fl += [f for f in ss.ledger_flags(r) if f not in fl]
        if ss.jiazhu_wide(ch.bbox_col, col_w, ch.sub):
            fl.append("JZW")
        if fl:
            note = "" if r is None else f"fr {r['fr']:.3f} foreign {r['foreign']} cut {r['cut']}"
            rows["cell_flags"].append((book, page, col, ",".join(fl), f"{ch.id.split(':')[3]} {note}".strip()))
            c["cell_flags"] += 1


def write_report(rows: dict[str, list], counts: dict, out, seal_blank: bool = False) -> str:
    from pathlib import Path
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    for k, rs in rows.items():
        if k == "seal_blank" and not seal_blank:
            continue
        with open(out / f"{k}.tsv", "w", encoding="utf-8") as f:
            f.write("book\tpage\tcol\tvalue\tnote\n")
            f.writelines("\t".join(map(str, r)) + "\n" for r in rs)
    hdr = ["册", "页数", *[k for k in CHECKS if k != "seal_blank" or seal_blank]]
    lines = ["# 切分筛查", "", "| " + " | ".join(hdr) + " |", "|" + " --- |" * len(hdr)]
    for b, c in counts.items():
        lines.append("| " + " | ".join([b, str(c["pages"]), *[str(c[k]) for k in hdr[2:]]]) + " |")
    same = sum(c.get("layout_same_count", 0) for c in counts.values())
    lines += ["", "edge_ink、pitch_free_ignored、cell_size、page_pitch、half_width、pin_slots、pin_stale、layout_slots 按列计；colnet_page、frame_margin、layout_col_shift、"
              "layout_fallback 按页计；edge_frame_only、cell_flags、block_tall、seal_blank 按格计；orphan 按块计；cut_through 按格线计。"
              f"版式对格号「同数」（只编号不同，判过）{same} 列，只计数不出行。"]
    off = [b for b, c in counts.items() if c.get("cut_through_off")]
    if off:
        lines += ["", f"cut_through 没跑（缺 U-Net 归属裁判：torch／权重）：{'、'.join(off)}。"]
    text = "\n".join(lines) + "\n"
    (out / "summary.md").write_text(text, encoding="utf-8")
    return text
