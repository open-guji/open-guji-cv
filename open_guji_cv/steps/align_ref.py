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

## 2026-09-22 replace 段加「库证据闸」（任务卡 T7；图像代价闸是负结果）

T7 原想把长度闸换成「图像代价闸」（字块 embedding 与整理本字模板的余弦 ⊕ IDS 距离）。
在四库两册 270 页、1,910 个等长 replace 位、513 条用户 confirm 上量（`scripts/eval_align_replace_gate.py`，
载体串只用 `glyph_match`、云端没装 OCR）：

| 闸 | 采信率 | 人裁错采 | 漏采 |
|---|---|---|---|
| 长度闸（现役） | 97.5% | 19/491 = 3.9% | 22/494 |
| 余弦 / 模板名次 / cos_top1 差，各档 | 96–100% | **19，一个都分不开** | 22 |
| 长度闸 ∧（异体 ∨ 库 cov < 0.996）——本闸 | 94.7% | **5/476 = 1.1%** | 23/494 |

余弦对均值模板普遍 ≥0.94、错采位的 cos_gold 反而常高于 cos_hyp，形近字对在全局相似度下
分不开（老负结果 g3g4 §核心）。真能分开的是**库证据**：19 个错采里 14 个是
「库以 cov ≥0.999 认下了这一格是 X，整理本给的既不是 X 也不是 X 的异体」——入/人、筍/笱、
艮/良、矩/炬、壁/璧、諭/論、日/曰、祟/崇、睽/暌、塵/麈……人裁全站在刻本这边。这是整理本
与刻本的**真实差异**（版本差 / 整理本错），不是对齐错位，不该拿整理本盖掉刻本。
剩 5 个是乱区里 len=2 段两头都对错位（思愚/汝、夏蔓/枝），载体错、gold 也错、人裁是第三个字，
库 cov 只有 0.93–0.95，任何闸都拦不住，只能靠 Step6 上下文。

于是 replace 位再过一道：`glyph_match` 对这一格的 cov ≥ `lib_cov_min`（0.996，与库 same 档
门槛同口径；0.995~0.999 之间数字一样）且库认的字与 gold 不是异体（`variants.are_variants`），
就不采信这一位。「异体」这一档必须放行：巳/已、郎/郞、宮/宫、寬/寛 这类库 cov 也 ≥0.999，
但整理本给的是正字，采信没错（人裁 66/66 全对）。
不限段长（只要夹住）在 8 个 4 字段上 8/8 对、0 错采，但样本太薄，长度闸照旧。

## 多证人合并：现状是什么（2026-09-27，任务书 D-多证人对齐策略）

`BookSpec.references` 的字段注释写着「`quality` 用于多证人不一致时加权，不是简单
多数」——**这是意愿，不是实现**。真正在跑的 `book_corpus()` 只有一行数：

    refs = load_book(book).references
    if refs and refs[0].get("file"): return corpus_path(refs[0]["file"])

只取**列表第 0 项**，从不看 `quality`。`align_ref` 全程只吃这一份 `corpus`，
`slots_from_evidence`/`label_page`/`lib_gate` 都只在这一份语料上跑。换句话说，
「多证人」目前只存在于 `books/<id>.yaml` 的注释与 `report/witness.py`（Step9-9.3
对勘用）里，**Step5-d 的锚定/放行这一路完全没有多证人合并**——`references` 列了
几家、哪家标 `best`，对 `align_ref` 的产出没有任何影响，唯一起作用的是「谁排第一个」。

Z5 全唐文 v003 实测正是这个原因：`references` 里 Kanripo 排第一（标 `best`）、
维基排第二（标 `mid`），"组合"跑出来的自动放行率／锚定率与"仅 Kanripo"逐字节
相同（65.76%／24.43%）；而"仅维基"反而更高（69.38%／36.64%）——因为 Kanripo
底本把刻本的「爲」统一录成「為」，这类系统性差异被 `difflib` 判成 `replace`，
拉低了整段 margin，而 `align_ref` 从来没机会用到维基那份更贴合刻本用字的证人。

`witness_strategy` 参数（见 `AlignRefParams`）把「归一再比」「多证人表决」接进来，
缺省仍是 `"legacy"`（行为与加这个参数之前逐字节相同）；三种策略的实测数字见
overview 仓 `进度/inbox/D-多证人/` 的 done 单。

## 2026-09-28 5-b 候选并入锚定载体（D 道，overview#126）

`rare_candidates`（Step5-b）此前下游一个都不读。借库书上库（像素）首位在难例上
只对 52%，5-b／CNN 首位对 94%（R 道 #86），锚定串因此错字连篇、8-gram 连续对上
的太少。`AlignRefParams.rare_topk > 0` 时，库判 `same` 以外的位，载体从「库首位」
换成「库候选 ∪ 5-b 前 k 名」RRF 融合首位（`rrf_carrier`，同分 5-b 赢）；`same` 位、
OCR 比较、锚定与采信闸一概不动。缺省 0 = 关：不读 5-b、不进指纹
（`StepSpec.optional_consumes_when`）、不进参数哈希。

实测（沙箱，k=5；`scripts/experiments/rare_downstream/`）：

| | 锚定页 | 待审率 |
|---|---|---|
| 全唐文 v006（借四庫库，86 页，`use_context:false`） | 61 → **72** | 38.7% → 28.6% |
| 四庫 vol03（107 页） | 101 → 101 | 3.72% → 3.75% |

v006 新锚上的 11 页照旧走现有通道放行；人裁难例里新放出 121 格，严格口径错 10 格：
8 格是 `match_margin` 放了整理本的「為」而刻本是「爲」（关开关时这条通道在已锚页上
同样放了 23 格「為」，是通道本身的字形问题，不是本改动引入的），2 格「乎/平」是库与
整理本都给「乎」、人裁「平」。vol03 上载体变化只让 128 格在 `match_ref`/`match_replace`
之间改名（equal↔replace），放出格与光盘版的字面差异 130 → 129。
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, model_serializer

