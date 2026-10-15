#!/usr/bin/env python3
"""只读：量「seed_admit 口径」与「group_decide 口径」的 ctx 差多少，以及 ry-v2 答案表命中格怎么变（GUJI-208aq）。

只读：不写 products/、事件、答案表、人裁；单进程。读：
  products/<book>/{seed_admit,glyph_match,align_ref}/pNNNN.json（用 cv 仓的 ProductStore 读）
  ry-v2 答案表 json（utils/ry_group.py 格式，`{"cells": {cell_id: {ctx, ver, votes}}}`）
三种 ctx：
  adm      seed_admit._clf_ctx：整页（列号升序、剔 excluded）序列；邻格 admit→其 char，否则 align 字，否则 □
  pre_col  group_decide（cv#47 现码）：按列分开的序列；邻格 same 档字，否则 align 字，否则 □
  pre_page 假想口径：整页序列（同 adm），邻格 same 档字，否则 align 字，否则 □
每个都过 ctx_key（左取最近 □ 之后、右取第一个 □ 之前，各至多 30 字）再比哈希，所以「相同」是答案表真看到的相同。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

W = 30


def _tail(seq: list[str], i: int, step: int) -> str:
    out: list[str] = []
    j = i + step
    while 0 <= j < len(seq) and len(out) < W:
        out.append(seq[j])
        j += step
    return "".join(reversed(out)) if step < 0 else "".join(out)


def ctx_triplet(seq: list[str], i: int) -> tuple[str, str]:
    return _tail(seq, i, -1), _tail(seq, i, 1)


def analyze_page(page, adm, match, ref, table, ry_decide, ctx_key, ry_family, jys_family):
    """返回该页每个目标格一行 dict。adm/match/ref 可为 None（缺产物则跳过该页）。"""
    if adm is None or match is None or ref is None or not ref.anchored:
        return []
    amap = {c.id: c.align_char for c in ref.chars}
    same = {r.id: (r.char if r.verdict == "same" else None) for col in match.columns for r in col.chars}

    # —— adm：整页序列（seed_admit._ry_group_pass 的 seq）
    adm_recs = [r for c in sorted(adm.columns, key=lambda c: c.col) for r in c.chars
                if not (r.doubts and "excluded" in r.doubts)]
    adm_seq = [(r.char if r.admit and r.char else None) or amap.get(r.id) or "□" for r in adm_recs]
    # —— pre_page：同一整页序列，字取 same→align→□
    pre_page_seq = [same.get(r.id) or amap.get(r.id) or "□" for r in adm_recs]
    # —— pre_col：group_decide 现码，按列
    col_seqs: dict[int, list[tuple[str, str]]] = {}
    col_index: dict[str, tuple[int, int]] = {}
    for col in sorted(match.columns, key=lambda c: c.col):
        seq = [(same.get(r.id) or amap.get(r.id) or "□") for r in col.chars]
        col_seqs[col.col] = seq
        for k, r in enumerate(col.chars):
            col_index[r.id] = (col.col, k)

    # —— adm_col：seed_admit 取字 + 按列分序列（用来单独量"序列差"：adm vs adm_col）
    adm_col_pos: dict[str, tuple[int, int]] = {}
    adm_col_seqs: dict[int, list[str]] = {}
    for c in sorted(adm.columns, key=lambda c: c.col):
        cr = [r for r in c.chars if not (r.doubts and "excluded" in r.doubts)]
        adm_col_seqs[c.col] = [(r.char if r.admit and r.char else None) or amap.get(r.id) or "□" for r in cr]
        for k, r in enumerate(cr):
            adm_col_pos[r.id] = (c.col, k)

    rows = []
    for i, r in enumerate(adm_recs):
        ref_ch = amap.get(r.id)
        if not ref_ch:
            continue
        grp = "ry" if ref_ch in ry_family else "jys" if ref_ch in jys_family else None
        if not grp:
            continue
        la, ra = ctx_triplet(adm_seq, i)
        lp, rp = ctx_triplet(pre_page_seq, i)
        if r.id in col_index:
            cc, k = col_index[r.id]
            lc, rc = ctx_triplet(col_seqs[cc], k)
        else:
            lc = rc = None
        if r.id in adm_col_pos:
            cc2, k2 = adm_col_pos[r.id]
            lac, rac = ctx_triplet(adm_col_seqs[cc2], k2)
            kac = ctx_key(lac, rac)
        else:
            kac = None
        ka, kp = ctx_key(la, ra), ctx_key(lp, rp)
        kc = ctx_key(lc, rc) if lc is not None else None
        row = {"id": r.id, "group": grp, "ref": ref_ch, "admit": bool(r.admit), "channel": r.channel,
               "key_adm": ka, "key_adm_col": kac, "key_pre_col": kc, "key_pre_page": kp,
               # 口径差 1＝取字不同（序列同为整页）；口径差 2＝序列不同（取字同）；叠加＝两者都不同（现码 vs 现行）
               "diff1_fetch": ka != kp, "diff2_seq_adm": kac is not None and ka != kac,
               "diff2_seq_pre": kc is not None and kc != kp, "diff_both": kc is not None and ka != kc,
               "same_adm_pre_col": ka == kc, "same_adm_pre_page": ka == kp,
               "same_pre_col_pre_page": kc == kp}
        if grp == "ry" and table is not None:
            for name, (l, rr) in (("adm", (la, ra)), ("pre_col", (lc, rc)), ("pre_page", (lp, rp))):
                if l is None:
                    row[f"hit_{name}"] = None
                    continue
                res = ry_decide(table, r.id, l, rr) or {}
                row[f"hit_{name}"] = {"char": res.get("char"), "why": res.get("why")}
            rec = (r.evidence or {}).get("ry_group")
            row["recorded_why"] = (rec or {}).get("why") if rec else None
            row["recorded_char"] = (rec or {}).get("char") if rec else None
        rows.append(row)
    return rows


def summarize(rows: list[dict]) -> dict:
    s: dict = {"n_cells": len(rows)}
    for g in ("ry", "jys"):
        R = [r for r in rows if r["group"] == g]
        s[g] = {"n": len(R),
                "口径差1_取字(adm≠pre_page)": sum(r["diff1_fetch"] for r in R),
                "口径差2_序列(adm≠adm_col)": sum(r["diff2_seq_adm"] for r in R),
                "口径差2_序列(pre_page≠pre_col)": sum(r["diff2_seq_pre"] for r in R),
                "叠加(adm≠pre_col, 即现行 vs cv#47)": sum(r["diff_both"] for r in R),
                "same_adm_pre_col": sum(r["same_adm_pre_col"] for r in R),
                "same_adm_pre_page": sum(r["same_adm_pre_page"] for r in R),
                "same_pre_col_pre_page": sum(r["same_pre_col_pre_page"] for r in R)}
    R = [r for r in rows if r["group"] == "ry" and "hit_adm" in r]
    if R:
        def hits(name): return sum(1 for r in R if (r.get(f"hit_{name}") or {}).get("char"))
        s["ry_table"] = {
            "n": len(R),
            "hit_adm(char非空)": hits("adm"), "hit_pre_col": hits("pre_col"), "hit_pre_page": hits("pre_page"),
            "why_adm": dict(Counter((r["hit_adm"] or {}).get("why") for r in R)),
            "why_pre_col": dict(Counter((r["hit_pre_col"] or {}).get("why") for r in R if r.get("hit_pre_col"))),
            "why_pre_page": dict(Counter((r["hit_pre_page"] or {}).get("why") for r in R)),
            "lost_pre_col": sum(1 for r in R if (r["hit_adm"] or {}).get("char") and not (r.get("hit_pre_col") or {}).get("char")),
            "lost_pre_page": sum(1 for r in R if (r["hit_adm"] or {}).get("char") and not (r["hit_pre_page"] or {}).get("char")),
            "changed_char_pre_col": sum(1 for r in R if (r["hit_adm"] or {}).get("char") and (r.get("hit_pre_col") or {}).get("char")
                                        and r["hit_adm"]["char"] != r["hit_pre_col"]["char"]),
            "recon_check": {  # 自校：重建的 adm 口径与 seed_admit 产物里记录的 evidence.ry_group 是否一致（仅未放行格有记录）
                "n_recorded": sum(1 for r in R if r.get("recorded_why") is not None),
                "n_match": sum(1 for r in R if r.get("recorded_why") is not None
                               and (r["hit_adm"] or {}).get("why") == r["recorded_why"]
                               and (r["hit_adm"] or {}).get("char") == r["recorded_char"])}}
    return s


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--code-root", required=True, help="cv 仓（候选分支 4a78280 的 worktree）根目录，用来 import")
    ap.add_argument("--products-root", required=True, help="产物根（含 <book>/seed_admit/ 等）；只读")
    ap.add_argument("--books", nargs="+", required=True, help="如 vol01 vol02 … vol07")
    ap.add_argument("--ry-table", default="", help="ry-v2 答案表 json；不给则只比 ctx 不比命中")
    ap.add_argument("--out", required=True, help="输出目录（新建；不放在 products/ 下）")
    ap.add_argument("--pages", default="", help="可选，逗号分隔页号，小样例自测用")
    a = ap.parse_args(argv)
    sys.path.insert(0, a.code_root)
    from open_guji_cv.products.store import ProductStore
    import open_guji_cv.steps  # noqa: F401  注册 kind
    from open_guji_cv.utils.ji_yi_si_clf import FAMILY as JYS, ctx_key
    from open_guji_cv.utils import ry_group as RG

    table = None
    if a.ry_table:
        table = a.ry_table
        RG._load(table)  # 预读，失败早报

    def ry_decide(_t, cid, l, r):
        return RG.decide(table, cid, l, r)

    store = ProductStore(Path(a.products_root))
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    want = {int(x) for x in a.pages.split(",") if x} or None
    allsum = {}
    with open(out / "cells.jsonl", "w", encoding="utf-8") as fo:
        for book in a.books:
            rows = []
            for key in store.keys(book, "seed_admit"):
                page = int(key[1:])
                if want and page not in want:
                    continue
                adm = store.read(book, "seed_admit", key, "seed_admit")
                match = store.read(book, "glyph_match", key, "glyph_match")
                ref = store.read(book, "align_ref", key, "align_ref")
                for r in analyze_page(page, adm, match, ref, table, ry_decide, ctx_key, RG.FAMILY, JYS):
                    r["book"] = book
                    rows.append(r)
                    fo.write(json.dumps(r, ensure_ascii=False) + "\n")
            allsum[book] = summarize(rows)
    (out / "summary.json").write_text(json.dumps(allsum, ensure_ascii=False, indent=2), encoding="utf-8")
    md = ["# ctx 口径比对汇总（只读脚本输出；数的是 ctx 哈希**不同**的格）", "",
          "| 册 | 组 | 目标格 | 口径差1 取字 | 口径差2 序列(adm取字) | 口径差2 序列(pre取字) | 两者叠加 |", "|---|---|---|---|---|---|---|"]
    for b, s in allsum.items():
        for g in ("ry", "jys"):
            x = s[g]
            md.append(f"| {b} | {g} | {x['n']} | {x['口径差1_取字(adm≠pre_page)']} | {x['口径差2_序列(adm≠adm_col)']} | "
                      f"{x['口径差2_序列(pre_page≠pre_col)']} | {x['叠加(adm≠pre_col, 即现行 vs cv#47)']} |")
    md += ["", "## ry-v2 命中变化（需 --ry-table）", ""]
    for b, s in allsum.items():
        if "ry_table" in s:
            md.append(f"- {b}: `{json.dumps(s['ry_table'], ensure_ascii=False)}`")
    (out / "summary.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
