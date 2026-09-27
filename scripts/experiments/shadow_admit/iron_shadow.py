# -*- coding: utf-8 -*-
"""铁证放行影子验收：铁证（总览/14 §二）+ 小笔画判别器（总览/14 §八 方案③）合成一条独立的
候选放行规则，对**全部字位**算「若这条规则接管，这一位会不会自动放行、放行成什么字」——
不看 `seed_admit` 当前是否已放行、不依赖 OCR（`page_slots` 只借 Step7 产物拿字位流与
`is_text`，取字判断全部自己重算）。

真值只用 `feedback.lookup.human_chars`（人裁字形，真源，不看整理本、不看 OCR）：
    GUJI_WORKSPACE=<ws> PYTHONPATH=. .venv/bin/python scripts/experiments/shadow_admit/iron_shadow.py bxgb \
        --pages 3-56 --out <ws>/reports/bxgb/shadow/iron_shadow.json \
        --sample-out <ws>/reports/bxgb/shadow/audit_sample.json --sample-n 300 --seed 20260927

判别器触发条件、护栏见总览/14 §八「下一步」，**2026-09-27 bxgb 全书实测后收紧过一版**：
① 归一化按书级统一尺度（不按本字紧框拉伸）、去墨点连通块；
② 两个候选都要有 ≥2 个人裁实例，否则弃权；
③ 入/八 这类「形不可分」登记表，直接弃权交文意；
④ **触发条件收紧为「两个人裁字都 ≥0.99」**（`iron()` 自己的「两个人裁字都像」判据）——
   最初按 §八 字面「次优异字 cov ≥ 0.90」广撒网，bxgb 全书实测 35/322 对人裁核对错
   （10.9%），逐条看图全是语义无关的字（晴/躋、衞/帝、國/回……）：本书字格只有
   ~70px 高，elastic verify 在这个分辨率上会给结构无关、只是左右密度相近的合体字
   虚高的 cov，判别器从没在这种「语义无关」的对子上验证过，等于抛硬币。收紧后
   见下方「结果」一节。距离差 ≥2 才下结论，否则弃权。

只出报表 + 抽样名单，不改任何产物、不写库、不写 admissions、不碰 seed_admit.py。
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
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # 找 scripts/audit_iron_evidence.py

from audit_iron_evidence import human_matcher, iron  # noqa: E402

CANVAS = 96
MIN_INK_AREA = 10
DISC_MARGIN = 2.0
DISC_MIN_INSTANCES = 2
# 总览/14 §八实测：这类刻本近同形字对，判别器也分不开，交文意判断（不是判别器的锅）。
FORM_INSEPARABLE = {frozenset(("入", "八"))}

# 共享形近表（clustering/confusable.py）没收、但 verify 的 elastic cov 对它们的
# 小笔画差异不敏感的对子——本道 shadow 闸自己用的复核名单，**不改共享表**：
# 玉/王、石/右、早/皁、州/川 出自总览/14 §七 16 条冲突抽查；自/目、且/旦 是
# 2026-09-27 bxgb 全书实测新踩到的同型坑（见本文件 iron_with_disc 文档）。
EXTRA_CONFUSABLE_PAIRS: list[tuple[str, str]] = [
    ("玉", "王"), ("石", "右"), ("上", "土"), ("早", "皁"), ("州", "川"),
    ("自", "目"), ("且", "旦"),
    # 2026-09-27 随机抽检 01 实测踩到的两条：
    # 「入/八」本已在 FORM_INSEPARABLE（判别器分不开、交文意），但没进这张表就从来
    # 不会走到 _discriminate 里去查 FORM_INSEPARABLE——bxgb:26:3:4 放「八」其实像「入/人」，
    # 没被拦下就是这个原因，补进来才会真的强制弃权。
    ("入", "八"),
]
EXTRA_CONFUSABLE_PARTNERS: dict[str, frozenset[str]] = {}
for _a, _b in EXTRA_CONFUSABLE_PAIRS:
    EXTRA_CONFUSABLE_PARTNERS.setdefault(_a, set()).add(_b)
    EXTRA_CONFUSABLE_PARTNERS.setdefault(_b, set()).add(_a)
EXTRA_CONFUSABLE_PARTNERS = {k: frozenset(v) for k, v in EXTRA_CONFUSABLE_PARTNERS.items()}

# 码位规矩（字形库/11 草案，H 道起草、用户未定表）：这几对是「同一刻本字形分落两个
# 码位」的记录习惯岔子（库/人裁各按各的敲法），不是形状误判——总管 2026-09-27 裁定
# 单列一档「码位不一致」，不算进错误率，等用户定表后按定的口径重算。
CODEPOINT_CONVENTION_PAIRS = {frozenset(p) for p in (
    ("别", "別"), ("内", "內"), ("幷", "并"),
    # bxgb:11:11:17（随机抽检 01 实测）：放行「回」，图是「囘」——同一刻本字形分落
    # 两个码位，归总管 2026-09-27 裁定的「码位不一致」档，等用户定码位表。
    ("回", "囘"),
)}


def _clean_ink(gray: np.ndarray) -> np.ndarray:
    _, b = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(b, 8)
    keep = np.zeros_like(b)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] >= MIN_INK_AREA:
            keep[lab == i] = 255
    return keep


def _place_center(img: np.ndarray, canvas: int = CANVAS) -> np.ndarray:
    h, w = img.shape
    if h > canvas:
        y0 = (h - canvas) // 2
        img = img[y0:y0 + canvas]
        h = canvas
    if w > canvas:
        x0 = (w - canvas) // 2
        img = img[:, x0:x0 + canvas]
        w = canvas
    out = np.zeros((canvas, canvas), np.uint8)
    y0, x0 = (canvas - h) // 2, (canvas - w) // 2
    out[y0:y0 + h, x0:x0 + w] = img
    return out


def normalize_book_scale(gray: np.ndarray, scale: float) -> np.ndarray:
    """按**书级统一尺度**缩放（不按本字墨迹紧框拉伸——避免窄字放大/宽字压扁），去墨点，居中。"""
    b = _clean_ink(gray)
    h, w = gray.shape
    rw, rh = max(1, round(w * scale)), max(1, round(h * scale))
    r = (cv2.resize(b, (rw, rh), interpolation=cv2.INTER_AREA) > 127).astype(np.uint8) * 255
    return _place_center(r)


def _dt(b: np.ndarray) -> np.ndarray:
    return cv2.distanceTransform((1 - (b > 0).astype(np.uint8)), cv2.DIST_L2, 3)


def chamfer(a: np.ndarray, b: np.ndarray) -> float:
    """刚性对齐（平移 ±5、缩放 3 档）后的对称倒角距离（97 分位，取较差一侧）。"""
    if not a.any() or not b.any():
        return 1e9
    da, best, best_bb = _dt(a), 1e9, None
    for sc in (0.94, 1.0, 1.06):
        bs = cv2.resize(b, None, fx=sc, fy=sc, interpolation=cv2.INTER_NEAREST)
        c = _place_center(bs)
        for dy in range(-5, 6):
            for dx in range(-5, 6):
                bb = np.roll(np.roll(c, dy, 0), dx, 1)
                if not bb.any():
                    continue
                s = float(np.percentile(da[bb > 0], 97))
                if s < best:
                    best, best_bb = s, bb
    if best_bb is None:
        return 1e9
    return max(best, float(np.percentile(_dt(best_bb)[a > 0], 97)))


def iron_with_disc(cands, human_chars_set, partners_map, raw_patch, ex_raws_fn, scale):
    """→ (放行字 | None, top cov, 次优异字 cov, 理由, 判别器距离对 | None)。

    先走纯铁证闸（`iron()`）；**只在 `iron()` 判定「两个人裁字都像」（top/second 都
    ≥ IRON_COV）时**才交判别器对 top/second 两个候选各自的人裁实例做成对判别。

    2026-09-27 实测教训（bxgb 全书）：最初按总览/14 §八字面「次优异字 cov ≥ 0.90」
    广撒网触发判别器，35/322 对人裁核对错（10.9%），逐条看图全是**语义无关的字**
    （晴/躋、衞/帝、國/回……）——本书字格只有 ~70px 高，elastic verify 在这个分辨率上
    对**结构无关但左右密度相近**的合体字会给出虚高的 cov 近打平分，判别器只在「候选
    确实形近」的窄集合上验证过（总览/14 §八用的是 87 条冲突里的王/玉、石/右…），
    对这种大集合里混进来的语义不相关对子等于抛硬币。收紧到只在**两个人裁字都
    ≥0.99**（iron() 自己的「两个人裁字都像」判据）时才用，见 shadow 报告。
    """
    ic, top, second, why = iron(cands, human_chars_set, partners_map)
    if ic is not None:
        # 复核：iron 直接判成的字如果在「本道追加形近表」里有对手，交判别器确认一次——
        # 现有共享形近表（clustering/confusable.py）不收玉/王、上/土、自/目、且/旦
        # 这类对子（2026-09-27 bxgb 实测踩到，总览/14 §七已点过王/玉这个坑），cov 对
        # 这类小笔画差异不敏感，光凭 ≥0.99 会静默放错。
        # ⚠️ 2026-09-27 第一版要求对手字先出现在 GlyphMatcher 的 top-k（k=10）候选里
        # 才触发，实测 bxgb:25:9:17（土/上）因为「土」没挤进前十而漏判——**对手不必
        # 在候选集里**，直接查表触发即可，`_discriminate` 会自己对对手的库实例算 cov。
        partner = next(iter(EXTRA_CONFUSABLE_PARTNERS.get(ic, frozenset())), None)
        if partner is None:
            return ic, top, second, "铁证", None
        return _discriminate(ic, partner, raw_patch, ex_raws_fn, scale, top, second,
                              base_why="铁证", confirm=True)
    if why != "两个人裁字都像" or not cands:
        return None, top, second, why, None
    top_c, top_v = cands[0]
    second_c = next((c for c, v in cands[1:] if c != top_c and abs(v - second) < 1e-9), None)
    if second_c is None:
        return None, top, second, why, None
    return _discriminate(top_c, second_c, raw_patch, ex_raws_fn, scale, top, second,
                          base_why=why, confirm=False)


def _discriminate(cand_a, cand_b, raw_patch, ex_raws_fn, scale, top, second, base_why, confirm):
    """判别 cand_a／cand_b 哪个更像 raw_patch。`confirm=True`：cand_a 是 iron() 已经给出的
    字，只是要用追加形近表复核一次——查不了（实例不够）时**弃权**而不是照旧放行，
    宁可多送审也不让已知的小笔画混淆对蒙混过关。"""
    if frozenset((cand_a, cand_b)) in FORM_INSEPARABLE:
        return None, top, second, "形不可分", None
    ex_a, ex_b = ex_raws_fn(cand_a), ex_raws_fn(cand_b)
    if len(ex_a) < DISC_MIN_INSTANCES or len(ex_b) < DISC_MIN_INSTANCES:
        reason = "候选实例不足(复核)" if confirm else "候选实例不足(判别器)"
        return None, top, second, reason, None
    a0 = normalize_book_scale(raw_patch, scale)
    da = min(chamfer(a0, normalize_book_scale(b, scale)) for b in ex_a[:6])
    db = min(chamfer(a0, normalize_book_scale(b, scale)) for b in ex_b[:6])
    if abs(da - db) < DISC_MARGIN:
        return None, top, second, f"判别器距离差不够({da:.1f}v{db:.1f})", None
    winner = cand_a if da < db else cand_b
    tag = "铁证(判别器复核)" if confirm else "铁证(判别器)"
    return winner, top, second, tag, (round(da, 2), round(db, 2))


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
    Path(a.out).write_text(json.dumps({
        "book": book, "pages": a.pages, "disc": not a.no_disc,
        "n_human_lib": n_lib, "book_scale": round(scale, 4), "book_side_px": round(book_side, 1),
        "stat": dict(stat),
        "n_checked_vs_human": n_checked, "n_wrong_vs_human": err,
        "err_rate_vs_human": (err / n_checked) if n_checked else None,
        "rows_checked_wrong_or_variant": rows,
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
            watch_chars = set(EXTRA_CONFUSABLE_PARTNERS) | {c for p in CODEPOINT_CONVENTION_PAIRS for c in p}
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