from ..clustering.align_eval import GRAM, WINDOW_PAD
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


def book_corpus(book: str) -> str:
    """这册书的整理本语料路径：`books/<id>.yaml` 的 `references[0].file`。

    2026-09-15 加。此前几处直接用 `DEFAULT_CORPUS`（刻本链那份总目语料），
    换一本书就指向一个不存在的文件——北行日錄的生僻字面板因此整个 500，
    Step6 的 n-gram 也悄悄退化成「只有两份泛古籍语料」（`人` 比 `入` 常见，
    于是每个「入」都判成「人」）。查不到就退回 `DEFAULT_CORPUS`，行为不变。
    """
    try:
        from ..core.book import load_book
        refs = load_book(book).references
        if refs and refs[0].get("file"):
            p = corpus_path(str(refs[0]["file"]))
            if Path(p).exists():
                return str(p)
    except Exception:
        pass
    return DEFAULT_CORPUS


def _with_book_corpus(p, ctx):
    """**已搬到 `core.step`**（2026-09-21），这里只转发，保持旧调用点可用。

    搬家的理由：原先它只在 `run_page` 里调，而 `Engine.fingerprint()` 拿到的是
    **没换过语料**的参数——两边算出不同的 `corpus_fingerprint`，于是 `align_ref` /
    `context_decide` 永远判过期、跑多少次都洗不掉。现在换语料发生在
    `RunContext.params_for()`，指纹与 run_page 必然拿到同一份。

    `AlignRefParams.corpus` 的缺省值是 `DEFAULT_CORPUS`（四庫總目那份语料），
    而参数是在**不知道是哪本书**的时候构造的（`StepSpec.params()` 不带 ctx），
    于是换一本书就拿总目语料去锚它——北行日錄实测 `book_corpus()` 指向
    `beixingrilu_jiaoduiben.txt`，而缺省指向工作区里根本不存在的
    `zongmu_wenyuange_wikisource.txt`。

    **只在「用的还是缺省值」时替换**：显式传了 `--params` 的照用不误。
    """
    from ..core.step import _with_book_corpus as _impl
    return _impl(p, ctx)


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


def rare_topk_map(rare, k: int) -> dict[str, list[str]]:
    """`rare_candidates`（Step5-b）产物 → {字位 id: 前 k 个候选字（按 5-b 融合名次，去重）}。

    **只用名次、不用分数**：5-b 候选的 `score` 按来源各是各的量纲（`emb` 是余弦
    ~0.99、`cnn` 分类头是概率、字体模板又是另一种），同一张列表里不可比，只有
    融合后的先后顺序有意义（`clustering.rare_panel.rare_for_batch`）。
    `rare` 为 None 或 `k <= 0` → 空表（下游按「这一路没有」跑）。
    """
    if rare is None or k <= 0:
        return {}
    out: dict[str, list[str]] = {}
    for cc in rare.columns:
        for r in cc.chars:
            seen: list[str] = []
            for c in r.candidates:
                if c.char and c.char not in seen:
                    seen.append(c.char)
                if len(seen) >= k:
                    break
            if seen:
                out[r.id] = seen
    return out


def rrf_carrier(pixel: list, cnn: list[str], k: int = 60) -> str | None:
    """库候选（`[(字, cov), …]`，按 cov 降序）与 5-b 候选（按名次）做 RRF 取首位。
    同分时 5-b 名次靠前的赢（R 道实测借库书上 CNN 首位几乎严格优于像素首位）。
    同一口径见 `review.borrow_first.rrf_fuse`；这里只要首位字，不引那个模块（它带
    库原型索引与 torch 依赖）。"""
    rp: dict[str, int] = {}
    for i, (ch, _s) in enumerate(pixel or []):
        rp.setdefault(ch, i + 1)
    rc: dict[str, int] = {}
    for i, ch in enumerate(cnn or []):
        rc.setdefault(ch, i + 1)
    if not rp and not rc:
        return None
    big = 10 ** 6

    def score(ch: str) -> float:
        return (1.0 / (k + rp[ch]) if ch in rp else 0.0) + (1.0 / (k + rc[ch]) if ch in rc else 0.0)
    return min((*rp, *rc), key=lambda ch: (-score(ch), rc.get(ch, big), rp.get(ch, big)))


def carrier_fn(match, ocr, rare: dict[str, list[str]] | None = None):
    """字位 id → 锚定载体字（`slots_from_evidence` 的逐位取字规则，单独拿出来给
    坐标对位 `align_ref_coord` 复用；规则见 `slots_from_evidence` 文档字符串）。"""
    mmap = {r.id: r for cc in (match.columns if match else []) for r in cc.chars}
    omap = {r.id: r for cc in (ocr.columns if ocr else []) for r in cc.chars}
    rare = rare or {}

    def _best(rid: str) -> str | None:
        m = mmap.get(rid)
        if m and m.verdict == "same" and m.char:
            return m.char
        ch, conf = None, -1.0
        if m and m.candidates:
            ch, conf = m.candidates[0][0], m.candidates[0][1]
        rc = rare.get(rid)
        if rc:
            ch = rrf_carrier(list(m.candidates) if m else [], rc)
        o = omap.get(rid)
        if o and o.topk and o.topk[0][1] > conf:
            ch = o.topk[0][0]
        return ch
    return _best


