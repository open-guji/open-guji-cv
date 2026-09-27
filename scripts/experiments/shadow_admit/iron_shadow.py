# -*- coding: utf-8 -*-
"""铁证放行影子验收：铁证（总览/14 §二）+ 小笔画判别器（总览/14 §八 方案③）合成一条独立的
候选放行规则，对**全部字位**算「若这条规则接管，这一位会不会自动放行、放行成什么字」——
不看 `seed_admit` 当前是否已放行、不依赖 OCR（`page_slots` 只借 Step7 产物拿字位流与
`is_text`，取字判断全部自己重算）。

真值只用 `feedback.lookup.human_chars`（人裁字形，真源，不看整理本、不看 OCR）：
    GUJI_WORKSPACE=<ws> PYTHONPATH=. .venv/bin/python scripts/experiments/shadow_admit/iron_shadow.py bxgb \
        --pages 3-56 --out <ws>/reports/bxgb/shadow/iron_shadow.json \
        --sample-out <ws>/reports/bxgb/shadow/audit_sample.json --sample-n 300 --seed 20260927

只出报表 + 抽样名单，不改任何产物、不写库、不写 admissions、不碰 seed_admit.py。

**判据实现在** `open_guji_cv.clustering.iron_evidence`（2026-09-27 转正时从这个文件搬
过去、生产 `steps/seed_admit.py` 的 `iron` 通道与这里共用同一份代码，护栏与判别器
触发条件的实测教训都写在那个模块的头注释里）。本文件只剩：批处理壳（估书级尺度、
逐页跑、写报表）、按字种去重抽样、以及本道自己评测用的 `CODEPOINT_CONVENTION_PAIRS`
——码位习惯口径，只用于「跟人裁真值比对」这一步怎么分类，不是放行判据的一部分，
所以留在这里而不进共享模块。
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from open_guji_cv.clustering.iron_evidence import (  # noqa: E402
    CANVAS, extra_confusable_partners, human_matcher, iron, iron_with_disc,
)

# 码位规矩（字形库/11，用户 2026-09-27 定表）：这两对是「书级统一指定一个码位」的
# 记录习惯岔子（库/人裁各按各的敲法），评测里当同字、不算错——只影响本文件跟人裁真值
# 比对时怎么分类，不是放行判据，所以留在这里而不是共享模块。
# ⚠️ 幷/并、回/囘 **不在这张表**——用户看抽检 02 样张后判「错」，说明这两对在本书上
# 也能按刻形区分，已改收进共享模块的 EXTRA_CONFUSABLE_PAIRS 走复核（同 强/強、卻/却）。
CODEPOINT_CONVENTION_PAIRS = {frozenset(p) for p in (("别", "別"), ("内", "內"))}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("book")
    ap.add_argument("--pages", default="3-56")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sample-out")
    ap.add_argument("--sample-n", type=int, default=300)
    ap.add_argument("--seed", type=int, default=20260927)
    ap.add_argument("--no-disc", action="store_true", help="只跑纯铁证闸，不接判别器（对照用）")
    ap.add_argument("--dedup-char", action="store_true",
                     help="按字种去重抽样（总管 2026-09-27 定）：同一字种只出 1 张，"
                          "优先「没裁过的字种」与「本道追加形近/码位表里有对手的字种」")
    ap.add_argument("--exclude-chars-file",
                     help="JSON 字符数组：已经裁过、判对的字种，去重时跳过（不再出卡）")
    a = ap.parse_args()

    from open_guji_cv.clustering.glyph_db import GlyphDB
    from open_guji_cv.clustering.confusable import partners as _partners
    from open_guji_cv.clustering.normalize import normalize_patch
    from open_guji_cv.clustering.variants import VariantMap
    from open_guji_cv.core.book import load_book
    from open_guji_cv.feedback.lookup import human_chars
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore
    from open_guji_cv.report.slots import page_slots
    from open_guji_cv.steps.glyph_match import GlyphMatchParams
    from open_guji_cv.utils.image_io import imread

    book = a.book
    bk = load_book(book)
    ns = getattr(bk, "norm_stroke", None)
    db_path = GlyphMatchParams().db_path
    matcher, n_lib = human_matcher(db_path, ns)
    partners_map = _partners()
    human_chars_set = set(matcher._chars)
    vm = VariantMap.load()
    st, cache = ProductStore(), ImageCache()
    extra_partners = extra_confusable_partners()

    truth = human_chars(book)
    print(f"人裁真值 {len(truth)} 格；库人裁实例 {n_lib}", file=sys.stderr)

    db = GlyphDB(db_path)
    human_ids: dict[str, list[str]] = {}
    for ch, iid in db.conn.execute(
            """SELECT g.char, e.instance_id FROM exemplars e JOIN glyphs g ON g.glyph_id=e.glyph_id
               JOIN instances i ON i.instance_id=e.instance_id WHERE i.label_status='human'"""):
        human_ids.setdefault(ch, []).append(iid.replace("v2:", ""))

    def raw_of(cid: str):
        bk_, p, c, s = cid.split(":")
        sub = s[-1] if s[-1] in "ab" else ""
        s = s.rstrip("ab")
        path = cache.get(bk_, "char_patch", f"p{int(p):04d}c{int(c):02d}s{s}{sub}")
        return None if path is None else imread(str(path), cv2.IMREAD_GRAYSCALE)

    raw_cache: dict[str, np.ndarray] = {}

    def raw_cached(cid: str):
        if cid not in raw_cache:
            raw_cache[cid] = raw_of(cid)
        return raw_cache[cid]

    human_raws: dict[str, list] = {}

    def ex_raws(ch: str, self_id: str):
        key = (ch, self_id)
        if key not in human_raws:
            ids = [i for i in human_ids.get(ch, []) if i != self_id]
            human_raws[key] = [r for i in ids[:8] if (r := raw_cached(i)) is not None]
        return human_raws[key]

    lo, _, hi = a.pages.partition("-")
    pages = list(range(int(lo), int(hi or lo) + 1))

    # 书级统一尺度：抽样若干页取字块中位边长（总览/14 §八 ①）
    sizes = []
    for pg in pages:
        for s in page_slots(st, book, pg):
            if not s.is_text:
                continue
            path = cache.get(book, "char_patch", f"p{pg:04d}c{s.col:02d}s{s.slot}{s.sub or ''}")
            if path is None:
                continue
            img = imread(str(path), cv2.IMREAD_GRAYSCALE)
            if img is not None:
                sizes.append(max(img.shape))
        if len(sizes) >= 300:
            break
    book_side = float(np.median(sizes)) if sizes else float(CANVAS)
    scale = (CANVAS - 8) / book_side
    print(f"书级尺度：{len(sizes)} 个字块中位边长 {book_side:.1f}px → scale {scale:.4f}", file=sys.stderr)

    stat: Counter = Counter()
    rows = []          # 铁证放行、且有人裁真值可核对的：同字异形/错，全存
    fire_no_truth = []  # 铁证放行、未经人看：抽检池

    for pg in pages:
        for s in page_slots(st, book, pg):
            if not s.is_text or s.char == "□":  # □
                continue
            ck = f"p{pg:04d}c{s.col:02d}s{s.slot}{s.sub or ''}"
            path = cache.get(book, "char_patch", ck)
            if path is None:
                stat["无图块"] += 1
                continue
            img = imread(str(path), cv2.IMREAD_GRAYSCALE)
            if img is None:
                stat["无图块"] += 1
                continue
            res = matcher.match(normalize_patch(img, stroke_width=ns), exclude_id=f"v2:{s.id}")
            cands = [(c, float(v)) for c, v in res.candidates]
            if res.verdict == "same" and res.char and all(c != res.char for c, _ in cands):
                cands.insert(0, (res.char, float(res.cov)))
            cands.sort(key=lambda t: -t[1])

            if a.no_disc:
                winner, top, second, why = iron(cands, human_chars_set, partners_map)
                disc = None
                if winner is not None:
                    why = "铁证"
            else:
                winner, top, second, why, disc = iron_with_disc(
                    cands, human_chars_set, partners_map, img,
                    lambda ch, _s=s.id: ex_raws(ch, _s), scale)

            gt = truth.get(s.id)
            if winner is None:
                stat["无铁证:" + why.split("(")[0]] += 1
                continue
            stat["铁证放行"] += 1
            row = {"id": s.id, "page": pg, "gt": gt, "winner": winner,
                   "top": round(top, 4), "second": round(second, 4), "why": why, "disc": disc}
            if gt is not None:
                if winner == gt:
                    stat["核对人裁·对"] += 1
                elif vm.semantic(winner) == vm.semantic(gt):
                    stat["核对人裁·同字异形"] += 1
                    rows.append(row)
                elif frozenset((winner, gt)) in CODEPOINT_CONVENTION_PAIRS:
                    stat["核对人裁·码位不一致"] += 1
                    rows.append(row)
                else:
                    stat["核对人裁·错"] += 1
                    rows.append(row)
            else:
                stat["放行·未经人看"] += 1
                fire_no_truth.append({"id": s.id, "char": winner})
        print(f"p{pg} 累计 {dict(stat)}", file=sys.stderr, flush=True)

    n_checked = stat["核对人裁·对"] + stat["核对人裁·同字异形"] + stat["核对人裁·错"]
    err = stat["核对人裁·错"]
    no_truth_char_counts = dict(Counter(r["char"] for r in fire_no_truth))
    Path(a.out).write_text(json.dumps({
        "book": book, "pages": a.pages, "disc": not a.no_disc,
        "n_human_lib": n_lib, "book_scale": round(scale, 4), "book_side_px": round(book_side, 1),
        "stat": dict(stat),
        "n_checked_vs_human": n_checked, "n_wrong_vs_human": err,
        "err_rate_vs_human": (err / n_checked) if n_checked else None,
        "rows_checked_wrong_or_variant": rows,
        # 「放行·未经人看」池按字种计数——按字种加权合并多轮抽检估计用，见任务书回报。
        "no_truth_char_counts": no_truth_char_counts,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"完成。{dict(stat)}", file=sys.stderr)
    print(f"对人裁核对：{n_checked} 格，错 {err}"
          + (f"（{err/n_checked*100:.4f}%）" if n_checked else "（分母为 0）"), file=sys.stderr)

    if a.sample_out:
        random.seed(a.seed)
        pool = fire_no_truth[:]
        random.shuffle(pool)
        if a.dedup_char:
            # 总管 2026-09-27 定：随机抽检 01 里高频简单字（十/之/一/五…）反复出、把人
            # 累坏了才停在 71/300。改按字种去重：同一字种只留 1 张；已裁过判对的字种
            # 整个跳过；优先出「没裁过的字种」与「本道形近/码位表里有对手的字种」。
            exclude = set()
            if a.exclude_chars_file:
                exclude = set(json.loads(Path(a.exclude_chars_file).read_text(encoding="utf-8")))
            watch_chars = set(extra_partners) | {c for p in CODEPOINT_CONVENTION_PAIRS for c in p}
            by_char: dict[str, dict] = {}
            for row in pool:
                ch = row["char"]
                if ch in exclude or ch in by_char:
                    continue
                by_char[ch] = row
            ranked = sorted(by_char.values(), key=lambda r: 0 if r["char"] in watch_chars else 1)
            sample = ranked[:a.sample_n]
            n_pool_cells = sum(1 for r in pool if r["char"] not in exclude)
            print(f"去重：池 {len(pool)} 格 → {len(by_char)} 个未裁字种（已排除 {len(exclude)} 个"
                  f"已判对字种）；本页 {len(sample)} 张，其中 {sum(1 for r in sample if r['char'] in watch_chars)} "
                  f"张是形近/码位表里的字种", file=sys.stderr)
        else:
            sample = pool[:a.sample_n]
            n_pool_cells = len(pool)
        Path(a.sample_out).write_text(json.dumps({
            "book": book, "seed": a.seed, "pool_size": len(fire_no_truth),
            "pool_cells_excluding_confirmed": n_pool_cells, "dedup_char": a.dedup_char,
            "n": len(sample), "sample": sample,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"随机抽检名单：池 {len(fire_no_truth)} 格，抽 {len(sample)}（种子 {a.seed}）", file=sys.stderr)


if __name__ == "__main__":
    main()
