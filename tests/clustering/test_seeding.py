"""seeding.py 单测：六条疑问判定、双信号零疑问自动进库、ingest 幂等、
断点续跑。全部用合成微型书（构造手法参考 test_align_label / test_match），
不依赖真实 output/ 数据。

fixture 一次搭好 7 页合成书并跑一遍 seed_book（module 级，跑一次全模块
断言）；ingest / resume 的测试放在只读断言之后，避免共享状态互踩。
"""

import json
import random

import cv2
import numpy as np
import pytest

from open_guji_cv.clustering.glyph_db import GlyphDB
from open_guji_cv.clustering.seed_queue import (DOUBT_DB_INCONSISTENT,
                                                DOUBT_DEGRADED_CROP,
                                                DOUBT_NEAR_FORM,
                                                DOUBT_REPLACE_ALIGN,
                                                DOUBT_SIGNAL_CONFLICT,
                                                DOUBT_WEAK_SINGLE,
                                                STATUS_AUTO, STATUS_CONFIRMED,
                                                STATUS_NOT_A_CHAR,
                                                STATUS_PENDING,
                                                STATUS_SKIPPED, SeedItem,
                                                parse_seed_events)
from open_guji_cv.clustering.seeding import ingest_decisions, seed_book
from open_guji_cv.clustering.synth import synthetic_glyph

# ── 合成书设计（每页一列；页文本 = 语料连续片段）──────────────────────
# 1: 全部双信号一致零疑问 → 全页自动进库
# 2: idx10 载体给错字「馬」（真字 致）→ signal_conflict + replace_align
# 3: idx9 载体给异体「珎」（真字 珍，测试 variants 表归一）→ 仅 replace_align
# 4: idx6 是形近家族字「大」→ near_form
# 5: idx0「弔」库里预置了完全不同形状的刻例 → db_inconsistent
# 6: idx3 图块手工造残留（碰边伸进核心区）→ degraded_crop
# 7: 页文本不在语料里（锚定失败，无对齐）→ weak_single / 单信号高置信
PAGES = {
    # 注意别在本页放形近家族字（日/大/人…）：本页是「纯净双信号全 auto」
    # 的样例页，家族字会触发 near_form 疑问（2026-08-24 日/曰 入家族后
    # 「日」也算）——那是对的行为，但不是本页要测的
    "1": "天地玄黃宇宙洪荒星月盈昃辰宿列張寒來暑往秋收冬藏",
    "2": "閏餘成歲律呂調陽雲騰致雨露結為霜金生麗水玉出崑岡",
    "3": "劍號巨闕珠稱夜光果珍李柰菜重芥薑海鹹河淡鱗潛羽翔",
    "4": "龍師火帝鳥官大皇始制文字乃服衣裳推位讓國有虞陶唐",
    "5": "弔民伐罪周發殷湯愛育黎首臣伏戎羌",
    "6": "遐邇壹體率賓歸王鳴鳳在樹白駒食場",
    "7": "化被草木賴及萬方",          # 不进语料 → 整页无对齐
}
CORPUS_PAGES = ("1", "2", "3", "4", "5", "6")
ALTERED = {("2", 10): "馬", ("3", 9): "珎"}      # 载体（OCR）故意给的字
PROBS = {("7", 1): 0.30}                          # 低置信槽位
EMPTY_OCR = {("7", 2)}                            # OCR 空识别槽位
DEGRADED = {("6", 3)}                             # 手工残留图块
BOOK = "tb"


def _glyph(ch: str) -> np.ndarray:
    return synthetic_glyph(random.Random(ord(ch)))        # 64×64 {0,1}


def _patch(ch: str) -> np.ndarray:
    """80×80 灰度图块：64×64 字形居中，四周 8px padding，干净不碰边。"""
    canvas = np.full((80, 80), 245, dtype=np.uint8)
    region = canvas[8:72, 8:72]
    region[_glyph(ch) > 0] = 20
    return canvas