def slots_from_evidence(match, ocr, rare: dict[str, list[str]] | None = None
                        ) -> list[tuple[int, int, str, str]]:
    """`glyph_match` + `ocr_candidates`（+ 可选 `rare_candidates`）→ 对齐要的 slots，不碰 Step6。

    每个字位取两路里信度最高的候选当锚定载体，见模块头「2026-09-10」一节。
    `match` 与 `ocr` 都缺席的字位没有任何候选，跳过（不占位）——这与旧版
    「候选都没有就丢」的口径一致，跳过的位会让后面的字位在锚定串里前移，
    但两路证据都空的位极少见（vol01 dev_set 实测 0 例，见模块头实测数字）。

    `rare`（`rare_topk_map` 的输出，`AlignRefParams.rare_topk` 开了才给）：库判
    `same` 以外的位，库那一路的首选换成「库候选 ∪ 5-b 前 k 名」RRF 融合的首位
    （`rrf_carrier`），OCR 比较照旧。见模块头「2026-09-28 5-b 候选并入锚定载体」。
    `rare` 为空时与加这个参数之前逐位相同。
    """
    _best = carrier_fn(match, ocr, rare)

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
    lib_gate: bool = True
    """replace 位的库证据闸（模块头 2026-09-22）：库高信度认下的字与整理本字不是异体 → 不采信。"""
    lib_cov_min: float = 0.996
    """库证据闸的 cov 门槛，与 `glyph_match` same 档同口径。"""
    witness_strategy: str = "legacy"
    """多证人合并策略（2026-09-27，任务书 D-多证人对齐策略；见模块头「多证人合并」一节）：

    - ``"legacy"``（默认，开关缺省关）：`book_corpus()` 只取 `references[0]`——
      **不管 quality 标签，只看列表里排第几个**。这是现状，也是 Z5 全唐文实测
      「Kanripo(best)+维基(mid) 组合」与「仅 Kanripo」逐字节相同的根源：维基那份
      从没被读过，`references` 列表顺序偶然与 quality 排序一致时才不出事。
    - ``"normalize"``：只用一家证人（按 `quality` 排序取最高的，不再依赖列表顺序），
      但锚定/对齐前先过异体字语义表归一（`VariantMap.normalize_text`）——
      「爲/為」这类系统性版本差不再被判成 `replace`，取字仍是证人原文的字形
      （归一只影响判等/判异，不影响最终写进 `align_char` 的字）。
    - ``"majority_vote"``：`references` 每家证人各自跑一次锚定 + `difflib`
      （原始字形比较，不歸一），逐字位在锚定成功的证人里按 `quality` 加权
      多数表决；只有一家覆盖的字位直接用它，别的证人在这一位缺席不算票。
    """
    witness_fingerprint: str = ""
    """多证人策略用的证人文件指纹，`witness_strategy != "legacy"` 才填——
    legacy 只有单一 `corpus`，继续用 `corpus_fingerprint`。留空自动填，见
    `core/step.py::_with_witness_fingerprint`（同 `corpus_fingerprint` 的道理：
    `model_post_init` 造实例时不知道是哪本书，只能留空，`params_for` 里补）。"""

    uncontested_relax: bool = False
    """低票兜底（2026-09-27，任务卡 D-align_ref锚定召回-全唐文）：`label_page`
    走正常 n-gram 投票锚不上时，只在**没有任何竞争簇**（真实 runner_up == 0，
    不是 `anchor_page_diag` 早退时的占位 0——它在 `n_votes < MIN_VOTES` 就直接
    返回，从没算过真正的次高票簇）的前提下，改用候选窗口的 difflib 命中率
    兜底：命中率达标就仍然收下这个锚点，字符级仍过 `align_label.label_page`
    同一套 `replace_len_gate`（段长 ≤3 且被 equal 夹住），不会因为兜底而放松
    单字采信。

    ## 根因：v006 实测证明这类失败多是「连续 8 字全对太难」，不是「套语碰撞」

    整理 Z15（cross `整理Z15-align_ref套语文体`）报告全唐文 v006 16-18 页正文
    锚不住，**猜测**是诏令/制书体裁骈俪套语多、同一 8-gram 在语料里多处命中、
    票被摊薄（"套语碰撞"）。本卡在 v006 全书 86 页上实测（`glyph-db rebuild
    --store <四庫真库>` 借四庫库、Kanripo 语料，见
    `scripts/experiments/align_anchor_recall/diagnose_v006.py`）：14 个
    「最高票簇 1-4 票，低于绝对下限 5」失败页里，**12 个 `avg_hits_per_hit_gram`
    ≈1、`n_clusters`==1**（唯一命中的极少数 8-gram 各自在语料里只出现一次，
    彼此又聚成同一个偏移簇，没有第二个候选位置）——这与"套语碰撞"的特征
    （同一 8-gram 到处出现、多个候选簇势均力敌）正相反：**多数 8-gram 根本
    没命中任何位置**（如 p16 171 个 gram 只有 2 个命中、p30 169 个只有 1 个），
    是刻本侧字串本身噪声大（借四庫库对全唐文这类新书字形覆盖不足，逐字位
    top1 常错），连续 8 字全部对上本来就难，不是内容被别处摊薄。10 个候选页
    (p3/4/6/11/16/30/36/38/54/64) 目视核对候选窗口与整理本，字面逐句连贯、
    差异全是形近字混淆（今/令、泰/秦、玉/王、流/涼……），确认是正确锚点；
    另外 2 个「1-4 票」页（p2/61）与 1 个「占比/优势不达标」页（p67）**真的有
    竞争簇**（`runner_up` 分别 1/1/8），本判据的 `runner_up == 0` 闸天然把它们
    挡在外面，不会误收。v006 实测：67/86 → 77/86（新增 10 页），旧锚定页
    （offset 已确定的那部分）逐页不变——见 done 单核验数字。

    只对 `witness_strategy == "legacy"` 生效；多证人路径另有自己的失败报告，
    不叠加这条（保持两条路径互不纠缠，同 `witness_strategy` 模块头的原则）。
    默认关，不改变现有行为。
    """
    uncontested_min_votes: int = 1
    """低票兜底生效的最低票数——低于它（即真的一票命中都没有）不兜底，
    防止把候选太少/语料未命中的页也拉进来（那类页应该继续报「候选太少」/
    「一个 n-gram 都没命中」，不该被这条参数掩盖）。"""
    uncontested_min_equal_frac: float = 0.5
    """低票兜底的候选窗口 difflib 命中率门槛。v006 实测：10 个确认应收的
    低票页命中率落在 0.58~0.82；门槛设在明显低于这个区间的 0.5，留安全边界。
    未观测到假阳性样本落进 [0.5, 0.58) 这一段，样本量不大，口径偏保守。"""

    rare_topk: int = 0
    """5-b 生僻字候选并入锚定载体（2026-09-28，D 道 overview#126）：取 `rare_candidates`
    前几名。**0 = 关（缺省）**——不读 5-b、不进指纹（`optional_consumes_when`）、
    也不进参数哈希（见 `_drop_off_rare`），四庫等书产物与加这个字段之前逐字节相同。
    书 yaml `params: {align_ref: {rare_topk: 5}}` 打开。实测见模块头同日一节。"""

    coord: str = "auto"
    """按坐标对位（2026-09-28，D 道 overview#195；见 `steps/align_ref_coord` 模块头）。

    - ``"auto"``（缺省）：整理本是**逐列分行**的才做——书 yaml `references[0]` 标了
      `line_is_column: true`，或语料本身 ≥95% 的非空行字位数不超过每列格数
      （`chars_per_line`，+1 容抬头）。四庫光盘版满足（一行 = 刻本一列），北行日錄
      校對本、全唐文这类整段录入的整理本不满足，自动不做。
    - ``"on"`` / ``"off"``：强制。

    结果另记在 `PageAlignRef.coord`，**不改现役 `chars`、不进任何准入通道**。"""

    @model_serializer(mode="wrap")
    def _drop_off_rare(self, handler):
        """`rare_topk == 0` 时不进 dump：没开的书 `params_hash` 与加字段前逐位相同。"""
        d = handler(self)
        if isinstance(d, dict) and not self.rare_topk:
            d.pop("rare_topk", None)
        return d

    def model_post_init(self, _ctx) -> None:
        if not self.corpus_fingerprint:
            from .context_decide import corpus_fingerprint
            object.__setattr__(self, "corpus_fingerprint",
                               corpus_fingerprint([self.corpus]))


