"""C1 进库准入：库判决 + OCR + 上下文定字 → 自动进库 / 落回人审。

包的是 `clustering/seeding.admission_decision`（十条通道，2600+ 条真实裁决
逐轮定型），**算法一行没改**。这一步只负责：把 v2 三步的产物摊成它要的入参、
把裁决落成 numeric 产物，供审查页与 `glyphdb_admit` 消费。

## 通道与证据强度（抄自 glyph_db_first_design §7.2/§7.3）

| 信号 | 难例准确率 | 说明 |
|---|---|---|
| 库 verify same | **100%**（27/27） | 形状证据，cov 0.99 是实测拐点 |
| 整理本·过闸对齐 | 95.8% | 文本证据 |
| OCR | **45.0%** | **置信度也不可信**（「人/入」给了 0.95 仍错） |

**四条原则**（背下来）：整理本在场时它有一票否决权；OCR 只供候选、置信度
不参与任何自动判断；库匹配按 cov 分档采信，0.99 是拐点；凑双信号要挑**误差
独立**的两路——文本 × 形状可以，OCR × 形状不行（那 4 条错例正是两者同错）。

## 这一步现在能走哪几条通道

`admission_decision` 最强的几条（常规 / match_ref / match_replace）都要
**整理本对齐字**，那来自 `align_label` 的页面锚定，还没进 v2 产物（B2 之后
才有）。所以现在只走**纯字形**那两条：

- `match_solo`：无整理本参照 + 库内 cov ≥ 0.99；
- `match_solo_ocr`：cov 0.95~0.99 + OCR 字符背书（语义同字）。

dev_set 3624 字位实测：match_solo 55.8% + match_solo_ocr 17.2% = **自动 73%**，
人审 27%。接上整理本之后自动率会更高（v1 上实测 61% → 77%）。

## 进库不在这一步做

这一步只产出**裁决**。真正写库要走 Event → 路由 → `glyphdb_admit` 消费者，
理由是设计 §3 纪律 1：逐实例证据、可重放。自动通道的裁决由
`review/batches` 转成 `confirm` 事件，人审的进审查页。
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel

from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.recog import (AdmitRec, ColumnAdmit, PageAdmit,
                                    PageAlignRef, PageDecision, PageMatch,
                                    PageOcr)


class SeedAdmitParams(BaseModel):
    variants: str = ""                  # 异体表；空 = VariantMap 默认
    solo_cov: float = 0.99              # match_solo 的 cov 闸，实测拐点
    use_context: bool = True            # 把 Step6 的定字当第三路证据
    context_margin: float = 0.70        # 用它时的 margin 门槛（生产值）
    always_review: str = "己已巳"       # 这些字永远人审（用户 2026-09-04 定）
    edition: str = "wuyingdian_zongmu"  # 本书用字账（variant_ledger）的键
    # 整理本通道原来在这里配 corpus/corpus_fingerprint，2026-09-09 挪去了
    # `align_ref`（Step5-d，正式 Step，产物带自己的语料指纹）——本步只消费
    # 它的产物，通道开不开看 `align_ref` 锚没锚上，不用再在这里配一份。
    use_exclusions: bool = True         # 查 config/crop_exclusions.jsonl（切坏的图块不进库不出卡）
    exclusions: str = ""                # 名单路径；空 = exclusions.py 默认
    exclusion_origins: str = "human,gate,pipeline"
    """采信名单里的哪几档来源（逗号分隔）。

    **按证据强度分级，别一刀切**（`exclusions.py` 模块头的纪律）：`human` 是人眼实锤；
    `gate` / `pipeline` 是管线确定层旗标；`pipeline-suspect` 那 216 条**实测只有约 27%
    是真有问题**——全采信会误伤约 150 个好格子（58 页上实测命中 68 条）。所以默认不含它，
    要复核时显式打开，或等重扫后逐条判。
    """
    use_note_lexicon: bool = True       # 版本注闭集通道（段级，只作用于夹注格）
    note_lexicon: str = ""              # 词表路径；空 = note_lexicon.py 默认
    note_min_sim: float = 0.70          # 段相似度下限（见 note_lexicon.MIN_SIM）
    note_fingerprint: str = ""          # 自动填：词表变了产物过期
    use_human_verdicts: bool = True     # 人裁过的位直接采信人裁字形（最高优先级）
    db_path: str = ""    # 读人裁记录用；与 glyph_match 同一个库。留空 = 按 workspace 解析
    human_fingerprint: str = ""         # 自动填：人裁进库了本步要重跑
    relax_split_ref: bool = True
    """己/已/巳：整理本给了字就放行——文意取整理本，字形取库 top1（用户 2026-09-06：
    「没必要每次都单独让我选文意，根据上下文或整理本直接选；字形选哪个都行」）。
    实测 41 条人裁：文意对 39、字形对 40。关掉 = 回到「永远人审」。"""
    relax_ref_agree: bool = True
    """整理本字 ≡ 库 top1（语义同字）或 == 上下文定字 时直接放行（用户 2026-09-06：
    「很多都是在整理本存在时非常明显的选择，能不能放松要求」）。形取库 top1（刻本形），
    文意取整理本。两册人审位实测 整理本≡库top1 10/10、==上下文 4/4，全部 1,1xx 条
    人裁真值上反例 0。同时让「义定形未定」的位在库 top1 属组内形时直接取它当形
    （evidence.form.state=guess，判据 E 会把它算进抽审分母）。"""
    ledger_fingerprint: str = ""        # 自动填：账本变了产物过期
    variants_fingerprint: str = ""      # 自动填：语义表（auto + 手工）变了产物过期
    exclusions_fingerprint: str = ""    # 自动填：名单变了产物过期

    def model_post_init(self, _ctx) -> None:
        if not self.db_path:
            from ..core.workspace import glyph_db_path
            object.__setattr__(self, "db_path", str(glyph_db_path()))
        from ..steps.context_decide import corpus_fingerprint
        # 用字账与语义表同理（2026-09-05）：两张表都是派生物，重建就该让准入重跑
        if not self.ledger_fingerprint:
            from ..variant_ledger import ledger_path
            object.__setattr__(self, "ledger_fingerprint",
                               corpus_fingerprint([str(ledger_path(self.edition))]))
        if not self.variants_fingerprint:
            from ..clustering.variants import DEFAULT_AUTO_PATH, DEFAULT_VARIANTS_PATH
            paths = [self.variants] if self.variants else [str(DEFAULT_AUTO_PATH), str(DEFAULT_VARIANTS_PATH)]
            object.__setattr__(self, "variants_fingerprint", corpus_fingerprint(paths))
        if self.use_exclusions and not self.exclusions_fingerprint:
            from ..clustering.exclusions import DEFAULT_PATH
            object.__setattr__(self, "exclusions_fingerprint",
                               corpus_fingerprint([self.exclusions or str(DEFAULT_PATH)]))
        # 人裁表直接读 glyph.db，这一步自己带库指纹——上游 glyph_match 的指纹只保证
        # 它自己重跑，不会让本步过期（人裁进库时 match 产物可能没变）。
        if self.use_human_verdicts and not self.human_fingerprint:
            from .glyph_match import db_fingerprint
            object.__setattr__(self, "human_fingerprint", db_fingerprint(self.db_path))
        # 版本注词表也是派生物（scripts/build_note_lexicon.py），同理
        if self.use_note_lexicon and not self.note_fingerprint:
            from ..clustering.note_lexicon import DEFAULT_LEXICON
            object.__setattr__(self, "note_fingerprint",
                               corpus_fingerprint([self.note_lexicon or str(DEFAULT_LEXICON)]))


@register_step
class SeedAdmitStep(Step):
    spec = StepSpec(
        id="seed_admit", title="C1 进库准入", version="1.5", unit="cell",
        consumes=("glyph_match", "ocr_candidates", "context_decision", "align_ref"),
        produces=("seed_admit",),
        params=SeedAdmitParams,
        needs=("db",),
        code_deps=("open_guji_cv.clustering.seeding",
                   "open_guji_cv.clustering.variants",
                   "open_guji_cv.clustering.variant_form",
                   "open_guji_cv.variant_ledger",
                   "open_guji_cv.clustering.note_lexicon",
                   "open_guji_cv.utils.jiazhu_order"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        from ..clustering.exclusions import excluded_ids
        from ..clustering.note_lexicon import load_lexicon, match_segment
        from ..clustering.seeding import (MATCH_SOLO_OCR_COV, NEAR_FORM_CHARS,
                                          admission_decision)
        from ..clustering.variant_form import decide_form, group_forms
        from ..clustering.variants import VariantMap
        from ..utils.jiazhu_order import segments as jz_segments
        from ..utils.jiazhu_order import sort_by_reading
        from ..variant_ledger import BookLedger
        p: SeedAdmitParams = ctx.params_for(self)  # type: ignore[assignment]
        vmap = VariantMap.load(p.variants or None)
        ledger = BookLedger.load_or_empty(p.edition)
        # 排除名单：人裁标过「切坏 / 带残留 / 非字」的图块**不进库也不出审查卡**
        # （用户 2026-08-25 定的口径，exclusions.py 模块头）。v1 的 seeding 一直
        # 查它，v2 此前漏了——于是标了缺陷的格子下一轮照样出现在待审队列里。
        from ..clustering.exclusions import DEFAULT_PATH as _EX_PATH
        _ex_path = p.exclusions or str(_EX_PATH)
        _origins = tuple(s.strip() for s in (p.exclusion_origins or "").split(",") if s.strip())
        excluded = (excluded_ids(_ex_path, _origins or None)
                    if p.use_exclusions else frozenset())
        # 人裁过的位：**人裁是最强证据，任何自动通道都不许改写它**（2026-09-06）。
        # 实测 vol02:18:9:5——图上刻的是 曾（八字头），用户人裁 曾 且已进库
        # （provenance=human），但整理本这一处印 會，`context` 通道就按整理本放行成了
        # 會，判据 A 的「对你的裁决」因此掉到 210/211。库匹配、上下文、整理本对齐
        # 全都是间接证据，人看着图下的判断不是——它该一票定案。
        human_shapes = _human_shapes(p.db_path) if p.use_human_verdicts else {}

        def excluded_note(iid: str) -> str:
            from ..clustering.exclusions import load_exclusions
            rec = load_exclusions(_ex_path).get(iid, {})
            return f"{rec.get('origin', '?')}:{rec.get('reason', '?')}"
        match: PageMatch = ctx.product("glyph_match", page)
        ocr: PageOcr | None = _opt(ctx, "ocr_candidates", page)
        dec: PageDecision | None = _opt(ctx, "context_decision", page)

        omap = {r.id: r for cc in (ocr.columns if ocr else []) for r in cc.chars}
        dmap = {r.id: r for cc in (dec.columns if dec else []) for r in cc.chars}
        amap = _align(ctx, page)
        always = set(p.always_review or "")
        out: list[ColumnAdmit] = []
        n_auto = n_review = n_excluded = 0
        for cc in match.columns:
            if not cc.ok:
                out.append(ColumnAdmit(col=cc.col, ok=False, error=cc.error))
                continue
            recs: list[AdmitRec] = []
            # ── 版本注闭集通道（段级预扫，2026-09-06）─────────────────
            # 夹注小字库里样本极少（16,019 例里 59 个），逐字认必然卡在
            # cov 0.93~0.99 的灰带上落人审。但版本注是闭集（78 个短语），
            # 整段一起认反而稳。段级判据见 clustering/note_lexicon 模块头，
            # 三条硬约束（格数相等 / 相似度 / 唯一最佳）缺一不可。
            # 这里只产出「这一格该读什么」的建议，**写不写库仍走下面的
            # 逐格通道**——短语给的是读法，字形还要过账本的组内定形。
            note_char: dict[str, str] = {}
            note_sim: dict[str, float] = {}
            if p.use_note_lexicon:
                jz = [r for r in cc.chars if r.sub]
                if jz:
                    lex = load_lexicon(p.note_lexicon or None)
                    for seg in jz_segments((r.slot, r.sub) for r in jz):
                        sset = set(seg)
                        rs = sort_by_reading([r for r in jz if r.slot in sset])
                        cands: list[set[str]] = []
                        for r in rs:
                            cs = {c for c, _v in r.candidates[:5]}
                            oo = omap.get(r.id)
                            if oo:
                                cs |= {c for c, _v in oo.topk[:5]}
                            dd0 = dmap.get(r.id)
                            if dd0 and dd0.char:
                                cs.add(dd0.char)
                            cands.append(cs)
                        hit = match_segment(cands, lex, min_sim=p.note_min_sim,
                                            semantic=vmap.semantic)
                        if hit:
                            phrase, sim = hit
                            for r, ch in zip(rs, phrase):
                                note_char[r.id] = ch
                                note_sim[r.id] = sim
            for r in cc.chars:
                # 排除名单命中：这块图人已判过切坏/带残留/非字。既不进库也不出
                # 审查卡，只落一行留账（v1 的 seeding 同款处理）。放在最前面——
                # 后面那些证据都建立在「这块图是完整的一个字」之上，图都不成立
                # 就没什么可判的。
                if r.id in excluded:
                    n_excluded += 1
                    recs.append(AdmitRec(
                        id=r.id, slot=r.slot, sub=r.sub, admit=False,
                        channel=None, char=None, provenance="",
                        doubts=["excluded"],
                        evidence={"excluded": excluded_note(r.id)}))
                    continue
                # 人裁过的位：一票定案，后面所有自动通道都不再看（2026-09-06）。
                # 人是**看着图**判的，库匹配/上下文/整理本对齐全是间接证据；实测
                # vol02:18:9:5 图上刻 曾、用户裁 曾 已进库，整理本这一处印 會，
                # `context` 通道就把它放行成了 會——人裁被机器覆盖，判据 A 的
                # 「对你的裁决」掉到 210/211。放在排除名单之后、其余通道之前。
                hs = human_shapes.get(r.id)
                if hs:
                    n_auto += 1
                    recs.append(AdmitRec(
                        id=r.id, slot=r.slot, sub=r.sub, admit=True,
                        channel="human", char=hs, reading=None,
                        provenance="human", doubts=[],
                        evidence={"human": True}))
                    continue
                o = omap.get(r.id)
                # OCR 只供候选，**置信度不参与任何自动判断**（见模块头）
                ocr_in = ({"char": o.topk[0][0], "prob": o.topk[0][1]}
                          if o and o.topk else None)
                # **near_form 疑问要自己判**（2026-09-04 修）。`judge_doubts`
                # 在 v1 里靠整理本/载体产出六条疑问，这里没有整理本，但
                # `near_form` 只看候选字属不属于形近家族，自己就能判——
                # 不判的话 `admission_decision` 的形近防线整条失效。
                # 实锤：vol01:151:8:4 库候选 諭 0.9923 / 論 0.9898 只差
                # 0.0025，matcher 已把它从 same 降档 unsure（但 guard 字段
                # 是 None，v1 就没填），match_solo 只看 cov ≥ 0.99 就放行，
                # 结果把「論」认成「諭」——**dev_set 1619 条金标里唯一的错**。
                cand_chars = {c for c, _v in r.candidates[:3]}
                if r.char:
                    cand_chars.add(r.char)
                doubts = (["near_form"] if cand_chars & NEAR_FORM_CHARS else [])
                # 整理本这一路（2026-09-04 接上）。v1 标定过 match_ref 144/144、
                # match_replace 70/70、match_margin 102/102，靠的就是「文本证据 ×
                # 形状证据同源性为零」；v2 此前一直传 align_char=None，这些通道
                # 一条都没生效，于是每个库 unsure 都要人点。
                # replace 段照 v1 记 DOUBT_REPLACE_ALIGN（那层有独立的更严闸）。
                al = amap.get(r.id)
                align_char = al[0] if al else None
                if al and al[1] == "replace":
                    doubts.append("replace_align")
                note_ch = note_char.get(r.id)
                # 账本人确认过的 T2 对（variant_strategy.md §4.3 第 6 行）：两头都是正字、
                # 语义表不合并（注/註、鍾/鐘），但本书人裁明确记过「刻 X 读 Y」——对这一位
                # 把 X 当 Y 的同义看，让 match_ref / match_replace 照常评。只影响这一次调用。
                lib_top = r.char or (r.candidates[0][0] if r.candidates else None)
                vm_here = vmap
                if (align_char and lib_top and lib_top != align_char
                        and vmap.semantic(lib_top) != vmap.semantic(align_char)
                        and ledger.pair_confirmed(lib_top, align_char)):
                    vm_here = _PairAwareMap(vmap, {lib_top: vmap.semantic(align_char)})
                # CNN 字形背书（match_solo_cnn 用）：只在**灰区且无整理本**时才算，
                # 别的档一律不看它——避免把一路弱独立证据混进已经成立的两路里。
                # 取图有代价（要读 char_patch 并过网络），所以先判档位再算。
                cnn_char = None
                if (align_char is None and r.verdict != "same" and r.candidates
                        and max(c for _, c in r.candidates) >= MATCH_SOLO_OCR_COV):
                    cnn_char = _cnn_top(ctx.book.id, page, cc.col, r.slot, r.sub)
                ok, channel = admission_decision(
                    ocr=ocr_in, align_char=align_char, ref_char=None,
                    doubts=doubts, vmap=vm_here,
                    match_char=r.char if r.verdict == "same" else None,
                    match_candidates=list(r.candidates),
                    match_guard=r.guard, match_wmax=r.wmax,
                    solo_cov=p.solo_cov, cnn_char=cnn_char)
                # ── 版本注闭集通道 note_lexicon（2026-09-06）──────────
                # 走到这里还没放行、而段级匹配给出了读法时补一刀。判据与
                # match_ref 同构（文本证据 × 形状证据、来源独立），但证据来自
                # **整段**而不是单格，所以另立通道名，出了错能按通道归因。
                # 四条护栏：
                #   1. 只对夹注格（sub 非空）——正文有整理本逐字对齐，用不着它；
                #   2. 库候选里要有语义同字的（形状不背书就不算两路互证）；
                #   3. 形近家族、never_match/db_inconsistent 护栏照拦；
                #   4. always_review 的字不碰（下面那道闸也会再拦一次）。
                #   5. **字级证据强时不许短语改写字形**（2026-09-06 异体字线实锤）：
                #      vol02:157:2:12b 库判 same cov 0.9984、OCR top1 也同字，两路形状
                #      证据一致，而短语把它读成了别的字——产物因此留下一条假转换，
                #      在账本的「关系图外转换对」才露头。段级匹配的价值是「整段比逐字稳」，
                #      但短语只差一个字也能匹配上，于是那个字被短语的读法改写。
                #      所以：库 same 且 cov ≥ solo_cov 时，短语只能**同意**不能**改写**。
                #      全书实测该通道只放行 5 条，加这条护栏一条都不损失。
                lib_same_strong = (r.verdict == "same" and r.char
                                   and r.cov >= p.solo_cov)
                if (not ok and note_ch and r.sub
                        and r.guard is None
                        and "db_inconsistent" not in doubts
                        and not (lib_same_strong
                                 and vmap.semantic(r.char) != vmap.semantic(note_ch))):
                    cands_sem = {vmap.semantic(c) for c, _v in r.candidates[:5]}
                    if (vmap.semantic(note_ch) in cands_sem
                            and note_ch not in NEAR_FORM_CHARS):
                        ok, channel = True, "note_lexicon"
                        align_char = align_char or note_ch
                # 己/已/巳 永远人审（用户 2026-09-04 定）。这三个字的字形与
                # 文意会分岔（同词异写 + 真的另一个字），任何自动通道都不该
                # 替人决定读法——字形层护栏拦不住 align×库 这种跨源一致。
                if (align_char in always
                        or (r.candidates and r.candidates[0][0] in always)
                        or (r.char in always)):
                    if p.relax_split_ref and align_char in always:
                        # 用户 2026-09-06 改口：「己已巳 没必要每次都单独选文意，根据上下文
                        # 或整理本直接选；字形选哪个都行，不太重要」。文意 = 整理本字，
                        # 字形 = 库 top1（若也是这三字之一，否则跟整理本）。字形/文意
                        # 的取值在 _pick_char 之后统一写（见下）。整理本没给字的仍人审。
                        ok, channel = True, "split_ref"
                    elif ok:
                        ok, channel = False, None

                char, reading = _pick_char(
                    ok=ok, channel=channel, align_char=align_char,
                    match_char=r.char, verdict=r.verdict,
                    candidates=list(r.candidates))
                if channel == "split_ref":
                    _top = r.candidates[0][0] if r.candidates else None
                    char = _top if _top in always else align_char
                    reading = align_char if align_char != char else None
                # variant_form 分支要用**改名前**的 channel 判——见下面「⚠️ dual 档判 variant_form
                # 判早了」。这里先存一份，改名（下一段）之后再用它，别被 "dual" 字符串盖掉。
                is_corpus_channel = channel in _CORPUS_CHANNELS
                # `admission_decision` 给 dual 档返回 None（历史口径，别去改它
                # ——`_pick_char` 与 seeding 的一串标定注释都按 None 写的）。但
                # **产物里不许有匿名准入**：每条自动进库都得说清走的哪条通道，
                # 否则出了错没法按通道归因（test_seed_admit_step 有护栏）。
                # 所以在取完字之后、写产物之前补上名字。
                if ok and channel is None:
                    channel = "dual"
                prov = "match" if ok else ""
                # 「义定形未定」（2026-09-05，variant_strategy.md §4.2）：整理本通道
                # 放行的、库又没下 same 断言的位，`_pick_char` 把整理本形当成了刻本形。
                # 整理本对多数组只用一种形，它定得了义定不了形——刻 髪 存 髮 就是这么
                # 来的。组里有 ≥2 个可能的形时，用形状证据（库候选 / 组内三源检索）
                # 定形；定不了就落人审，卡片只列组内的形，人点一次账本就记住。
                #
                # ⚠️ dual 档判 variant_form 判早了（2026-09-06 实锤）：本该判的是
                # 「这条通道用没用整理本」，但这里一度直接拿**改名后**的 channel 去比
                # `_CORPUS_CHANNELS`（里面收的是 None，不是字符串 "dual"），于是 dual
                # 档永远进不了这个分支——隸/𨽾、變/𠮓 这些账本已经改判优先形（preferred=
                # 𨽾/𠮓）的组，dual 位还是照写库 unsure 时的整理本形，E 报 82/91 才发现。
                form_ev = None
                form_open = False
                if ok and align_char and is_corpus_channel and r.verdict != "same":
                    forms = group_forms(ledger, align_char)
                    if len(forms) >= 2:
                        ranks = None
                        fd = decide_form(align_char, forms, list(r.candidates), ledger)
                        if fd.state == "open":
                            ranks = _image_ranks(ctx.book.id, page, cc.col, r.slot, r.sub, forms)
                            if ranks:
                                fd = decide_form(align_char, forms, list(r.candidates), ledger, ranks)
                        form_ev = fd.to_evidence()
                        _top = r.candidates[0][0] if r.candidates else None
                        if fd.state == "open" and p.relax_ref_agree and _top in forms:
                            # 用户 2026-09-06「整理本和字形分析一致时直接放行」：组里哪个形
                            # 没定，但库 top1 就是组内的一个形——拿它当形（最好的猜测），文意
                            # 取整理本。证据里 state=guess，判据 E 的分母（_multi_form）会把
                            # 它算进抽审；错了走 audit_glyph_consistency 那套人裁子库复查。
                            char = _top
                            reading = align_char if align_char != char else None
                            form_ev = {**form_ev, "state": "guess"}
                        elif fd.state == "open":
                            ok, channel, prov, form_open = False, None, "", True
                            doubts = doubts + ["form_open"]
                            char = None
                            reading = align_char
                        else:
                            char = fd.char
                            reading = align_char if align_char != char else None
                # 上下文当第三路：库没定下来、但 Step6 过了门槛，仍可进库
                # （provenance=context，设计 §3.2 的分级）。字形层照录 —— 这里
                # 用的是候选内选出的 surface，不引入候选外的字。形未定时不走：
                # 上下文只能定义，定不了形。
                # ⚠️ 己/已/巳 的「永远人审」在这里也要守（2026-09-06 补）。上面那道闸只拦
                # admission_decision 的通道，context 这条是后接的，此前直接绕过去了：
                # vol01 有 30 条 context 放行的 已/巳，用户抽审 18 条里 16 条形不对（刻 巳
                # 存成整理本的 已）。字形库本身没脏——glyphdb_admit 把人裁的 shape 单独存
                # 字形层，审计 617 条里字形只错 2 条；脏的是产物里的 char 与判据 E 的分母。
                d = dmap.get(r.id)
                if not ok and not form_open and p.use_context and d and d.source == "context" \
                        and d.char and d.margin >= p.context_margin \
                        and d.char not in always \
                        and not (r.candidates and r.candidates[0][0] in always):
                    ok, channel, char, prov = True, "context", d.char, "context"

                # 整理本 × 形状/上下文 一致 → 放行（用户 2026-09-06「很多都是整理本存在时
                # 非常明显的选择，能不能放松要求」）。走到这里还没放行的位，若整理本字与库
                # top1 语义同字（刻本形归一后是同一个字），或与 Step6 上下文定字相同，就放行：
                # 形取库 top1（它是刻本形），文意取整理本。两册人审位实测（关掉人裁通道的
                # 产物）整理本≡库top1 10/10、==上下文 4/4；全部人裁真值上反例 0（relax_study）。
                # 己已巳 不走这里（上面 split_ref 单独处理）。
                if (not ok and p.relax_ref_agree and align_char and align_char not in always):
                    _top = r.candidates[0][0] if r.candidates else None
                    _d = dmap.get(r.id)
                    if _top and _top not in always \
                            and vmap.semantic(_top) == vmap.semantic(align_char):
                        ok, channel, prov = True, "ref_lib", "match"
                        char = _top
                        reading = align_char if align_char != _top else None
                    elif _d and _d.char and _d.char == align_char:
                        ok, channel, prov = True, "ref_ctx", "context"
                        char = align_char
                        reading = None
                if ok:
                    n_auto += 1
                else:
                    n_review += 1
                recs.append(AdmitRec(
                    id=r.id, slot=r.slot, sub=r.sub, admit=ok, channel=channel,
                    char=char, reading=reading, provenance=prov,
                    doubts=[] if ok else (_doubts(r, d) + doubts),
                    evidence={"verdict": r.verdict, "cov": r.cov, "wmax": r.wmax,
                              "guard": r.guard,
                              "ocr": (o.topk[:3] if o else []),
                              "ctx_margin": (d.margin if d else None),
                              **({"form": form_ev} if form_ev else {})}))
            out.append(ColumnAdmit(col=cc.col, ok=True, chars=recs))
        return {"seed_admit": PageAdmit(page=page, n_auto=n_auto, n_excluded=n_excluded,
                                        n_review=n_review, columns=out)}


# 整理本参与的通道：`reading` 记整理本字（字形仍照录图上的形）。
# ⚠️ match_ref 也在内（2026-09-05 补）：它放行的依据就是「库 top1 语义 == 整理本字」，
# 漏掉它的后果是 vol01:18:8:6 刻「㫖」、整理本「旨」被存成 reading=None——
# 体检判据 A 把这种异体位当成错例（99.99%），其实是转换没记下来。
@lru_cache(maxsize=4)
def _human_shapes(db_path: str) -> dict[str, str]:
    """字形库里人裁过的位 → 人裁的**字形**。`{裸 id: shape}`（去掉 v2: 前缀）。

    取 `provenance='human'` 的 admissions，字形从 glyphs 经 exemplars 取——
    `admissions.char` 存的是**释读**，己/已/巳 那三个字它与字形会分岔，
    拿它当字形会把「刻 巳 读 已」写成「刻 已」（09-06 那批 62 条脏数据就是这么来的）。

    ## ⚠️ 只认 `v2:` 前缀，v1 的记录一条都不能要

    库里 1,925 条人裁有 **1,021 条是 v1 的 id**（`book:page:col:idx`，idx 从 0、含
    margin 格），与 v2 的 `book:page:col:slot`（slot 从 1）**长得一模一样但指的不是
    同一格**——这正是 `glyphdb_admit` 当初给 v2 加前缀要隔离的东西
    （见该消费者 docstring「v2 的 id 必须加前缀，否则会污染 15332 条已有记录」）。
    第一版这里去掉前缀后不加区分地收，vol01 判据 A 当场从 100% 掉到 94.70%：
    `vol01:4:1:10` 判「編」而金标「三」，整列错开。
    """
    import sqlite3
    from pathlib import Path
    if not Path(db_path).exists():
        return {}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        rows = conn.execute(
            "SELECT a.instance_id, g.char FROM admissions a "
            "  JOIN exemplars e ON e.instance_id = a.instance_id "
            "  JOIN glyphs g ON g.glyph_id = e.glyph_id "
            " WHERE a.provenance = 'human' AND a.instance_id LIKE 'v2:%'").fetchall()
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    return {iid[3:]: ch for iid, ch in rows if ch}


_CORPUS_CHANNELS = (None, "match_ref", "match_replace", "match_ref_weak", "match_margin",
                    # note_lexicon（2026-09-06）：版本注闭集给的读法同样是**文本证据**，
                    # 与整理本那几路一个性质——`reading` 该填、字形该照录图上的形、
                    # 「义定形未定」的组内定形该走。漏进这个元组会有两个后果：
                    # reading 不填（账本统计不到转换），以及 variant_form 整段跳过
                    # （刻本形被整理本形盖掉，正是判据 E 82/91 那次的机制）。
                    "note_lexicon")


def _pick_char(ok: bool, channel: str | None, align_char: str | None,
               match_char: str | None, verdict: str,
               candidates: list) -> tuple[str | None, str | None]:
    """决定这一位的 **(字形, 文意)**。

    - `char`（字形）：same 档用库继承的字；否则取**库候选 top1**——那正是
      match_solo / match_solo_ocr 采信的东西，不取就会「自动进库却没有字」。
    - `reading`（文意）：整理本参与的通道填整理本字；与 char 相同时返回 None。

    ## ⚠️ 整理本字不能覆盖 `char`

    第一版让整理本字直接覆盖 `char`，结果 7 条异体字位被写成了整理本的形：
    刻本刻「㫖」存成「旨」、「彚」存成「彙」、「卽」存成「即」。`AdmitRec.char`
    喂的是字形库，**字形库存的是刻本上实际刻的形**——用整理本改它，将来一个真
    刻成这形状的实例会继承错误的字形（charset_and_lm.md §四的实锤）。所以整理本
    字只进 `reading`，`char` 永远照录图上的形。

    ## ⚠️ `channel is None` 也是一条通道

    `dual` 档（align × OCR 双信号一致且零疑问）在 `admission_decision` 里是
    `return True, None`——**没有通道名**。漏掉它，`reading` 就不会填；更早的一版
    连 `char` 都会掉进库 top1 兜底，实测判错 9 条金标（vol01:42:3:20 align 与
    OCR 都读「敷」，库 top1 却是「數」，0.957 vs 0.955 的 HOG 饱和差距）。
    所以按「这条通道用没用整理本」判，而不是列通道名。
    """
    char = match_char if verdict == "same" else None
    reading = None
    if ok and align_char and channel in _CORPUS_CHANNELS:
        reading = align_char
        # ⚠️ 库 unsure 时，**别拿库 top1 当字形**。
        #
        # unsure 的字面意思就是「库不知道这是什么」：实测 8 条 dual 位
        # （vol01:42:3:20 等）库 top1 与 top2 只差 0.0017~0.0023，而 align 与
        # OCR 两路独立证据都指向另一个字，且那个字**根本不在库的候选里**
        # （敷/顯/毫/昌）。此时把库的猜测写进 `char`，等于往字形库塞 8 个错
        # 例——下一页再遇到同形字就会继承这个错（charset_and_lm.md §四）。
        #
        # 库判 same 才有资格定字形（那是它下了断言）；unsure 时两路零同源证据
        # 一致，整理本字是更好的字形估计。异体位（㫖/旨、彚/彙）不受影响：
        # 库对它们判 same，char 仍照录刻本的形，只有 reading 取整理本。
        if char is None:
            char = align_char
    if char is None and candidates:
        char = candidates[0][0]
    return char, (reading if reading and reading != char else None)


def _align(ctx: RunContext, page: int) -> dict[str, tuple[str, str]]:
    """`align_ref` 的产物 → {字位: (整理本字, equal|replace)}。

    Step5-d 已经把 8-gram 锚定 + difflib 挪成正式 Step（`steps/align_ref.py`）：
    这里只读它的产物，不再自己 import `gold.v2_align` 的私有函数现算一遍——
    那是任务书点名的"绕道读金标"，对齐这个动作因此在两处各算一遍、互相漂移。
    产物缺失或未锚定就返回空表，所有整理本通道自动失效，退回改动之前的行为，
    不会把错的/缺的对齐硬塞进准入。这是「拿不准就保持基线」在这一层的落法。
    """
    ref: PageAlignRef | None = _opt(ctx, "align_ref", page)
    if ref is None or not ref.anchored:
        return {}
    return {c.id: (c.align_char, c.align_op) for c in ref.chars}


def _opt(ctx: RunContext, kind: str, page: int):
    """可选上游：缺了就 None，不炸——OCR 要引擎、上下文要语料，都可能没有。"""
    try:
        return ctx.product(kind, page)
    except Exception:
        return None


class _PairAwareMap:
    """VariantMap 的一次性包装：额外把几个形映到指定语义（本书人确认过的 T2 转换对）。
    只给 `admission_decision` 这一次调用用，不改全局语义表。"""

    def __init__(self, base, extra: dict[str, str]):
        self._base, self._extra = base, extra

    def semantic(self, char: str) -> str:
        return self._extra.get(char) or self._base.semantic(char)

    def __getattr__(self, name):
        return getattr(self._base, name)


def _cnn_top(book: str, page: int, col: int, slot: int, sub: str | None) -> str | None:
    """CNN embedding 检索的 top1 字（模板 = 字体 + 康熙字头 + 字统网真刻本）。

    只给 `match_solo_cnn` 用：无整理本 + 库形状落在 0.95~0.99 灰区时的第二路背书。
    没图 / 没 checkpoint → None（通道自动不触发）。
    """
    try:
        import cv2

        from ..clustering.cnn_candidates import shared
        from ..clustering.font_candidates import book_charset
        from ..clustering.normalize import normalize_patch
        from ..products.cache import ImageCache
        key = f"p{page:04d}c{col:02d}s{slot}{sub or ''}"
        path = ImageCache().get(book, "char_patch", key)
        if path is None:
            return None
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        cc = shared()
        top = cc.emb_topk(normalize_patch(img), tuple(book_charset()), k=1)
        return top[0][0] if top else None
    except Exception:
        return None


def _image_ranks(book: str, page: int, col: int, slot: int, sub: str | None,
                 forms: list[str]) -> dict | None:
    """组内 closed-set 检索要看图：从 Step4 落的 `char_patch` 缓存取字块。没图 → None。"""
    try:
        import cv2

        from ..clustering.normalize import normalize_patch
        from ..clustering.variant_form import image_ranks_for
        from ..products.cache import ImageCache
        key = f"p{page:04d}c{col:02d}s{slot}{sub or ''}"
        path = ImageCache().get(book, "char_patch", key)
        if path is None:
            return None
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        return image_ranks_for(normalize_patch(img), forms)
    except Exception:
        return None


def _doubts(match_rec, dec_rec) -> list[str]:
    """人审时把「为什么拿不准」说出来——审查页要显示它。"""
    out: list[str] = []
    if match_rec.guard:
        out.append(f"护栏:{match_rec.guard}")
    if match_rec.verdict == "unsure":
        out.append(f"库 unsure(cov={match_rec.cov:.3f})")
    elif match_rec.verdict == "diff":
        out.append("库里没有这个字")
    elif match_rec.verdict == "same":
        # same 档还落回人审，只可能是 admission_decision 的某条防线拦下的
        # （异语义对手同到阈档、残差窗超限需 OCR 背书……）。不写原因的话
        # 审查页显示空白，人不知道在问什么。
        out.append(f"库 same 但准入被拦(cov={match_rec.cov:.3f}, wmax={match_rec.wmax:.1f})")
    if dec_rec is not None and dec_rec.source == "prior":
        out.append(f"上下文 margin 不足({dec_rec.margin:.2f})")
    return out
