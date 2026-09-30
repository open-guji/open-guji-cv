# -*- coding: utf-8 -*-
"""铁证放行闸：本格与一个**人裁过、别的格**的实例比对，够像就直接放行——不看整理本、
不看 OCR，只认字形库里已经被人确认过的刻例。总览/14 §二的证据等级、§八 的小笔画判别器
（成对倒角距离），加上 D 道影子验收（2026-09-25～27，bxgb／vol03 全书）三轮实测踩出来
的四条护栏，在这一份模块里定型，`steps/seed_admit.py`（生产）与
`scripts/experiments/shadow_admit/`（影子验收）共用，不再各查各的。

**证据来源只认人裁**：`human_matcher()` 建的匹配器只吃 `instances.label_status='human'`
的库实例，align/播种等机器来源的实例一律不算数——这是「铁证」这个名字的字面意思。

## 四条护栏（都是实测踩出来的，别删）

1. **排除自匹配**：调用方传 `exclude_id` 摘掉本格自己的库副本。
2. **两个人裁字都 ≥0.99 不算铁证**：两份人裁证据互相打架，比如 0.9961/旦 0.9935。
3. **低档（0.95~0.99）必须 ≥2 个候选**：候选只有 1 个时「次优 < 0.80」恒成立，
   「没有对手」被错当成「像」的证据，其实是「库里没这个字」的证据（vol03:94:1:4
   实测踩到：库里「生」零人裁实例，唯一候选「注」cov 0.9576 单独蒙混过关）。
4. **形近对家不在人裁库里，不算铁证**：cov 对一点一横不敏感，人裁库只有「太」没有
   「大」时，刻本的「大」对「太」能到 0.994。

## 小笔画判别器什么时候用

只在两种情形触发（**别的情形都不触发**——2026-09-25 bxgb 实测：按「次优 cov ≥0.90」
广撒网触发是负结果，10.87% 错，逐条看图全是语义无关的字，本书字格分辨率低时 elastic
verify 会给结构无关的合体字虚高 cov）：

- 护栏 2 命中（两个人裁字都 ≥0.99）时，对这两个候选做成对判别；
- 铁证已经给出结论，但这个字在 `EXTRA_CONFUSABLE_PAIRS`（本模块配置）里有登记的对手
  ——不管这个对手有没有挤进候选列表的 top-k，直接对它的库实例复核一次
  （2026-09-27 实测：要求对手先出现在 top-k 里会漏判，早/皁、上/土 都因此漏过）。

判别器本身查不了（两个候选都要 ≥2 个人裁实例，查不到就弃权，不回退成「铁证」）。
`FORM_INSEPARABLE`（入/八 这类）直接弃权，交人/文意判断，判别器也分不开。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

IRON_COV = 0.99
IRON_COV_LOW = 0.95
IRON_SECOND_MAX = 0.80

CANVAS = 96
MIN_INK_AREA = 10
DISC_MARGIN = 2.0
DISC_MIN_INSTANCES = 2

_CONFIG = Path(__file__).resolve().parents[2] / "config" / "iron_extra_confusable.json"


@lru_cache(maxsize=1)
def _load_extra_tables(path: str | None = None) -> tuple[dict, frozenset]:
    p = Path(path) if path else _CONFIG
    data = json.loads(p.read_text(encoding="utf-8"))
    partners: dict[str, set[str]] = {}
    for a, b in data.get("extra_confusable_pairs", []):
        partners.setdefault(a, set()).add(b)
        partners.setdefault(b, set()).add(a)
    form_inseparable = frozenset(
        frozenset(p) for p in data.get("form_inseparable_pairs", []))
    return {k: frozenset(v) for k, v in partners.items()}, form_inseparable


def extra_confusable_partners(path: str | None = None) -> dict[str, frozenset[str]]:
    """字 → 追加形近表里的对手集合（config/iron_extra_confusable.json）。"""
    return _load_extra_tables(path)[0]


def form_inseparable(path: str | None = None) -> frozenset[frozenset[str]]:
    """判别器也分不开、直接弃权交人/文意的字对（如 入/八）。"""
    return _load_extra_tables(path)[1]


def human_matcher(db_path: str, norm_stroke: int | None):
    """只吃人裁实例的内存匹配器。返回 (matcher, 人裁实例数)。"""
    from .glyph_db import GlyphDB
    from .match import GlyphMatcher
    from .normalize import normalize_patch
    db = GlyphDB(db_path)
    m = GlyphMatcher(k=10)
    rows = db.conn.execute(
        """SELECT g.char, e.instance_id, i.patch_png FROM exemplars e
           JOIN glyphs g ON g.glyph_id = e.glyph_id
           JOIN instances i ON i.instance_id = e.instance_id
           WHERE i.label_status = 'human'""").fetchall()
    for char, iid, png in rows:
        img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            m.add(iid, char, normalize_patch(img, stroke_width=norm_stroke))
    return m, len(rows)


def iron(cands: list[tuple[str, float]], human_chars: set[str],
         partners: dict[str, frozenset[str]]) -> tuple[str | None, float, float, str]:
    """→ (铁证字 | None, top cov, 次优异字 cov, 不成铁证的原因)。见模块头「四条护栏」。"""
    if not cands:
        return None, 0.0, 0.0, "无候选"
    top_c, top_v = cands[0]
    second = max((v for c, v in cands[1:] if c != top_c), default=0.0)
    if not (top_v >= IRON_COV
            or (top_v >= IRON_COV_LOW and len(cands) >= 2 and second < IRON_SECOND_MAX)):
        return None, top_v, second, "分数不够"
    if second >= IRON_COV:
        return None, top_v, second, "两个人裁字都像"
    missing = sorted(partners.get(top_c, frozenset()) - human_chars)
    if missing:
        return None, top_v, second, "形近对家未入人裁库:" + "".join(missing[:5])
    return top_c, top_v, second, ""


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


def book_scale_from_patches(patches: list[np.ndarray]) -> float:
    """给一批该书的原始字块图（不必很多，几百张即可），算书级统一归一尺度。"""
    sizes = [max(p.shape) for p in patches if p is not None]
    side = float(np.median(sizes)) if sizes else float(CANVAS)
    return (CANVAS - 8) / side


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


def _discriminate(cand_a, cand_b, raw_patch, ex_raws_fn, scale, top, second, base_why, confirm):
    """判别 cand_a／cand_b 哪个更像 raw_patch。`confirm=True`：cand_a 是 `iron()` 已经给出的
    字，只是要用追加形近表复核一次——查不了（实例不够）时**弃权**而不是照旧放行。"""
    fi = form_inseparable()
    if frozenset((cand_a, cand_b)) in fi:
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


def iron_with_disc(cands: list[tuple[str, float]], human_chars_set: set[str],
                    partners_map: dict[str, frozenset[str]], raw_patch: np.ndarray,
                    ex_raws_fn, scale: float
                    ) -> tuple[str | None, float, float, str, tuple[float, float] | None]:
    """铁证闸的完整判定：`iron()` + 判别器复核。见模块头。

    `ex_raws_fn(char) -> list[np.ndarray]`：给一个字，回它在人裁库里的原始字块图列表
    （调用方按需摘除本格自己、按跨书/跨册取图，见 `steps/seed_admit.py` 里的用法）。
    """
    ic, top, second, why = iron(cands, human_chars_set, partners_map)
    if ic is not None:
        partner = next(iter(extra_confusable_partners().get(ic, frozenset())), None)
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
