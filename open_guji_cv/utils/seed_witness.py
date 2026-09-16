# -*- coding: utf-8 -*-
"""从证人标签播种字形库：文本（witness-align）× 形状（字体模板 top-1）两路零同源互证才进库。

方案 §五.2「书自己长的库为主」的第一步。刻本链的库是人裁一票一票攒出来的；现代排印本
有一行一列的证人，`witness-align` 一次给两万个字位贴了标签——但那是**文本一路**的证据，
按「OCR 只供候选不投票／自动放行必须两路零同源互证」的纪律，不能单凭它进库。
第二路用字体模板：拿字位的归一图在字体来源（`calibrate-font` 选出的那几套）里检索，
top-1 与证人字相同才算形状路也认了。字体 recall@1 只有 0.92（北行日錄实测），
所以约 8% 的字位会因为字体认不出而不进库——宁缺毋滥；证人错的字位（换行错位整列
已被 witness-align 拒掉，剩下的是错字）字体 top-1 几乎不可能恰好也错成同一个字。

进库：`GlyphDB.admit_instance(provenance="align", edition_tag="modern:<book>")`，来源 kind 记 `print`。
每个字位一条 admissions 审计（证据里记证人页/行、字体 top-1 与 cov），改判可重放。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np


#: 播种检索时每次 match 精验几个候选。只取 top-1，k 大了纯属浪费——见 `seed_from_witness`
#: 里建 matcher 处的实测表。
SEED_KNN_K = 5

SKIP_FLAGS = ("boundary_ink", "truncated", "contaminated", "frame_bars", "bad_seg", "rule_bar", "edge_blob")


def _prep_one(args):
    """一个字位：读 png → 解码 → 归一。进程池的 worker（模块级函数才能 pickle）。"""
    key, path, isotropic, norm_stroke = args
    import cv2
    import numpy as np
    from ..clustering.canonical import to_canonical
    from ..clustering.normalize import normalize_patch
    p = Path(path)
    if not p.exists():
        return key, None
    png = p.read_bytes()
    g = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    if g is None:
        return key, None
    return key, (png, g, normalize_patch(to_canonical(g), stroke_width=norm_stroke,
                                         isotropic=isotropic))


def _prep_patches(rows, cache_root: Path, book_id: str, norm_stroke, jobs: int = 1) -> dict:
    """批量把字块读进来并归一。`jobs>1` 走进程池（纯 CPU、无状态，这段占检索三分之一）。"""
    from ..core.spec import cell_key
    tasks = []
    for d in rows:
        key = cell_key(d["page"], d["col"], d["slot"])
        tasks.append((key, str(cache_root / book_id / "char_patch" / (key + ".png")),
                      d.get("cell_kind") == "punct", norm_stroke))
    out: dict = {}
    if jobs and jobs > 1:
        import multiprocessing as mp
        with mp.Pool(jobs) as pool:
            for key, got in pool.imap(_prep_one, tasks, chunksize=64):
                if got is not None:
                    out[key] = got
        return out
    for t in tasks:
        key, got = _prep_one(t)
        if got is not None:
            out[key] = got
    return out


def seed_from_witness(db, book, *, labels_path: Path, cache_root: Path, font_editions: list[str],
                      edition_tag: str | None = None, kinds=("char", "punct"), limit: int | None = None,
                      products_root: Path | None = None, skip_flags=SKIP_FLAGS,
                      norm_stroke: int | None = None, jobs: int = 1,
                      only_chars: str | None = None, log=print) -> dict:
    """两阶段：先对全部字位做字体检索（只读，检索缓存稳定），再逐条进库（只写）。

    第一版是边检索边进库——每 `admit_instance` 一条就让 `GlyphDB.query` 的特征缓存失效
    （缓存键含 exemplar 条数），下一次检索重建整张表，25 分钟只进了 4,101 条；
    拆成两阶段后检索 ~15ms/次、进库 ~10ms/条。"""
    from ..clustering.canonical import to_canonical
    from ..clustering.normalize import normalize_patch
    from ..core.spec import cell_key

    edition = edition_tag or f"modern:{book.id}"
    # 标点也播种（2026-09-15）。此前只收 `kind=char`，于是库里一个逗号句号都没有，
    # 全书 3,572 个标点字位在 Step5-a 全部落进 diff/unsure——覆盖率的最大单项缺口。
    # 标点的图块 Step4 早就有了（Step3 的 punct 格照样出 patch，只是 cell_type 记成 char），
    # 缺的只是这道闸放行。**标点必须用等比归一**（`isotropic=True`）：它的宽高比本身就是
    # 判据（，0.65 / 、1.04 / 。1.00 / ：0.48，方差 ±0.02），默认那 ±20% 各向异性拉伸
    # 会把判据抹平——实测 `，`/`、` 的间隔从 +0.336 掉到 +0.044。
    def norm_of(d, img):
        return normalize_patch(to_canonical(img), stroke_width=norm_stroke,
                               isotropic=(d.get("cell_kind") == "punct"))
    # 形状证人这一路必须与 Step5-a 用同一把尺子（笔宽归一 `norm_stroke`）。2026-09-15 北行日錄
    # 实锤：不归一时书块 4.6px vs 字体 2.7px，cov 0.6～0.8 量的是粗细，字→宇、旦→且、宣→宜/直
    # 在两套字体下**每个实例**都反，于是 字/旦/宣 一个都没进库，Step5-a 只剩形近字可配——
    # 五例「真错」有三例根子在这。归一后字体 top-1 对这些字全对（见 modern_print_pipeline.md §五.4）。
    matchers: dict[str, object] = {}
    if norm_stroke:
        from ..clustering.seeding import load_matcher_from_db
        for ed in font_editions:
            # `knn_k=5`：播种只用 top-1（下面 `font_top1` 只读第一名），k 是**精验几个候选**。
            # 每次 match 的开销几乎全在这 k 次 elastic 精验上。北行日錄实测（399 个字位）：
            #   k=10 → 21.1 ms/次，top-1 一致 96.49%
            #   k= 5 →  9.2 ms/次，top-1 一致 96.49%   ← 一致率一模一样，快 2.3 倍
            #   k= 3 →  6.1 ms/次，top-1 一致 95.49%   ← 开始掉，不取
            # 全书两套字体：12 分钟 → 5 分钟。
            matchers[ed], _ = load_matcher_from_db(db, edition=ed, norm_stroke=norm_stroke,
                                                   knn_k=SEED_KNN_K)
            log(f"[seed] 字体 {ed} 模板按 norm_stroke={norm_stroke} 现算完毕（k={SEED_KNN_K}）")

    def font_top1(norm_img, ed):
        """→ (字, cov) 或 None：归一协议走内存匹配器的候选表，否则走库检索。"""
        if norm_stroke:
            m = matchers[ed].match(norm_img)
            if m.candidates:
                return m.candidates[0][0], round(float(m.candidates[0][1]), 4)
            return (m.char, round(float(m.cov), 4)) if m.char else None
        hits = db.query(norm_img, editions=[ed], k=1)
        return (hits[0].char, round(float(hits[0].f1), 4)) if hits else None
    # Step4 自检旗标：截断/污染的字块不进库（刻本链的排除名单 r3 同一条纪律——
    # 「宁可少一批好图也不留一条坏图」）。北行日錄 2026-09-15 实锤：库里三个「宣」全是列末字、
    # 底横被 Step4 当框线抹掉、都带 boundary_ink，害得整本书的「宣」配到「直」。
    bad_flags = set(skip_flags)
    cell_flags: dict[tuple[int, int, int], tuple[str, ...]] = {}
    for p in sorted((products_root / book.id / "cell_shrink").glob("p*.json")) if products_root else []:
        doc = json.loads(p.read_text(encoding="utf-8"))["char_index"]
        for c in doc["columns"]:
            for x in c.get("chars", []):
                cell_flags[(doc["page"], c["col"], x["slot"])] = tuple(x.get("flags") or [])
    rows: list[dict] = []
    n_flagged = 0
    flagged_by = Counter()
    for ln in labels_path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        d = json.loads(ln)
        if d.get("kind") not in kinds or d.get("cell_kind") not in ("char", "punct"):
            continue
        fl = cell_flags.get((d["page"], d["col"], d["slot"]), ())
        hit = [f for f in fl if f in bad_flags]
        if hit:
            n_flagged += 1
            for f in hit:
                flagged_by[f] += 1
            continue
        d["step4_flags"] = list(fl)
        rows.append(d)
    if only_chars:
        # 只播这些字头（`admit_instance` 幂等，已在库的算 n_dup）。修好某一类字的形状
        # 证人之后补播用——北行日錄 2026-09-15：字体模板转 90° 修好引号，只需补 170 个
        # 引号字位，没必要为它把两万条全检索一遍（全量 ~8 分钟，只补引号 ~5 秒）。
        want = set(only_chars)
        rows = [d for d in rows if d["char"] in want]
        log(f"[seed] 只播 {len(want)} 个字头：{only_chars} → {len(rows)} 个字位")
    if limit:
        rows = rows[:limit]
    n_seen = len(rows)
    log(f"[seed] Step4 旗标排除 {n_flagged} 个字位：{dict(flagged_by)}")

    # ── 阶段一：检索（只读）──
    plan: list[tuple[dict, bytes, np.ndarray, list[str], dict]] = []
    n_font_reject = n_missing = 0
    rejects: list[dict] = []
    agree_by = Counter()
    # 读图 + 解码 + 归一是纯 CPU、无状态的一段，占检索总时长的三分之一，先并行做完再检索。
    # （检索本身不并行：matcher 带着 2000 个模板的特征矩阵，进程间传它比算还贵。）
    prepped = _prep_patches(rows, cache_root, book.id, norm_stroke, jobs=jobs)
    for i, d in enumerate(rows):
        key = cell_key(d["page"], d["col"], d["slot"])
        got = prepped.get(key)
        if got is None:
            n_missing += 1
            continue
        png, g, norm = got
        ch = d["char"]
        agreed, tops = [], {}
        for ed in font_editions:
            t = font_top1(norm, ed)
            if t:
                tops[ed] = t
                if t[0] == ch:
                    agreed.append(ed)
        if not agreed:
            n_font_reject += 1
            if len(rejects) < 200:
                rejects.append({"key": key, "char": ch, "tops": tops})
            continue
        agree_by[",".join(agreed)] += 1
        plan.append((d, png, g, agreed, tops))
        if (i + 1) % 2000 == 0:
            log(f"  [seed/检索] {i + 1}/{n_seen}：字体认可 {len(plan)} 不认 {n_font_reject}")
    log(f"[seed/检索] 字位 {n_seen}：字体认可 {len(plan)}，不认 {n_font_reject}，缺字块 {n_missing}")

    # ── 阶段二：进库（只写）──
    n_admit = n_dup = 0
    for j, (d, png, g, agreed, tops) in enumerate(plan):
        iid = f"{book.id}:{d['page']}:{d['col']}:{d['slot']}"
        ok = db.admit_instance(
            iid, d["char"], png, provenance="align", edition_tag=edition,
            evidence={"witness_page": d.get("witness_page"), "line_idx": d.get("line_idx"),
                      "font_agree": agreed, "font_tops": tops, "step4_flags": d.get("step4_flags", [])},
            page=str(d["page"]), col=int(d["col"]), idx=int(d["slot"]),
            ink_ratio=float((g < 128).mean()), width=float(g.shape[1]), height=float(g.shape[0]))
        if ok:
            n_admit += 1
        else:
            n_dup += 1
        if (j + 1) % 2000 == 0:
            db.conn.commit()
            log(f"  [seed/进库] {j + 1}/{len(plan)}：新进 {n_admit} 已有 {n_dup}")
    db.conn.execute("UPDATE sources SET kind='print' WHERE source_id=?", (book.id,))
    db.conn.commit()
    n_glyphs = db.conn.execute("SELECT COUNT(*) FROM glyphs WHERE edition_tag=?", (edition,)).fetchone()[0]
    stats = {"edition": edition, "labels_seen": n_seen, "admitted": n_admit,
             "step4_flag_rejected": n_flagged, "step4_flag_by": dict(flagged_by),
             "font_rejected": n_font_reject, "patch_missing": n_missing, "duplicate": n_dup,
             "agree_by": dict(agree_by), "glyphs": n_glyphs, "reject_samples": rejects[:40]}
    log(f"[seed] {edition}: 字位 {n_seen} → 新进库 {n_admit}（已有 {n_dup}，字头 {n_glyphs}），"
        f"字体不认 {n_font_reject}，缺字块 {n_missing}")
    return stats