def _degraded_patch() -> np.ndarray:
    """主体方块（不碰边）+ 从左边界伸进核心区的残带 → residue/degraded。"""
    canvas = np.full((80, 80), 245, dtype=np.uint8)
    canvas[25:55, 30:60] = 20
    canvas[36:45, 0:14] = 20
    return canvas


def _square_norm() -> np.ndarray:
    """与任何笔画字形都对不上的库内刻例（制造 db_inconsistent）。"""
    sq = np.zeros((64, 64), dtype=np.uint8)
    sq[12:52, 12:52] = 1
    return sq


def build_book(root):
    """phase4_chars（index.jsonl + 图块）+ OCR 载体 + 语料 + 异体表。"""
    book_dir = root / BOOK
    chars_dir = book_dir / "phase4_chars"
    (chars_dir / "patches").mkdir(parents=True)

    index_lines, carrier_lines = [], []
    for page, text in PAGES.items():
        for i, gold in enumerate(text):
            iid = f"{BOOK}:{page}:1:{i}"
            rel = f"patches/{page}_{i}.png"
            img = _degraded_patch() if (page, i) in DEGRADED else _patch(gold)
            cv2.imwrite(str(chars_dir / rel), img)
            index_lines.append(json.dumps(
                {"id": iid, "book": BOOK, "page": page, "col": 1, "idx": i,
                 "bbox": [0, 0, 80, 80], "cell_type": "char",
                 "ocr_text": None, "ocr_confidence": 0.0, "patch_path": rel,
                 "ink_ratio": 0.2, "height": 64, "width": 64, "flags": []},
                ensure_ascii=False))
            ocr_char = "" if (page, i) in EMPTY_OCR \
                else ALTERED.get((page, i), gold)
            carrier_lines.append(json.dumps(
                {"id": iid, "char": ocr_char,
                 "prob": PROBS.get((page, i), 0.92)}, ensure_ascii=False))
    (chars_dir / "index.jsonl").write_text(
        "".join(x + "\n" for x in index_lines), encoding="utf-8")
    (chars_dir / "ocr_carrier.jsonl").write_text(
        "".join(x + "\n" for x in carrier_lines), encoding="utf-8")

    corpus_path = root / "corpus.txt"
    corpus_path.write_text("\n".join(PAGES[p] for p in CORPUS_PAGES),
                           encoding="utf-8")
    variants_path = root / "variants.tsv"
    variants_path.write_text("珎\t珍\n", encoding="utf-8")
    return book_dir, corpus_path, variants_path


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    root = tmp_path_factory.mktemp("seedbook")
    book_dir, corpus_path, variants_path = build_book(root)
    db = GlyphDB(root / "glyph.db")
    # 预置库：一个与真实「弔」字形完全不同的已验证刻例（人工 provenance）
    sq = _square_norm()
    png = cv2.imencode(".png", (255 - sq * 255).astype(np.uint8))[1].tobytes()
    assert db.admit_instance("pre:9:1:1", "弔", png, sq, provenance="human")
    summary = seed_book(book_dir, db, corpus_path, variants=variants_path)
    yield {"root": root, "book_dir": book_dir, "db": db, "summary": summary,
           "corpus": corpus_path, "variants": variants_path}
    db.close()


def _queue(seeded) -> dict[str, SeedItem]:
    path = seeded["book_dir"] / "phase9_seed" / "queue.jsonl"
    out: dict[str, SeedItem] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            it = SeedItem.from_json(line)
            out[it.instance_id] = it
    return out


def _admitted_ids(db) -> set[str]:
    return {r[0] for r in db.conn.execute(
        "SELECT instance_id FROM admissions").fetchall()}


# ── 双信号一致零疑问 → 自动进库 ──────────────────────────────────────

