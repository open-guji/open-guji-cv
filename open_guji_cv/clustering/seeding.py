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

from .align_eval import build_ngram_index
from .align_label import (carrier_slots, clean_labels, is_han, label_book,
                          page_reference)
from .crop_quality import assess_crop
from .extractor import CharInstance, load_index
from .glyph_db import GlyphDB, _unpng
from .lm import BaseLM, CharNgramLM, InterpolatedLM, train_ngram
from .match import NEVER_MATCH_FAMILIES, GlyphMatcher, MatchResult
from .context_step import build_strategy
from .recognize_flow import ColumnContext, fuse_priors
from .normalize import normalize_patch, sauvola_binarize
from .verify import MISS_WMAX
from .seed_queue import (DOUBT_DB_INCONSISTENT, DOUBT_DEGRADED_CROP,
                         DOUBT_NEAR_FORM, DOUBT_REPLACE_ALIGN,
                         DOUBT_SIGNAL_CONFLICT, DOUBT_WEAK_SINGLE,
                         STATUS_AUTO, STATUS_CONFIRMED, STATUS_LABEL_ONLY,
                         STATUS_NOT_A_CHAR, STATUS_PENDING, STATUS_SKIPPED,
                         SeedItem)
from .variants import VariantMap

# weak_single 的 OCR prob 阈。**待 char-ocr 集标定**（设计 §3.5 条目 2），
# 当前 0.85 只是保守起点：book9 金标上 top1 88.75%，低置信段错误集中。
DEFAULT_PROB_THRESHOLD = 0.85

# 形近否决家族的全部成员（near_form 疑问用；单一事实源在 match.py）
NEAR_FORM_CHARS = frozenset(c for pair in NEVER_MATCH_FAMILIES for c in pair)

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

