"""逐页进库（种子）流程侧（glyph_db_first_design.md §3.5）。

库优先架构的一切建立在「库里的字是对的」上——种子准确性是 100% 目标
而不是统计目标。本模块按页序推进，每个字位取三路证据：

- **OCR 载体**（``build_ocr_carrier.py`` 产出，逐块 RapidOCR top1 + s2t）；
- **整理本对齐字**（``align_label`` 现有机制：8-gram 锚定 + 采信闸，
  产出 equal/replace op）；
- **crop tier**（``assess_crop`` 在原始图块上分 clean/degraded）。

再对**当前库**（GlyphDB 载入 + 本轮已进库实例增量累加）跑
``GlyphMatcher.match`` 拿逐实例证据，过设计 §3.5 的六条疑问判定：

- 双信号一致（语义归一后 OCR == 对齐字）且六条全不命中 →
  以 ``align`` provenance 直接进库，落 ``auto_admitted`` 审计行；
- 其余 → ``SeedItem(status=pending_review)`` 进队列，**不进库**，
  等审查页面裁决（``seed-ingest`` 回收后以 ``human`` provenance 进库）。

接口契约（疑问码 / SeedItem / 决策事件）在 ``seed_queue.py``——那是
流程侧与审查页面侧唯一的耦合点，本模块只消费不定义。

输出（``output/{book}/phase9_seed/``）：

- ``queue.jsonl``：全部 SeedItem（含 auto_admitted 审计行）；
- ``progress.json``：每页 ``{total, auto, pending, done}`` 与推进指针。
  断点续跑按页粒度：progress 里 ``done`` 的页整页跳过。
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

from .align_eval import build_ngram_index
from .align_label import (carrier_slots, clean_labels, is_han, label_book,
                          page_reference)
from .crop_quality import assess_crop, detect_intrusion
from .extractor import CharInstance, load_index
from .glyph_db import GlyphDB, _unpng
from .lm import BaseLM, CharNgramLM, InterpolatedLM, train_ngram
from .match import NEVER_MATCH_FAMILIES, GlyphMatcher, MatchResult
from .context_step import build_strategy
from .recognize_flow import ColumnContext, fuse_priors
from .normalize import normalize_patch, sauvola_binarize
from .verify import MISS_WMAX
from .exclusions import load_exclusions
from .seed_queue import (DOUBT_DB_INCONSISTENT, DOUBT_DEGRADED_CROP,
                         DOUBT_NEAR_FORM, DOUBT_REPLACE_ALIGN,
                         DOUBT_SIGNAL_CONFLICT, DOUBT_WEAK_SINGLE,
                         STATUS_AUTO, STATUS_CONFIRMED, STATUS_LABEL_ONLY,
                         STATUS_EXCLUDED, STATUS_NOT_A_CHAR, STATUS_PENDING,
                         STATUS_RECROPPED, STATUS_REJECTED, STATUS_SKIPPED,
                         SeedItem)
from .variants import VariantMap

# weak_single 的 OCR prob 阈。**待 char-ocr 集标定**（设计 §3.5 条目 2），
# 当前 0.85 只是保守起点：book9 金标上 top1 88.75%，低置信段错误集中。
DEFAULT_PROB_THRESHOLD = 0.85

# 形近否决家族的全部成员（near_form 疑问用；单一事实源在 match.py）
NEAR_FORM_CHARS = frozenset(c for pair in NEVER_MATCH_FAMILIES for c in pair)

# 「同词异写」而非「认错字」的形近对（用户 2026-08-26 定；考据见
# charset_and_lm.md §四）。已/巳 历史上就是同一个词的两种写法（段玉裁：
# 巳久已用为「已然」之已），config/variants/variants.json 里
# 已→巳 登记为 hydzd/yitizi 异体关系——字形层拦得对（近形护栏防的是
# **形状判据**自己会错认），但**上下文/语言模型的文意判断**不该被同一
# 道闸挡下：这道题字形本就不重要，文意才是唯一相关的证据。
#
# 严格窄集，不等于 NEAR_FORM_CHARS：己 长得像已/巳但是**真的另一个字**
# （自己 vs 已经/地支），vol01:21:3:19 实锤过把己错认成巳/已——己不进
# 这张表，上下文通道对它照样要拦，仍然人审。
SEMANTIC_MERGED_PAIRS: frozenset[tuple[str, str]] = frozenset({("已", "巳")})
SEMANTIC_MERGED_CHARS = frozenset(
    c for pair in SEMANTIC_MERGED_PAIRS for c in pair)

SEED_DIR = "phase9_seed"

# 上下文通道的 margin 准入阈。八轮重标定：语料字入候选池后 margin 分布
# 整体左移（LM softmax 摊薄），vol02 基准的 0.99 阈在这套配置下几乎全拦。
# 改用**用户前 13 页 303 条真实裁决**重标（同配置回放）：
#   margin ≥0.70 → 198/198 全对（覆盖 65.3%）；≥0.60 → 213/213；
#   首个错例出现在 0.5 档。取 0.70，离首错留 0.2 缓冲。
# 另有单候选防护（见 context 通道注释）兜底。
DEFAULT_CONTEXT_MARGIN = 0.70

# 语言模型混合（charset_and_lm.md §二标定）：通用语料只配低权重，
# 本书语料拿大头；线性插值（对数线性会被通用语料的零概率专名拖死）。
BOOK_LM_WEIGHT = 0.9
GENERAL_LM_WEIGHT = 0.1
GENERAL_LM_PRUNE = 3      # 通用语料剪枝阈（≥10M 字，n-gram 表才装得下）

# 字体字形兜底（十六轮实测接线）：刻本库匹配不上时，从字体渲染字形库
# 里找**备选**。三条纪律，缺一条就会毁掉库的纯净：
#   ① 只当候选源，**永不参与准入裁决**——字体形与刻本形的相似度分布
#      重叠（bench separable=false，字体 recall@1 仅 21%），没法拿阈值
#      定生死；进库通道（match_ref/match_solo）一律只认刻本库；
#   ② 只在刻本库**弱**时才查（top cov < FONT_COV_GATE）——库强的层
#      现有候选已含金标 99~100%，查字体是白花钱还添噪声；
#   ③ 权重低于任何真证据（库 3.0 / 语料 2.5 / OCR 1.5），且按检索名次
#      衰减——它的价值是「把正确字带进候选集」，不是「说它是对的」。
# 529 条人审难例实测：查字体后定字对 +9、门槛进库对 +15、**错 +0**，
# 门槛精度 99.4% 不变；增益全部来自 cov<0.95 那 245 格。
FONT_COV_GATE = 0.95     # 刻本库 top cov 低于此才查字体库
FONT_WEIGHT = 0.6        # 字体候选的先验权重（第 1 名；后续按名次衰减）
FONT_TOPK = 10           # 每格取多少个字体候选

# match_solo 通道（十轮用户定案，十一轮上调）：无整理本锚定时，
# 库内形状验证 cov ≥ 此阈单独放行。初值 0.98 首日即出一例压线错
# （揀/棟 0.9802），用户裁定收紧到 0.99（约让出四成通道量换稳）；
# 护栏与形近防线见 admission_decision docstring。
# 2026-08-24 判据换 elastic 后本闸数值未动：elastic 的分数经**分位校准**
# 搬回了 coverage 的刻度（verify.py `_CAL_*`），同一个数放行同样比例的对。
# 但「放行谁」变了，而本闸当年是**人裁回放**标定的——严格说欠一次回放
# 复核，记在 glyph_match_stack.md §七。MATCH_SOLO_OCR_COV / FONT_COV_GATE 同理。
MATCH_SOLO_COV = 0.99

# match_solo 的 OCR 字符背书档（十八轮，167 条无语料人裁回放定标）：
# 库形状证据 0.95~0.99 单独不够（历史标定 68.5%），但再要求 OCR **字符**
# 同字（语义归一后）时，两路证据（形状 kNN × 识别模型）独立到足以互证
# ——回放 81/81 全对（cov≥0.99 9 条 + 0.95~0.99 72 条），错案零。
# 形近家族除外（那正是两路会同错的地方：已/巳、人/入、日/曰、今/全
# 四条历史反例全在家族里）；不同语义的竞争候选到 0.95 档也禁。
# 0.95 以下无「OCR×库一致」样本，不外推。
MATCH_SOLO_OCR_COV = 0.95
# replace 层对齐 × 库 top 一致的放行阈（2026-08-25 十七轮实审标定：
# 756 条历史人裁回放，@0.95 触发 70 全对——OCR 认错才产生 replace 层，
# 而「OCR 不参与自动判断」本就是定案；整理本（文本）× 库（形状）两路
# 零同源证据同指一字，与 match_ref 通道同一机理，只是对齐来自 replace
# 层所以单独设档留观察窗）
MATCH_REPLACE_COV = 0.95
# 免闸参考 × 库 top 一致的放行阈（同一轮标定：@0.98 触发 25 全对；
# @0.97 出 祗/祇 一错——免闸参考噪声大于过闸对齐，阈往上顶一档）
MATCH_REF_WEAK_COV = 0.98

# match_margin 通道用：库 top1 与 top2 的覆盖率差（不是绝对 cov）。
# 用户 2026-08-27 定：「即使庫內匹配率未達到 0.99，但是沒有競爭者，
# 且整理本一致，完全可以自動錄入。只有有相似競爭者，或整理本不一致
# 時，需要人工」——上面几条通道全部按**绝对 cov** 卡阈，会漏掉「cov
# 不高但根本没有第二名」的场面（比如 top1 0.85、top2 0.30，比 top1
# 0.97、top2 0.95 那种真竞争更不该拦）。全部历史人裁回放定标：
# margin≥0.05 触发 102 全对；0.04 档出第一错（祗/祇，MATCH_REF_WEAK_COV
# 注释里同一对，免闸参考噪声大），阈定在错例之上留一档。
MATCH_MARGIN_THRESH = 0.05


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def margins_of(rec: CharInstance) -> tuple[int, int]:
    """核心区（bbox 去 padding）到图块边缘的像素距离（assess_crop 用）。

    与 build_normalization_dataset.margins_of 同一算法：bbox 含 padding，
    height/width 是不含 padding 的字框，差的一半即边距。
    """
    bh = rec.bbox[3] - rec.bbox[1]
    bw = rec.bbox[2] - rec.bbox[0]
    return (max(0, int(round((bh - rec.height) / 2))),
            max(0, int(round((bw - rec.width) / 2))))


def load_matcher_from_db(db: GlyphDB, edition: str | None = None,
                         knn_k: int = 10) -> tuple[GlyphMatcher, set[str]]:
    """GlyphDB 的 exemplar（含种子准入实例）→ 内存匹配器 + 库内字集合。

    返回的字集合供 db_inconsistent 疑问（§3.5 条目 5）判「库里有没有
    这个字」——GlyphMatcher 不对外暴露字表，这里自己记账。
    """
    matcher = GlyphMatcher(k=knn_k)
    chars: set[str] = set()
    cur = db.conn.cursor()
    sql = """SELECT g.char, e.instance_id, d.data
             FROM exemplars e
             JOIN glyphs g ON g.glyph_id = e.glyph_id
             JOIN derived d ON d.instance_id = e.instance_id AND d.kind='norm'"""
    args: tuple = ()
    if edition:
        sql += " WHERE g.edition_tag = ?"
        args = (edition,)
    for char, iid, data in cur.execute(sql, args).fetchall():
        matcher.add(iid, char, _unpng(data))
        chars.add(char)
    return matcher, chars


# ── 疑问判定（纯函数，可单测）─────────────────────────────────────────

def judge_doubts(ocr: dict | None, align: dict | None, tier: str,
                 proposed: str | None, match: MatchResult,
                 db_chars: set[str], vmap: VariantMap,
                 prob_threshold: float = DEFAULT_PROB_THRESHOLD) -> list[str]:
    """六条疑问判定（编号对齐设计 §3.5 的表）。任一命中即入审查队列。"""
    doubts: list[str] = []
    ocr_char = ocr["char"] if ocr else None
    align_char = align["char"] if align else None
    # 1 双信号打架：载体已过 s2t，这里再过 VariantMap 语义归一后仍不同
    if ocr_char and align_char \
            and vmap.semantic(ocr_char) != vmap.semantic(align_char):
        doubts.append(DOUBT_SIGNAL_CONFLICT)
    # 2 单信号且弱：无对齐字，OCR 缺失或 prob 低于阈
    if align_char is None and (ocr is None or ocr.get("prob", 0.0) < prob_threshold):
        doubts.append(DOUBT_WEAK_SINGLE)
    # 3 图块本身可能不是完整的字（empty 一并按 degraded 计）
    if tier != "clean":
        doubts.append(DOUBT_DEGRADED_CROP)
    # 4 形近否决家族成员：两个信号源都容易犯同样的错
    if proposed and proposed in NEAR_FORM_CHARS:
        doubts.append(DOUBT_NEAR_FORM)
    # 5 库内不自洽：库里已有同字条目，但本次匹配既没 same 到它、
    #   也没让它进 unsure 候选（= 对它们全部 diff）
    if proposed and proposed in db_chars and match.char != proposed \
            and proposed not in {c for c, _ in match.candidates}:
        doubts.append(DOUBT_DB_INCONSISTENT)
    # 6 replace 层本来就是 OCR 与整理本不一致的位置（即便过了采信闸）
    if align and align.get("op") == "replace":
        doubts.append(DOUBT_REPLACE_ALIGN)
    return doubts


BLANK_INK_RATIO = 0.01   # R1：去噪（<6px 组件不计）后墨量占比低于此 = 空白格
#                          校准：1198 个已定真字实例抽样最低 0.0846（8 倍余量）
NONCHAR_OCR_PROB = 0.30  # R2：列尾格 OCR 置信低于此（或非汉字）算垃圾输出


def detect_nonchar(gray: "np.ndarray", ocr: dict | None,
                   ref_char: str | None, is_tail: bool,
                   page_anchored: bool) -> str | None:
    """空白/非字自动探测（六轮实审后加）。返回原因或 None。

    校准依据：用户前几页手标的 16 条非字**全部**是列尾格 + 整理本对不上
    + OCR 垃圾输出（低置信/非汉字/幻觉字）；其中 6 条纯空白。规则对
    1198 个已定真字实例验证零误杀。

    - R1 **blank**：Sauvola 二值 + 去噪后墨量 < BLANK_INK_RATIO。
      任何位置都适用（真字抽样最低 8.5%，8 倍余量）；
    - R2 **tail_junk**：锚定页的列尾格 + 无整理本参考 + OCR 非汉字或
      prob < NONCHAR_OCR_PROB —— 版框线/残带占格的典型形态。只在
      **锚定页**启用：整理本对不上是判据的一半，没锚定就没这道安全网
      （「一」与框线形状上判不准，是记档的粘连盲区，靠的就是语料）。
    """
    binary = sauvola_binarize(gray)
    n, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    ink = sum(int(stats[i, cv2.CC_STAT_AREA]) for i in range(1, n)
              if stats[i, cv2.CC_STAT_AREA] >= 6)
    if ink / binary.size < BLANK_INK_RATIO:
        return "blank"
    if is_tail and page_anchored and ref_char is None:
        och = (ocr or {}).get("char")
        if not och or not is_han(och) \
                or (ocr or {}).get("prob", 0.0) < NONCHAR_OCR_PROB:
            return "tail_junk"
    return None


def admission_decision(ocr: dict | None, align_char: str | None,
                       ref_char: str | None, doubts: list[str],
                       vmap: VariantMap,
                       match_char: str | None = None,
                       match_candidates: list[tuple[str, float]] | None = None,
                       match_guard: str | None = None,
                       match_wmax: float = 0.0,
                       solo_cov: float = MATCH_SOLO_COV,
                       ) -> tuple[bool, str | None]:
    """进库裁决：返回 (可自动进库, 通道名 None|"match_ref"|"match_solo")。

    五轮实审定型（此前的 OCR prob 强信号/三重通道已废）：**OCR 不参与
    自动判断**——实测置信度校准不可靠（100% 也照样认错形近字），它只
    负责给审查页面供候选。可信的两路是：

    - **常规通道**：过闸对齐（整理本 × 载体逐字印证 + 采信闸）且六条
      疑问全不命中。载体在这里只是把页锚到语料的运输工具，站着的证据
      是整理本；
    - **库 × 整理本通道**：库匹配完美档（verify same，cov ≥ 判据自己的
      same 闸——elastic 0.988 / coverage 0.992，见 verify.py——的
      **形状**证据）继承的字与整理本（过闸对齐字，或无对齐时的免闸
      参考字）同字 → 直接进库，degraded_crop 单独不拦。两路证据
      同源性为零，同时错到同一个字上的概率可忽略。never-match 护栏
      在匹配层已把形近家族降档 unsure（match_char 为 None），本通道
      天然触不到形近字；
    - **库匹配单独通道（match_solo）**：无整理本可参照时（奏折/上谕
      页，corpus_char 为 None），库内形状验证 cov ≥ solo_cov（默认
      0.99，见 MATCH_SOLO_COV 注释）单独放行——库里的条目都是已验证的，同字
      同刻工的覆盖率天然到这个档。防线：护栏（never_match/conflict）
      触发即禁；候选里有**不同语义**的字也到 0.98 档 → 形近存疑，禁；
      残差窗 wmax 超 MISS_WMAX（偏旁之差的典型形态）时需 OCR 字符
      背书；near_form / db_inconsistent 照拦。weak_single（无对齐 +
      OCR 弱）不拦——形状证据自己站得住，OCR 置信度不参与判断。
    near_form 对 match_solo / 免闸 match_ref 仍拦；**过闸对齐 × 库 top
    一致**时穿透（75 条家族人裁回放 35/35，见通道内注释）。
    db_inconsistent 全通道仍拦（毒化库的路）。
    """
    ocr_char = ocr["char"] if ocr else None
    dual = (ocr_char is not None and align_char is not None
            and vmap.semantic(ocr_char) == vmap.semantic(align_char))
    if dual and not doubts:
        return True, None
    corpus_char = align_char if align_char is not None else ref_char
    overridable = all(d == DOUBT_DEGRADED_CROP for d in doubts)
    if dual and overridable:
        # 双信号一致 + 仅 degraded：前 13 页实审 58/58 全数照准——
        # 机器残留分级在双信号一致面前误报居多（七轮实审定案）
        return True, "dual_degraded"
    # 形近家族放行（2026-08-24，用户实锤「人 处处 100% 还要手点」后
    # 用 75 条已裁 near_form 回放定案）：near_form 拦的是**形状判据
    # 自己**——已/巳 库内错配也能到 cov 0.999，OCR × 库还会同错
    # （14:2:18）。但**过闸对齐 × 库 top 一致**是文本 × 形状两路零同
    # 源证据，实测 35/35 全对，而所有人工推翻 align 的家族案例
    # （巳→已、入→人等）全落在「两路不一致」侧，本来就不命中。
    # 只对过闸 align 放（op=equal，replace 层有 REPLACE_ALIGN 拦）；
    # 免闸参考（ref_char）零家族样本，继续拦。
    ref_overridable = overridable or (
        align_char is not None
        and all(d in (DOUBT_DEGRADED_CROP, DOUBT_NEAR_FORM)
                for d in doubts))
    if ref_overridable and corpus_char is not None:
        # 库 × 整理本通道。十四轮全量交叉分析（529 条人审难例回放）把它
        # 从「库须 verify same」放宽到「库 top 候选一致即可」：文本证据 ×
        # 形状证据同源性为零，实测 **144/144 全对**，其中 33 条属形近家族
        # 也全对——形近护栏防的是形状判据，文本证据不受形状干扰，本就该
        # 穿透它。相形之下 OCR × 库 一致只有 97.1%（已/巳、人/入、日/曰、
        # 今/全 四条漏网，且这四条的整理本全是对的），故 OCR 永不与库配对。
        db_char = match_char
        if db_char is None and match_candidates:
            db_char = max(match_candidates, key=lambda t: t[1])[0]
        if db_char is not None \
                and vmap.semantic(db_char) == vmap.semantic(corpus_char):
            return True, "match_ref"
    # replace 层对齐 × 库 top 一致（十七轮，70/70）：signal_conflict 与
    # replace_align 这两条疑问都在说「OCR 与整理本不一致」——可 OCR 本来
    # 就不参与自动判断，拦错了对象。整理本字与库内形状 top 候选同字且
    # cov 够高时放行，进库字取**整理本字**（库只是形状旁证）。
    # db_inconsistent 不在允许集，照拦。near_form 2026-08-27 加入
    # ——match_ref（equal 层）早就放了 near_form（33/33 全对，见上面
    # ref_overridable 注释），replace 层没跟上纯属疏漏：证据独立性论证
    # 一样成立，整理本×库 zero-shared-source，与对齐是 equal 还是
    # replace 无关。全部历史人裁回放：143/143 全对。
    d_replace = {DOUBT_SIGNAL_CONFLICT, DOUBT_REPLACE_ALIGN,
                 DOUBT_DEGRADED_CROP, DOUBT_NEAR_FORM}
    if align_char is not None and doubts \
            and all(d in d_replace for d in doubts) and match_candidates:
        c1, cov1 = max(match_candidates, key=lambda t: t[1])
        if cov1 >= MATCH_REPLACE_COV \
                and vmap.semantic(c1) == vmap.semantic(align_char):
            return True, "match_replace"
    # 免闸参考 × 库 top 一致（十七轮，25/25 @0.98）：无对齐的页（上谕/
    # 奏折补录）weak_single 几乎必然在场，此前它把 参考 × 库 双证据的路
    # 整个堵死。参考虽免闸（噪声大），但库形状 0.98 档同字时两路互证。
    # db_inconsistent 判的是 **proposed**——无对齐时 proposed 退回 OCR 字，
    # 这条疑问于是在说「这块图不像库里的 **OCR 字**」。本通道要进的却是
    # 参考字，两者不同字时这句话与放行毫无关系，反而是「它不该是 OCR 字」
    # 的旁证（用户 2026-08-25 实锤 vol01:22:5:4：OCR 司 18%、整理本 詞、
    # 库 top 詞 cov 1.00，疑问 5 说的是「不像库里的司」——完全正确）。
    # 与 signal_conflict 拦 match_replace 同一形态：疑问码描述 OCR，
    # 而 OCR 不投票。放行的字自己不可能 db_inconsistent——库里最像它的
    # 就是同字刻例，cov 还压着 0.98。
    # 回放：@0.98 触发 25 → 38 全对（剔除自证行 32/32）。
    d_weak = {DOUBT_WEAK_SINGLE, DOUBT_DEGRADED_CROP}
    if (align_char is None and ref_char is not None and ocr_char is not None
            and vmap.semantic(ocr_char) != vmap.semantic(ref_char)):
        d_weak = d_weak | {DOUBT_DB_INCONSISTENT}
    if align_char is None and ref_char is not None and doubts \
            and all(d in d_weak for d in doubts) and match_candidates:
        c1, cov1 = max(match_candidates, key=lambda t: t[1])
        if cov1 >= MATCH_REF_WEAK_COV \
                and vmap.semantic(c1) == vmap.semantic(ref_char):
            return True, "match_ref_weak"
    solo_ok = all(d in (DOUBT_DEGRADED_CROP, DOUBT_WEAK_SINGLE)
                  for d in doubts)
    if (corpus_char is None and solo_ok and match_guard is None
            and match_candidates):
        c1, cov1 = max(match_candidates, key=lambda t: t[1])
        rival = any(cov >= solo_cov
                    and vmap.semantic(ch) != vmap.semantic(c1)
                    for ch, cov in match_candidates)
        # 残差窗形近防线（十轮实锤：揀 页匹配库内 棟 cov 0.9802——
        # 偏旁之差全落在一个残差窗里，wmax 13 恰好超阈）：wmax 超
        # MISS_WMAX（same 档同款护栏）时要求 OCR **字符**背书——
        # 用的是它读出的偏旁（字符层证据），不是不可靠的置信度。
        shape_clean = match_wmax <= MISS_WMAX
        ocr_backs = (ocr_char is not None
                     and vmap.semantic(ocr_char) == vmap.semantic(c1))
        if cov1 >= solo_cov and not rival and (shape_clean or ocr_backs):
            return True, "match_solo"
        # OCR 字符背书档（MATCH_SOLO_OCR_COV 注释，81/81 回放）：
        # 形状 0.95~0.99 + OCR 字符同字 = 两路独立证据互证。
        # 形近家族显式禁（proposed=OCR 字时 near_form 疑问已拦一道，
        # 这里对 c1 也拦——两侧任一属家族都算）；异语义竞争到
        # 0.95 档也禁。
        rival95 = any(cov >= MATCH_SOLO_OCR_COV
                      and vmap.semantic(ch) != vmap.semantic(c1)
                      for ch, cov in match_candidates)
        if (cov1 >= MATCH_SOLO_OCR_COV and ocr_backs and not rival95
                and c1 not in NEAR_FORM_CHARS
                and ocr_char not in NEAR_FORM_CHARS):
            return True, "match_solo_ocr"
    # match_margin（用户 2026-08-27 定，见 MATCH_MARGIN_THRESH 注释）：
    # 兜底通道——上面全部通道都没吃到的，最后看一眼「有没有 competitor」。
    # 不管疑问是什么组合（db_inconsistent 除外——它说的是库本身对不上，
    # margin 再大也不该信）、不管 cov 绝对值，corpus_char（过闸对齐或
    # 免闸参考）与库 top1 语义一致，且 top1 断档领先 top2 达
    # MATCH_MARGIN_THRESH 即放行——「没有竞争者 + 整理本一致」，与
    # match_replace/match_ref_weak 同一机理，进库字同样取整理本字
    # （库只是形状旁证）。全部历史人裁回放：margin≥0.05 触发 102 全对。
    if (corpus_char is not None and DOUBT_DB_INCONSISTENT not in doubts
            and match_candidates):
        ranked = sorted(match_candidates, key=lambda t: -t[1])
        c1, cov1 = ranked[0]
        cov2 = ranked[1][1] if len(ranked) > 1 else 0.0
        if (vmap.semantic(c1) == vmap.semantic(corpus_char)
                and cov1 - cov2 >= MATCH_MARGIN_THRESH):
            return True, "match_margin"
    return False, None


# ── 语言模型 ─────────────────────────────────────────────────────────

def _load_general_lm(paths: list[Path]) -> CharNgramLM:
    """通用语料 LM：训练一次（~30s/10M 字）后缓存在首个语料同目录。

    缓存键 = 各源文件 (name, size, mtime) + 剪枝阈；源变了自动重训。
    """
    key = json.dumps([[p.name, p.stat().st_size, int(p.stat().st_mtime)]
                      for p in paths] + [GENERAL_LM_PRUNE])
    cache = paths[0].parent / ".general_lm_cache.json"
    meta = paths[0].parent / ".general_lm_cache.meta"
    if cache.exists() and meta.exists() \
            and meta.read_text(encoding="utf-8") == key:
        return CharNgramLM.load(cache)
    lm = CharNgramLM(order=3)
    lm.train(p.read_text(encoding="utf-8") for p in paths)
    lm.prune(min_count=GENERAL_LM_PRUNE)
    lm.save(cache)
    meta.write_text(key, encoding="utf-8")
    return lm


def build_seed_lm(corpus_text: str,
                  general_corpus: list[str | Path] | None = None) -> BaseLM:
    """上下文通道的 LM：本书 3-gram，可选与通用语料线性混合。

    charset_and_lm.md §二标定定案：本书 0.9 / 通用 0.1。通用语料补的
    是本书语料没见过的搭配（LM 判「通不通顺」的底气），权重压低使
    本书专名（人名/书名）不被通用分布淹没。
    """
    book = train_ngram([corpus_text], order=3)
    paths = [Path(p) for p in (general_corpus or []) if Path(p).exists()]
    if not paths:
        return book
    general = _load_general_lm(paths)
    return InterpolatedLM([(book, BOOK_LM_WEIGHT),
                           (general, GENERAL_LM_WEIGHT)])


# ── progress.json ────────────────────────────────────────────────────

def _load_progress(seed_dir: Path) -> dict:
    p = seed_dir / "progress.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {"pages": {}}


def _save_progress(seed_dir: Path, progress: dict,
                   all_pages: list[str]) -> None:
    done = progress.get("pages", {})
    pending_pages = [p for p in all_pages if not done.get(p, {}).get("done")]
    progress["pointer"] = pending_pages[0] if pending_pages else None
    progress["updated_at"] = _now()
    (seed_dir / "progress.json").write_text(
        json.dumps(progress, ensure_ascii=False, indent=1), encoding="utf-8")


# 人裁过 = 不可再生。force 重跑一页时这些行原样留下，其余（auto/pending/
# skipped/excluded/机器判的 not_a_char）按新证据重生。
# not_a_char 要分来源：``note="auto:..."`` 是规则自动判的，规则改了就该重判；
# 没有 auto: 前缀的是人按下「非字」。
_HUMAN_STATUSES = (STATUS_CONFIRMED, STATUS_LABEL_ONLY, STATUS_REJECTED,
                   STATUS_RECROPPED)


def _is_human_decided(row: dict) -> bool:
    st = row.get("status")
    if st in _HUMAN_STATUSES:
        return True
    return st == STATUS_NOT_A_CHAR and not str(
        row.get("note") or "").startswith("auto:")


def _page_key(p: str) -> tuple[int, str]:
    return (len(p), p)


# ── 主流程：逐页进库 ─────────────────────────────────────────────────

def seed_book(book_out_dir: str | Path, db: GlyphDB, corpus: str | Path,
              pages: set[str] | None = None,
              carrier_path: str | Path | None = None,
              max_pages: int | None = None,
              prob_threshold: float = DEFAULT_PROB_THRESHOLD,
              context_margin: float = DEFAULT_CONTEXT_MARGIN,
              solo_cov: float = MATCH_SOLO_COV,
              general_corpus: list[str | Path] | None = None,
              font_store: str | Path | None = None,
              font_editions: list[str] | None = None,
              font_cov_gate: float = FONT_COV_GATE,
              edition: str | None = None, knn_k: int = 10,
              variants: str | Path | None = None,
              force_pages: set[str] | None = None) -> dict:
    """按页序逐页处理正文页（正文筛选交给调用方的 pages 参数）。

    断点续跑：progress.json 里 ``done`` 的页整页跳过；进库幂等
    （GlyphDB.admit_instance 按 instance_id 判重），中途崩掉重跑安全。
    max_pages 限制**本次调用**处理的页数（已完成页不计）。

    ``force_pages`` 给了就**只跑这几页**（即使已 done），其余一律不碰——
    定量重跑用：上游切分/载体/判据改过、或库长大了要刷新 match 快照。重跑不会毁掉人工成果：队列清理只删
    「机器可再生」的行，人裁过的行（confirmed / confirmed_label_only /
    rejected / 人工 not_a_char）原样留下，对应字位也跳过不再判——
    见 ``_is_human_decided``。
    """
    book_out_dir = Path(book_out_dir)
    book = book_out_dir.name
    root = book_out_dir / "phase4_chars"
    seed_dir = book_out_dir / SEED_DIR
    seed_dir.mkdir(parents=True, exist_ok=True)

    carrier_path = Path(carrier_path) if carrier_path \
        else root / "ocr_carrier.jsonl"
    if not carrier_path.exists():
        raise FileNotFoundError(
            f"OCR 载体不存在: {carrier_path}（先跑 scripts/build_ocr_carrier.py）")

    # 语料可给多份（主整理本 + 用户自补的奏折/上谕文本）：拼接成一份
    # 落在 seed 目录里用，锚定/参考/LM 三处同源
    if isinstance(corpus, (list, tuple)):
        parts = [Path(p).read_text(encoding="utf-8") for p in corpus
                 if Path(p).exists()]
        combined = seed_dir / "corpus_combined.txt"
        combined.write_text("\n".join(parts), encoding="utf-8")
        corpus = combined

    # 实例索引（只取 char 格位）
    recs = [r for r in load_index(root) if r.cell_type == "char"]
    by_page: dict[str, list[CharInstance]] = defaultdict(list)
    for r in recs:
        by_page[r.page].append(r)
    for rs in by_page.values():
        rs.sort(key=lambda r: (r.col, r.idx))
    rec_quality_index = {r.id: {"ink_ratio": r.ink_ratio, "flags": r.flags}
                         for r in recs}

    all_pages = sorted(
        (p for p in by_page if pages is None or p in pages), key=_page_key)

    # 断点续跑：done 的页跳过；max_pages 限制本次处理页数
    progress = _load_progress(seed_dir)
    progress.setdefault("book", book)
    progress.setdefault("prob_threshold", prob_threshold)
    page_state: dict = progress.setdefault("pages", {})
    force = set(force_pages or ())
    if force:
        # 给了 force_pages 就**只跑这几页**（2026-08-26 用户实锤）。
        # 早先的语义是「追加到待办」——可待办本来就含全部没 seed 过的页，
        # 于是「再匹配十页」跑成了 108 页 12 分钟。用户要的是定量重跑：
        # 库每轮都在长，后面页的 match 快照迟早还要再刷一次，跑多了是白烧。
        todo = [p for p in all_pages if p in force]
        missing = force - set(all_pages)
        if missing:
            print(f"⚠ --force-pages 里这些页不在索引/页型筛选内，忽略："
                  f"{sorted(missing, key=_page_key)}")
    else:
        todo = [p for p in all_pages if not page_state.get(p, {}).get("done")]
    skipped_done = len(all_pages) - len(todo)
    if max_pages is not None:
        todo = todo[:max_pages]

    summary: dict = {"book": book, "pages_total": len(all_pages),
                     "pages_skipped_done": skipped_done,
                     "pages_processed": 0, "n_slots": 0, "n_auto": 0,
                     "n_pending": 0, "db_added": 0, "n_missing_patch": 0,
                     "doubt_counts": {}, "per_page": {}}
    if not todo:
        _save_progress(seed_dir, progress, all_pages)
        return summary

    # OCR 载体：证据用 {id: {char, prob}}；对齐用 slots_by_page
    carrier: dict[str, dict] = {}
    with open(carrier_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                r = json.loads(line)
                carrier[r["id"]] = r
    slots_by_page = carrier_slots(carrier_path,
                                  valid_ids={r.id for r in recs})

    # 整理本对齐（align_label 现有机制：结构校验 + 锚定 + 采信闸 + 清洗）
    corpus_text = Path(corpus).read_text(encoding="utf-8")
    corpus_index = build_ngram_index(corpus_text)
    labels, _stats = label_book(book, book_out_dir, corpus, pages=set(todo),
                                corpus_index=corpus_index,
                                slots_by_page=slots_by_page)
    labels, _dropped = clean_labels(labels, rec_quality_index)
    align_of = {x.instance_id: x for x in labels}

    # 审查上下文：免闸参考对齐（page_reference，参考≠金标）+ 列文
    ref_by_page: dict[str, dict] = {
        p: page_reference(p, slots_by_page.get(p, []), corpus_text,
                          corpus_index)
        for p in todo}
    # 列文按 **index 的 char 格位** 建，不按 OCR 载体建（2026-08-25 定案）。
    # 载体可能缺格（那一格没识别出东西），缺一格整列文本就短一位，高亮
    # 的 pos 与审查页按 index 数出来的「第几字」对不上——用户对着原图数
    # 「文字错了一位」正是这个。以 index 为准、载体缺格补 □，则
    # ``pos == 该格在列内的 char 位次 - 1`` 恒成立，与卡片头的 seq 同源。
    cols_by_page: dict[str, dict[int, list[tuple[int, str]]]] = {}
    for p in todo:
        cols: dict[int, list[tuple[int, str]]] = defaultdict(list)
        for r in by_page.get(p, []):
            c0 = carrier.get(r.id)
            cols[r.col].append((r.idx, (c0 or {}).get("char") or "□"))
        cols_by_page[p] = {c: sorted(v) for c, v in cols.items()}

    def _col_strings(page: str, col: int) -> tuple[str, str] | None:
        entries = (cols_by_page.get(page) or {}).get(col)
        if not entries:
            return None
        refs = ref_by_page.get(page, {})
        ocr_s = "".join(ch for _, ch in entries)
        ref_s = "".join((refs.get((col, i), (None, ""))[0] or "·")
                        for i, _ in entries)
        return ocr_s, ref_s

    def slot_context(page: str, col: int, idx: int) -> dict | None:
        cur = _col_strings(page, col)
        if cur is None:
            return None
        entries = cols_by_page[page][col]
        refs = ref_by_page.get(page, {})
        col_ocr, col_ref = cur
        pos = next((n for n, (i, _) in enumerate(entries) if i == idx), None)
        ref_char, ref_op = refs.get((col, idx), (None, ""))
        out = {"col_ocr": col_ocr, "col_ref": col_ref, "pos": pos,
               "ref_char": ref_char, "ref_op": ref_op or None}
        # 跨列上下文：列首/列尾的字要接上邻列（古籍阅读序：上一列尾 →
        # 本列 → 下一列首）。只截端部 5 字，页面按需取用。
        prev = _col_strings(page, col - 1)
        if prev:
            out["prev_ocr"], out["prev_ref"] = prev[0][-5:], prev[1][-5:]
        nxt = _col_strings(page, col + 1)
        if nxt:
            out["next_ocr"], out["next_ref"] = nxt[0][:5], nxt[1][:5]
        return out

    # 当前库 → 内存匹配器（本轮进库实例增量累加）
    matcher, db_chars = load_matcher_from_db(db, edition=edition, knn_k=knn_k)
    vmap = VariantMap.load(variants)

    # 上下文通道件：本书 LM（可混通用语料）+ 同列已定字滚动窗口；
    # 裁决走 context_step 的 gated_ngram 策略（与评测同一核心）
    lm = build_seed_lm(corpus_text, general_corpus)
    ctx_decider = build_strategy("gated_ngram", lm=lm,
                                 semantic_fn=vmap.semantic)
    ctx_window = ColumnContext()

    # 字体兜底库（独立于进库用的 GlyphDB：刻本库只进真实刻本字形，
    # 字体库是可由 glyph-db import-font 一键重建的旁路资产）
    font_db = None
    if font_store and font_editions:
        fp = Path(font_store)
        fp = fp / "glyphdb.sqlite" if fp.is_dir() else fp
        if fp.exists():
            font_db = GlyphDB(fp)
            have = {r[0] for r in font_db.conn.execute(
                "SELECT DISTINCT edition_tag FROM glyphs")}
            font_editions = [e for e in font_editions if e in have]
            if not font_editions:
                font_db.close()
                font_db = None
    summary["font_consulted"] = 0

    # 队列：崩溃页残行清理（done 页永不重写；todo 页的旧行整页替换）。
    # **人裁过的行不动**（2026-08-25）：force 重跑一页时，机器判的行要按
    # 新证据重生，人裁的结论却是不可再生的成果——留行，并把那些字位记进
    # keep_ids 本轮跳过，免得同一 id 出两行（旧队列里 125 个重号就是这么
    # 来的，页面因此拿错卡片的证据）。
    queue_path = seed_dir / "queue.jsonl"
    todo_set = set(todo)
    keep_ids: set[str] = set()
    valid_ids = {r.id for r in recs}
    if queue_path.exists():
        kept = []
        for ln in queue_path.read_text(encoding="utf-8").splitlines():
            if not ln.strip():
                continue
            row = json.loads(ln)
            if row.get("instance_id") not in valid_ids:
                continue        # 切分重跑后已不存在的字位：整行作废
            if row.get("page") in todo_set:
                if not _is_human_decided(row):
                    continue
                keep_ids.add(row["instance_id"])
            kept.append(ln)
        queue_path.write_text("".join(x + "\n" for x in kept),
                              encoding="utf-8")

    exclusions = load_exclusions()
    summary["n_excluded"] = 0
    # 库里已进过的字位（任何通道）：重跑时只复述、不重判，见主循环注释
    already_admitted: dict[str, tuple[str, str]] = {
        r[0]: (r[1], r[2]) for r in db.conn.execute(
            "SELECT instance_id, char, provenance FROM admissions")}

    doubt_counts: Counter = Counter()
    with open(queue_path, "a", encoding="utf-8") as qf:
        for page in todo:
            n_auto = n_pending = 0
            page_recs = by_page[page]
            refs = ref_by_page.get(page, {})
            page_anchored = any(v[0] for v in refs.values())
            tail_idx: dict[int, int] = {}
            for r in page_recs:
                tail_idx[r.col] = max(tail_idx.get(r.col, -1), r.idx)
            for rec in page_recs:
                if rec.id in keep_ids:
                    continue            # 人裁过，队列里那行才是真源
                if rec.id in already_admitted:
                    # 库里已进过（上一轮任何通道），本轮判据即使不放行
                    # 也不能把它降回待审——库不会因此撤条目，只会让队列与
                    # 库分叉、把一个**已经进库**的字位再推给人审一遍。
                    # 用户 2026-08-25 实锤 vol01:22:5:4（库内 provenance
                    # =context，队列却是 pending_review）。
                    item = SeedItem(
                        instance_id=rec.id, book=book, page=page,
                        col=rec.col, idx=rec.idx, patch_path=rec.patch_path,
                        tier="clean", status=STATUS_AUTO,
                        decided_char=already_admitted[rec.id][0],
                        provenance=already_admitted[rec.id][1],
                        note="already_in_db",
                        context=slot_context(page, rec.col, rec.idx))
                    qf.write(item.to_json() + "\n")
                    n_auto += 1
                    continue
                # 排除名单（config/crop_exclusions.jsonl）：切坏/带残留的图块
                # **不进库也不出审查卡**——用户 2026-08-25 定的口径，重扫前
                # 一律保守处理。落一行 excluded 只为留账。
                if rec.id in exclusions:
                    item = SeedItem(
                        instance_id=rec.id, book=book, page=page,
                        col=rec.col, idx=rec.idx, patch_path=rec.patch_path,
                        tier="excluded", status=STATUS_EXCLUDED,
                        note="excluded:" + str(
                            exclusions[rec.id].get("reason", "")))
                    qf.write(item.to_json() + "\n")
                    summary["n_excluded"] = summary.get("n_excluded", 0) + 1
                    continue
                gray = cv2.imread(str(root / rec.patch_path),
                                  cv2.IMREAD_GRAYSCALE)
                if gray is None:
                    summary["n_missing_patch"] += 1
                    continue
                c0 = carrier.get(rec.id)
                ocr0 = ({"char": c0["char"], "prob": float(c0.get("prob", 0.0))}
                        if c0 and c0.get("char") else None)
                nonchar = detect_nonchar(
                    gray, ocr0, refs.get((rec.col, rec.idx), (None, ""))[0],
                    is_tail=(rec.idx == tail_idx[rec.col]),
                    page_anchored=page_anchored)
                if nonchar:
                    # 空白/版框格：自动判非字，不进审查也不进库（审计行照落）
                    item = SeedItem(instance_id=rec.id, book=book, page=page,
                                    col=rec.col, idx=rec.idx,
                                    patch_path=rec.patch_path, tier="degraded",
                                    ocr=ocr0, status=STATUS_NOT_A_CHAR,
                                    note=f"auto:{nonchar}",
                                    context=slot_context(page, rec.col, rec.idx))
                    qf.write(item.to_json() + "\n")
                    summary["n_auto_nonchar"] = summary.get(
                        "n_auto_nonchar", 0) + 1
                    n_auto += 1
                    continue
                q = assess_crop(gray, margins=margins_of(rec))
                tier = "clean" if q.tier == "clean" else "degraded"
                intrusion = detect_intrusion(gray)
                norm = normalize_patch(gray)
                # 摘掉自身：这个字位可能上一轮已进库，自比等于自证
                mr = matcher.match(norm, exclude_id=rec.id)

                c = carrier.get(rec.id)
                ocr = ({"char": c["char"], "prob": float(c.get("prob", 0.0))}
                       if c and c.get("char") else None)
                al = align_of.get(rec.id)
                align = {"char": al.char, "op": al.op} if al else None
                proposed = (al.char if al else None) or \
                    (ocr["char"] if ocr else None)

                doubts = judge_doubts(ocr, align, tier, proposed, mr,
                                      db_chars, vmap, prob_threshold)
                ctx = slot_context(page, rec.col, rec.idx)
                admit_ok, channel = admission_decision(
                    ocr, al.char if al else None,
                    (ctx or {}).get("ref_char"), doubts, vmap,
                    match_char=mr.char, match_candidates=mr.candidates,
                    match_guard=mr.guard, match_wmax=mr.wmax,
                    solo_cov=solo_cov)
                if admit_ok and channel in ("match_replace",
                                             "match_ref_weak",
                                             "match_margin"):
                    # 这三条通道站着的都是整理本/参考字，库只是形状旁证
                    # （match_margin 同一机理，见 MATCH_MARGIN_THRESH 注释）
                    proposed = (al.char if al else None) or \
                        (ctx or {}).get("ref_char")
                elif admit_ok and channel == "match_ref":
                    # 库 × 整理本通道的进库字取库匹配形——站着的是形状
                    # 证据（verify same）+ 整理本，OCR 只是旁证；否则
                    # 无对齐时 proposed 会落到 OCR 字（十轮实审：之 页
                    # OCR 报 芝，库 × 整理本同说 之，进库字必须是 之）
                    proposed = mr.char
                elif admit_ok and channel in ("match_solo",
                                              "match_solo_ocr"):
                    # 库匹配单独通道：进库字取库内验证 cov 最高的形
                    proposed = max(mr.candidates, key=lambda t: t[1])[0]
                elif admit_ok and proposed is None:
                    proposed = ocr["char"] if ocr else None

                item = SeedItem(instance_id=rec.id, book=book, page=page,
                                col=rec.col, idx=rec.idx,
                                patch_path=rec.patch_path, tier=tier,
                                ocr=ocr, align=align, proposed=proposed,
                                doubts=doubts, match=mr.to_dict(),
                                context=ctx, intrusion=intrusion)
                if admit_ok and proposed:
                    # 双信号一致（常规零疑问 / 强信号通道）→ align 进库；
                    # match_solo 无整理本参与，审计上以 match 记 provenance
                    prov = ("match" if channel in ("match_solo",
                                                   "match_solo_ocr")
                            else "align")
                    evidence = {"match": mr.to_dict(), "ocr": ocr,
                                "align": align, "tier": tier,
                                "crop": q.to_dict()}
                    if channel:
                        evidence["channel"] = channel
                        evidence["ref"] = {"char": (ctx or {}).get("ref_char"),
                                           "op": (ctx or {}).get("ref_op")}
                    admitted = db.admit_instance(
                        rec.id, proposed, (root / rec.patch_path).read_bytes(),
                        provenance=prov, evidence=evidence,
                        edition_tag=edition, page=page, col=rec.col,
                        idx=rec.idx, bbox=list(rec.bbox),
                        ink_ratio=rec.ink_ratio, width=rec.width,
                        height=rec.height, semantic=vmap.semantic(proposed))
                    if admitted:            # 重跑时库里已有，匹配器已载入
                        matcher.add(rec.id, proposed, norm)
                        db_chars.add(proposed)
                        summary["db_added"] += 1
                    item.status = STATUS_AUTO
                    item.decided_char = proposed
                    item.provenance = prov
                    if channel:
                        item.note = channel
                        key = f"n_auto_{channel}"
                        summary[key] = summary.get(key, 0) + 1
                    n_auto += 1
                else:
                    # 上下文通道（设计 §3 准入分级之 context）：候选融合
                    # （库 unsure 命中 ∪ OCR top1+s2t）+ 同列前文 LM 打分，
                    # margin ≥ 阈即以 context provenance 进库。
                    # 三道防护：① 只在锚定页跑（无语料没有安全网）；
                    # ② db_inconsistent 仍然只走人审——它说的是库本身
                    #    对不上，跟上下文判断是两回事，不该被 margin 盖过；
                    #    near_form **不再拦这条通道**（2026-08-27 用户定：
                    #    諭/論、曾/會、人/入这类反复靠人校对的形近字家族，
                    #    154 题盲测 n-gram 95.5%、大模型 98.7%，远超字形
                    #    层 top-1 64.3%——挡的一直是更可靠的证据。已/巳的
                    #    字形/释读分岔逻辑对其余家族不适用：那些是**真的
                    #    不同字**，context 判对了，形与义本就该是同一个值，
                    #    不需要再拆 shape）；
                    # ③ 单候选的 margin=1.0 是平凡值——要求 ranked ≥2
                    #    （真竞争胜出）或裁决字与整理本一致。
                    ctx_admit = False
                    if (page_anchored
                            and DOUBT_DB_INCONSISTENT not in doubts):
                        topk = [(ocr["char"], ocr["prob"])] if ocr else []
                        corpus_char = (al.char if al else None) or \
                            (ctx or {}).get("ref_char")
                        # 整理本字进候选池（八轮实审：OCR 认错时语料字
                        # 必须有资格被裁决；权重见 CORPUS_WEIGHT 注释）
                        extra = [(corpus_char, 1.0)] if corpus_char else []
                        # 字体兜底：只在刻本库弱时查（见 FONT_COV_GATE 注释）
                        if font_db is not None:
                            topcov = max((v for _, v in mr.candidates),
                                         default=0.0)
                            if topcov < font_cov_gate:
                                fh = font_db.query(norm, editions=font_editions,
                                                   k=FONT_TOPK)
                                extra += [(h.char, FONT_WEIGHT / (i + 1))
                                          for i, h in enumerate(fh)]
                                summary["font_consulted"] += 1
                        extra = extra or None
                        # 语义层量竞争、字形层选形（九轮实审：珎/珍 同语义
                        # 分票把 surface margin 摊薄到阈下）。选形优先取
                        # OCR/库真正见过的形——图上是什么形就录什么形。
                        prefs = {c for c, _ in mr.candidates}
                        if ocr:
                            prefs.add(ocr["char"])
                        res = ctx_decider.decide(
                            fuse_priors(mr.candidates, topk, extra=extra),
                            context=ctx_window.window(page, rec.col, rec.idx),
                            surface_prefs=prefs)
                        dec = res.decision
                        surface, sem_margin = res.surface, res.margin
                        safe = (len(dec.ranked) >= 2
                                or (surface is not None and corpus_char
                                    and vmap.semantic(surface) ==
                                    vmap.semantic(corpus_char)))
                        if surface and sem_margin >= context_margin and safe:
                            # 字形/释读分岔（只在 SEMANTIC_MERGED_PAIRS 触发，
                            # 用户 2026-08-26 定：字形是什么就录什么，已/巳
                            # 这三个字才按语意改——但改的是**释读**，不能
                            # 污染字形匹配层。字形库/GlyphMatcher 必须按
                            # OCR 这个纯视觉信号归类（它不掺文意判断），
                            # 不然未来一个真该读「巳」的同形实例会错误
                            # 继承这次的释读。OCR 缺失或本身不在家族里
                            # 时说明没有独立的形状信号，退回 surface
                            # （不引入分岔，绝大多数字符走这条路）。
                            shape_char = surface
                            if surface in SEMANTIC_MERGED_CHARS:
                                ocr_c = ocr["char"] if ocr else None
                                if ocr_c and ocr_c in SEMANTIC_MERGED_CHARS:
                                    shape_char = ocr_c
                            evidence = {"decision": dec.to_dict(),
                                        "surface": surface,
                                        "shape": shape_char,
                                        "sem_margin": sem_margin,
                                        "match": mr.to_dict(), "ocr": ocr,
                                        "align": align, "tier": tier,
                                        "crop": q.to_dict()}
                            admitted = db.admit_instance(
                                rec.id, surface,
                                (root / rec.patch_path).read_bytes(),
                                provenance="context",
                                evidence=evidence, edition_tag=edition,
                                page=page, col=rec.col, idx=rec.idx,
                                bbox=list(rec.bbox),
                                ink_ratio=rec.ink_ratio, width=rec.width,
                                height=rec.height,
                                semantic=vmap.semantic(surface),
                                shape=shape_char)
                            if admitted:
                                matcher.add(rec.id, shape_char, norm)
                                db_chars.add(shape_char)
                                summary["db_added"] += 1
                            item.status = STATUS_AUTO
                            item.decided_char = surface
                            item.provenance = "context"
                            item.note = "context"
                            summary["n_auto_context"] = summary.get(
                                "n_auto_context", 0) + 1
                            n_auto += 1
                            ctx_admit = True
                    if not ctx_admit:
                        item.status = STATUS_PENDING
                        if not doubts:
                            # 六条全不命中但双信号不齐（单信号高置信）——
                            # 契约无对应疑问码，审查侧凭 status 出队即可
                            item.note = "single_signal"
                        doubt_counts.update(doubts)
                        n_pending += 1
                if item.status == STATUS_AUTO and item.decided_char:
                    ctx_window.record(page, rec.col, rec.idx,
                                      item.decided_char)
                qf.write(item.to_json() + "\n")
            qf.flush()

            # force 重跑时保留下来的人裁行不参与本轮判定，单独记一笔，
            # 免得 auto+pending != total 看着像丢了字位
            n_keep = sum(1 for r in page_recs if r.id in keep_ids)
            page_state[page] = {"total": len(page_recs), "auto": n_auto,
                                "pending": n_pending, "done": True}
            if n_keep:
                page_state[page]["human_kept"] = n_keep
            _save_progress(seed_dir, progress, all_pages)
            summary["pages_processed"] += 1
            summary["n_slots"] += len(page_recs)
            summary["n_auto"] += n_auto
            summary["n_pending"] += n_pending
            summary["per_page"][page] = {"total": len(page_recs),
                                         "auto": n_auto,
                                         "pending": n_pending}
    summary["doubt_counts"] = dict(doubt_counts)
    return summary


# ── 决策回收：审查事件 → human 进库 ──────────────────────────────────

def apply_recrop(book_out_dir: Path, rec, bbox: list[float]) -> bytes | None:
    """按新 bbox 从**页图**重裁图块，覆盖 patch 与 index.jsonl 的 bbox。

    切分错位（格线整体偏移）时光改字没用——图块本身就是错的，收进库当
    范例会毒化匹配（vol01:5:2:15「言」：上边切掉亠头、下边吃进「等」）。
    这里改的是**上游产物**，所以要连 index.jsonl 一起改，否则下次重跑
    seed 又回到错的框。

    返回新 patch 的 PNG 字节；页图找不到或框越界返回 None。
    """
    page_img = book_out_dir / f"{rec.page}.png"
    if not page_img.exists():
        return None
    im = cv2.imread(str(page_img), cv2.IMREAD_GRAYSCALE)
    if im is None:
        return None
    h, w = im.shape[:2]
    x0, y0, x1, y1 = (int(round(v)) for v in bbox)
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, x1), min(h, y1)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    crop = im[y0:y1, x0:x1]
    ok, buf = cv2.imencode(".png", crop)
    if not ok:
        return None
    png = buf.tobytes()
    (book_out_dir / "phase4_chars" / rec.patch_path).write_bytes(png)

    # index.jsonl：整文件重写，只改这一行的 bbox/height/width
    idx_path = book_out_dir / "phase4_chars" / "index.jsonl"
    lines = idx_path.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        if not line.strip():
            continue
        d = json.loads(line)
        if d["id"] == rec.id:
            d["bbox"] = [float(x0), float(y0), float(x1), float(y1)]
            d["height"] = float(y1 - y0)
            d["width"] = float(x1 - x0)
            # 溯源标记放进已有的 flags 列表——CharInstance 是固定字段的
            # dataclass，新加顶层键会让 load_index 直接炸
            fl = d.get("flags") or []
            if "recropped" not in fl:
                fl.append("recropped")
            d["flags"] = fl
        out.append(json.dumps(d, ensure_ascii=False))
    idx_path.write_text("".join(x + "\n" for x in out), encoding="utf-8")
    return png


def ingest_decisions(book_out_dir: str | Path, db: GlyphDB,
                     events: list[dict], edition: str | None = None,
                     variants: str | Path | None = None) -> dict:
    """回收 ``seed_queue.parse_seed_events`` 的事件列表。

    - ``confirm`` → 该实例以 ``human`` provenance 进库，队列行
      status=confirmed、decided_char=事件的 char；
    - ``not_a_char`` / ``skip`` → 只更新队列行状态，不进库。

    幂等：进库按 instance_id 判重（GlyphDB.admit_instance），重复事件
    不重复进库；队列整文件重写，重放同一批事件结果不变。
    """
    book_out_dir = Path(book_out_dir)
    root = book_out_dir / "phase4_chars"
    seed_dir = book_out_dir / SEED_DIR
    queue_path = seed_dir / "queue.jsonl"
    if not queue_path.exists():
        raise FileNotFoundError(f"队列不存在: {queue_path}（先跑 seed）")

    order: list[str] = []
    items: dict[str, SeedItem] = {}
    with open(queue_path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            it = SeedItem.from_json(line)
            if it.instance_id not in items:
                order.append(it.instance_id)
            items[it.instance_id] = it

    rec_of = {r.id: r for r in load_index(root)}
    vmap = VariantMap.load(variants)
    n = Counter()
    # 事件分两个独立通道（十七轮用户定案：**重切与选字是两件事**）：
    # - 几何通道：recrop 事件只改 bbox/图块，不定字、不改裁决状态。
    #   同字位取 seq 最大的一条（用户可能拖了好几次框）。事件里若带
    #   char 一律忽略——那是首版 UI 误把重切与选字绑死留下的脏字段，
    #   实批实锤（14:9:18 出现 recrop→skip→confirm→skip→recrop 的反复，
    #   全是用户在跟自动选字对抗）。
    # - 裁决通道：confirm/not_a_char/skip 照旧后到覆盖。
    # 应用顺序：先几何后裁决——confirm 进库读的就是重切后的图块；
    # 已进库的字位被重切时刷新库里的真源与派生（refresh_instance_patch）。
    geom: dict[str, dict] = {}
    last: dict[str, dict] = {}
    for ev in sorted(events, key=lambda e: e.get("seq") or 0):
        iid = ev.get("instance_id", "")
        if not iid:
            continue
        if ev.get("op") == "recrop":
            geom[iid] = ev
        else:
            last[iid] = ev
    n["events"] = len(events)
    n["superseded"] = len(events) - len(last) - len(geom)

    # ── 几何通道 ──
    for iid, ev in geom.items():
        it = items.get(iid)
        rec = rec_of.get(iid)
        if it is None or rec is None:
            n["unknown"] += 1
            continue
        png = apply_recrop(book_out_dir, rec, ev["bbox"])
        if png is None:
            n["recrop_failed"] += 1
            continue
        n["recropped"] += 1
        it.note = "recropped"
        gray = cv2.imdecode(np.frombuffer(png, np.uint8),
                            cv2.IMREAD_GRAYSCALE)
        # 已进库的实例：库里的真源与派生一起刷新，否则检索用的还是错形
        if db.conn.execute("SELECT 1 FROM admissions WHERE instance_id=?",
                           (iid,)).fetchone():
            db.refresh_instance_patch(iid, png,
                                      bbox=[float(v) for v in ev["bbox"]])
            n["recrop_refreshed_db"] += 1

    # ── 裁决通道 ──
    # 排除名单守门：名单里的字位不进库（用户 2026-08-25 定的口径）。
    # 页面本就不出它们的卡，这里防的是旧批次事件与手写事件文件。
    excluded = load_exclusions()
    for ev in last.values():
        it = items.get(ev.get("instance_id", ""))
        if it is None:
            n["unknown"] += 1
            continue
        if it.instance_id in excluded:
            # 名单里的图块无论事件说什么都不进库；队列行也钉成 excluded
            it.status = STATUS_EXCLUDED
            it.decided_char = None
            it.provenance = None
            it.note = "excluded:" + str(
                excluded[it.instance_id].get("reason", ""))
            n["excluded"] += 1
            continue
        op = ev.get("op")
        if op == "confirm":
            char = (ev.get("char") or "").strip()
            if not char:
                n["invalid"] += 1
                continue
            if ev.get("admit") is False:
                # 仅定字·不入库：图块混有无法剥离的残余，字形不当范例
                it.status = STATUS_LABEL_ONLY
                it.decided_char = char
                it.provenance = None
                n["label_only"] += 1
                continue
            gray = cv2.imread(str(root / it.patch_path), cv2.IMREAD_GRAYSCALE)
            if gray is None:
                n["missing_patch"] += 1
                continue
            rec = rec_of.get(it.instance_id)
            admitted = db.admit_instance(
                it.instance_id, char, (root / it.patch_path).read_bytes(),
                provenance="human",
                evidence={"event": {k: ev.get(k) for k in
                                    ("op", "char", "batch", "seq", "ts")},
                          "doubts": it.doubts, "ocr": it.ocr,
                          "align": it.align, "match": it.match},
                edition_tag=edition, page=it.page, col=it.col, idx=it.idx,
                bbox=list(rec.bbox) if rec else None,
                ink_ratio=rec.ink_ratio if rec else None,
                width=rec.width if rec else None,
                height=rec.height if rec else None,
                semantic=vmap.semantic(char))
            n["admitted" if admitted else "already_admitted"] += 1
            it.status = STATUS_CONFIRMED
            it.decided_char = char
            it.provenance = "human"
        elif op == "not_a_char":
            it.status = STATUS_NOT_A_CHAR
            it.decided_char = None
            it.provenance = None
            n["not_a_char"] += 1
        elif op == "skip":
            # 存疑跳过：只对还没定的项生效，不把已确认的打回去
            if it.status in (STATUS_PENDING, STATUS_SKIPPED):
                it.status = STATUS_SKIPPED
            n["skipped"] += 1
        else:
            n["invalid"] += 1

    with open(queue_path, "w", encoding="utf-8") as f:
        for iid in order:
            f.write(items[iid].to_json() + "\n")

    _refresh_progress_pending(seed_dir, items)
    return {"events": len(events), **dict(n)}


def _refresh_progress_pending(seed_dir: Path,
                              items: dict[str, SeedItem]) -> None:
    """progress：pending = 仍待裁决（pending_review + skipped）。"""
    progress = _load_progress(seed_dir)
    open_by_page: Counter = Counter()
    for it in items.values():
        if it.status in (STATUS_PENDING, STATUS_SKIPPED):
            open_by_page[it.page] += 1
    for page, st in progress.get("pages", {}).items():
        st["pending"] = open_by_page.get(page, 0)
    all_pages = sorted(progress.get("pages", {}), key=_page_key)
    _save_progress(seed_dir, progress, all_pages)


def scrub_nonchar(book_out_dir: str | Path) -> dict:
    """对既有队列的待审行复扫空白/非字（detect_nonchar 加规则后回填存量）。

    只动 pending_review / skipped 行：命中 → status=not_a_char、
    note=auto:{reason}；不进库不删行（审计保留）。队列整文件重写，幂等。
    """
    book_out_dir = Path(book_out_dir)
    root = book_out_dir / "phase4_chars"
    seed_dir = book_out_dir / SEED_DIR
    queue_path = seed_dir / "queue.jsonl"
    if not queue_path.exists():
        raise FileNotFoundError(f"队列不存在: {queue_path}（先跑 seed）")

    order: list[str] = []
    items: dict[str, SeedItem] = {}
    for line in queue_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        it = SeedItem.from_json(line)
        if it.instance_id not in items:
            order.append(it.instance_id)
        items[it.instance_id] = it

    tail_idx: dict[tuple[str, int], int] = {}
    page_anchored: dict[str, bool] = {}
    for it in items.values():
        k = (it.page, it.col)
        tail_idx[k] = max(tail_idx.get(k, -1), it.idx)
        if (it.context or {}).get("ref_char"):
            page_anchored[it.page] = True

    n = Counter()
    for it in items.values():
        if it.status not in (STATUS_PENDING, STATUS_SKIPPED):
            continue
        gray = cv2.imread(str(root / it.patch_path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            n["missing_patch"] += 1
            continue
        reason = detect_nonchar(
            gray, it.ocr, (it.context or {}).get("ref_char"),
            is_tail=(it.idx == tail_idx[(it.page, it.col)]),
            page_anchored=page_anchored.get(it.page, False))
        if reason:
            it.status = STATUS_NOT_A_CHAR
            it.note = f"auto:{reason}"
            it.decided_char = None
            it.provenance = None
            n[f"auto_{reason}"] += 1
        else:
            n["kept"] += 1

    with open(queue_path, "w", encoding="utf-8") as f:
        for iid in order:
            f.write(items[iid].to_json() + "\n")
    _refresh_progress_pending(seed_dir, items)
    return dict(n)


def readjudicate_pending(book_out_dir: str | Path, db: GlyphDB,
                         variants: Path | None = None,
                         solo_cov: float = MATCH_SOLO_COV,
                         edition: str | None = None) -> dict:
    """裁决规则升级后，对既有队列的待审行按存证复裁（不重跑匹配）。

    scrub_nonchar 的姊妹函数：seed 重跑会整页重写队列、冲掉人裁，
    所以规则回填存量必须走这种「只动 pending/skipped 行」的窄口。
    用行内存下的 ocr/align/ref/doubts/match 重新调 admission_decision，
    如今能过的照 seed 同款方式进库（进库字取库匹配形）。存下的 match
    是 seed 当时对库的快照——只用它的 top 候选一致性，不重算 cov，
    宁可少放。首个用例：2026-08-24 形近家族「过闸对齐 × 库 top 一致」
    放行（人 处处 100% 却压给人点）。
    """
    book_out_dir = Path(book_out_dir)
    root = book_out_dir / "phase4_chars"
    seed_dir = book_out_dir / SEED_DIR
    queue_path = seed_dir / "queue.jsonl"
    if not queue_path.exists():
        raise FileNotFoundError(f"队列不存在: {queue_path}（先跑 seed）")
    vmap = VariantMap.load(variants)
    book = book_out_dir.name
    edition = edition or book

    order: list[str] = []
    items: dict[str, SeedItem] = {}
    for line in queue_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        it = SeedItem.from_json(line)
        if it.instance_id not in items:
            order.append(it.instance_id)
        items[it.instance_id] = it
    recs = {r.id: r for r in load_index(root)}

    n = Counter()
    for it in items.values():
        if it.status not in (STATUS_PENDING, STATUS_SKIPPED):
            continue
        m = it.match or {}
        cands = [(c, float(v)) for c, v in (m.get("candidates") or [])]
        admit_ok, channel = admission_decision(
            it.ocr, (it.align or {}).get("char"),
            (it.context or {}).get("ref_char"), it.doubts or [], vmap,
            match_char=m.get("char"), match_candidates=cands or None,
            match_guard=m.get("guard"), match_wmax=float(m.get("wmax") or 0.0),
            solo_cov=solo_cov)
        if not admit_ok:
            n["kept"] += 1
            continue
        if channel in ("match_replace", "match_ref_weak", "match_margin"):
            proposed = (it.align or {}).get("char") or \
                (it.context or {}).get("ref_char")
        elif channel in ("match_ref", "match_solo", "match_solo_ocr"):
            proposed = m.get("char") or (
                max(cands, key=lambda t: t[1])[0] if cands else None)
        else:
            proposed = it.proposed
        rec = recs.get(it.instance_id)
        if not proposed or rec is None:
            n["kept"] += 1
            continue
        gray = cv2.imread(str(root / rec.patch_path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            n["missing_patch"] += 1
            continue
        evidence = {"match": m, "ocr": it.ocr, "align": it.align,
                    "tier": it.tier, "channel": channel,
                    "readjudicated": True,
                    "ref": {"char": (it.context or {}).get("ref_char"),
                            "op": (it.context or {}).get("ref_op")}}
        prov = ("match" if channel in ("match_solo", "match_solo_ocr")
                else "align")
        db.admit_instance(
            it.instance_id, proposed, (root / rec.patch_path).read_bytes(),
            provenance=prov, evidence=evidence,
            edition_tag=edition, page=it.page, col=it.col, idx=it.idx,
            bbox=list(rec.bbox), ink_ratio=rec.ink_ratio, width=rec.width,
            height=rec.height, semantic=vmap.semantic(proposed))
        it.status = STATUS_AUTO
        it.decided_char = proposed
        it.provenance = prov
        it.note = f"{channel}:readj" if channel else "readj"
        n[f"auto_{channel or 'dual'}"] += 1

    with open(queue_path, "w", encoding="utf-8") as f:
        for iid in order:
            f.write(items[iid].to_json() + "\n")
    _refresh_progress_pending(seed_dir, items)
    return dict(n)