def test_auto_admit_dual_signal_zero_doubt(seeded):
    q = _queue(seeded)
    admitted = _admitted_ids(seeded["db"])
    for i, ch in enumerate(PAGES["1"]):
        it = q[f"{BOOK}:1:1:{i}"]
        assert it.status == STATUS_AUTO and it.doubts == []
        assert it.decided_char == ch and it.provenance == "align"
        assert it.tier == "clean"
        assert it.instance_id in admitted            # 真进了库
    # 审计行带完整证据：ocr / align / match 都在
    it = q[f"{BOOK}:1:1:0"]
    assert it.ocr["char"] == "天" and it.align == {"char": "天", "op": "equal"}
    assert it.match is not None and "verdict" in it.match


def test_admission_evidence_recorded(seeded):
    row = seeded["db"].conn.execute(
        "SELECT provenance, evidence FROM admissions WHERE instance_id=?",
        (f"{BOOK}:1:1:0",)).fetchone()
    assert row[0] == "align"
    ev = json.loads(row[1])
    assert ev["ocr"]["char"] == "天" and ev["align"]["op"] == "equal"
    assert "match" in ev


# ── 六条疑问判定 ─────────────────────────────────────────────────────

def test_doubt_signal_conflict_context_rescue(seeded):
    """载体「馬」 vs 语料「致」：双信号打架不再一律人审——语料字入池
    （九轮实审 118 例 92% 语料对）+ 同列 LM 裁决出「致」且 margin 过阈
    → context provenance 进库；疑问码照记（审计）。"""
    it = _queue(seeded)[f"{BOOK}:2:1:10"]
    assert it.status == STATUS_AUTO and it.provenance == "context"
    assert it.decided_char == "致"
    assert DOUBT_SIGNAL_CONFLICT in it.doubts
    assert DOUBT_REPLACE_ALIGN in it.doubts         # replace 位天然也命中 6
    assert it.ocr["char"] == "馬" and it.align == {"char": "致", "op": "replace"}
    assert it.instance_id in _admitted_ids(seeded["db"])


def test_doubt_replace_align_alone_when_semantically_equal(seeded):
    """异体（珎→珍 语义同字）不算双信号打架；七轮起走上下文通道进库
    ——裁决字与整理本语义一致（单候选防护第 ③ 条的后半支），
    字形层保留精确异体「珎」。"""
    it = _queue(seeded)[f"{BOOK}:3:1:9"]
    assert it.status == STATUS_AUTO and it.provenance == "context"
    assert it.decided_char == "珎"                   # 字形层不归并异体
    assert it.doubts == [DOUBT_REPLACE_ALIGN]
    assert it.ocr["char"] == "珎" and it.align["char"] == "珍"


def test_doubt_weak_single(seeded):
    q = _queue(seeded)
    low = q[f"{BOOK}:7:1:1"]                         # 无对齐 + prob 0.30
    empty = q[f"{BOOK}:7:1:2"]                       # 无对齐 + OCR 空识别
    for it in (low, empty):
        assert it.status == STATUS_PENDING
        assert DOUBT_WEAK_SINGLE in it.doubts
        assert it.align is None
    assert empty.ocr is None and empty.proposed is None


def test_single_signal_high_prob_still_pending(seeded):
    """单信号高置信：六条全不命中，但双信号不齐 → 仍 pending，不自动进库。"""
    it = _queue(seeded)[f"{BOOK}:7:1:0"]
    assert it.status == STATUS_PENDING and it.doubts == []
    assert it.note == "single_signal"
    assert it.instance_id not in _admitted_ids(seeded["db"])


def test_doubt_degraded_crop(seeded):
    """双信号一致 + 仅 degraded：七轮起 dual_degraded 通道直接进库
    （前 13 页实审 58/58 全数照准）。"""
    it = _queue(seeded)[f"{BOOK}:6:1:3"]
    assert it.status == STATUS_AUTO and it.note == "dual_degraded"
    assert it.tier == "degraded"
    assert it.doubts == [DOUBT_DEGRADED_CROP]        # 疑问照记（审计）


