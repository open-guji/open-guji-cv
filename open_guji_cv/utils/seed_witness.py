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


def seed_from_witness(db, book, *, labels_path: Path, cache_root: Path, font_editions: list[str],
                      edition_tag: str | None = None, kinds=("char",), limit: int | None = None,
                      log=print) -> dict:
    """两阶段：先对全部字位做字体检索（只读，检索缓存稳定），再逐条进库（只写）。

    第一版是边检索边进库——每 `admit_instance` 一条就让 `GlyphDB.query` 的特征缓存失效
    （缓存键含 exemplar 条数），下一次检索重建整张表，25 分钟只进了 4,101 条；
    拆成两阶段后检索 ~15ms/次、进库 ~10ms/条。"""
    from ..clustering.canonical import to_canonical
    from ..clustering.normalize import normalize_patch
    from ..core.spec import cell_key

    edition = edition_tag or f"modern:{book.id}"
    rows: list[dict] = []
    for ln in labels_path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        d = json.loads(ln)
        if d.get("kind") in kinds and d.get("cell_kind") == "char":
            rows.append(d)
    if limit:
        rows = rows[:limit]
    n_seen = len(rows)

    # ── 阶段一：检索（只读）──
    plan: list[tuple[dict, bytes, np.ndarray, list[str], dict]] = []
    n_font_reject = n_missing = 0
    rejects: list[dict] = []
    agree_by = Counter()
    for i, d in enumerate(rows):
        key = cell_key(d["page"], d["col"], d["slot"])
        p = cache_root / book.id / "char_patch" / (key + ".png")
        if not p.exists():
            n_missing += 1
            continue
        png = p.read_bytes()
        g = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
        norm = normalize_patch(to_canonical(g))
        ch = d["char"]
        agreed, tops = [], {}
        for ed in font_editions:
            hits = db.query(norm, editions=[ed], k=1)
            if hits:
                tops[ed] = (hits[0].char, round(float(hits[0].f1), 4))
                if hits[0].char == ch:
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
                      "font_agree": agreed, "font_tops": tops},
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
             "font_rejected": n_font_reject, "patch_missing": n_missing, "duplicate": n_dup,
             "agree_by": dict(agree_by), "glyphs": n_glyphs, "reject_samples": rejects[:40]}
    log(f"[seed] {edition}: 字位 {n_seen} → 新进库 {n_admit}（已有 {n_dup}，字头 {n_glyphs}），"
        f"字体不认 {n_font_reject}，缺字块 {n_missing}")
    return stats
