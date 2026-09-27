# -*- coding: utf-8 -*-
"""借库书人审卡的「AI 首选」：CNN 原型检索，或与像素首选 RRF 融合（2026-09-27）。

任务书：overview `控制台统一/任务书-C-借库书人审首选改CNN原型.md`；根因见 R 道
`inbox/R-全唐文借库失效/20260927-2206-done.md`。

**背景**：全唐文借四庫字形库，像素比对（5-a，`glyph_match`）在用户人裁难例上首选
只对 52.4%——全唐文笔画相对字身只有四庫约六成粗、刻工字样也不同，像素覆盖度的
排名跟着歪（以→取、令→今、平→乎……整批认反）。同一个借来的库，r5 embedding
按字取均值原型后做检索，首选 94.2%，且几乎严格优于像素（像素对而 CNN 错只 3–5
格/3000）。审卡上的默认字原先就是像素那一路，整理那边报的「AI 首选大面积错」
主要是它。

**只对借库书生效**：书 yaml 书级开关，缺省关——

    params:
      review:
        first_pick: rrf      # 或 cnn；不写 / off = 关，卡片与改前逐字节一样

`params:` 是 `{step_id: {…}}` 的书级覆盖（`core/book.py::BookSpec.params`）；
`review` 不是 Step id，引擎只按 `step.spec.id` 取，**不进任何 Step 的参数与指纹**，
开关只影响审卡装配，产物一个字节都不动。

**不碰放行**：只影响人审卡的默认字、排序、两路一致标记；`seed_admit` / `context_decide`
一行未改。「两路一致」精确率达不到 1% 门槛（R 实测维基集 97.6%、难例 90.7%），
**不许**拿它当放行通道（任务书「不做」）。

口径与 R 的 `scripts/experiments/qtw_libfail/a5_cnn.py` 相同：库里全部 exemplar
的 `derived.norm` → r5 embedding → 按字取均值再单位化；查询字块 → `normalize_patch`
缺省参数 → embedding，与全部原型取余弦。字集 = 库里的字（闭集）。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import numpy as np

MODES = ("cnn", "rrf")
#: RRF 常数（Cormack 2009 的 60）。与 `cnn_candidates` 5-b 的融合同一个惯例值。
RRF_K = 60
#: 卡片上留几个 CNN 候选（与 `db.candidates[:5]` 对齐）。
CNN_TOPK = 5


def first_pick_mode(book_spec) -> str | None:
    """书 yaml `params.review.first_pick` → `"cnn"` / `"rrf"` / `None`（关）。

    写错了（不是 cnn/rrf/off/空）直接报错，不静默当关——开关写错却以为开着，
    审卡照旧给像素首选，正是这件事要修的那个错。
    """
    cfg = ((getattr(book_spec, "params", None) or {}).get("review") or {})
    v = cfg.get("first_pick")
    if v in (None, "", False, "off"):
        return None
    if v not in MODES:
        raise ValueError(f"书 yaml params.review.first_pick 只认 {MODES} 或 off，得到 {v!r}")
    return v


def review_db_path(book_spec) -> str:
    """审卡用的字形库：书级 `params.glyph_match.db_path` 显式配了就用它，否则同
    `glyph_match` 的缺省解析（`GUJI_GLYPH_DB` → 工作区 `output/glyph.db`）。
    与像素那一路读**同一个**库，两路比的才是同一个字集。"""
    gm = ((getattr(book_spec, "params", None) or {}).get("glyph_match") or {})
    if gm.get("db_path"):
        return str(gm["db_path"])
    from ..core.workspace import glyph_db_path
    return str(glyph_db_path())


# ── 纯函数：融合、标注（不碰 IO / 模型，单测直接喂数）────────────────────


def rrf_fuse(pixel: list, cnn: list, k: int = RRF_K) -> list[tuple[str, float]]:
    """像素候选（`[(字, cov), …]`，已按 cov 降序）与 CNN 候选（`[(字, cos), …]`）
    按名次做 RRF：`Σ 1/(k+名次)`。同分时 **CNN 名次靠前的赢**——R 实测 CNN
    几乎严格优于像素，平局交给更可靠的一路。同一个字在一路里出现多次只算最好名次。
    """
    def ranks(lst):
        out: dict[str, int] = {}
        for i, (ch, _s) in enumerate(lst or []):
            out.setdefault(ch, i + 1)
        return out
    rp, rc = ranks(pixel), ranks(cnn)
    score = {ch: 0.0 for ch in (*rp, *rc)}
    for ch, r in rp.items():
        score[ch] += 1.0 / (k + r)
    for ch, r in rc.items():
        score[ch] += 1.0 / (k + r)
    big = 10 ** 6
    order = sorted(score, key=lambda ch: (-score[ch], rc.get(ch, big), rp.get(ch, big)))
    return [(ch, round(score[ch], 6)) for ch in order]


def pick_first(pixel: list, cnn: list, mode: str) -> str | None:
    """默认首选字。`cnn`：CNN 首位（CNN 没出就退像素首位）；`rrf`：融合首位。"""
    if mode == "cnn":
        if cnn:
            return cnn[0][0]
        return pixel[0][0] if pixel else None
    if mode == "rrf":
        fused = rrf_fuse(pixel, cnn)
        return fused[0][0] if fused else None
    raise ValueError(f"未知 first_pick 模式 {mode!r}")


def first_view(pixel: list, cnn: list, mode: str) -> dict:
    """卡片上的 `first` 字段：默认首选、两路各自首位、是否一致。

    `agree`：像素首位 == CNN 首位。任一路没出候选时是 `None`（无从谈一致），
    排序时与「不一致」一起排前面——没有第二路佐证的同样该先看。
    """
    p1 = pixel[0][0] if pixel else None
    c1 = cnn[0][0] if cnn else None
    return {
        "char": pick_first(pixel, cnn, mode),
        "mode": mode,
        "pixel": p1,
        "cnn": c1,
        "agree": (p1 == c1) if (p1 is not None and c1 is not None) else None,
        "cnn_candidates": [[ch, round(float(s), 4)] for ch, s in (cnn or [])[:CNN_TOPK]],
    }


def sort_disagree_first(cards: list[dict]) -> list[dict]:
    """不一致（含一路缺席）的排前面，其余保持原顺序（稳定排序）。没有 `first` 的卡不动位置档。"""
    def k(c):
        f = c.get("first")
        return 0 if (f is not None and f.get("agree") is not True) else 1
    return sorted(cards, key=k)


# ── 原型索引 ─────────────────────────────────────────────────────────


def _db_content_key(db_path: str) -> str:
    from ..steps.glyph_match import db_fingerprint
    return db_fingerprint(db_path)


def _load_exemplar_norms(db_path: str) -> dict[str, list[np.ndarray]]:
    from ..clustering.glyph_db import _unpng
    c = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        rows = c.execute(
            """SELECT g.char, d.data FROM exemplars e JOIN glyphs g ON g.glyph_id=e.glyph_id
               JOIN derived d ON d.instance_id=e.instance_id AND d.kind='norm'""").fetchall()
    finally:
        c.close()
    by: dict[str, list[np.ndarray]] = {}
    for ch, d in rows:
        by.setdefault(ch, []).append(_unpng(d).astype(np.uint8))
    return by


def build_protos(by_char: dict[str, list[np.ndarray]], embed, chunk: int = 256
                 ) -> tuple[list[str], np.ndarray]:
    """{字: [归一图…]} → (字表, 单位化均值原型矩阵 (n_char, d))。`embed` 注入，单测可换假的。"""
    chars = sorted(ch for ch, v in by_char.items() if v)
    protos = []
    for ch in chars:
        imgs = by_char[ch]
        acc = None
        for i in range(0, len(imgs), chunk):
            e = np.asarray(embed(imgs[i:i + chunk]), np.float64).sum(0)
            acc = e if acc is None else acc + e
        m = acc / len(imgs)
        protos.append((m / (np.linalg.norm(m) + 1e-9)).astype(np.float32))
    mat = np.stack(protos) if protos else np.zeros((0, 256), np.float32)
    return chars, mat


def rank_protos(emb: np.ndarray, chars: list[str], protos: np.ndarray, k: int = CNN_TOPK
                ) -> list[list[tuple[str, float]]]:
    """查询 embedding (N, d)（已单位化）× 原型 → 每条 top-k `[(字, 余弦)]`。"""
    if len(chars) == 0 or emb.shape[0] == 0:
        return [[] for _ in range(emb.shape[0])]
    S = emb @ protos.T
    kk = min(k, len(chars))
    out = []
    for row in S:
        idx = np.argpartition(-row, kk - 1)[:kk]
        idx = idx[np.argsort(-row[idx])]
        out.append([(chars[i], float(row[i])) for i in idx])
    return out


class ProtoIndex:
    """借来的库 → 按字均值原型。按 (库内容指纹, checkpoint 指纹) 落盘到
    `cache_root()/review_protos/`，内存里再留一份——17k 例首建 CPU 约一两分钟，
    之后秒开。库一变（H 道自举进了新刻例）指纹就变，自动重建。"""

    _mem: dict[str, tuple[list[str], np.ndarray]] = {}

    @classmethod
    def get(cls, db_path: str, cnn) -> tuple[list[str], np.ndarray]:
        from ..clustering import cnn_candidates as cc
        key = hashlib.sha1(
            f"{_db_content_key(db_path)}|{cc.fingerprint(cnn.ckpt)}".encode()).hexdigest()[:16]
        if key in cls._mem:
            return cls._mem[key]
        from ..core.workspace import cache_root
        f = Path(cache_root()) / "review_protos" / f"protos_{key}.npz"
        if f.exists():
            try:
                z = np.load(f, allow_pickle=False)
                got = (json.loads(str(z["chars"])), z["mat"])
                cls._mem[key] = got
                return got
            except Exception:       # noqa: BLE001 — 坏缓存当没有，重建
                pass
        chars, mat = build_protos(_load_exemplar_norms(db_path), cnn.embed)
        try:
            f.parent.mkdir(parents=True, exist_ok=True)
            tmp = f.with_suffix(".tmp.npz")
            np.savez(tmp, chars=json.dumps(chars, ensure_ascii=False), mat=mat)
            tmp.replace(f)
        except OSError:
            pass
        cls._mem[key] = (chars, mat)
        return chars, mat


# ── 装配：给卡片挂 `first` ───────────────────────────────────────────


def cnn_ranks_for_patches(norm_patches: list, db_path: str, cnn=None, k: int = CNN_TOPK
                          ) -> list[list[tuple[str, float]]]:
    """归一化 64² 图（可含 `None`＝缺图）→ 每条 CNN 原型 top-k。缺图的给 `[]`。
    评测脚本与卡片装配共用这一条，量的就是线上跑的那份代码。"""
    from ..clustering import cnn_candidates as cc
    cnn = cnn or cc.shared()
    out: list[list] = [[] for _ in norm_patches]
    if not cnn.available:
        return out
    chars, protos = ProtoIndex.get(db_path, cnn)
    idx = [i for i, p in enumerate(norm_patches) if p is not None]
    for s in range(0, len(idx), 256):
        part = idx[s:s + 256]
        emb = cnn.embed([norm_patches[i] for i in part])
        for i, r in zip(part, rank_protos(emb, chars, protos, k)):
            out[i] = r
    return out


def _card_patch(ctx, card: dict):
    from ..clustering.normalize import normalize_patch
    from ..core.spec import cell_key
    key = cell_key(card["page"], card["col"], card["slot"]) + (card.get("sub") or "")
    try:
        img = ctx.image("char_patch", key)
    except Exception:           # noqa: BLE001 — 缺图就这张卡没有 CNN 那一路
        return None
    return normalize_patch(img)


def annotate(book: str, cards: list[dict], store, mode: str, bk=None) -> dict:
    """给每张卡挂 `first`（见 `first_view`），原地改。返回摘要（一致率等，供面板/日志）。

    CNN 不可用（没装 torch / 缺 checkpoint）时 CNN 一路为空：`cnn` 模式退像素首位，
    `rrf` 模式等于像素排名——不报错、不挡审卡，`summary.cnn_ready=False` 讲明白。
    """
    from ..clustering import cnn_candidates as cc
    from ..core.book import load_book
    from ..core.step import RunContext
    from ..products.cache import ImageCache
    bk = bk or load_book(book)
    cnn = cc.shared()
    ranks: list[list] = [[] for _ in cards]
    if cnn.available and cards:
        ctx = RunContext(bk, store, ImageCache(), log=lambda *_: None)
        ranks = cnn_ranks_for_patches([_card_patch(ctx, c) for c in cards],
                                      review_db_path(bk), cnn)
    n_agree = n_both = 0
    for c, cr in zip(cards, ranks):
        pixel = [tuple(x) for x in ((c.get("db") or {}).get("candidates") or [])]
        c["first"] = first_view(pixel, cr, mode)
        if c["first"]["agree"] is not None:
            n_both += 1
            n_agree += bool(c["first"]["agree"])
    return {"mode": mode, "cnn_ready": bool(cnn.available), "n": len(cards),
            "n_both": n_both, "n_agree": n_agree}