def test_doubt_near_form(seeded):
    it = _queue(seeded)[f"{BOOK}:4:1:6"]             # 「大」∈ 大/太 家族
    assert it.status == STATUS_PENDING
    assert it.doubts == [DOUBT_NEAR_FORM]


def test_doubt_db_inconsistent(seeded):
    """库里已有「弔」但形状对不上（verify 全 diff）→ 库内不自洽。"""
    it = _queue(seeded)[f"{BOOK}:5:1:0"]
    assert it.status == STATUS_PENDING
    assert DOUBT_DB_INCONSISTENT in it.doubts
    assert it.proposed == "弔"


def test_summary_counts(seeded):
    s = seeded["summary"]
    n_slots = sum(len(t) for t in PAGES.values())
    assert s["n_slots"] == n_slots
    assert s["n_auto"] + s["n_pending"] == n_slots
    # 预期 pending：4:6 near_form / 5:0 db_inconsistent + 第 7 页整页
    # （8 格，未锚定上下文通道关闭）；2:10、3:9 走 context、
    # 6:3 走 dual_degraded 进库
    assert s["n_pending"] == 2 + len(PAGES["7"])
    assert s.get("n_auto_context", 0) == 2
    assert "tb:4:1:6" in {i for i in _queue(seeded)
                          if _queue(seeded)[i].status == STATUS_PENDING}
    assert s["doubt_counts"][DOUBT_WEAK_SINGLE] == 2
    assert s["pages_processed"] == len(PAGES)


# ── 断点续跑 ─────────────────────────────────────────────────────────

def test_resume_skips_done_pages(seeded):
    progress = json.loads(
        (seeded["book_dir"] / "phase9_seed" / "progress.json")
        .read_text(encoding="utf-8"))
    assert all(st["done"] for st in progress["pages"].values())
    assert progress["pointer"] is None

    before = len(_queue(seeded))
    s2 = seed_book(seeded["book_dir"], seeded["db"], seeded["corpus"],
                   variants=seeded["variants"])
    assert s2["pages_processed"] == 0
    assert s2["pages_skipped_done"] == len(PAGES)
    assert len(_queue(seeded)) == before             # 队列没有重复行


def test_max_pages_limits_this_run(tmp_path):
    book_dir, corpus_path, variants_path = build_book(tmp_path)
    db = GlyphDB(tmp_path / "g.db")
    try:
        s1 = seed_book(book_dir, db, corpus_path, variants=variants_path,
                       max_pages=2)
        assert s1["pages_processed"] == 2
        progress = json.loads(
            (book_dir / "phase9_seed" / "progress.json")
            .read_text(encoding="utf-8"))
        assert progress["pointer"] == "3"            # 推进指针指向下一页
        s2 = seed_book(book_dir, db, corpus_path, variants=variants_path)
        assert s2["pages_skipped_done"] == 2
        assert s2["pages_processed"] == len(PAGES) - 2
    finally:
        db.close()


# ── 决策回收（放最后：会改写共享 fixture 的队列状态）──────────────────

