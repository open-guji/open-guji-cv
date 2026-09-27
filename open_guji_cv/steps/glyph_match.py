"""Step5-a 库匹配：字块 → 与 GlyphDB 已验证字形比对，三档判决 + 逐实例证据。

包的是 `clustering/match.GlyphMatcher`（HOG kNN + `verify_pair_elastic` +
形近家族护栏），**算法一行没改**——它有 glyph-match/triplets 与 pairs 两套
金标和一串负结果记录（提分辨率、密度自适应半径、骨架失配都实测否掉了），
重写是浪费。这一步只负责：喂图、带上库指纹、把证据落成 numeric 产物。

## 三档语义（沿用设计 §2）

| 档 | 条件 | 下游怎么用 |
|---|---|---|
| same | cov ≥ 0.996 且 wmax ≤ 12 | 直接继承库里的字，记 (库条目 id, cov, wmax) 为证据 |
| same（共识升档） | unsure 档里 top 字 cov ≥ 0.99、比次优**异字**高 ≥ 0.03、且该字已有 ≥ 3 例人裁 | 同上，`via="consensus:<n>"`，无 matched_id |
| unsure | 0.85 ≤ cov < 0.996 | 命中的字进候选集（带 cov 当先验），与 OCR 合并交上下文裁决 |
| diff | 对全部 kNN 候选都 < 0.85 | 库里多半没有这个字，纯 OCR + 上下文 |

## 共识升档（2026-09-19，bxgb 人裁 648 格标定）

单对 cov ≥ 0.996 是给「同一版同一字的两次印」标的，刻本同字异印的 cov 常落在 0.99~0.996：
「𠊓」人裁 18 次进库，top 候选仍是 0.9903 的 unsure，于是每一处都再出卡——用户反映
「很多字反复审了很多遍」。按人裁 confirm 当真值量 top 候选的精确率：

| cov 区间 | n | top 正确 |
|---|---|---|
| ≥ 0.996 | 353 | 96.6% |
| [0.99, 0.996) | 49 | 89.8% |
| [0.985, 0.99) | 23 | 82.6% |
| [0.98, 0.985) | 24 | 54.2% |

单靠降 cov 门槛到 0.99 精确率 95.8%，比现役 same 档（96.7%）还低，不行。再加两条：
与次优**异字**的差距 ≥ 0.03（骑在两字之间的不升）、该字已有 ≥ 3 例人裁（库里只有一两例
时 kNN 邻域太薄）——真值内 79 格 **100%**，全书新增 155 个 same（现役 7910）；把 cov 放到
0.985 是 85 格 100%、新增 206，先取保守的 0.99。护栏照旧：匹配器判了 never_match /
conflict 的不升档。`n_confirmed` 只数人裁（`glyphs.n_confirmed`，排除 `font:*` 版），
产物里 `via` 记来源，出了错能按通道归因。

## ⚠️ 库是外部状态，指纹必须带上它

`GlyphMatcher` 查的是 `output/glyph.db`。库长大了、某个条目改判了，同一张
图块的判决就会变，而 Step 的代码、参数、上游产物一个都没动——指纹里不带它，
产物就永远显示 fresh、拿着过期判决往下走。所以 `db_fingerprint` 进了
`GlyphMatchParams`（参数参与指纹），换库或库变大之后这一步会自动标 stale。

指纹取**库内容**（2026-09-20 起；此前是 `(mtime_ns, size, exemplars 行数)`）：
exemplars / glyphs / admissions / derived 四表各自的 `(条数, 最大 rowid, 最新时间戳)`
拼起来哈希，四条聚合查询合计 <10 ms，**不哈希整库**。换掉 mtime 的原因：mtime 会被
与判决无关的写动到——备份复制、VACUUM、边跑边审时消费者落一条人裁，都让全书
Step5+ 过期；而内容指纹只在**匹配器会读到的东西**变了才变。`instances` 表不进指纹
（扫它的 patch_png 要 140 ms 且会随库线性涨），所以**改 instances/derived 内容的
写路径必须触碰 `exemplars.added_at`**（`GlyphDB.refresh_instance_patch` 就是这么做的，
`_exemplar_matrix` 的常驻缓存也靠这一戳）——只改派生表不碰戳，指纹与缓存都看不见。
`seed_admit` 的人裁通道只读 `provenance='human'` 的 admissions，用更窄的
`human_verdicts_fingerprint`，机器 align 进库不惊动它。

## 库指纹：记录，不判过期（2026-09-25 起，用户定）

上面那套「库一变就全书过期」执行了一周，代价压过了收益：人裁每进一批，指纹就变，
Step5-a 全书过期、格级复用的第一道闸（`self_hash`）也一并失效——一页半分钟、
vol02 一轮一个半小时，而新进的几个字形绝大多数格的判决一动不动。现在
`db_fingerprint` 是 `StepSpec.soft_params`：

- 仍然**记**：参数里有、产物 `PageMatch.db_fingerprint` 里有、manifest 条目 `soft` 里有；
- **不判过期**：不进 `params_hash` / `self_hash`，库变了 `status` 只在「漂移」一列报页数；
  上游（几何）变了照旧重跑，几何没动的格照旧复用——复用的记录是对旧库判的，这是接受的代价；
- **要吃新库**就点名：`guji recheck <book> --chars 𠊓,虜`（记录里出现这些字的格）、
  `--verdicts unsure,diff`（非 same 的格统统再查一遍，≈半价）、`--dead`（命中的库条目
  已撤或已改字头——这类格的 same 已经没有依据，建议每次撤库后跑）、`--all`（整页）。
  它只写 manifest 的格级失效，下一次 `guji pipeline --from glyph_match` 只重算这些格。
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
from ..products.kinds.recog import CandidateMatch, ColumnMatch, MatchRec, PageMatch

def _default_db() -> str:
    """默认库路径。空串表示「按 workspace 解析」——不在导入时定死，
    因为 `GUJI_WORKSPACE` 可能在导入之后才设（测试、控制台切册都会）。"""
    from ..core.workspace import glyph_db_path
    return str(glyph_db_path())


# 兼容旧引用；新代码用 _default_db() 或 core.workspace.glyph_db_path()
DEFAULT_DB = "output/glyph.db"


def _stat_stamp(p: Path) -> str:
    st = p.stat()
    return f"stat:{st.st_mtime_ns}:{st.st_size}"


def _db_stamp(path: str | Path | None, sql: str) -> str:
    """跑一条聚合 SQL 取库内容戳；库不存在 → "nodb"，读不了（锁/损坏）→ 退回 stat 戳。"""
    p = Path(path or _default_db())
    if not p.exists():
        return "nodb"
    try:
        import sqlite3
        with sqlite3.connect(f"file:{p}?mode=ro", uri=True) as c:
            row = c.execute(sql).fetchone()
        raw = "|".join("" if v is None else str(v) for v in row)
    except Exception:
        raw = _stat_stamp(p)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


_CONTENT_SQL = """SELECT
  (SELECT count(*) || '/' || max(rowid) || '/' || max(added_at)    FROM exemplars),
  (SELECT count(*) || '/' || max(rowid) || '/' || max(updated_at)  FROM glyphs),
  (SELECT count(*) || '/' || max(rowid) || '/' || max(admitted_at) FROM admissions),
  (SELECT count(*) || '/' || max(algo_version)                     FROM derived)"""

_HUMAN_SQL = """SELECT count(*), max(rowid), max(admitted_at)
  FROM admissions WHERE provenance = 'human'"""


def db_fingerprint(path: str | Path | None = None) -> str:
    """库的内容指纹（见模块头「库是外部状态」）。

    只看匹配器会读到的四张表的 (条数, 最大 rowid, 最新时间戳)：加条目、撤条目、
    撤后同秒重进（rowid 单调递增，count/时间戳都不变时它变）、改字头、重算派生
    （`refresh_instance_patch` 会碰 `exemplars.added_at`）都会变；复制文件、VACUUM、
    只读打开、mtime 被 touch 都不变。
    """
    return _db_stamp(path, _CONTENT_SQL)


def human_verdicts_fingerprint(path: str | Path | None = None) -> str:
    """只看 `provenance='human'` 的准入台账——`seed_admit` 人裁通道的输入。

    机器 align 进库、字头改判都不动它；人裁进库、撤裁（删行或改成
    `human_stale_*`）、撤后重进才动。与 `db_fingerprint` 同一套实现。
    """
    return _db_stamp(path, _HUMAN_SQL)


class GlyphMatchParams(BaseModel):
    db_path: str = ""
    """字形库路径。**留空 = 运行时按 workspace 解析**（`GUJI_GLYPH_DB` →
    `GUJI_WORKSPACE/output/glyph.db` → 仓内样本库），不在导入时定死——
    引擎与书的数据已分仓，路径得能指到别处。显式传值则原样用。"""
    db_fingerprint: str = ""
    """库指纹。**留空会在构造时自动填**（见下面的校验器）——它必须是参数的一
    部分，`params_hash` 才会把它算进 Step 指纹，库一变产物就自动 stale。
    显式传值只在一种场合有用：想按某个历史库的判决重放。"""
    knn_k: int = 10
    edition: str | None = None    # 只用某一版本的字形当库；None 且 Book.edition=modern 时 = modern:<book>
    max_candidates: int = 5       # unsure 档往产物里存几个候选
    norm_stroke: int | None = None
    """两边都骨架化再统一细化到 N px 再比（2026-09-15，现代印刷链）。1-bit 扫描的粗笔画
    （北行日錄归一后 5.5px）让软覆盖饱和：同书留一法错误命中 cov 最高 0.9996、same 闸漏
    2 个假 same；细到 3px 后错误命中最高 0.922、591 对 0 错。刻本链保持 None。"""
    exclude_self: bool = True
    """匹配时把字位自己摘出库（`GlyphMatcher.match(exclude_id=)`，按同一物理格摘，含 v2:/播种/v1
    各种 id 与重切漂移的邻格号）。不摘就是自证 cov 1.0。2026-09-26 起刻本链也默认摘
    （用户：「该改就改」）——此前刻本链一个格进库后，5-a 就是自己配自己，新 Step7 的
    「库里同形已定实例」铁证全被自证喂饱。"""
    consensus_cov: float = 0.99          # 共识升档三条件，见模块头；min_confirmed = 0 关掉
    consensus_margin: float = 0.03
    consensus_min_confirmed: int = 3

    def model_post_init(self, _ctx) -> None:
        # pydantic v2 的 model_post_init 里改字段要绕过校验（模型非 frozen，
        # 但直接赋值会再触发一轮 validate）——用 object.__setattr__ 最干净。
        if not self.db_path:
            object.__setattr__(self, "db_path", _default_db())
        if not self.db_fingerprint:
            object.__setattr__(self, "db_fingerprint", db_fingerprint(self.db_path))


def consensus_same(candidates, n_confirmed_of, cov_min: float, margin_min: float,
                   min_confirmed: int) -> tuple[str, int] | None:
    """unsure 档能不能按「共识」升成 same：返回 (字, 该字人裁例数) 或 None。

    三条件缺一不可（标定见模块头）：top 候选 cov ≥ cov_min；比次优**异字**高 ≥ margin_min
    （次优同字不算——同一字的多个刻例挨着很正常）；top 字已有 ≥ min_confirmed 例人裁。
    没有异字候选时，差距按 0.85（unsure 档下界）算。
    """
    if min_confirmed <= 0 or not candidates:
        return None
    top, cov = candidates[0]
    if cov < cov_min:
        return None
    nxt = next((v for c, v in candidates[1:] if c != top), None)
    if cov - (nxt if nxt is not None else 0.85) < margin_min:
        return None
    n = int(n_confirmed_of(top) or 0)
    if n < min_confirmed:
        return None
    return top, n


def human_confirmed_counts(db_path: str) -> dict[str, int]:
    """每个字的**人裁**例数：`admissions.provenance = 'human'` 的条目按 `instances.label` 计数。

    不能用 `glyphs.n_confirmed`：那一列机器准入也累加——bxgb 库里 v1 的 3748 条全是
    `align` 通道（整理本对齐）进的、字体模板版每字都是 1。按它数，bxgb 现役产物上会升档
    2349 格（真值只覆盖 29 格）；只数人裁是 126 格、真值 20/20。共识的前提是「人看过
    这个字的刻例」，机器自证不算。"""
    import sqlite3
    out: dict[str, int] = {}
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as c:
            for ch, n in c.execute(
                    "SELECT i.label, COUNT(*) FROM admissions a "
                    "JOIN instances i ON i.instance_id = a.instance_id "
                    "WHERE a.provenance = 'human' AND i.label IS NOT NULL GROUP BY i.label"):
                out[str(ch)] = int(n or 0)
    except Exception:
        return {}
    return out


@register_step
class GlyphMatchStep(Step):
    spec = StepSpec(
        id="glyph_match", title="Step5-a 库匹配", version="1.1", unit="cell",
        consumes=("char_index", "char_patch"), produces=("glyph_match",),
        params=GlyphMatchParams,
        code_deps=("open_guji_cv.clustering.match", "open_guji_cv.clustering.verify",
                   "open_guji_cv.clustering.normalize", "open_guji_cv.clustering.features"),
        # `norm_stroke` 来自册配置且直接改归一结果——不进指纹的话改了 yaml
        # 产物还报「新鲜」（与 leaf_layout 当初同一个坑）
        book_deps=("norm_stroke",),
        # 库指纹是**软参数**（2026-09-25，用户定）：库变了只报「漂移」不报过期，
        # 要重算点名格走 `guji recheck`。见模块头「库指纹：记录，不判过期」。
        soft_params=("db_fingerprint",),
    )

    def _matcher(self, p: GlyphMatchParams):
        """库 → 内存匹配器。走 `seeding.cached_matcher_from_db` 的进程级
        缓存（控制台 `/api/glyph-match/*` 单点查询路由也走这份），一次
        run 里几十页共用同一个库，每页重建要几秒。"""
        from ..clustering.glyph_db import assert_db_not_silently_empty
        from ..clustering.seeding import cached_matcher_from_db
        # 库路径 P0 自检：库路径解析错了、读到空库/别的文件时直接报错，
        # 不许静默出全 diff（见 glyph_db.assert_db_not_silently_empty 模块头）。
        assert_db_not_silently_empty(p.db_path)
        # 按参数里声明的那份库指纹取匹配器（而不是每页现算）：产物指纹、匹配器缓存键、
        # 产物里记的 db_fingerprint 三处必须是同一个值，否则边跑边审时三者会各说各话
        matcher, _chars = cached_matcher_from_db(
            p.db_path, p.db_fingerprint, edition=p.edition, knn_k=p.knn_k,
            norm_stroke=p.norm_stroke)
        return matcher

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        from ..clustering.normalize import normalize_patch as _normalize_patch
        p: GlyphMatchParams = ctx.params_for(self)  # type: ignore[assignment]
        # 笔宽归一是**册级**属性（取决于这本书的笔宽 vs 字体模板笔宽），
        # 参数没显式给就用册配置的 `BookSpec.norm_stroke`。必须与播种
        # （`seed-witness --norm-stroke`）同值，否则库被一把尺子筛、又被另一把
        # 尺子查，等于白播。
        if p.norm_stroke is None and getattr(ctx.book, "norm_stroke", None):
            p = p.model_copy(update={"norm_stroke": int(ctx.book.norm_stroke)})
        if p.edition is None and getattr(ctx.book, "edition", "keben") == "modern":
            # 现代链：库域默认 = 这本书自己长的库（三模式方案 §五.2）
            p = p.model_copy(update={"edition": f"modern:{ctx.book.id}"})
        matcher = self._matcher(p)
        # 共识升档要的人裁例数：一次 run 里几十页共用，按库指纹缓存在 step 实例上
        key = (p.db_path, p.db_fingerprint)
        if getattr(self, "_confirmed_key", None) != key:
            self._confirmed = human_confirmed_counts(p.db_path) if p.consensus_min_confirmed > 0 else {}
            self._confirmed_key = key
        confirmed = self._confirmed

        def normalize_patch(img, punct: bool = False):
            # 标点走等比归一（见 seed_witness 与 normalize.normalize_patch 的 isotropic 说明）：
            # 播种与匹配必须用同一把尺子，否则库被一把尺子筛、又被另一把尺子查。
            return _normalize_patch(img, stroke_width=p.norm_stroke, isotropic=punct)
        chars: PageChars = ctx.product("char_index", page)
        # 格级复用（core/reuse.py）：本步没变、只是上游重写了时，几何没动的格搬旧记录。
        from ..core.reuse import cell_reuse, log_reuse
        reuse = cell_reuse(ctx, self, page, "glyph_match")
        n_reused = n_total = 0
        out: list[ColumnMatch] = []
        for cc in chars.columns:
            if not cc.ok:
                out.append(ColumnMatch(col=cc.col, ok=False, error=cc.error))
                continue
            recs: list[MatchRec] = []
            for r in cc.chars:
                if r.cell_type != "char" or not r.patch_key:
                    continue
                n_total += 1
                if r.id in reuse:
                    recs.append(reuse[r.id])
                    n_reused += 1
                    continue
                try:
                    img = ctx.image("char_patch", r.patch_key)
                except Exception as e:              # 图块再生不出来就跳过，不炸整页
                    recs.append(MatchRec(id=r.id, slot=r.slot, sub=r.sub,
                                         verdict="diff", guard=f"no_patch:{e}"))
                    continue
                is_punct = (getattr(r, "step3_kind", None) == "punct")
                m = matcher.match(normalize_patch(img, is_punct),
                                  exclude_id=(r.id if p.exclude_self else None))
                cand_variants: list[CandidateMatch] = []
                for cv in (r.cand_variants or []):
                    try:
                        cimg = ctx.image("char_patch", cv.patch_key)
                    except Exception:
                        continue    # 候选试切图块再生不出来就跳过，不炸整页
                    cm = matcher.match(normalize_patch(cimg, is_punct),
                                       exclude_id=(r.id if p.exclude_self else None))
                    cand_variants.append(CandidateMatch(
                        side=cv.side, cand_idx=cv.cand_idx, verdict=cm.verdict, char=cm.char,
                        cov=round(float(cm.cov), 4), wmax=round(float(cm.wmax), 2),
                        candidates=[(cc, round(float(vv), 4))
                                    for cc, vv in cm.candidates[:p.max_candidates]]))
                verdict, char, via = m.verdict, m.char, None
                if verdict == "unsure" and m.guard is None:
                    # 共识升档（见模块头）。匹配器判了护栏（never_match / conflict）的不动。
                    hit = consensus_same(list(m.candidates), confirmed.get,
                                         p.consensus_cov, p.consensus_margin,
                                         p.consensus_min_confirmed)
                    if hit:
                        verdict, char, via = "same", hit[0], f"consensus:{hit[1]}"
                recs.append(MatchRec(
                    id=r.id, slot=r.slot, sub=r.sub,
                    verdict=verdict, char=char, matched_id=m.matched_id,
                    cov=round(float(m.cov), 4), wmax=round(float(m.wmax), 2),
                    candidates=[(c, round(float(v), 4))
                                for c, v in m.candidates[:p.max_candidates]],
                    guard=m.guard, n_verified=int(m.n_verified), via=via,
                    cand_variants=cand_variants))
            out.append(ColumnMatch(col=cc.col, ok=True, chars=recs))
        log_reuse(ctx, self, page, n_reused, n_total)
        return {"glyph_match": PageMatch(
            page=page, db_fingerprint=p.db_fingerprint, columns=out)}


def glyph_match_summary(book_id: str, pages: list[int] | None = None,
                        store=None) -> dict:
    """Step5-a 板块②聚合数字：匹配档位分布（same/unsure/diff 计数）+
    护栏触发计数。`glyph_match` 产物落盘的是逐字位 `MatchRec`，没有跨页
    聚合统计——07号任务卡已指出这个缺口，风格照抄 `align_ref_summary`。
    """
    from ..core.book import load_book
    from ..core.spec import page_key
    from ..products.store import ProductStore

    store = store or ProductStore()
    book = load_book(book_id)
    pages = pages if pages is not None else book.all_pages()
    n_pages = 0
    n_missing = 0
    verdict_counts = {"same": 0, "unsure": 0, "diff": 0}
    guard_counts: dict[str, int] = {}
    for pg in pages:
        pm: PageMatch | None = store.read(book_id, "glyph_match", page_key(pg), "glyph_match")
        if pm is None:
            n_missing += 1
            continue
        n_pages += 1
        for col in pm.columns:
            if not col.ok:
                continue
            for r in col.chars:
                verdict_counts[r.verdict] = verdict_counts.get(r.verdict, 0) + 1
                if r.guard:
                    guard_counts[r.guard] = guard_counts.get(r.guard, 0) + 1
    return {
        "n_pages": n_pages, "n_missing": n_missing,
        "verdict_counts": verdict_counts, "guard_counts": guard_counts,
    }


# ── 点名重算（`guji recheck`，见模块头「库指纹：记录，不判过期」）──────────────

def live_exemplars(db_path: str, edition: str | None = None) -> dict[str, set[str]]:
    """库里现役条目：{instance_id: {字头…}}，口径与 `seeding.load_matcher_from_db` 相同
    （exemplars ⋈ glyphs，按 edition 过滤）。`--dead` 拿它判「命中的条目还在不在、字头改没改」。"""
    import sqlite3
    sql = ("SELECT e.instance_id, g.char FROM exemplars e "
           "JOIN glyphs g ON g.glyph_id = e.glyph_id")
    args: tuple = ()
    if edition:
        sql += " WHERE g.edition_tag = ?"
        args = (edition,)
    out: dict[str, set[str]] = {}
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as c:
        for iid, ch in c.execute(sql, args):
            out.setdefault(str(iid), set()).add(str(ch))
    return out


def _rec_chars(r: MatchRec) -> set[str]:
    """一条记录里出现过的所有字：判定字、候选、候选试切的判定字与候选。"""
    out = {c for c, _ in r.candidates}
    if r.char:
        out.add(r.char)
    for cv in r.cand_variants:
        if cv.char:
            out.add(cv.char)
        out.update(c for c, _ in cv.candidates)
    return out


def recheck_reasons(r: MatchRec, chars: set[str] | frozenset = frozenset(),
                    verdicts: set[str] | frozenset = frozenset(),
                    live: dict[str, set[str]] | None = None) -> list[str]:
    """这一格为什么该重算（空表 = 不用）。三条相互独立，任一命中即点名：

    - `char`：记录里出现了点名的字（判定字 / 候选 / 候选试切）——那个字的库条目
      变了（新进、撤掉、改判），这些格的判决最可能跟着变；
    - `verdict`：判档在点名之列（如 unsure/diff：库长大后最可能升档的就是它们）；
    - `dead`：same 档命中的库条目已不在库里，或字头已不是记录里的字——
      判决的依据没了，必须重算（`live` 为 None 不查这一条）。
    """
    why: list[str] = []
    if chars and _rec_chars(r) & set(chars):
        why.append("char")
    if verdicts and r.verdict in verdicts:
        why.append("verdict")
    if live is not None and r.matched_id and r.char not in live.get(r.matched_id, ()):
        why.append("dead")
    return why