# match_solo 通道（十轮用户定案，十一轮上调）：无整理本锚定时，
# 库内形状验证 cov ≥ 此阈单独放行。初值 0.98 首日即出一例压线错
# （揀/棟 0.9802），用户裁定收紧到 0.99（约让出四成通道量换稳）；
# 护栏与形近防线见 admission_decision docstring。
MATCH_SOLO_COV = 0.99


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
    - **库 × 整理本通道**：库匹配完美档（verify same，cov ≥ 0.992 的
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
    near_form / db_inconsistent 仍拦（毒化库的两条路）。
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
    if (overridable and match_char is not None and corpus_char is not None
            and vmap.semantic(match_char) == vmap.semantic(corpus_char)):
        return True, "match_ref"
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
              edition: str | None = None, knn_k: int = 10,
              variants: str | Path | None = None) -> dict:
    """按页序逐页处理正文页（正文筛选交给调用方的 pages 参数）。

    断点续跑：progress.json 里 ``done`` 的页整页跳过；进库幂等
    （GlyphDB.admit_instance 按 instance_id 判重），中途崩掉重跑安全。
    max_pages 限制**本次调用**处理的页数（已完成页不计）。
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
    slots_by_page = carrier_slots(carrier_path)

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
    cols_by_page: dict[str, dict[int, list[tuple[int, str]]]] = {}
    for p in todo:
        cols: dict[int, list[tuple[int, str]]] = defaultdict(list)
        for col, idx, ch in slots_by_page.get(p, []):
            cols[col].append((idx, ch))
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

    # 队列：崩溃页残行清理（done 页永不重写；todo 页的旧行整页替换）
    queue_path = seed_dir / "queue.jsonl"
    todo_set = set(todo)
    if queue_path.exists():
        kept = [ln for ln in queue_path.read_text(encoding="utf-8").splitlines()
                if ln.strip()
                and json.loads(ln).get("page") not in todo_set]
        queue_path.write_text("".join(x + "\n" for x in kept),
                              encoding="utf-8")

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
                norm = normalize_patch(gray)
                mr = matcher.match(norm)

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
                if admit_ok and channel == "match_ref":
                    # 库 × 整理本通道的进库字取库匹配形——站着的是形状
                    # 证据（verify same）+ 整理本，OCR 只是旁证；否则
                    # 无对齐时 proposed 会落到 OCR 字（十轮实审：之 页
                    # OCR 报 芝，库 × 整理本同说 之，进库字必须是 之）
                    proposed = mr.char
                elif admit_ok and channel == "match_solo":
                    # 库匹配单独通道：进库字取库内验证 cov 最高的形
                    proposed = max(mr.candidates, key=lambda t: t[1])[0]
                elif admit_ok and proposed is None:
                    proposed = ocr["char"] if ocr else None

                item = SeedItem(instance_id=rec.id, book=book, page=page,
                                col=rec.col, idx=rec.idx,
                                patch_path=rec.patch_path, tier=tier,
                                ocr=ocr, align=align, proposed=proposed,
                                doubts=doubts, match=mr.to_dict(),
                                context=ctx)
                if admit_ok and proposed:
                    # 双信号一致（常规零疑问 / 强信号通道）→ align 进库；
                    # match_solo 无整理本参与，审计上以 match 记 provenance
                    prov = "match" if channel == "match_solo" else "align"
                    evidence = {"match": mr.to_dict(), "ocr": ocr,
                                "align": align, "tier": tier,
                                "crop": q.to_dict()}
                    if channel:
                        evidence["channel"] = channel
                        evidence["ref"] = {"char": (ctx or {}).get("ref_char"),
                                           "op": (ctx or {}).get("ref_op")}
                    admitted = db.admit_instance(
                        rec.id, proposed, (root / rec.patch_path).read_bytes(),
                        norm, provenance=prov, evidence=evidence,
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
                    # ② near_form / db_inconsistent 仍然只走人审；
                    # ③ 单候选的 margin=1.0 是平凡值——要求 ranked ≥2
                    #    （真竞争胜出）或裁决字与整理本一致。
                    ctx_admit = False
                    if (page_anchored
                            and DOUBT_NEAR_FORM not in doubts
                            and DOUBT_DB_INCONSISTENT not in doubts):
                        topk = [(ocr["char"], ocr["prob"])] if ocr else []
                        corpus_char = (al.char if al else None) or \
                            (ctx or {}).get("ref_char")
                        # 整理本字进候选池（八轮实审：OCR 认错时语料字
                        # 必须有资格被裁决；权重见 CORPUS_WEIGHT 注释）
                        extra = [(corpus_char, 1.0)] if corpus_char else None
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
                            evidence = {"decision": dec.to_dict(),
                                        "surface": surface,
                                        "sem_margin": sem_margin,
                                        "match": mr.to_dict(), "ocr": ocr,
                                        "align": align, "tier": tier,
                                        "crop": q.to_dict()}
                            admitted = db.admit_instance(
                                rec.id, surface,
                                (root / rec.patch_path).read_bytes(),
                                norm, provenance="context",
                                evidence=evidence, edition_tag=edition,
                                page=page, col=rec.col, idx=rec.idx,
                                bbox=list(rec.bbox),
                                ink_ratio=rec.ink_ratio, width=rec.width,
                                height=rec.height,
                                semantic=vmap.semantic(surface))
                            if admitted:
                                matcher.add(rec.id, surface, norm)
                                db_chars.add(surface)
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

            page_state[page] = {"total": len(page_recs), "auto": n_auto,
                                "pending": n_pending, "done": True}
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
    # 契约应用纪律：同一 instance_id 按 seq 后到覆盖——只应用每个字位
    # seq 最大的事件（confirm 后被 skip 撤销的，最终以 skip 为准）。
    last: dict[str, dict] = {}
    for ev in sorted(events, key=lambda e: e.get("seq") or 0):
        iid = ev.get("instance_id", "")
        if iid:
            last[iid] = ev
    n["events"] = len(events)
    n["superseded"] = len(events) - len(last)
    for ev in last.values():
        it = items.get(ev.get("instance_id", ""))
        if it is None:
            n["unknown"] += 1
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
                normalize_patch(gray), provenance="human",
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