def test_ingest_decisions_and_idempotency(seeded):
    db = seeded["db"]
    text = "\n".join([
        'GUJI-SEED-EVENT {"op": "confirm", "instance_id": "tb:7:1:3", '
        '"char": "木", "batch": "b1", "seq": 1}',
        'GUJI-SEED-EVENT {"op": "not_a_char", "instance_id": "tb:5:1:0", '
        '"batch": "b1", "seq": 2}',
        'GUJI-SEED-EVENT {"op": "skip", "instance_id": "tb:7:1:0", '
        '"batch": "b1", "seq": 3}',
    ])
    events = parse_seed_events(text)
    assert len(events) == 3

    r1 = ingest_decisions(seeded["book_dir"], db, events)
    assert r1["admitted"] == 1
    q = _queue(seeded)
    assert q["tb:7:1:3"].status == STATUS_CONFIRMED
    assert q["tb:7:1:3"].decided_char == "木"
    assert q["tb:7:1:3"].provenance == "human"
    assert q["tb:5:1:0"].status == STATUS_NOT_A_CHAR
    assert q["tb:7:1:0"].status == STATUS_SKIPPED
    row = db.conn.execute(
        "SELECT provenance FROM admissions WHERE instance_id='tb:7:1:3'"
    ).fetchone()
    assert row == ("human",)

    # 幂等：重复回收同一批事件，不重复进库、状态不变
    n_before = db.conn.execute("SELECT COUNT(*) FROM admissions").fetchone()[0]
    r2 = ingest_decisions(seeded["book_dir"], db, events)
    assert r2.get("admitted", 0) == 0 and r2["already_admitted"] == 1
    assert db.conn.execute(
        "SELECT COUNT(*) FROM admissions").fetchone()[0] == n_before
    q2 = _queue(seeded)
    assert q2["tb:7:1:3"].status == STATUS_CONFIRMED
    assert q2["tb:5:1:0"].status == STATUS_NOT_A_CHAR

    # not_a_char / skip 不进库
    admitted = _admitted_ids(db)
    assert "tb:5:1:0" not in admitted and "tb:7:1:0" not in admitted

    # progress 的 pending 随裁决下降（第 5 页清零；skip 留队列）
    progress = json.loads(
        (seeded["book_dir"] / "phase9_seed" / "progress.json")
        .read_text(encoding="utf-8"))
    assert progress["pages"]["5"]["pending"] == 0
    assert progress["pages"]["7"]["pending"] == len(PAGES["7"]) - 1


def test_ingest_label_only_and_last_wins(seeded):
    """仅定字·不入库（admit:false）+ 同字位事件按 seq 后到覆盖。"""
    db = seeded["db"]
    text = "\n".join([
        # 图块混残余：定字「珍」但字形不进库
        'GUJI-SEED-EVENT {"op": "confirm", "instance_id": "tb:4:1:6", '
        '"char": "大", "admit": false, "batch": "b2", "seq": 1}',
        # confirm 后撤销（skip 后到）→ 最终不进库、留队列（取 pending 字位）
        'GUJI-SEED-EVENT {"op": "confirm", "instance_id": "tb:7:1:1", '
        '"char": "被", "batch": "b2", "seq": 2}',
        'GUJI-SEED-EVENT {"op": "skip", "instance_id": "tb:7:1:1", '
        '"batch": "b2", "seq": 3}',
    ])
    events = parse_seed_events(text)
    r = ingest_decisions(seeded["book_dir"], db, events)
    assert r["label_only"] == 1
    assert r.get("admitted", 0) == 0          # 两条 confirm 都没进库

    q = _queue(seeded)
    it = q["tb:4:1:6"]
    assert it.status == "confirmed_label_only"
    assert it.decided_char == "大" and it.provenance is None
    assert q["tb:7:1:1"].status == STATUS_SKIPPED

    admitted = _admitted_ids(db)
    assert "tb:4:1:6" not in admitted and "tb:7:1:1" not in admitted


