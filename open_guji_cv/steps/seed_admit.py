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
                                    PageDecision, PageMatch, PageOcr)

DEFAULT_CORPUS = "corpus/zongmu_wuyingdian_reference.txt"


class SeedAdmitParams(BaseModel):
    variants: str = ""                  # 异体表；空 = VariantMap 默认
    solo_cov: float = 0.99              # match_solo 的 cov 闸，实测拐点
    use_context: bool = True            # 把 Step6 的定字当第三路证据
    context_margin: float = 0.70        # 用它时的 margin 门槛（生产值）
    corpus: str = DEFAULT_CORPUS        # 整理本；空字符串 = 不用整理本通道
    corpus_fingerprint: str = ""        # 自动填，进 params_hash（外部可变状态）
    always_review: str = "己已巳"       # 这些字永远人审（用户 2026-09-04 定）
    edition: str = "wuyingdian_zongmu"  # 本书用字账（variant_ledger）的键
    ledger_fingerprint: str = ""        # 自动填：账本变了产物过期
    variants_fingerprint: str = ""      # 自动填：语义表（auto + 手工）变了产物过期

    def model_post_init(self, _ctx) -> None:
        # 语料是**外部可变状态**：换了整理本，准入结论会变，产物必须过期。
        # 与 glyph_match 的 db_fingerprint、context_decide 的 corpus_fingerprint
        # 同一套做法（见 context_decide 模块头）。
        from ..steps.context_decide import corpus_fingerprint
        if self.corpus and not self.corpus_fingerprint:
            object.__setattr__(self, "corpus_fingerprint",
                               corpus_fingerprint([self.corpus]))
        # 用字账与语义表同理（2026-09-05）：两张表都是派生物，重建就该让准入重跑
        if not self.ledger_fingerprint:
            from ..variant_ledger import ledger_path
            object.__setattr__(self, "ledger_fingerprint",
                               corpus_fingerprint([str(ledger_path(self.edition))]))
        if not self.variants_fingerprint:
            from ..clustering.variants import DEFAULT_AUTO_PATH, DEFAULT_VARIANTS_PATH
            paths = [self.variants] if self.variants else [str(DEFAULT_AUTO_PATH), str(DEFAULT_VARIANTS_PATH)]
            object.__setattr__(self, "variants_fingerprint", corpus_fingerprint(paths))


