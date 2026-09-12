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
`glyph_match`／`ocr_candidates` 平级；`seed_admit` 改读这个产物；
`gold.v2_align` 的金标派生也改读它（见该模块模块头），`GoldChar{shape,
reading, conversion, source}` 的两个身份（金标 vs 文本证据）从此分开。

## 2026-09-10 去掉对 Step6（`context_decision`）的依赖

此前锚定串优先取 `context_decision` 的定字，只在弃权位才退到库/OCR
top1（`slots_from_decision`，见下方旧版说明）。这让 Step5-d 名义上是
「Step5 四路证据之一」，实际却吃 Step6 的输出，`consumes` 也因此带上
`context_decision`，把它锁死在 `context_decide` 之后——四路本该互相独立、
并行收集证据，Step5-d 却不是。

改成 `slots_from_evidence`：**每个字位只在 `glyph_match` 与
`ocr_candidates` 之间取信度最高的候选**，不碰 Step6：

- `glyph_match` verdict 为 `same` 时用它的 `char`，信度＝`cov`（该档
  ≥0.996，几乎总赢）；
- 否则比较 `glyph_match.candidates[0]` 的 `(char, cov)` 与
  `ocr_candidates.topk[0]` 的 `(char, prob)`，取信度高的那个——两者量纲
  不同（cov 是 kNN 覆盖度，prob 是 OCR softmax），但都落在 [0,1]，这里
  只是拼锚定用的查询串、不是最终定字，量纲不严格对齐不影响锚定质量
  （见下方实测）。

实测 vol01 dev_set（12 页，`exp_align_anchor.py`）：换掉 Step6 依赖后
锚定 **12/12 全部成功**，与旧版（依赖 Step6）持平；p70（生僻字密集、
旧版曾整页锚不上的难页）这里同样能锚上——库/OCR 兜底本身已经够撑起
锚定串，不需要 Step6 的判断再垫一层。

## 编辑距离定位：实测跟现有 n-gram 投票打平，不换

评估过把锚定阶段整体换成「n-gram 投票选出候选簇 → 对候选窗口精确算编辑
距离、取距离最小的」。vol01 12 页实测两者都 12/12 锚定成功；3 页两法选的
偏移差 1 字，逐一验证互有胜负（无一方显著更准）。锚定环节本就只需要**先
用 n-gram 投票圈出几个候选窗口**，n-gram 索引建一次只要 0.12s（345K 字
语料，已缓存），不是全文暴力扫描，所以「先按卷分段减少计算量」在当前
两段式设计下也没有实质收益。综合考虑不引入新依赖（无编辑距离库）、不
增加复杂度，**保留现有 `anchor_page` n-gram 投票 + `difflib` 局部对齐**，
只换了喂给它的查询串来源。

## 指纹要带语料指纹

整理本换了，同一批字位的对齐结果就会变，而代码/参数/上游产物一个都没动——
与 `context_decide`／`glyph_match` 带语料/库指纹是一回事，见那两处模块头。

## 怎么锚（原样照抄，算法一行没改）

复用 `clustering/align_label.label_page`：定字串 → 8-gram 锚到整理本 →
`difflib` 对齐 → **采信闸**（`equal` 段全收；等长 `replace` 段要求段长 ≤3
且左右各有 ≥2 字的 `equal` 段贴身夹住，一侧 ≥2、另一侧 ≥1 即可）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..core.workspace import corpus_path
from ..products.kinds.recog import AlignRec, PageAlignRef, PageMatch, PageOcr
from ..utils.jiazhu_order import sort_by_reading

# ⚠️ 走 `core.workspace.corpus_path`，不要再写死 "corpus/xxx.txt" 这种相对
# 路径字符串——那种写法靠进程 cwd 解析，在 cv 仓根下跑会读到仓内样本、在
# GUJI_WORKSPACE 下跑才读到工作区真语料。两份一度分叉 4680 行却完全无感知
# （2026-09-11 实锤，见 corpus_path 模块头）。
DEFAULT_CORPUS = str(corpus_path("zongmu_wenyuange_wikisource.txt"))


