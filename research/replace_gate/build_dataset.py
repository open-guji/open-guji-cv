# -*- coding: utf-8 -*-
"""replace 位采信学习模型·建数据集（R1 道，2026-10-01，overview #334）。

    GUJI_WORKSPACE=<临时工作区：products/<book> 指向快照> GUJI_GLYPH_DB=<重建的 db> PYTHONPATH=. \
        python research/replace_gate/build_dataset.py vol01 vol02 --out <dir>/rows.jsonl

对每页：用 `slots_from_evidence(match, None)`（云端无 OCR、快照无 rare_candidates，载体=库首选）重算
锚定 + difflib，枚举**全部**等长 replace 位（`align_label.align_ops`，与生产同源，不过闸），
每位出一行信号 + 现行两道闸的判定 + 人裁标签。只读产物与事件，不写任何东西。

标签口径同 `research/shadow_admit/extract_snap.py`：confirm 事件经绑定表（`feedback.bindings`）
落到现行编号，后到覆盖；撤下作废的丢；绑定不采信的丢（计数）。「采对」= 整理本字 == 人裁 shape，
或二者互为异体（忠于刻本字形方针），己已巳合并。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

JYS = set("己已巳")


def J(c):
    return "己" if c in JYS else c


def demojibake(s: str) -> str:
    """UTF-8 字节被当 cp1252/latin1 读出来的乱码（H-mojibake-fix-20260927 修过事件文件，
    但快照 seed_admit 的 human 通道里还留着，如 `别`→`åˆ«`）。能还原就还原，否则原样。"""
    if not s or all(ord(c) > 0x2E7F or ord(c) < 0x80 for c in s) and not any(0x80 <= ord(c) < 0x3000 for c in s):
        return s
    for enc in ("cp1252", "latin-1"):
        try:
            t = s.encode(enc).decode("utf-8")
            if t:
                return t
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return s


def load_labels(book: str):
    from open_guji_cv.core.workspace import feedback_root, glyph_store_path
    from open_guji_cv.feedback.bindings import book_bindings, usable
    from open_guji_cv.feedback.events import EventLog
    gs = glyph_store_path()
    stale: dict[str, str] = {}
    p = gs / "admissions.jsonl"
    if p.exists():
        for l in open(p, encoding="utf-8"):
            r = json.loads(l)
            prov = r.get("provenance") or ""
            if prov.startswith("human_stale_"):
                iid = r["instance_id"]
                key = iid[3:] if iid.startswith("v2:") else iid
                if key.startswith(book + ":"):
                    stale[key] = prov.rsplit("_", 1)[-1]
    sv = feedback_root() / "lists" / "stale_verdicts.tsv"
    if sv.exists():
        for l in sv.read_text(encoding="utf-8").splitlines():
            q = l.split("\t")
            if len(q) >= 2 and q[0].startswith(book + ":"):
                stale[q[0]] = q[1]
    log = EventLog()
    bound = book_bindings(book, log)
    evs = sorted((e for e in log.iter_all() if e.kind == "confirm" and e.target.unit == "cell"
                  and e.target.key.startswith(book + ":") and e.target.step == "seed_admit"),
                 key=lambda e: (e.ts, e.batch, e.seq))
    verdict: dict[str, dict] = {}
    cnt = Counter()
    for e in evs:
        p = e.payload or {}
        cut = stale.get(e.target.key)
        if cut and e.ts.replace("-", "").replace(":", "")[:len(cut)] <= cut:
            cnt["stale"] += 1
            continue
        key = usable(bound.get(e.id)) if e.id in bound else e.target.key
        if key is None:
            cnt["unbound"] += 1
            continue
        verdict[key] = {"v": p.get("v"), "shape": p.get("shape"), "via": p.get("via")}
    cnt["events"] = len(evs); cnt["cells"] = len(verdict)
    return verdict, cnt


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("books", nargs="+")
    ap.add_argument("--out", required=True)
    ap.add_argument("--human-channel-books", default="",
                    help="逗号分隔：这些册的标签改取快照 seed_admit 的 human 通道（服务器 Step7 过绑定表后的结果）。"
                         "用于云端没有字块缓存、绑定表对不上老裁决的册（vol01：4048 条事件 0 条能绑）")
    a = ap.parse_args()
    hc_books = set(filter(None, a.human_channel_books.split(",")))

    from open_guji_cv.clustering.align_eval import anchor_page_diag
    from open_guji_cv.clustering.align_label import AlignedLabel, align_ops, flank_runs, replace_len_gate
    from open_guji_cv.clustering.confusables import is_pair
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.steps.align_ref import (_corpus_index, _corpus_text, book_corpus, lib_char_of,
                                              lib_gate, slots_from_evidence)
    from open_guji_cv.variants import are_variants

    st = ProductStore()
    out = open(a.out, "w", encoding="utf-8")
    meta = {}
    for book in a.books:
        verdict, cnt = load_labels(book)
        via_h = book in hc_books
        if via_h:
            cnt["bind_cells_direct"] = cnt["cells"]
            verdict = {}
        corpus_path = book_corpus(book)
        text = _corpus_text(corpus_path); index = _corpus_index(corpus_path)
        pages = sorted(int(p.stem[1:]) for p in (st.root / book / "glyph_match").glob("p*.json"))
        n_rows = n_pages = n_anch = n_verd_all = 0
        for pg in pages:
            key = page_key(pg)
            match = st.read(book, "glyph_match", key, "glyph_match")
            if match is None:
                continue
            n_pages += 1
            if via_h:
                sa = st.read(book, "seed_admit", key, "seed_admit")
                for cc in (sa.columns if sa else []):
                    for r in cc.chars:
                        if r.channel == "human" and r.char:
                            verdict[r.id] = {"v": "confirm", "shape": demojibake(r.char), "via": "human_channel"}
            rare = st.read(book, "rare_candidates", key, "rare_candidates") if (st.root / book / "rare_candidates").exists() else None
            slots = slots_from_evidence(match, None)
            if len(slots) < 12:
                continue
            al = align_ops(slots, text, index)
            if al is None:
                continue
            n_anch += 1
            norm, window, ops = al
            diag = anchor_page_diag("".join(t[-1] for t in slots), index)
            mrec = {r.id: r for cc in match.columns for r in cc.chars}
            rrec = {}
            if rare is not None:
                for cc in rare.columns:
                    for r in cc.chars:
                        seen = []
                        for c in r.candidates:
                            if c.char not in seen:
                                seen.append(c.char)
                        rrec[r.id] = seen
            ncol = Counter(t[0] for t in norm)
            n_eq = sum(i2 - i1 for tag, i1, i2, _, _ in ops if tag == "equal")
            n_rep = sum(i2 - i1 for tag, i1, i2, j1, j2 in ops if tag == "replace" and (i2 - i1) == (j2 - j1))
            n_ops_nonequal = sum(1 for o in ops if o[0] != "equal")
            for n, (tag, i1, i2, j1, j2) in enumerate(ops):
                if tag != "replace" or (i2 - i1) != (j2 - j1):
                    continue
                prev_run, next_run = flank_runs(ops, n)
                L = i2 - i1
                lg = replace_len_gate(ops, n)
                seg = []
                for k in range(L):
                    col, idx, sub, hyp = norm[i1 + k]
                    gold = window[j1 + k]
                    cid = f"{book}:{pg}:{col}:{idx}{sub}"
                    seg.append((cid, col, idx, sub, hyp, gold, mrec.get(cid)))
                # 现行库证据闸：直接调生产函数
                labs = [AlignedLabel(c[0], pg, c[5], c[4], "replace", L) for c in seg]
                kept, _ = lib_gate(labs, match, 0.996)
                kept_ids = {l.instance_id for l in kept}
                # 段级特征
                seg_cov = [c[6].cov if c[6] else 0.0 for c in seg]
                seg_var = [are_variants(c[4], c[5]) and c[4] != c[5] for c in seg]
                seg_conf = [1 if (c[6] and c[6].cov >= 0.996 and lib_char_of(c[6]) not in (None, c[5])
                                  and not are_variants(lib_char_of(c[6]), c[5])) else 0 for c in seg]
                seg_rank = []
                for c in seg:
                    lst = rrec.get(c[0])
                    seg_rank.append((lst.index(c[5]) + 1) if (lst and c[5] in lst) else (0 if lst else -1))
                for k, (cid, col, idx, sub, hyp, gold, m) in enumerate(seg):
                    x = lib_char_of(m)
                    cands = m.candidates if m else []
                    s1 = cands[0][1] if cands else 0.0
                    s2 = cands[1][1] if len(cands) > 1 else 0.0
                    gold_in_lib = [i for i, (ch, _s) in enumerate(cands) if ch == gold]
                    gold_in_lib_rank = gold_in_lib[0] + 1 if gold_in_lib else 0
                    gold_in_lib_score = cands[gold_in_lib[0]][1] if gold_in_lib else 0.0
                    rl = rrec.get(cid)
                    v = verdict.get(cid)
                    shape = v["shape"] if (v and v["v"] == "confirm" and v["shape"]) else None
                    ok = None
                    if shape:
                        ok = bool(J(gold) == J(shape) or are_variants(gold, shape))
                    n_verd_all += 1 if v else 0
                    row = {
                        "id": cid, "book": book, "page": pg, "hyp": hyp, "gold": gold,
                        "len": L, "pos": k, "prev": prev_run, "next": next_run,
                        "flank_min": min(prev_run, next_run), "flank_max": max(prev_run, next_run),
                        "slot": idx, "col": col, "is_sub": 1 if sub else 0,
                        "col_len": ncol[col], "slot_rel": round(idx / max(1, ncol[col]), 3),
                        "page_slots": len(norm), "page_rep_rate": round(n_rep / max(1, len(norm)), 4),
                        "page_eq_rate": round(n_eq / max(1, len(norm)), 4), "page_n_ops": n_ops_nonequal,
                        "an_votes": diag.n_votes, "an_frac": round(diag.vote_frac, 4),
                        "an_dom": round(min(diag.dominance if diag.dominance is not None else 99.0, 99.0), 3),
                        "m_cov": round(m.cov, 4) if m else 0.0, "m_verdict": m.verdict if m else "",
                        "m_nver": m.n_verified if m else 0, "m_wmax": round(m.wmax, 3) if (m and m.wmax is not None) else -1.0,
                        "lib_s1": round(s1, 4), "lib_gap": round(s1 - s2, 4), "lib_n": len(cands),
                        "lib_eq_gold": int(x == gold), "lib_eq_hyp": int(x == hyp),
                        "lib_var_gold": int(bool(x) and x != gold and are_variants(x, gold)),
                        "lib_gold_rank": gold_in_lib_rank, "lib_gold_score": round(gold_in_lib_score, 4),
                        "var_hg": int(hyp != gold and are_variants(hyp, gold)), "conf_hg": int(bool(is_pair(hyp, gold))),
                        "rare_has": int(rl is not None), "rare_gold_rank": seg_rank[k],
                        "rare_top1_gold": int(bool(rl) and rl[0] == gold),
                        "rare_top1_hyp": int(bool(rl) and rl[0] == hyp),
                        "seg_mean_cov": round(sum(seg_cov) / L, 4), "seg_min_cov": round(min(seg_cov), 4),
                        "seg_n_var": sum(seg_var), "seg_n_libconf": sum(seg_conf),
                        "seg_other_libconf": sum(seg_conf) - seg_conf[k],
                        "len_gate": int(lg), "lib_gate_keep": int(cid in kept_ids),
                        "cur_adopt": int(lg and cid in kept_ids),
                        "shape": shape, "gold_ok": ok, "via": (v or {}).get("via"),
                    }
                    n_rows += 1
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
        meta[book] = {"pages_with_match": n_pages, "anchored": n_anch, "rows": n_rows,
                      "verdict_events": cnt["events"], "dropped_stale": cnt["stale"],
                      "dropped_unbound": cnt["unbound"], "verdict_cells_bound": cnt["cells"],
                      "label_source": "seed_admit.human" if via_h else "bindings",
                      "bind_cells_direct": cnt["bind_cells_direct"], "label_cells": len(verdict)}
        print(book, meta[book], file=sys.stderr, flush=True)
    out.close()
    Path(a.out).with_suffix(".meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
