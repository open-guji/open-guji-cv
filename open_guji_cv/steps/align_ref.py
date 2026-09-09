"""Step5-d 整理本对齐：四路证据里的文本那一路。

## 从 `gold/v2_align.py` 挪出来的理由

对齐这个动作（v2 定字串 → 8-gram 锚到整理本 → `difflib` 过闸对齐）此前住在
`gold/v2_align.py` 里，身份是「金标生成器」。但它同时是**四路证据里的文本
那一路**——`match_ref`（库 × 整理本）、`match_replace`、`dual`（OCR × 整理本）
这些准入通道都要用它的结果，且是四路里唯一能与形状路凑成零同源双信号的一路
（`step5_step6_benchmark.md` 数字）。一个东西担两个身份，后果是它的产物没有
独立指纹与过期传播：`seed_admit` 要用 `align_char` 得绕道 import
`gold.v2_align` 里带下划线的私有函数、自己再算一遍对齐，`gold` 那边的产物
又完全不经过 Step 缓存/指纹体系。

归位之后：本 Step 产出逐字位 `{align_char, align_op, ref_run}`，与
`glyph_match`／`ocr_candidates`／`context_decision` 三路平级；`seed_admit`
改读这个产物；`gold.v2_align` 的金标派生也改读它（见该模块模块头），
`GoldChar{shape, reading, conversion, source}` 的两个身份（金标 vs 文本证据）
从此分开。

## 指纹要带语料指纹

整理本换了，同一批字位的对齐结果就会变，而代码/参数/上游产物一个都没动——
与 `context_decide`／`glyph_match` 带语料/库指纹是一回事，见那两处模块头。

## 怎么锚（原样照抄，算法一行没改）

复用 `clustering/align_label.label_page`：定字串 → 8-gram 锚到整理本 →
`difflib` 对齐 → **采信闸**（`equal` 段全收；等长 `replace` 段要求段长 ≤3
且左右各有 ≥2 字的 `equal` 段贴身夹住，一侧 ≥2、另一侧 ≥1 即可）。

定字串（对齐载体）来自 `slots_from_decision`：优先取 `context_decision` 的
定字，弃权位逐级兜底 **库 kNN top1 → OCR top1**（2026-09-04 改，兜底字只是
对齐载体，不进 `align_char`，最多让那一位落进 `replace` 段）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.recog import (AlignRec, PageAlignRef, PageDecision,
                                    PageMatch, PageOcr)
from ..utils.jiazhu_order import sort_by_reading

DEFAULT_CORPUS = "corpus/zongmu_wuyingdian_reference.txt"


def slots_from_decision(dec, match=None, ocr=None
                       ) -> tuple[list[tuple[int, int, str, str]], dict]:
    """Step6 的 `context_decision`（+ 库/OCR 兜底）→ 对齐要的 slots + 溯源表。

    ## 弃权位要用库/OCR 兜底填上，不能跳过（2026-09-04 改）

    原先只收**定了字**的位。理由当时是「弃权位没有假设可对齐」，但这恰好
    弄反了 `difflib` 的工作方式：对齐要的是一条**位位对应**的串，跳过一个
    位不会「留空」，而是把后面的字全部前移一格——弃权越多，错位越狠。

    实测代价极大：**p70 整页锚不上**（132 位只定出 72 个），而那页的文字
    在整理本里明明有（「繭紙朱題芸帙之名蟠屈鸞章」）。它是生僻字密集页，
    库里没样本、OCR 字表也不够，于是定字最少、最需要整理本帮忙的那些页，
    反而是最锚不上的——正好把整理本这路证据挡在了最该用它的地方。

    改成逐级兜底：**定字 → 库 kNN top1 → OCR top1**。兜底字只是**对齐载体**
    （`AlignedLabel.hyp`），最终 `align_char` 取的是整理本给的 `char`，
    所以兜底字错了也不会污染 `align_char`，最多让那一位落进 `replace` 段
    （本来就该分层读）。

    实测 vol01 dev_set：锚上的金标 **1619 → 1897 / 1933**（83.8% → 98.1%），
    p70 从 0 → 115。

    `match` / `ocr` 传 None 时退回旧行为（只收定字位）。
    """
    mmap = {r.id: r for cc in (match.columns if match else []) for r in cc.chars}
    omap = {r.id: r for cc in (ocr.columns if ocr else []) for r in cc.chars}

    def _fallback(rid: str) -> str | None:
        m = mmap.get(rid)
        if m and m.candidates:
            return m.candidates[0][0]
        o = omap.get(rid)
        if o and o.topk:
            return o.topk[0][0]
        return None

    slots: list[tuple[int, int, str, str]] = []
    meta: dict[tuple[int, int, str], str] = {}
    # 有 match 时以它为准列举字位——context_decision 可能整列缺席（弃权），
    # 那样按 dec 列举会把整列丢掉，锚定串又会错位。
    src = match if match is not None else dec
    dmap = {r.id: r for cc in dec.columns for r in cc.chars} if dec else {}
    for cc in sorted(src.columns, key=lambda c: c.col):
        if not cc.ok:
            continue
        # ⚠️ **按阅读顺序**，不是 (slot, sub)（2026-09-06 修，同 context_decide）。
        # 夹注 a/b 是两行小字，(slot, sub) 排出来交错成「兩採淮進鹽本政」，
        # 8-gram 锚不上、difflib 还会把邻近正文一起拖进 replace 段。
        for r in sort_by_reading(cc.chars):
            d = dmap.get(r.id)
            ch = (d.char if d and d.char else None)
            source = (d.source if d and d.char else "")
            if ch is None and (match is not None or ocr is not None):
                ch = _fallback(r.id)
                source = "fallback"
            if not ch:
                continue
            sub = r.sub or ""
            slots.append((cc.col, r.slot, sub, ch))
            meta[(cc.col, r.slot, sub)] = source
    return slots, meta


class AlignRefParams(BaseModel):
    corpus: str = DEFAULT_CORPUS
    corpus_fingerprint: str = ""
    """整理本指纹，留空自动填——理由同 `context_decide` 的语料指纹。"""

    def model_post_init(self, _ctx) -> None:
        if not self.corpus_fingerprint:
            from .context_decide import corpus_fingerprint
            object.__setattr__(self, "corpus_fingerprint",
                               corpus_fingerprint([self.corpus]))


@lru_cache(maxsize=4)
def _corpus_text(path: str) -> str:
    p = Path(path)
    return p.read_text(encoding="utf-8") if p.exists() else ""


@lru_cache(maxsize=4)
def _corpus_index(path: str):
    from ..clustering.align_label import build_ngram_index
    return build_ngram_index(_corpus_text(path))


@register_step
class AlignRefStep(Step):
    spec = StepSpec(
        id="align_ref", title="Step5-d 整理本对齐", version="1.0", unit="cell",
        consumes=("context_decision", "glyph_match", "ocr_candidates"),
        produces=("align_ref",),
        params=AlignRefParams,
        needs=("corpus",),
        code_deps=("open_guji_cv.clustering.align_label",
                   "open_guji_cv.utils.jiazhu_order"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: AlignRefParams = ctx.params_for(self)  # type: ignore[assignment]
        dec: PageDecision | None = _opt(ctx, "context_decision", page)
        match: PageMatch | None = _opt(ctx, "glyph_match", page)
        ocr: PageOcr | None = _opt(ctx, "ocr_candidates", page)
        if dec is None:
            return {"align_ref": PageAlignRef(
                page=page, anchored=False, corpus_fingerprint=p.corpus_fingerprint,
                note="没有定字产物")}
        if not p.corpus:
            return {"align_ref": PageAlignRef(
                page=page, anchored=False, corpus_fingerprint=p.corpus_fingerprint,
                note="未配置整理本")}
        text = _corpus_text(p.corpus)
        if not text:
            return {"align_ref": PageAlignRef(
                page=page, anchored=False, corpus_fingerprint=p.corpus_fingerprint,
                note="整理本读不到")}
        slots, _meta = slots_from_decision(dec, match, ocr)
        if len(slots) < 12:
            return {"align_ref": PageAlignRef(
                page=page, anchored=False, corpus_fingerprint=p.corpus_fingerprint,
                note=f"定字太少（{len(slots)}），锚不住")}

        from ..clustering.align_label import label_page
        # ⚠️ book 必须传真名：`label_page` 拼的是 `book:page:col:idx`，传空字符串
        # 会得到 ":24:1:2" 这种键，与产物的 "vol01:24:1:2" 对不上——查表全 miss，
        # 整理本通道一条都不触发（本轮实际踩到，靠比对键样例才发现）。
        labs, ok = label_page(str(page), slots, ctx.book.id, text,
                              _corpus_index(p.corpus))
        if not ok:
            return {"align_ref": PageAlignRef(
                page=page, anchored=False, corpus_fingerprint=p.corpus_fingerprint,
                note="8-gram 锚定失败")}

        chars = [AlignRec(id=lab.instance_id, col=_col_of(lab.instance_id),
                          slot=_slot_of(lab.instance_id), sub=_sub_of(lab.instance_id),
                          align_char=lab.char, align_op=lab.op, ref_run=lab.op_run)
                 for lab in labs]
        return {"align_ref": PageAlignRef(
            page=page, anchored=True, corpus_fingerprint=p.corpus_fingerprint,
            chars=chars)}


def _opt(ctx: RunContext, kind: str, page: int):
    """可选上游：缺了就 None，不炸——OCR 要引擎、上下文要语料，都可能没有。"""
    try:
        return ctx.product(kind, page)
    except Exception:
        return None


def _col_of(instance_id: str) -> int:
    return int(instance_id.split(":")[2])


def _slot_of(instance_id: str) -> int:
    tail = instance_id.split(":")[3]
    sub = tail[-1] if tail[-1:] in ("a", "b") else ""
    return int(tail[:-1] if sub else tail)


def _sub_of(instance_id: str) -> str | None:
    tail = instance_id.split(":")[3]
    sub = tail[-1] if tail[-1:] in ("a", "b") else ""
    return sub or None