def slots_from_decision(dec, match=None, ocr=None
                       ) -> tuple[list[tuple[int, int, str, str]], dict]:
    """Step6 的 `context_decision`（+ 库/OCR 兜底）→ 金标要的 slots + 溯源表。

    **只给 `gold/v2_align.py` 用**——`GoldChar.shape`（刻本字形金标）要的是
    「管线当前认为这一位是什么字」这个事实本身，Step6 融合了上下文的判断
    天然比单纯库/OCR top1 更准，这里就该用它，跟 `align_ref` 锚定串要不要
    依赖 Step6 是两回事（`align_ref` 2026-09-10 改用 `slots_from_evidence`，
    见模块头）。这个函数留着不删，只是不再喂给锚定。

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


def slots_from_evidence(match, ocr) -> list[tuple[int, int, str, str]]:
    """`glyph_match` + `ocr_candidates` → 对齐要的 slots，不碰 Step6。

    每个字位取两路里信度最高的候选当锚定载体，见模块头「2026-09-10」一节。
    `match` 与 `ocr` 都缺席的字位没有任何候选，跳过（不占位）——这与旧版
    「候选都没有就丢」的口径一致，跳过的位会让后面的字位在锚定串里前移，
    但两路证据都空的位极少见（vol01 dev_set 实测 0 例，见模块头实测数字）。
    """
    mmap = {r.id: r for cc in (match.columns if match else []) for r in cc.chars}
    omap = {r.id: r for cc in (ocr.columns if ocr else []) for r in cc.chars}

    def _best(rid: str) -> str | None:
        m = mmap.get(rid)
        if m and m.verdict == "same" and m.char:
            return m.char
        ch, conf = None, -1.0
        if m and m.candidates:
            ch, conf = m.candidates[0][0], m.candidates[0][1]
        o = omap.get(rid)
        if o and o.topk and o.topk[0][1] > conf:
            ch = o.topk[0][0]
        return ch

    slots: list[tuple[int, int, str, str]] = []
    src = match if match is not None else ocr
    if src is None:
        return slots
    for cc in sorted(src.columns, key=lambda c: c.col):
        if not cc.ok:
            continue
        # ⚠️ **按阅读顺序**，不是 (slot, sub)（2026-09-06 修，同 context_decide）。
        # 夹注 a/b 是两行小字，(slot, sub) 排出来交错成「兩採淮進鹽本政」，
        # 8-gram 锚不上、difflib 还会把邻近正文一起拖进 replace 段。
        for r in sort_by_reading(cc.chars):
            ch = _best(r.id)
            if not ch:
                continue
            slots.append((cc.col, r.slot, r.sub or "", ch))
    return slots


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
        id="align_ref", title="Step5-d 整理本对齐", version="2.0", unit="cell",
        consumes=("glyph_match", "ocr_candidates"),
        produces=("align_ref",),
        params=AlignRefParams,
        needs=("corpus",),
        code_deps=("open_guji_cv.clustering.align_label",
                   "open_guji_cv.utils.jiazhu_order"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: AlignRefParams = ctx.params_for(self)  # type: ignore[assignment]
        match: PageMatch | None = _opt(ctx, "glyph_match", page)
        ocr: PageOcr | None = _opt(ctx, "ocr_candidates", page)
        if match is None and ocr is None:
            return {"align_ref": PageAlignRef(
                page=page, anchored=False, corpus_fingerprint=p.corpus_fingerprint,
                note="没有库匹配或 OCR 候选产物")}
        if not p.corpus:
            return {"align_ref": PageAlignRef(
                page=page, anchored=False, corpus_fingerprint=p.corpus_fingerprint,
                note="未配置整理本")}
        text = _corpus_text(p.corpus)
        if not text:
            return {"align_ref": PageAlignRef(
                page=page, anchored=False, corpus_fingerprint=p.corpus_fingerprint,
                note="整理本读不到")}
        slots = slots_from_evidence(match, ocr)
        if len(slots) < 12:
            return {"align_ref": PageAlignRef(
                page=page, anchored=False, corpus_fingerprint=p.corpus_fingerprint,
                note=f"候选太少（{len(slots)}），锚不住")}

        from ..clustering.align_label import label_page
        # ⚠️ book 必须传真名：`label_page` 拼的是 `book:page:col:idx`，传空字符串
        # 会得到 ":24:1:2" 这种键，与产物的 "vol01:24:1:2" 对不上——查表全 miss，
        # 整理本通道一条都不触发（本轮实际踩到，靠比对键样例才发现）。
        labs, ok = label_page(str(page), slots, ctx.book.id, text,
                              _corpus_index(p.corpus))
        if not ok:
            # label_page 内部已经跑过一次 anchor_page，这里为了拿判据明细
            # 重算一次 anchor_page_diag——多一次 8-gram 投票，索引已缓存，
            # 只在锚定失败这条本就罕见的路径上多花这一点，换来的是不用再
            # 像本次一样临时写脚本复算才知道卡在票数还是占比/优势上。
            from ..clustering.align_eval import anchor_page_diag
            query = "".join(t[-1] for t in slots)
            diag = anchor_page_diag(query, _corpus_index(p.corpus))
            return {"align_ref": PageAlignRef(
                page=page, anchored=False, corpus_fingerprint=p.corpus_fingerprint,
                note=f"8-gram 锚定失败：{diag.reason}" if diag.reason else "8-gram 锚定失败",
                n_grams=diag.n_grams, n_votes=diag.n_votes,
                vote_frac=diag.vote_frac, dominance=diag.dominance)}

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


def align_ref_summary(book_id: str, pages: list[int] | None = None,
                      store=None) -> dict:
    """逐页汇总 `align_ref` 的锚定情况——控制台 5-d 面板/人工排查用，不用
    再像本次一样临时写脚本复算判据卡在哪。风格照抄 `gates.query.gate_summary`，
    但不进 `GATES` 表：`align_ref` 不是闸（不拦截，四路证据里任一路缺席只
    降级不阻塞，见 `Step5-字符识别/README.md`），是证据可用性上报。
    """
    from ..core.book import load_book
    from ..core.spec import page_key
    from ..products.store import ProductStore

    store = store or ProductStore()
    book = load_book(book_id)
    pages = pages if pages is not None else book.all_pages()
    rows: list[dict] = []
    n_anchored = 0
    for pg in pages:
        ar: PageAlignRef | None = store.read(book_id, "align_ref", page_key(pg), "align_ref")
        if ar is None:
            rows.append({"page": pg, "status": "missing"})
            continue
        if ar.anchored:
            n_anchored += 1
            rows.append({"page": pg, "status": "anchored", "n_chars": len(ar.chars)})
            continue
        rows.append({
            "page": pg, "status": "not_anchored", "note": ar.note,
            "n_grams": ar.n_grams, "n_votes": ar.n_votes,
            "vote_frac": ar.vote_frac, "dominance": ar.dominance,
        })
    n_pages = len(rows)
    n_missing = sum(1 for r in rows if r["status"] == "missing")
    return {
        "pages": rows,
        "n_pages": n_pages, "n_anchored": n_anchored, "n_missing": n_missing,
        "n_not_anchored": n_pages - n_anchored - n_missing,
    }