def test_admission_decision_match_ref():
    """五轮定型：自动判断只看 库匹配 × 整理本；OCR 不参与（只供候选）。"""
    from open_guji_cv.clustering.seed_queue import (DOUBT_DB_INCONSISTENT,
                                                    DOUBT_DEGRADED_CROP,
                                                    DOUBT_NEAR_FORM)
    from open_guji_cv.clustering.seeding import admission_decision
    from open_guji_cv.clustering.variants import VariantMap
    vmap = VariantMap({})
    hi = {"char": "文", "prob": 0.999}
    lo = {"char": "文", "prob": 0.4}
    # 常规通道：过闸对齐一致 + 零疑问（载体只是运输工具）
    assert admission_decision(lo, "文", None, [], vmap) == (True, None)
    # 双信号一致 + 仅 degraded → dual_degraded 通道（58/58 实证）
    assert admission_decision(lo, "文", None, [DOUBT_DEGRADED_CROP],
                              vmap, match_char="文") == (True, "dual_degraded")
    # 库 × 整理本通道（OCR 认错也不碍事：非 dual 场景）
    assert admission_decision({"char": "又", "prob": 0.99}, "文", None,
                              [DOUBT_DEGRADED_CROP],
                              vmap, match_char="文") == (True, "match_ref")
    assert admission_decision({"char": "又", "prob": 0.99}, None, "文",
                              [], vmap, match_char="文") == (True, "match_ref")
    assert admission_decision(None, None, "文", [DOUBT_DEGRADED_CROP],
                              vmap, match_char="文") == (True, "match_ref")
    # OCR prob 本身不是通道（strong_dual/triple 已废）：无过闸对齐时
    # 单靠 OCR 高置信 + 免闸参考不能进（需 match 或 dual）
    assert admission_decision(hi, None, "文", [], vmap)[0] is False
    # 库匹配与整理本不同字 / 无整理本 → 不进（用非 dual 场景隔离验证）
    assert admission_decision({"char": "又", "prob": 0.9}, "文", None,
                              [DOUBT_DEGRADED_CROP],
                              vmap, match_char="又")[0] is False
    assert admission_decision(lo, None, None, [], vmap,
                              match_char="文")[0] is False
    # near_form / db_inconsistent 仍拦
    assert admission_decision(lo, "文", None,
                              [DOUBT_DEGRADED_CROP, DOUBT_NEAR_FORM],
                              vmap, match_char="文")[0] is False
    assert admission_decision(lo, None, "文", [DOUBT_DB_INCONSISTENT],
                              vmap, match_char="文")[0] is False


def test_match_ref_accepts_unsure_top_candidate():
    """R2（十四轮全量交叉分析）：库 × 整理本通道放宽到 top 候选。

    文本证据 × 形状证据同源性为零，529 条人审难例回放 144/144 全对，
    其中 33 条属形近家族也全对——形近护栏防的是形状判据，文本证据
    不受形状干扰，本就该穿透它。
    """
    from open_guji_cv.clustering.seed_queue import DOUBT_NEAR_FORM
    from open_guji_cv.clustering.seeding import admission_decision
    from open_guji_cv.clustering.variants import VariantMap
    vmap = VariantMap({})
    lo = {"char": "又", "prob": 0.4}
    # 库没到 same 档（match_char=None），但 top 候选与整理本一致 → 进库
    assert admission_decision(lo, "文", None, [], vmap,
                              match_candidates=[("文", 0.96), ("又", 0.90)]
                              ) == (True, "match_ref")
    # 免闸参考（无过闸对齐）同样算数
    assert admission_decision(lo, None, "文", [], vmap,
                              match_candidates=[("文", 0.96)]
                              ) == (True, "match_ref")
    # 形近家族**仍然拦**：交叉分析里 corpus×db 一致的 33 条形近字虽然
    # 全对，但 n=33 撑不起拆护栏；而反例（已/巳、人/入、日/曰）恰恰都
    # 出在这一族。放宽与否留给后续更大样本，当前保守。
    assert admission_decision(lo, "日", None, [DOUBT_NEAR_FORM], vmap,
                              match_candidates=[("日", 0.96)])[0] is False
    # 库 top 与整理本不一致 → 仍不进（这正是 4 条 OCR×库 反例的形态）
    assert admission_decision(lo, "巳", None, [], vmap,
                              match_candidates=[("已", 0.949)])[0] is False
    # 没有整理本时本通道不生效（那是 match_solo 的地盘）
    assert admission_decision(lo, None, None, [], vmap,
                              match_candidates=[("文", 0.96)])[0] is False


