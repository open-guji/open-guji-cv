# -*- coding: utf-8 -*-
"""字体判定：这本书的字最像库里哪套字体，以及那套字体能不能当模板。

三模式方案 §五.1 的 `calibrate font`：拿**已有标签**的字位（现代链来自 `witness-align`，
刻本链可来自人裁）当查询，只在一套字体来源里检索（`GlyphDB.query(editions=[...])`），
看正确字排第几、正确命中的 cov 与错误命中的 cov 分不分得开——量法照搬
`.claude/doc/glyph_db_expansion_research.md` §6.2（那里的负结果是「字体 vs 刻本不可分」；
现代排印本是「字体 vs 同一类字体的扫描」，这里就是把它量出来）。

结果每套字体一行：覆盖率、recall@1/@5、正确命中 cov 的 p10/中位、错误命中 cov 的中位/p90、
可分性 margin = p10(正确) − p90(错误)。margin > 0 才有资格当精确模板；不然只当候选源。
"""

from __future__ import annotations

import json
import random
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np


@dataclass
class FontScore:
    edition: str
    n_queries: int
    covered: int                 # 查询字里字体有字形的
    recall1: float
    recall5: float
    cov_correct_p10: float
    cov_correct_med: float
    cov_wrong_med: float
    cov_wrong_p90: float
    margin: float
    n_same: int                  # verify 判 same 的次数（按刻本闸）
    detail: dict = field(default_factory=dict)


def _pct(xs, q):
    return float(np.percentile(xs, q)) if xs else float("nan")


def load_labels(path: Path, *, kinds=("char",), max_per_char: int = 3,
                max_chars: int = 600, seed: int = 0) -> list[dict]:
    """labels.jsonl → 抽样：每个字最多 max_per_char 个字位，最多 max_chars 个字。"""
    by_char: dict[str, list[dict]] = defaultdict(list)
    for ln in path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        d = json.loads(ln)
        if d.get("kind") in kinds and d.get("cell_kind") == "char":
            by_char[d["char"]].append(d)
    rng = random.Random(seed)
    chars = sorted(by_char)
    rng.shuffle(chars)
    out: list[dict] = []
    for ch in chars[:max_chars]:
        items = by_char[ch]
        rng.shuffle(items)
        out.extend(items[:max_per_char])
    return out


def patch_path(cache_root: Path, book_id: str, d: dict) -> Path:
    from ..core.spec import cell_key
    return cache_root / book_id / "char_patch" / (cell_key(d["page"], d["col"], d["slot"]) + ".png")


def score_fonts(db, book_id: str, labels: list[dict], cache_root: Path, editions: list[str],
                *, k: int = 5, exclude_self: bool = False, log=print) -> list[FontScore]:
    """`exclude_self=True`：留一法——查询字位自己若已在库里（播种过的 `modern:<book>`），
    把它摘掉再检索，否则是自证（cov 1.0、matched 自己），量不出任何东西。"""
    from ..clustering.canonical import to_canonical
    from ..clustering.normalize import normalize_patch

    norms: list[tuple[dict, np.ndarray]] = []
    missing = 0
    for d in labels:
        p = patch_path(cache_root, book_id, d)
        g = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if g is None:
            missing += 1
            continue
        norms.append((d, normalize_patch(to_canonical(g))))
    log(f"[calibrate-font] 查询字位 {len(norms)}（字块缺失 {missing}）")
    has: dict[str, set[str]] = {}
    for ed in editions:
        has[ed] = {r[0] for r in db.conn.execute(
            "SELECT char FROM glyphs WHERE edition_tag=?", (ed,))}
    out: list[FontScore] = []
    for ed in editions:
        r1 = r5 = covered = n_same = 0
        cov_ok: list[float] = []
        cov_wrong: list[float] = []
        per_char_wrong: dict[str, int] = defaultdict(int)
        for d, norm in norms:
            ch = d["char"]
            if ch not in has[ed]:
                continue
            covered += 1
            excl = [f"{book_id}:{d['page']}:{d['col']}:{d['slot']}"] if exclude_self else None
            hits = db.query(norm, editions=[ed], k=k, exclude=excl)
            if not hits:
                continue
            top = hits[0]
            if top.verdict == "same":
                n_same += 1
            ranks = [h.char for h in hits]
            if ranks and ranks[0] == ch:
                r1 += 1
                cov_ok.append(top.f1)
            else:
                cov_wrong.append(top.f1)
                per_char_wrong[f"{ch}→{ranks[0] if ranks else '∅'}"] += 1
            if ch in ranks:
                r5 += 1
        n = covered or 1
        out.append(FontScore(
            edition=ed, n_queries=len(norms), covered=covered,
            recall1=r1 / n, recall5=r5 / n,
            cov_correct_p10=_pct(cov_ok, 10), cov_correct_med=_pct(cov_ok, 50),
            cov_wrong_med=_pct(cov_wrong, 50), cov_wrong_p90=_pct(cov_wrong, 90),
            margin=_pct(cov_ok, 10) - _pct(cov_wrong, 90) if cov_ok and cov_wrong else float("nan"),
            n_same=n_same,
            detail={"top_confusions": sorted(per_char_wrong.items(), key=lambda kv: -kv[1])[:15]}))
        log(f"  {ed:20s} 覆盖 {covered}/{len(norms)} recall@1 {out[-1].recall1:.3f} "
            f"recall@5 {out[-1].recall5:.3f} cov正确 p10/中位 {out[-1].cov_correct_p10:.3f}/"
            f"{out[-1].cov_correct_med:.3f} cov错误 中位/p90 {out[-1].cov_wrong_med:.3f}/"
            f"{out[-1].cov_wrong_p90:.3f} margin {out[-1].margin:+.3f} same {n_same}")
    out.sort(key=lambda s: (-s.recall1, -s.margin))
    return out


def format_table(scores: list[FontScore]) -> str:
    lines = ["| 字体 | 覆盖 | recall@1 | recall@5 | cov正确 p10 / 中位 | cov错误 中位 / p90 | margin | same |",
             "|---|---|---|---|---|---|---|---|"]
    for s in scores:
        lines.append(f"| {s.edition} | {s.covered}/{s.n_queries} | {s.recall1:.3f} | {s.recall5:.3f} | "
                     f"{s.cov_correct_p10:.3f} / {s.cov_correct_med:.3f} | {s.cov_wrong_med:.3f} / {s.cov_wrong_p90:.3f} | "
                     f"{s.margin:+.3f} | {s.n_same} |")
    return "\n".join(lines)