@register_step
class SeedAdmitStep(Step):
    spec = StepSpec(
        id="seed_admit", title="C1 进库准入", version="1.3", unit="cell",
        consumes=("glyph_match", "ocr_candidates", "context_decision"),
        produces=("seed_admit",),
        params=SeedAdmitParams,
        needs=("db",),
        code_deps=("open_guji_cv.clustering.seeding",
                   "open_guji_cv.clustering.variants",
                   "open_guji_cv.clustering.variant_form",
                   "open_guji_cv.variant_ledger",
                   "open_guji_cv.clustering.align_label"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        from ..clustering.seeding import NEAR_FORM_CHARS, admission_decision
        from ..clustering.variant_form import decide_form, group_forms
        from ..clustering.variants import VariantMap
        from ..variant_ledger import BookLedger
        p: SeedAdmitParams = ctx.params_for(self)  # type: ignore[assignment]
        vmap = VariantMap.load(p.variants or None)
        ledger = BookLedger.load_or_empty(p.edition)
        match: PageMatch = ctx.product("glyph_match", page)
        ocr: PageOcr | None = _opt(ctx, "ocr_candidates", page)
        dec: PageDecision | None = _opt(ctx, "context_decision", page)

        omap = {r.id: r for cc in (ocr.columns if ocr else []) for r in cc.chars}
        dmap = {r.id: r for cc in (dec.columns if dec else []) for r in cc.chars}
        amap = _align(p, match, dec, ocr, page, ctx.book.id)
        always = set(p.always_review or "")
        out: list[ColumnAdmit] = []
        n_auto = n_review = 0
        for cc in match.columns:
            if not cc.ok:
                out.append(ColumnAdmit(col=cc.col, ok=False, error=cc.error))
                continue
            recs: list[AdmitRec] = []
            for r in cc.chars:
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
                # 账本人确认过的 T2 对（variant_strategy.md §4.3 第 6 行）：两头都是正字、
                # 语义表不合并（注/註、鍾/鐘），但本书人裁明确记过「刻 X 读 Y」——对这一位
                # 把 X 当 Y 的同义看，让 match_ref / match_replace 照常评。只影响这一次调用。
                lib_top = r.char or (r.candidates[0][0] if r.candidates else None)
                vm_here = vmap
                if (align_char and lib_top and lib_top != align_char
                        and vmap.semantic(lib_top) != vmap.semantic(align_char)
                        and ledger.pair_confirmed(lib_top, align_char)):
                    vm_here = _PairAwareMap(vmap, {lib_top: vmap.semantic(align_char)})
                ok, channel = admission_decision(
                    ocr=ocr_in, align_char=align_char, ref_char=None,
                    doubts=doubts, vmap=vm_here,
                    match_char=r.char if r.verdict == "same" else None,
                    match_candidates=list(r.candidates),
                    match_guard=r.guard, match_wmax=r.wmax,
                    solo_cov=p.solo_cov)
                # 己/已/巳 永远人审（用户 2026-09-04 定）。这三个字的字形与
                # 文意会分岔（同词异写 + 真的另一个字），任何自动通道都不该
                # 替人决定读法——字形层护栏拦不住 align×库 这种跨源一致。
                if ok and (align_char in always
                           or (r.candidates and r.candidates[0][0] in always)
                           or (r.char in always)):
                    ok, channel = False, None

                char, reading = _pick_char(
                    ok=ok, channel=channel, align_char=align_char,
                    match_char=r.char, verdict=r.verdict,
                    candidates=list(r.candidates))
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
                form_ev = None
                form_open = False
                if ok and align_char and channel in _CORPUS_CHANNELS and r.verdict != "same":
                    forms = group_forms(ledger, align_char)
                    if len(forms) >= 2:
                        ranks = None
                        fd = decide_form(align_char, forms, list(r.candidates), ledger)
                        if fd.state == "open":
                            ranks = _image_ranks(ctx.book.id, page, cc.col, r.slot, r.sub, forms)
                            if ranks:
                                fd = decide_form(align_char, forms, list(r.candidates), ledger, ranks)
                        form_ev = fd.to_evidence()
                        if fd.state == "open":
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
                d = dmap.get(r.id)
                if not ok and not form_open and p.use_context and d and d.source == "context" \
                        and d.char and d.margin >= p.context_margin:
                    ok, channel, char, prov = True, "context", d.char, "context"

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
        return {"seed_admit": PageAdmit(page=page, n_auto=n_auto,
                                        n_review=n_review, columns=out)}


# 整理本参与的通道：`reading` 记整理本字（字形仍照录图上的形）。
# ⚠️ match_ref 也在内（2026-09-05 补）：它放行的依据就是「库 top1 语义 == 整理本字」，
# 漏掉它的后果是 vol01:18:8:6 刻「㫖」、整理本「旨」被存成 reading=None——
# 体检判据 A 把这种异体位当成错例（99.99%），其实是转换没记下来。
_CORPUS_CHANNELS = (None, "match_ref", "match_replace", "match_ref_weak", "match_margin")


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


@lru_cache(maxsize=4)
def _corpus_text(path: str) -> str:
    from pathlib import Path
    f = Path(path)
    return f.read_text(encoding="utf-8") if f.exists() else ""


@lru_cache(maxsize=4)
def _corpus_index(path: str):
    """8-gram 索引建一次就好——整本书每页都要用，重建一次约 1 秒。"""
    from ..clustering.align_label import build_ngram_index
    return build_ngram_index(_corpus_text(path))


def _align(p, match, dec, ocr, page: int, book: str = "") -> dict[str, tuple[str, str]]:
    """整页锚到整理本 → {字位: (整理本字, equal|replace)}。

    锚不上就返回空表——那样所有整理本通道自动失效，退回本次改动之前的行为，
    不会把错的对齐硬塞进准入。这是「拿不准就保持基线」在这一层的落法。
    """
    if not p.corpus:
        return {}
    from ..clustering.align_label import label_page
    from ..gold.v2_align import _slots_from_decision
    text = _corpus_text(p.corpus)
    if not text:
        return {}
    slots, _meta = _slots_from_decision(dec, match, ocr)
    if len(slots) < 12:
        return {}
    # ⚠️ book 必须传真名：`label_page` 拼的是 `book:page:col:idx`，传空字符串
    # 会得到 ":24:1:2" 这种键，与产物的 "vol01:24:1:2" 对不上——**查表全 miss，
    # 不报错，只是整理本通道一条都不触发**（本轮实际踩到，靠比对键样例才发现）。
    labs, ok = label_page(str(page), slots, book, text, _corpus_index(p.corpus))
    if not ok:
        return {}
    return {l.instance_id: (l.char, l.op) for l in labs}


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