def test_admission_decision_match_solo():
    """十轮定案（十一轮上调 0.99）：无整理本锚定时，库内形状验证
    cov ≥ 0.99 单独放行。"""
    from open_guji_cv.clustering.seed_queue import (DOUBT_NEAR_FORM,
                                                    DOUBT_WEAK_SINGLE)
    from open_guji_cv.clustering.seeding import admission_decision
    from open_guji_cv.clustering.variants import VariantMap
    vmap = VariantMap({})
    lo = {"char": "又", "prob": 0.4}
    # same 档（cov 1.0）无整理本 → match_solo；weak_single 不拦
    assert admission_decision(lo, None, None, [DOUBT_WEAK_SINGLE], vmap,
                              match_char="文", match_candidates=[("文", 1.0)]
                              ) == (True, "match_solo")
    # unsure 带（char None）但顶部候选 cov 过阈也放行——OCR 空识别也不碍
    assert admission_decision(None, None, None, [DOUBT_WEAK_SINGLE], vmap,
                              match_candidates=[("文", 0.995)]
                              ) == (True, "match_solo")
    # cov 差一点（旧阈 0.98 放行档）→ 不进
    assert admission_decision(lo, None, None, [], vmap,
                              match_candidates=[("文", 0.985)])[0] is False
    # 有整理本参照的字位不走本通道（归 match_ref / 人审管）
    assert admission_decision(lo, None, "文", [DOUBT_WEAK_SINGLE], vmap,
                              match_candidates=[("文", 1.0)])[0] is False
    # 护栏触发（never_match/conflict）→ 禁
    assert admission_decision(lo, None, None, [], vmap,
                              match_candidates=[("日", 0.995), ("曰", 0.97)],
                              match_guard="never_match")[0] is False
    # 不同语义的对手也到阈档 → 形近存疑，禁
    assert admission_decision(lo, None, None, [], vmap,
                              match_candidates=[("文", 0.995), ("又", 0.991)]
                              )[0] is False
    # 同语义异体不算对手（珎/珍 都到档也放行，取 cov 最高形）
    vm2 = VariantMap({"珎": "珍"})
    assert admission_decision(lo, None, None, [], vm2,
                              match_candidates=[("珎", 0.995), ("珍", 0.991)]
                              ) == (True, "match_solo")
    # near_form 仍拦
    assert admission_decision(lo, None, None, [DOUBT_NEAR_FORM], vmap,
                              match_candidates=[("文", 0.995)])[0] is False
    # 残差窗防线（揀/棟 实锤）：wmax 超阈 + OCR 不背书 → 禁；
    # OCR 字符背书（偏旁读对）则放行；wmax 达标本来就行
    assert admission_decision(lo, None, None, [], vmap,
                              match_candidates=[("棟", 0.991)],
                              match_wmax=13.0)[0] is False
    assert admission_decision({"char": "棟", "prob": 0.5}, None, None, [],
                              vmap, match_candidates=[("棟", 0.991)],
                              match_wmax=13.0) == (True, "match_solo")
    assert admission_decision(lo, None, None, [], vmap,
                              match_candidates=[("棟", 0.991)],
                              match_wmax=12.0) == (True, "match_solo")


def test_build_seed_lm_mixture_and_cache(tmp_path):
    """LM 混合：无通用语料退化为纯本书；有则线性混合并落盘缓存。"""
    from open_guji_cv.clustering.seeding import build_seed_lm
    book_text = "四庫全書總目提要"
    assert build_seed_lm(book_text, None).name == "ngram"
    gen = tmp_path / "general.txt"
    gen.write_text("欽定四庫全書\n" * 50, encoding="utf-8")
    lm = build_seed_lm(book_text, [gen])
    assert lm.name.startswith("mix(")
    assert (tmp_path / ".general_lm_cache.json").exists()
    # 二次构造走缓存（源未变）；源变了重训不炸
    lm2 = build_seed_lm(book_text, [gen])
    assert lm2.logp("庫", ("四",)) == lm.logp("庫", ("四",))
    # 本书没见过、通用语料见过的搭配：混合后概率高于纯本书
    pure = build_seed_lm(book_text, None)
    assert lm.logp("定", ("欽",)) > pure.logp("定", ("欽",))


