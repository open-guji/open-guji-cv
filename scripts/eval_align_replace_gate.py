# -*- coding: utf-8 -*-
"""Step5-d `replace` 段采信闸评测：长度闸（现役） vs 代价闸（emb 余弦 ⊕ IDS/异体关系）。

    PYTHONIOENCODING=utf-8 python scripts/eval_align_replace_gate.py -w <工作区> --books vol01,vol02 \
        [--pages 1-50] [--out cache/align_gate] [--dump-only]

## 量什么（任务卡 2026-09-22 T7）

`align_ref` 只采信「段长 ≤3 且被 equal 夹住」的等长 replace 段（`align_label.replace_len_gate`），
这道闸只看**位置**，不看这一格的图像像不像整理本给的字。本脚本把锚定 + difflib 之后**全部**
等长 replace 位枚举出来（`align_label.align_ops`，与生产同一份枚举），每位算：

- `cos_gold`：字块 r5 embedding 与整理本字（gold）字体模板均值的余弦；`cos_hyp`：与载体字的余弦
- `same_top` / `jac`：载体字与 gold 的 IDS 顶层结构是否相同、`部件@槽` 集合的 Jaccard
- `variant` / `confusable`：`config/variants/variants.json` 里是不是异体对、T6 形近对表里是不是形近对
- `len` / `prev` / `next`：段长、左右 equal 段长；`len_gate`：现役长度闸过不过

真值：`feedback/events/<book>-*decide*.jsonl` 里用户 confirm 的 `shape`（刻本字形口径）。
一位「采对」= gold == shape，或 gold 与 shape 是异体对（忠于刻本字形方针下的正常分歧，
见 `replace_len_gate` 注释里 櫽/檃 那段）。

报：各闸的**采信率**（采信位 / 全部等长 replace 位）与人裁子集上的**错采率**（采信且采错 / 采信）、
**漏采率**（采对但被拦 / 采对）。载体串这里只用 `glyph_match`（云端没装 OCR），与生产
`slots_from_evidence(match, ocr)` 差一路，报数时注明。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))


def load_confirms(ws: Path, book: str) -> dict[str, str]:
    """用户 confirm → {cell key: shape}，同一格取最后一次。"""
    out: dict[str, tuple[int, str]] = {}
    for f in sorted((ws / "feedback/events").glob(f"{book}-*decide*.jsonl")):
        for ln in f.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            r = json.loads(ln)
            if r.get("kind") != "confirm" or r.get("actor") != "user":
                continue
            shape = (r.get("payload") or {}).get("shape")
            key = (r.get("target") or {}).get("key")
            if not shape or not key:
                continue
            seq = int(r.get("seq") or 0)
            if key not in out or seq >= out[key][0]:
                out[key] = (seq, shape)
    return {k: v[1] for k, v in out.items()}


def variant_rel():
    d = json.loads((REPO / "config/variants/variants.json").read_text(encoding="utf-8"))
    pairs = d.get("pairs", {}); directed = d.get("directed", {})

    def rel(a: str, b: str) -> bool:
        if a == b:
            return True
        return (b in (pairs.get(a) or {})) or (a in (pairs.get(b) or {})) \
            or (b in (directed.get(a) or {})) or (a in (directed.get(b) or {}))
    return rel


def dump_book(ws: Path, book: str, pages: list[int] | None, cnn, out_dir: Path) -> list[dict]:
    from open_guji_cv.clustering.align_label import align_ops, flank_runs, replace_len_gate
    from open_guji_cv.clustering.confusables import is_pair
    from open_guji_cv.clustering.ids_struct import slot_keys_of, structure_of
    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.core.book import load_book
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.core.spec import page_key
    from open_guji_cv.core.step import RunContext
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.steps.align_ref import _corpus_index, _corpus_text, book_corpus, slots_from_evidence

    bk = load_book(book)
    store = ProductStore(); cache = ImageCache()
    ctx = RunContext(bk, store, cache)
    corpus_path = book_corpus(book)
    text = _corpus_text(corpus_path); index = _corpus_index(corpus_path)
    confirms = load_confirms(ws, book)
    rel = variant_rel()
    pages = pages or bk.all_pages()

    rows: list[dict] = []
    n_anch = n_pages = 0
    for pg in pages:
        match = store.read(book, "glyph_match", page_key(pg), "glyph_match")
        chars = store.read(book, "cell_shrink", page_key(pg), "char_index")
        if match is None or chars is None:
            continue
        n_pages += 1
        slots = slots_from_evidence(match, None)
        if len(slots) < 12:
            continue
        aligned = align_ops(slots, text, index)
        if aligned is None:
            continue
        n_anch += 1
        norm, window, ops = aligned
        pk = {r.id: r.patch_key for cc in chars.columns for r in cc.chars if r.patch_key}
        mrec = {r.id: r for cc in match.columns for r in cc.chars}
        for n, (tag, i1, i2, j1, j2) in enumerate(ops):
            if tag != "replace" or (i2 - i1) != (j2 - j1):
                continue
            prev_run, next_run = flank_runs(ops, n)
            lg = replace_len_gate(ops, n)
            for k in range(i2 - i1):
                col, idx, sub, hyp = norm[i1 + k]
                gold = window[j1 + k]
                cid = f"{book}:{pg}:{col}:{idx}{sub}"
                m = mrec.get(cid)
                rows.append({"id": cid, "book": book, "page": pg, "hyp": hyp, "gold": gold,
                             "len": i2 - i1, "pos": k, "prev": prev_run, "next": next_run, "len_gate": lg,
                             "m_verdict": m.verdict if m else "", "m_cov": round(m.cov, 4) if m else 0.0,
                             "patch_key": pk.get(cid), "shape": confirms.get(cid)})
    print(f"{book}: 有产物 {n_pages} 页，锚上 {n_anch} 页，等长 replace 位 {len(rows)}，"
          f"其中人裁 {sum(1 for r in rows if r['shape'])}", flush=True)

    # ── 图像代价：字块 embedding vs 模板均值 ──
    charset = tuple(sorted({r["gold"] for r in rows} | {r["hyp"] for r in rows}
                           | {r["shape"] for r in rows if r["shape"]}))
    mat, names = cnn._emb_index(charset)
    tidx = {c: i for i, c in enumerate(names)}
    embs: dict[str, "object"] = {}
    todo = [r for r in rows if r["patch_key"] and r["id"] not in embs]
    B = 256
    for s in range(0, len(todo), B):
        chunk = todo[s:s + B]; norms = []; ids = []
        for r in chunk:
            try:
                img = ctx.image("char_patch", r["patch_key"])
            except Exception:
                continue
            norms.append(normalize_patch(img)); ids.append(r["id"])
        if norms:
            e = cnn.embed(norms)
            for i, v in zip(ids, e):
                embs[i] = v
    for r in rows:
        v = embs.get(r["id"])
        def cos(c):
            j = tidx.get(c)
            return round(float(v @ mat[j]), 4) if (v is not None and j is not None) else None
        r["cos_gold"] = cos(r["gold"]); r["cos_hyp"] = cos(r["hyp"])
        r["cos_shape"] = cos(r["shape"]) if r["shape"] else None
        sg, sh = structure_of(r["gold"]), structure_of(r["hyp"])
        kg, kh = set(slot_keys_of(r["gold"])), set(slot_keys_of(r["hyp"]))
        r["same_top"] = sg.top == sh.top
        r["jac"] = round(len(kg & kh) / max(1, len(kg | kh)), 3)
        r["variant"] = rel(r["hyp"], r["gold"])
        r["confusable"] = is_pair(r["hyp"], r["gold"])
        if r["shape"]:
            r["gold_ok"] = (r["gold"] == r["shape"]) or rel(r["gold"], r["shape"])
        else:
            r["gold_ok"] = None
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{book}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                           encoding="utf-8")
    return rows


def report(rows: list[dict]) -> None:
    H = [r for r in rows if r["gold_ok"] is not None]
    n_all = len(rows); n_h = len(H); n_ok = sum(1 for r in H if r["gold_ok"])
    print(f"\n全部等长 replace 位 {n_all}；人裁 {n_h}（gold 对 {n_ok} = {100 * n_ok / max(1, n_h):.1f}%）")

    def line(name, f):
        acc = [r for r in rows if f(r)]
        accH = [r for r in H if f(r)]
        wrong = sum(1 for r in accH if not r["gold_ok"])
        missed = sum(1 for r in H if r["gold_ok"] and not f(r))
        print(f"{name:<44s} 采信 {len(acc):5d}/{n_all} = {100 * len(acc) / max(1, n_all):5.1f}% │ "
              f"人裁采信 {len(accH):4d} 错采 {wrong:3d} = {100 * wrong / max(1, len(accH)):5.1f}% │ "
              f"漏采 {missed:3d}/{n_ok} = {100 * missed / max(1, n_ok):5.1f}%")

    def cg(r, t): return r["cos_gold"] is not None and r["cos_gold"] >= t
    def margin(r, t): return r["cos_gold"] is not None and r["cos_hyp"] is not None and r["cos_gold"] - r["cos_hyp"] >= t
    flank = lambda r: max(r["prev"], r["next"]) >= 2 and min(r["prev"], r["next"]) >= 1
    print("── 闸 ──")
    line("G0 长度闸（现役：len≤3 & 夹住）", lambda r: r["len_gate"])
    line("   不设闸（全部等长 replace）", lambda r: True)
    line("   只要夹住（不限段长）", flank)
    for t in (0.5, 0.6, 0.7, 0.8):
        line(f"G1 代价闸 cos_gold ≥ {t}", lambda r, t=t: cg(r, t))
    for t in (0.5, 0.6, 0.7):
        line(f"G2 cos_gold ≥ {t} 或 异体/形近", lambda r, t=t: cg(r, t) or r["variant"] or r["confusable"])
    for t in (0.5, 0.6, 0.7):
        line(f"G3 长度闸 ∧ cos_gold ≥ {t}", lambda r, t=t: r["len_gate"] and cg(r, t))
    for t in (0.6, 0.7, 0.8):
        line(f"G4 长度闸 ∨ (夹住 ∧ cos_gold ≥ {t})", lambda r, t=t: r["len_gate"] or (flank(r) and cg(r, t)))
    for t in (0.0, 0.05, 0.1):
        line(f"G5 长度闸 ∧ (cos_gold − cos_hyp ≥ {t} 或 异体)", lambda r, t=t: r["len_gate"] and (margin(r, t) or r["variant"]))
    print("── 分层：段长 × 人裁 gold 对不对 ──")
    by = defaultdict(lambda: [0, 0])
    for r in H:
        b = "1" if r["len"] == 1 else "2-3" if r["len"] <= 3 else "4-6" if r["len"] <= 6 else "7+"
        by[b][0] += 1; by[b][1] += r["gold_ok"]
    for b in ("1", "2-3", "4-6", "7+"):
        n, k = by[b]; print(f"  len {b:<4s} n={n:4d} gold 对 {k:4d} = {100 * k / max(1, n):5.1f}%")
    print("── 分层：cos_gold 档 × 人裁 gold 对不对 ──")
    by = defaultdict(lambda: [0, 0])
    for r in H:
        c = r["cos_gold"]
        b = "无图" if c is None else "<0.5" if c < 0.5 else "<0.6" if c < 0.6 else "<0.7" if c < 0.7 else "<0.8" if c < 0.8 else "≥0.8"
        by[b][0] += 1; by[b][1] += r["gold_ok"]
    for b in ("无图", "<0.5", "<0.6", "<0.7", "<0.8", "≥0.8"):
        n, k = by[b]; print(f"  cos {b:<5s} n={n:4d} gold 对 {k:4d} = {100 * k / max(1, n):5.1f}%")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-w", "--workspace", required=True)
    ap.add_argument("--books", default="vol01,vol02")
    ap.add_argument("--pages", default=None, help="页号表达式；默认全书")
    ap.add_argument("--out", default=str(REPO / "cache/align_gate"))
    ap.add_argument("--report-only", action="store_true", help="只读 --out 里已 dump 的行重报")
    a = ap.parse_args()
    ws = Path(a.workspace).resolve()
    os.environ["GUJI_WORKSPACE"] = str(ws)
    out_dir = Path(a.out)
    rows: list[dict] = []
    if a.report_only:
        for b in a.books.split(","):
            f = out_dir / f"{b}.jsonl"
            if f.exists():
                rows += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    else:
        from open_guji_cv.clustering.cnn_candidates import shared
        from open_guji_cv.core.book import load_book
        cnn = shared()
        if not cnn._ensure():
            print("CNN 不可用（缺 torch 或 checkpoint）"); return 1
        for b in a.books.split(","):
            pages = load_book(b).resolve_pages(a.pages) if a.pages else None
            rows += dump_book(ws, b, pages, cnn, out_dir)
    report(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