#: 锚定载体是**刻本字位**：没有标点、没有整理者补的注记。语料这一侧必须同样
#: 只留汉字，否则 8-gram 永远对不上——`真定在春秋時屬鮮虞國` 在原文里是
#: `……行者。真定在春秋時屬鮮虞國，爲晉所滅。` 中间夹着句读。
#: 四庫總目那份语料标点密度 0.000（几乎没有标点），所以这条一直没暴露；
#: 北行日錄校對本是 0.215，7/7 页全部锚定失败（"语料里一个 n-gram 都没命中"）。
_NON_HAN_RE = re.compile(r"[^一-鿿]")


@lru_cache(maxsize=4)
def _corpus_text(path: str) -> str:
    """语料 → **只留汉字**的一维字流。

    ⚠️ 必须与 `_corpus_index` 用同一个字符串：`label_page` 拿 `anchor_page` 给的
    偏移去切 `corpus[lo:hi]` 当窗口，文本与索引不同源的话偏移就错位了。
    两者都走本函数（本函数带 lru_cache），保证同源。
    """
    p = Path(path)
    if not p.exists():
        return ""
    return _NON_HAN_RE.sub("", p.read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def _corpus_index(path: str):
    from ..clustering.align_label import build_ngram_index
    return build_ngram_index(_corpus_text(path))


@register_step
class AlignRefStep(Step):
    spec = StepSpec(
        id="align_ref", title="Step5-d 整理本对齐", version="2.1", unit="cell",   # 2.1：按坐标对位 coord（overview#195）
        consumes=("glyph_match",), optional_consumes=("ocr_candidates", "rare_candidates", "cells"),
        optional_consumes_when=(("rare_candidates", "rare_topk"),),
        produces=("align_ref",),
        params=AlignRefParams,
        needs=("corpus",),
        code_deps=("open_guji_cv.clustering.align_label",
                   "open_guji_cv.utils.jiazhu_order",
                   # 2026-09-27 加（任务书 D-多证人对齐策略）：非 legacy 策略还吃这两个
                   # 模块的算法——`report.witness` 装载证人/排序，`clustering.variants`
                   # 提供归一表。改了它们，`align_ref` 的非 legacy 产物也该判过期。
                   "open_guji_cv.report.witness",
                   "open_guji_cv.clustering.variants",
                   "open_guji_cv.steps.align_ref_coord"),
        # `corpus` 缺省是仓内绝对路径（2026-09-29 K238），内容由 `corpus_fingerprint` 把关。
        path_params=("corpus",),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: AlignRefParams = ctx.params_for(self)  # type: ignore[assignment]
        p = _with_book_corpus(p, ctx)
        match: PageMatch | None = _opt(ctx, "glyph_match", page)
        ocr: PageOcr | None = _opt(ctx, "ocr_candidates", page)
        rare = (rare_topk_map(_opt(ctx, "rare_candidates", page), p.rare_topk)
                if p.rare_topk else None)
        out = self._run_legacy(ctx, p, page, match, ocr, rare)
        if _coord_enabled(p, ctx.book) and match is not None:
            attach_coord(out["align_ref"], ctx.book.id, page, match, ocr, rare,
                         _opt(ctx, "cells", page), p.corpus)
        return out

    def _run_legacy(self, ctx: RunContext, p: "AlignRefParams", page: int,
                    match: PageMatch | None, ocr: PageOcr | None,
                    rare: dict | None) -> dict[str, BaseModel]:
        """8-gram 锚定 + difflib 的现役对位（2026-09-28 从 `run_page` 原样拆出，
        一行没改，坐标对位在 `run_page` 里接在它后面）。"""
        if match is None and ocr is None:
            return {"align_ref": PageAlignRef(
                page=page, anchored=False, corpus_fingerprint=p.corpus_fingerprint,
                note="没有库匹配或 OCR 候选产物")}
        if p.witness_strategy != "legacy":
            # 多证人策略走独立函数，自己算 slots/门槛——**不动 legacy 分支
            # 原有的检查顺序**（下面 corpus/text/slots 三条判据的先后次序，
            # 换了就会在多条同时失败时改变报出来的 note，是可观测的行为变化）。
            return {"align_ref": _run_multi_witness(ctx, p, page, match, ocr, rare)}
        if not p.corpus:
            return {"align_ref": PageAlignRef(
                page=page, anchored=False, corpus_fingerprint=p.corpus_fingerprint,
                note="未配置整理本")}
        text = _corpus_text(p.corpus)
        if not text:
            return {"align_ref": PageAlignRef(
                page=page, anchored=False, corpus_fingerprint=p.corpus_fingerprint,
                note="整理本读不到")}
        slots = slots_from_evidence(match, ocr, rare)
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
        anchor_via = "ngram"
        if not ok and p.uncontested_relax:
            alt = _uncontested_fallback(ctx.book.id, page, slots, text,
                                        _corpus_index(p.corpus), p)
            if alt:
                labs, ok, anchor_via = alt, True, "uncontested"
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

        n_dropped = 0
        if p.lib_gate and match is not None:
            labs, n_dropped = lib_gate(labs, match, p.lib_cov_min)
        chars = [AlignRec(id=lab.instance_id, col=_col_of(lab.instance_id),
                          slot=_slot_of(lab.instance_id), sub=_sub_of(lab.instance_id),
                          align_char=lab.char, align_op=lab.op, ref_run=lab.op_run)
                 for lab in labs]
        return {"align_ref": PageAlignRef(
            page=page, anchored=True, corpus_fingerprint=p.corpus_fingerprint,
            chars=chars, n_lib_dropped=n_dropped, anchor_via=anchor_via)}


def _raw_vote_clusters(text: str, index: dict[str, list[int]],
                       gram: int = GRAM) -> tuple[int | None, int, int]:
    """`align_eval.anchor_page_diag` 同一套投票核心，但不套 `MIN_VOTES` 提前
    返回——`AlignRefParams.uncontested_relax` 要看真实的次高票簇，
    `anchor_page_diag` 在 `n_votes < MIN_VOTES` 时直接返回 `runner_up=0`，
    那是占位值不是真算出来的（见该函数），不能拿来判「有没有竞争簇」。

    刻意不改 `anchor_page_diag` 本身——它是 `anchor_page`/`align_label`／
    `gold` 等一大票调用方共用的锚定核心，这里只加一个新的独立函数，
    `uncontested_relax` 缺省关时这个函数从不会被调用，零行为变化。

    返回 `(peak_offset, peak_votes, runner_up_votes)`；没有任何命中时
    `(None, 0, 0)`。
    """
    from collections import Counter

    from ..clustering.align_eval import POOL_RADIUS, index_lookup
    if len(text) < gram:
        return None, 0, 0
    votes: Counter[int] = Counter()
    n_grams = len(text) - gram + 1
    for i in range(n_grams):
        for pos in index_lookup(index, text[i:i + gram]):
            votes[pos - i] += 1
    if not votes:
        return None, 0, 0
    peak = votes.most_common(1)[0][0]
    near = [o for o in votes if abs(o - peak) <= POOL_RADIUS]
    peak_votes = sum(votes[o] for o in near)
    rest = {o: v for o, v in votes.items() if abs(o - peak) > POOL_RADIUS}
    runner_up = 0
    if rest:
        peak2 = max(rest, key=rest.get)
        runner_up = sum(v for o, v in rest.items() if abs(o - peak2) <= POOL_RADIUS)
    return min(near), peak_votes, runner_up


def _uncontested_fallback(book: str, page: int, slots: list[tuple], corpus: str,
                          index: dict[str, list[int]], p: "AlignRefParams",
                          ) -> list | None:
    """`AlignRefParams.uncontested_relax` 的兜底路径（模块头「低票兜底」一节）。

    只在**没有竞争簇**（`runner_up == 0`）且票数达到 `uncontested_min_votes`
    时才去算 difflib 命中率；命中率达标才收，否则 `None`（调用方退回原有的
    失败报告，不吞掉任何诊断信息）。返回的标签仍过
    `align_label.label_page` 同一套 `replace_len_gate`（`_labels_from_ops`
    直接复用，规则一字不改）。
    """
    import difflib

    norm = _norm_slots(slots)
    query = "".join(t[-1] for t in norm)
    offset, peak_votes, runner_up = _raw_vote_clusters(query, index)
    if offset is None or runner_up != 0 or peak_votes < p.uncontested_min_votes:
        return None
    lo = max(0, offset)
    hi = min(len(corpus), offset + len(query) + WINDOW_PAD)
    window = corpus[lo:hi].replace("\n", "")  # 同 `align_label.align_ops`：清洗语料换行
    sm = difflib.SequenceMatcher(None, query, window, autojunk=False)
    equal = sum(b.size for b in sm.get_matching_blocks())
    if not query or equal / len(query) < p.uncontested_min_equal_frac:
        return None
    labs = _labels_from_ops(book, page, norm, sm.get_opcodes(), window)
    return labs or None


def _refs_key(refs: list[dict]) -> tuple:
    """`book.references`（`list[dict]`，不可哈希）→ 按内容去重的可哈希键，
    供 `_witnesses_for_book` 缓存——同 `_corpus_text`/`_corpus_index` 的道理，
    避免每页都重读一遍语料、重建两套 ngram 索引（270 万字级语料实测单页
    要花 5~6 秒，12 页跑批里页页都花这个钱）。

    ⚠️ `file` 必须换成 `corpus_path()` 解析后的**绝对路径**再进键，不能留
    裸文件名：控制台一个进程同时服务多个标签页、各自 `GUJI_WORKSPACE` 不同
    （`core.workspace._WORKSPACE_OVERRIDE`），四庫十册的 `references` 又几乎
    都写同一批文件名——裸文件名当键会让不同工作区的证人在缓存里互相串号，
    与 `_corpus_text`/`_corpus_index` 按（已解析）路径缓存是同一个道理，只是
    那两个函数的调用方本来就只传解析过的路径，这里的输入是 yaml 里的裸名，
    必须自己先解析。（缓存按路径不按内容——同一路径中途换内容不会失效，
    这点与 `_corpus_text` 等价，不是新引入的限制。）
    """
    resolved = []
    for r in (refs or []):
        item = dict(r)
        if item.get("file"):
            item["file"] = str(corpus_path(item["file"]))
        resolved.append(tuple(sorted(item.items())))
    return tuple(resolved)


@lru_cache(maxsize=8)
def _witnesses_for_book_cached(refs_key: tuple) -> tuple:
    from ..report.witness import load_witnesses
    specs = [dict(items) for items in refs_key]
    return tuple(load_witnesses(specs))


def _witnesses_for_book(book) -> list:
    """`book.references` → 按 `quality` 排序的证人列表（复用 `report.witness.load_witnesses`，
    最高质量在前）。空 `references` 时退回单一默认证人（光盘版），与 legacy 的
    `DEFAULT_CORPUS` 是同一份文件。结果按 `references` 内容缓存，见 `_refs_key`。"""
    return list(_witnesses_for_book_cached(_refs_key(book.references)))


@lru_cache(maxsize=8)
def _witness_norm_index(text_norm: str):
    """证人归一文本的 ngram 索引，按内容缓存——同 `_corpus_index` 的道理，
    避免每页都重建一次（270 万字级语料重建一次要花得上秒级）。"""
    from ..clustering.align_eval import build_ngram_index
    return build_ngram_index(text_norm)


def _norm_slots(slots: list[tuple]) -> list[tuple]:
    """`(col, slot, [sub,] char)` → `(col, slot, sub, char)`，与
    `clustering.align_label.align_ops` 的 `norm` 构造逐字相同（一处逻辑两份
    必须一致，否则多证人策略与 legacy 对「这一批字位是什么」的理解会岔开）。"""
    return [(t[0], t[1], (t[2] or "") if len(t) > 3 else "", t[-1]) for t in slots]


def _witness_align(query: str, w, *, normalize: bool, window_pad: int = WINDOW_PAD):
    """单个证人上锚定 + `difflib`（模块头「多证人合并」一节）。

    `normalize=True`：锚定与对齐都在异体归一字符流（`VariantMap.normalize_text`）
    上比——它是逐字映射、不改变长度，位置与证人原文一一对应，所以取字仍从
    `w.text`（原文）切，不会把归一目标字写进 `align_char`。`normalize=False`
    就是 legacy 那套原始字形比较，只是换了证人来源（`majority_vote` 用这个，
    避免把「多证人」和「归一比较」两个变量搅在一起，三种策略才能分开验收）。

    返回 `(result, diag)`：`result` 是 `(ops, window_original, offset)` 或
    `None`（锚不上，看 `diag` 判据明细）。
    """
    import difflib

    from ..clustering.align_eval import anchor_page_diag
    if normalize:
        from ..clustering.variants import VariantMap
        q = VariantMap.load().normalize_text(query)
        base_cmp = w.text_norm
        index = _witness_norm_index(base_cmp)
    else:
        q = query
        base_cmp = w.text
        index = w.index
    diag = anchor_page_diag(q, index)
    if diag.offset is None:
        return None, diag
    lo = max(0, diag.offset)
    hi = min(len(base_cmp), diag.offset + len(q) + window_pad)
    window_cmp = base_cmp[lo:hi]
    sm = difflib.SequenceMatcher(None, q, window_cmp, autojunk=False)
    window_original = w.text[lo:hi]
    return (sm.get_opcodes(), window_original, diag.offset), diag


def _labels_from_ops(book: str, page: int, norm: list[tuple], ops: list[tuple],
                     window: str) -> list:
    """`align_label.label_page` 同一段过闸逻辑（`equal` 全收；等长 `replace`
    段长 ≤3 且被 `equal` 夹住才收，见 `align_label.replace_len_gate`）搬来给
    多证人策略复用——规则一字不改，只是输入换成某个证人自己的 `ops`/`window`。
    返回 `AlignedLabel` 列表，字段与 legacy 路径完全一致，下游（`lib_gate`／
    `AlignRec` 转换）不用区分策略。"""
    from ..clustering.align_label import AlignedLabel, replace_len_gate
    out = []
    for n, (tag, i1, i2, j1, j2) in enumerate(ops):
        if tag == "equal":
            pass
        elif tag == "replace" and (i2 - i1) == (j2 - j1):
            if not replace_len_gate(ops, n):
                continue
        else:
            continue
        for k in range(i2 - i1):
            col, idx, sub, hyp = norm[i1 + k]
            gold = window[j1 + k]
            out.append(AlignedLabel(f"{book}:{page}:{col}:{idx}{sub}", str(page),
                                    gold, hyp, tag, i2 - i1))
    return out


def _majority_vote_labels(book: str, page: int, norm: list[tuple], query: str,
                          witnesses: list) -> list | None:
    """`references` 每家证人各自锚定 + 过闸（原始字形比较，`normalize=False`），
    逐字位在锚定成功的证人里按 `quality` 加权多数表决；只有一家覆盖的字位
    直接用它，别的证人在这一位缺席不算票。返回 `None` 表示没有任何一家证人
    锚上这一页——`_run_multi_witness` 据此报「未锚定」。
    """
    from collections import Counter, defaultdict

    per_slot: dict[tuple, list[tuple]] = defaultdict(list)   # (col, tail) -> [(lab, rank), ...]
    any_anchored = False
    for w in witnesses:
        result, _diag = _witness_align(query, w, normalize=False)
        if result is None:
            continue
        any_anchored = True
        ops, window, _offset = result
        for lab in _labels_from_ops(book, page, norm, ops, window):
            _, _, col, tail = lab.instance_id.split(":")
            per_slot[(col, tail)].append((lab, w.rank))
    if not any_anchored:
        return None

    out = []
    for entries in per_slot.values():
        if len(entries) == 1:
            out.append(entries[0][0])
            continue
        votes = Counter(lab.char for lab, _rank in entries)
        top = max(votes.values())
        tied = [c for c, n in votes.items() if n == top]
        if len(tied) == 1:
            winner_char = tied[0]
        else:
            # 票数并列（含「两家证人各给一票、谁都不占多数」的常态）：
            # 取质量 rank 最高的那家给的字。
            winner_char = max((e for e in entries if e[0].char in tied),
                              key=lambda e: e[1])[0].char
        supporting = [lab for lab, _rank in entries if lab.char == winner_char]
        out.append(max(supporting, key=lambda lab: (lab.op == "equal", lab.op_run)))
    return out


def _run_multi_witness(ctx: RunContext, p: AlignRefParams, page: int,
                       match: PageMatch | None, ocr: PageOcr | None,
                       rare: dict[str, list[str]] | None = None) -> PageAlignRef:
    """`witness_strategy in ("normalize", "majority_vote")` 的产出路径
    （模块头「多证人合并」一节）。与 legacy 路径共享下游处理（库证据闸 →
    `AlignRec`），只是锚定/对齐这一段换成多证人版本。
    """
    witnesses = _witnesses_for_book(ctx.book)
    if not witnesses:
        return PageAlignRef(page=page, anchored=False,
                            corpus_fingerprint=p.witness_fingerprint,
                            witness_strategy=p.witness_strategy,
                            note="未配置证人")
    slots = slots_from_evidence(match, ocr, rare)
    if len(slots) < 12:
        return PageAlignRef(page=page, anchored=False,
                            corpus_fingerprint=p.witness_fingerprint,
                            witness_strategy=p.witness_strategy, n_witnesses=len(witnesses),
                            note=f"候选太少（{len(slots)}），锚不住")
    norm = _norm_slots(slots)
    query = "".join(t[-1] for t in norm)

    if p.witness_strategy == "normalize":
        best = witnesses[0]
        result, diag = _witness_align(query, best, normalize=True)
        if result is None:
            return PageAlignRef(
                page=page, anchored=False, corpus_fingerprint=p.witness_fingerprint,
                witness_strategy=p.witness_strategy, n_witnesses=len(witnesses),
                note=(f"8-gram 锚定失败（证人：{best.label}）：{diag.reason}"
                      if diag.reason else "8-gram 锚定失败"),
                n_grams=diag.n_grams, n_votes=diag.n_votes,
                vote_frac=diag.vote_frac, dominance=diag.dominance)
        ops, window, _offset = result
        labs = _labels_from_ops(ctx.book.id, page, norm, ops, window)
    elif p.witness_strategy == "majority_vote":
        labs = _majority_vote_labels(ctx.book.id, page, norm, query, witnesses)
        if labs is None:
            _, diag = _witness_align(query, witnesses[0], normalize=False)
            return PageAlignRef(
                page=page, anchored=False, corpus_fingerprint=p.witness_fingerprint,
                witness_strategy=p.witness_strategy, n_witnesses=len(witnesses),
                note=(f"8-gram 锚定失败（{len(witnesses)} 家证人都没锚上，以 "
                      f"{witnesses[0].label} 的判据为例）：{diag.reason}"
                      if diag.reason else "8-gram 锚定失败"),
                n_grams=diag.n_grams, n_votes=diag.n_votes,
                vote_frac=diag.vote_frac, dominance=diag.dominance)
    else:
        raise ValueError(f"未知的 witness_strategy: {p.witness_strategy!r}")

    n_dropped = 0
    if p.lib_gate and match is not None:
        labs, n_dropped = lib_gate(labs, match, p.lib_cov_min)
    chars = [AlignRec(id=lab.instance_id, col=_col_of(lab.instance_id),
                      slot=_slot_of(lab.instance_id), sub=_sub_of(lab.instance_id),
                      align_char=lab.char, align_op=lab.op, ref_run=lab.op_run)
             for lab in labs]
    return PageAlignRef(
        page=page, anchored=True, corpus_fingerprint=p.witness_fingerprint,
        witness_strategy=p.witness_strategy, n_witnesses=len(witnesses),
        chars=chars, n_lib_dropped=n_dropped)


def lib_char_of(m) -> str | None:
    """库对这一格认的字：same 档取 `char`，否则取候选首位。"""
    if m is None:
        return None
    if m.char:
        return m.char
    return m.candidates[0][0] if m.candidates else None


def lib_gate(labs: list, match: PageMatch, cov_min: float) -> tuple[list, int]:
    """replace 位的库证据闸（模块头 2026-09-22）。

    库以 cov ≥ `cov_min` 认下这一格是 X、而整理本给的 gold 既不是 X 也不是 X 的异体
    → 整理本与刻本在这一位真的不同，不采信。equal 位不动（gold == 载体，闸无从谈起）。
    """
    from ..variants import are_variants
    mrec = {r.id: r for cc in match.columns for r in cc.chars}
    out, dropped = [], 0
    for lab in labs:
        if lab.op == "replace":
            m = mrec.get(lab.instance_id)
            x = lib_char_of(m)
            if m is not None and x and m.cov >= cov_min and x != lab.char \
                    and not are_variants(x, lab.char):
                dropped += 1
                continue
        out.append(lab)
    return out, dropped


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


# ── 按坐标对位（overview#195，算法见 `steps/align_ref_coord` 模块头）────────
def _coord_enabled(p: "AlignRefParams", book) -> bool:
    if p.coord == "off" or p.witness_strategy != "legacy":
        return False
    if p.coord == "on":
        return True
    refs = getattr(book, "references", None) or []
    if refs and refs[0].get("line_is_column"):
        return True
    return _corpus_line_is_column(p.corpus, int(getattr(book, "chars_per_line", None) or 0))


@lru_cache(maxsize=8)
def _corpus_line_is_column(path: str, cap: int) -> bool:
    """语料是不是逐列分行的：≥95% 的非空行字位数 ≤ cap+1（+1 容抬头）。"""
    if cap <= 0:
        return False
    from .align_ref_coord import ref_lines
    lines, _ = ref_lines(path)
    if len(lines) < 100:
        return False
    if any(ln.leaf_start for ln in lines[:50]):
        return True                     # 逐列本（`#@` 半叶头）
    ok = sum(1 for ln in lines if ln.n <= cap + 1)
    return ok >= 0.95 * len(lines)


def attach_coord(res: PageAlignRef, book: str, page: int, match, ocr, rare,
                 cells, corpus: str) -> None:
    """在 `res`（现役对位的产物）上补坐标对位：`coord` / `coord_cols` /
    `coord_fallback` / `coord_note`。现役 `chars` 一个字不动。"""
    from . import align_ref_coord as C
    if cells is None:
        res.coord_note = "没有 Step3 字格产物（cells）"
        return
    lines, starts = C.ref_lines(corpus)
    text = _corpus_text(corpus)
    if not lines or not text:
        res.coord_note = "整理本读不到"
        return
    carrier = carrier_fn(match, ocr, rare)
    cols = [cc for cc in sorted(match.columns, key=lambda c: c.col) if cc.ok and cc.chars]
    carriers = [(cc.col, "".join(carrier(r.id) or "" for r in sort_by_reading(cc.chars)))
                for cc in cols]
    query = "".join(c for _col, c in carriers)
    off, votes, _ru = _raw_vote_clusters(query, _corpus_index(corpus))
    if off is None or votes < 2:
        off, votes = C.scan_offset(query, text)
    if off is None:
        res.coord_note = "定不了页在整理本里的位置（8-gram/4-gram 都没命中）"
        return
    grid = bool(lines) and any(ln.leaf_start for ln in lines[:50])
    l0 = C.line_at(starts, max(0, off))
    win = C.COORD_WINDOW_LINES + (9 if grid else 0)
    pm = C.map_columns(carriers, lines, l0 - win, l0 + len(carriers) + win, grid=grid)
    if pm.base is None:
        res.coord_note = pm.note
        return
    from ..products.kinds.recog import CoordRec
    legacy = {c.id: c for c in res.chars} if res.anchored else {}
    same = {r.id: r.char for cc in cols for r in cc.chars if r.verdict == "same" and r.char}
    work = []
    for cc in cols:
        li = pm.col_line.get(cc.col)
        if li is None:
            res.coord_fallback[str(cc.col)] = "列行对应不成立"
            continue
        units = C.column_units(book, page, cc.col, cc, cells.column(cc.col), carrier)
        if not units:
            res.coord_fallback[str(cc.col)] = "缺几何（cells 查不到这一列的格）"
            continue
        work.append((cc, units, lines[li], C.coord_column(units, lines[li])))
    # 逐列本的格位是绝对值：几何上只有一种配法的列量出页级「格位 → 行号」偏移，
    # 拿它去分有歧义的列（印章假格与字格混在一起时常见）。光盘版没有格位，不做。
    bs = sorted(r.b for _cc, _u, _ln, r in work if r.ok and r.unique and r.b is not None)
    if grid and bs:
        b_page = bs[len(bs) // 2]
        work = [(cc, u, ln, r if r.ok else C.coord_column(u, ln, b_hint=b_page))
                for cc, u, ln, r in work]
    for cc, _units, _ln, r in work:
        if not r.ok:
            res.coord_fallback[str(cc.col)] = r.note
            continue
        why = _coord_conflict(r.recs, legacy, same)
        if why:
            res.coord_fallback[str(cc.col)] = why
            continue
        res.coord_cols.append(cc.col)
        res.coord.extend(CoordRec(id=i, col=cc.col, slot=sl, sub=sub, ref_char=ch, row=round(g, 2))
                         for i, sl, sub, ch, g in r.recs)


def _coord_conflict(recs, legacy: dict, same: dict) -> str:
    """坐标对位这一列与别的强证据打架 → 整列退回，返回原因；不打架返回空串。

    vol03 全册实测（未加这道闸时）：坐标对位与现役对位不一致的 83 格落在 15 列上，
    **全部是整列错一位**——光盘版这一行的分行比刻本多/少一个字（行首或行尾的字
    归了邻行），几何上照样配得上（多出来的那格被当成空格位），字却整列错开一格。
    这些格的现役对位几乎全是 `equal`（认出来的字与整理本逐字相同），所以：

    - 与现役 `equal` 位的字不同 → 退回（现役 `replace` 位本身存疑，不作数）；
    - 被判成空格位的格，库却以 `same` 认下了一个字 → 退回（锚不上的页没有现役
      对位可比，靠这条挡同一种错位）。"""
    for i, _sl, _sub, ch, _g in recs:
        lg = legacy.get(i)
        if lg is not None and lg.align_op == "equal" and lg.align_char != ch:
            return f"与现役对位冲突（{i} 坐标 {ch or '空'} / 现役 {lg.align_char}）"
        if ch == "" and i in same:
            return f"空格位上库认出了字（{i} 库 same {same[i]}）"
    return ""