def test_context_crosses_columns(seeded):
    """列首/列尾的上下文接邻列（prev_/next_ 字段）。"""
    q = _queue(seeded)
    # 合成书每页只有 1 列 → 无邻列，prev/next 不出现（守拙不造假上下文）
    it = q["tb:2:1:0"]
    assert it.context and "prev_ocr" not in (it.context or {})


def test_detect_nonchar_rules():
    """空白/非字自动探测：R1 blank 任意位置；R2 tail_junk 只在锚定页。"""
    import numpy as np
    from open_guji_cv.clustering.seeding import detect_nonchar

    blank = np.full((80, 80), 245, dtype=np.uint8)          # 纯空白
    speck = blank.copy(); speck[40:42, 40:42] = 20          # 仅噪点（<6px）
    char = _patch("文")                                      # 真字
    bar = np.full((80, 80), 245, dtype=np.uint8)
    bar[70:76, 0:80] = 20                                    # 版框横线

    # R1：空白/纯噪点 → blank，位置无关
    assert detect_nonchar(blank, None, None, False, True) == "blank"
    assert detect_nonchar(speck, {"char": "司", "prob": 0.01},
                          None, True, True) == "blank"
    # 真字永不判 blank
    assert detect_nonchar(char, None, None, False, True) is None
    # R2：锚定页列尾 + 无参考 + OCR 垃圾 → tail_junk
    assert detect_nonchar(bar, {"char": "—", "prob": 0.5},
                          None, True, True) == "tail_junk"
    assert detect_nonchar(bar, {"char": "的", "prob": 0.02},
                          None, True, True) == "tail_junk"
    # 安全网：非列尾 / 未锚定 / 有参考字 / OCR 高置信汉字 → 不判
    assert detect_nonchar(bar, {"char": "—", "prob": 0.5},
                          None, False, True) is None
    assert detect_nonchar(bar, {"char": "—", "prob": 0.5},
                          None, True, False) is None
    assert detect_nonchar(bar, {"char": "—", "prob": 0.5},
                          "一", True, True) is None
    assert detect_nonchar(bar, {"char": "一", "prob": 0.9},
                          None, True, True) is None


def test_font_fallback_only_when_woodblock_weak(tmp_path):
    """字体兜底的三条纪律，逐条钉死（十六轮实测接线）。"""
    import numpy as np
    from open_guji_cv.clustering import seeding

    # 纪律 ②：只在刻本库弱时才查
    assert seeding.FONT_COV_GATE == 0.95
    # 纪律 ③：权重低于任何真证据
    from open_guji_cv.clustering.recognize_flow import (CORPUS_WEIGHT,
                                                        DB_WEIGHT, OCR_WEIGHT)
    assert seeding.FONT_WEIGHT < min(DB_WEIGHT, OCR_WEIGHT, CORPUS_WEIGHT)


def test_font_never_reaches_admission(tmp_path):
    """纪律 ①：准入裁决只认刻本库——admission_decision 根本没有字体入口。

    这是**接口层**的保证，比任何阈值都硬：字体候选进的是 fuse_priors 的
    extra（候选池），而 match_ref/match_solo 只读 match_candidates。
    """
    import inspect

    from open_guji_cv.clustering.seeding import admission_decision
    sig = inspect.signature(admission_decision)
    assert not [p for p in sig.parameters if "font" in p.lower()]


def test_seed_book_without_font_store_is_unchanged(seeded):
    """不给字体库时行为与从前完全一致（font_consulted 为 0）。"""
    assert seeded["summary"].get("font_consulted", 0) == 0
