"""Step5-a 库匹配：字块 → 与 GlyphDB 已验证字形比对，三档判决 + 逐实例证据。

包的是 `clustering/match.GlyphMatcher`（HOG kNN + `verify_pair_elastic` +
形近家族护栏），**算法一行没改**——它有 glyph-match/triplets 与 pairs 两套
金标和一串负结果记录（提分辨率、密度自适应半径、骨架失配都实测否掉了），
重写是浪费。这一步只负责：喂图、带上库指纹、把证据落成 numeric 产物。

## 三档语义（沿用设计 §2）

| 档 | 条件 | 下游怎么用 |
|---|---|---|
| same | cov ≥ 0.996 且 wmax ≤ 12 | 直接继承库里的字，记 (库条目 id, cov, wmax) 为证据 |
| unsure | 0.85 ≤ cov < 0.996 | 命中的字进候选集（带 cov 当先验），与 OCR 合并交上下文裁决 |
| diff | 对全部 kNN 候选都 < 0.85 | 库里多半没有这个字，纯 OCR + 上下文 |

## ⚠️ 库是外部状态，指纹必须带上它

`GlyphMatcher` 查的是 `output/glyph.db`。库长大了、某个条目改判了，同一张
图块的判决就会变，而 Step 的代码、参数、上游产物一个都没动——指纹里不带它，
产物就永远显示 fresh、拿着过期判决往下走。所以 `db_fingerprint` 进了
`GlyphMatchParams`（参数参与指纹），换库或库变大之后这一步会自动标 stale。

指纹取 `(mtime_ns, size, exemplars 行数)`：前两个便宜，行数防「同尺寸不同内容」
（compact/vacuum 之后 size 可能巧合相同）。**不哈希整库**——77 MB 每次读一遍
太贵，而这三个量联合变化的概率低到可以忽略。
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from ..core.spec import StepSpec, cell_key, column_key
from ..core.step import RunContext, Step, register_step
from ..products.kinds.chars import PageChars
from ..products.kinds.recog import ColumnMatch, MatchRec, PageMatch

DEFAULT_DB = "output/glyph.db"


def db_fingerprint(path: str | Path = DEFAULT_DB) -> str:
    """库的轻量指纹：(mtime_ns, size, exemplars 行数) 的哈希。见模块头。"""
    p = Path(path)
    if not p.exists():
        return "nodb"
    st = p.stat()
    n = ""
    try:
        import sqlite3
        with sqlite3.connect(f"file:{p}?mode=ro", uri=True) as c:
            n = str(c.execute("SELECT count(*) FROM exemplars").fetchone()[0])
    except Exception:
        n = "?"
    raw = f"{st.st_mtime_ns}:{st.st_size}:{n}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


class GlyphMatchParams(BaseModel):
    db_path: str = DEFAULT_DB
    db_fingerprint: str = ""
    """库指纹。**留空会在构造时自动填**（见下面的校验器）——它必须是参数的一
    部分，`params_hash` 才会把它算进 Step 指纹，库一变产物就自动 stale。
    显式传值只在一种场合有用：想按某个历史库的判决重放。"""
    knn_k: int = 10
    edition: str | None = None    # 只用某一版本的字形当库
    max_candidates: int = 5       # unsure 档往产物里存几个候选

    def model_post_init(self, _ctx) -> None:
        if not self.db_fingerprint:
            # pydantic v2 的 model_post_init 里改字段要绕过校验（模型非 frozen，
            # 但直接赋值会再触发一轮 validate）——用 object.__setattr__ 最干净。
            object.__setattr__(self, "db_fingerprint", db_fingerprint(self.db_path))


@register_step
class GlyphMatchStep(Step):
    spec = StepSpec(
        id="glyph_match", title="Step5 库匹配", version="1.0", unit="cell",
        consumes=("char_index", "char_patch"), produces=("glyph_match",),
        params=GlyphMatchParams,
        code_deps=("open_guji_cv.clustering.match", "open_guji_cv.clustering.verify",
                   "open_guji_cv.clustering.normalize", "open_guji_cv.clustering.features"),
    )

    def _matcher(self, p: GlyphMatchParams):
        """库 → 内存匹配器。按 (db_path, 指纹, k, edition) 缓存在实例上——
        一次 run 里几十页共用同一个库，每页重建要几秒。"""
        key = (p.db_path, db_fingerprint(p.db_path), p.knn_k, p.edition)
        cached = getattr(self, "_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        from ..clustering.glyph_db import GlyphDB
        from ..clustering.seeding import load_matcher_from_db
        db = GlyphDB(p.db_path)
        matcher, _chars = load_matcher_from_db(db, edition=p.edition, knn_k=p.knn_k)
        self._cache = (key, matcher)      # type: ignore[attr-defined]
        return matcher

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        from ..clustering.normalize import normalize_patch
        p: GlyphMatchParams = ctx.params_for(self)  # type: ignore[assignment]
        matcher = self._matcher(p)
        chars: PageChars = ctx.product("char_index", page)
        out: list[ColumnMatch] = []
        for cc in chars.columns:
            if not cc.ok:
                out.append(ColumnMatch(col=cc.col, ok=False, error=cc.error))
                continue
            recs: list[MatchRec] = []
            for r in cc.chars:
                if r.cell_type != "char" or not r.patch_key:
                    continue
                try:
                    img = ctx.image("char_patch", r.patch_key)
                except Exception as e:              # 图块再生不出来就跳过，不炸整页
                    recs.append(MatchRec(id=r.id, slot=r.slot, sub=r.sub,
                                         verdict="diff", guard=f"no_patch:{e}"))
                    continue
                m = matcher.match(normalize_patch(img))
                recs.append(MatchRec(
                    id=r.id, slot=r.slot, sub=r.sub,
                    verdict=m.verdict, char=m.char, matched_id=m.matched_id,
                    cov=round(float(m.cov), 4), wmax=round(float(m.wmax), 2),
                    candidates=[(c, round(float(v), 4))
                                for c, v in m.candidates[:p.max_candidates]],
                    guard=m.guard, n_verified=int(m.n_verified)))
            out.append(ColumnMatch(col=cc.col, ok=True, chars=recs))
        return {"glyph_match": PageMatch(
            page=page, db_fingerprint=db_fingerprint(p.db_path), columns=out)}
