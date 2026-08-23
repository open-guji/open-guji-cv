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
from .align_label import (carrier_slots, clean_labels, label_book,
                          page_reference)
from .crop_quality import assess_crop
from .extractor import CharInstance, load_index
from .glyph_db import GlyphDB, _unpng
from .match import NEVER_MATCH_FAMILIES, GlyphMatcher, MatchResult
from .normalize import normalize_patch
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


DEFAULT_STRONG_PROB = 0.995   # 「OCR 100%」强信号阈（显示层四舍五入到 100%）


def admission_decision(ocr: dict | None, align_char: str | None,
                       ref_char: str | None, doubts: list[str],
                       vmap: VariantMap,
                       strong_prob: float = DEFAULT_STRONG_PROB,
                       ) -> tuple[bool, bool]:
    """进库裁决：返回 (可自动进库, 是否走了强信号通道)。

    - 常规通道：双信号一致（OCR × 过闸对齐）且六条疑问全不命中；
    - **强信号通道**（首两页实审后加）：OCR prob ≥ strong_prob 且与
      整理本一致（过闸对齐字，或无对齐时的免闸参考字）时，
      **degraded_crop 单独不再拦**——实审校准：这类字位人工全数照准，
      机器分级的残留线索在双 100% 信号面前误报居多。
      near_form / db_inconsistent 仍然拦（形近与库不自洽正是毒化库的
      两条路，字对了字形也可能骑在两字之间）；signal_conflict /
      weak_single / replace_align 与强信号在逻辑上互斥，无需另判。
    """
    ocr_char = ocr["char"] if ocr else None
    dual = (ocr_char is not None and align_char is not None
            and vmap.semantic(ocr_char) == vmap.semantic(align_char))
    if dual and not doubts:
        return True, False
    corpus_char = align_char if align_char is not None else ref_char
    strong = (ocr is not None and ocr.get("prob", 0.0) >= strong_prob
              and ocr_char is not None and corpus_char is not None
              and vmap.semantic(ocr_char) == vmap.semantic(corpus_char))
    if strong and all(d == DOUBT_DEGRADED_CROP for d in doubts):
        return True, True
    return False, False


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
              strong_prob: float = DEFAULT_STRONG_PROB,
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
            for rec in page_recs:
                gray = cv2.imread(str(root / rec.patch_path),
                                  cv2.IMREAD_GRAYSCALE)
                if gray is None:
                    summary["n_missing_patch"] += 1
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
                admit_ok, strong = admission_decision(
                    ocr, al.char if al else None,
                    (ctx or {}).get("ref_char"), doubts, vmap, strong_prob)
                if admit_ok and proposed is None:
                    proposed = ocr["char"] if ocr else None

                item = SeedItem(instance_id=rec.id, book=book, page=page,
                                col=rec.col, idx=rec.idx,
                                patch_path=rec.patch_path, tier=tier,
                                ocr=ocr, align=align, proposed=proposed,
                                doubts=doubts, match=mr.to_dict(),
                                context=ctx)
                if admit_ok and proposed:
                    # 双信号一致（常规零疑问 / 强信号通道）→ align 进库
                    evidence = {"match": mr.to_dict(), "ocr": ocr,
                                "align": align, "tier": tier,
                                "crop": q.to_dict()}
                    if strong:
                        evidence["strong_dual"] = True
                        evidence["ref"] = {"char": (ctx or {}).get("ref_char"),
                                           "op": (ctx or {}).get("ref_op")}
                    admitted = db.admit_instance(
                        rec.id, proposed, (root / rec.patch_path).read_bytes(),
                        norm, provenance="align", evidence=evidence,
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
                    item.provenance = "align"
                    if strong:
                        item.note = "strong_dual"
                        summary["n_auto_strong"] = summary.get(
                            "n_auto_strong", 0) + 1
                    n_auto += 1
                else:
                    item.status = STATUS_PENDING
                    if not doubts:
                        # 六条全不命中但双信号不齐（单信号高置信）——
                        # 契约无对应疑问码，审查侧凭 status 出队即可
                        item.note = "single_signal"
                    doubt_counts.update(doubts)
                    n_pending += 1
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

    # progress：pending = 仍待裁决（pending_review + skipped）
    progress = _load_progress(seed_dir)
    open_by_page: Counter = Counter()
    for it in items.values():
        if it.status in (STATUS_PENDING, STATUS_SKIPPED):
            open_by_page[it.page] += 1
    for page, st in progress.get("pages", {}).items():
        st["pending"] = open_by_page.get(page, 0)
    all_pages = sorted(progress.get("pages", {}), key=_page_key)
    _save_progress(seed_dir, progress, all_pages)
    return {"events": len(events), **dict(n)}
