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
    # 8: idx10「已」是 SEMANTIC_MERGED_PAIRS 成员（已/巳 同词异写，
    # 2026-08-26 用户定：字形不重要，上下文文意才是判据）。载体故意
    # 给成家族搭档「巳」→ signal_conflict + near_form + replace_align
    # 三条疑问都命中，换作表里任何别的形近字这里就该卡人审——但
    # 已/巳 不该被同一道 near_form 闸拦住上下文通道，语料训练过这句
    # 原文，margin 应该过阈，走 context 通道自动进库判「已」。
    # （两侧各留 10 字不动——align_label 的 8-gram 锚定要求替换位
    # 至少一侧有 ≥8 个连续未改字符才能锚上，太短的页会整页无对齐）
    "8": "光風霽月虛懷若谷學海已至誠力行不倦志存高遠",
}
CORPUS_PAGES = ("1", "2", "3", "4", "5", "6", "8")
ALTERED = {("2", 10): "馬", ("3", 9): "珎", ("8", 10): "巳"}  # 载体故意给的字
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
    assert db.admit_instance("pre:9:1:1", "弔", png, provenance="human")
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
    """near_form 疑问照记（审计用），但 2026-08-27 起不再单独拦上下文
    通道——用户实锤 諭/論、曾/會、人/入这类家族反复要人工校对，而 154
    题盲测 n-gram 95.5%/大模型 98.7% 远胜字形层 64.3%，挡的一直是更可靠
    的证据。这条「大」OCR 与整理本本就一致（equal），语料训练过这句
    原文，上下文通道径直确认，不必再等人。"""
    it = _queue(seeded)[f"{BOOK}:4:1:6"]             # 「大」∈ 大/太 家族
    assert it.doubts == [DOUBT_NEAR_FORM]
    assert it.status == STATUS_AUTO and it.provenance == "context"
    assert it.decided_char == "大"


def test_semantic_merged_pair_context_bypasses_near_form(seeded):
    """已/巳 同词异写：near_form 挡字形通道，不挡上下文通道。

    「大」（上一测试）近形家族命中就只能人审；已/巳 不一样——它俩历史
    上就是同一个词的两种写法（charset_and_lm.md §四），字形层拦得对
    （近形护栏防的是形状判据自己会认错），但文意判断不该被同一道闸
    挡下。这条位载体故意给错成家族搭档「巳」，三条疑问全命中
    （signal_conflict + near_form + replace_align），换作表里任何别的
    形近字这里就该卡人审——但 SEMANTIC_MERGED_PAIRS 让它照走 context
    通道，按上下文判「已」自动进库。"""
    it = _queue(seeded)[f"{BOOK}:8:1:10"]
    assert it.ocr["char"] == "巳" and it.align == {"char": "已", "op": "replace"}
    assert set(it.doubts) == {DOUBT_SIGNAL_CONFLICT, DOUBT_NEAR_FORM,
                              DOUBT_REPLACE_ALIGN}
    assert it.status == STATUS_AUTO and it.provenance == "context"
    assert it.decided_char == "已"
    iid = it.instance_id
    assert iid in _admitted_ids(seeded["db"])

    # 释读（已）进 admissions.char/instances.semantic/queue.decided_char——
    # 用户显示看到、进最终文本的都是这个。字形（这条位载体给的形状信号
    # 是「巳」）进 instances.label/glyphs/exemplars——GlyphMatcher 的
    # 形状索引必须按刻本实际形状分类，绝不能被这次的释读污染，否则
    # 未来一个真刻成同一形状、该读别的字的实例会错误继承「已」。
    db = seeded["db"]
    label, semantic = db.conn.execute(
        "SELECT label, semantic FROM instances WHERE instance_id=?",
        (iid,)).fetchone()
    assert label == "巳" and semantic == "已"
    admitted_char = db.conn.execute(
        "SELECT char FROM admissions WHERE instance_id=?", (iid,)).fetchone()[0]
    assert admitted_char == "已"
    n_si = db.conn.execute(
        "SELECT n_confirmed FROM glyphs WHERE edition_tag=? AND char='巳'",
        (BOOK,)).fetchone()
    assert n_si and n_si[0] >= 1, "字形库必须按巳（实际形状）建条目"
    n_yi_has_this = db.conn.execute(
        """SELECT 1 FROM exemplars e JOIN glyphs g ON g.glyph_id=e.glyph_id
           WHERE g.edition_tag=? AND g.char='已' AND e.instance_id=?""",
        (BOOK, iid)).fetchone()
    assert n_yi_has_this is None, "这个实例不该出现在「已」的字形示例里"


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
    # 预期 pending：5:0 db_inconsistent + 第 7 页整页（8 格，未锚定上下文
    # 通道关闭）；2:10、3:9、4:6、8:5 走 context、6:3 走 dual_degraded
    # 进库——4:6「大」near_form 不再单独拦上下文通道（2026-08-27 起）
    assert s["n_pending"] == 1 + len(PAGES["7"])
    assert s.get("n_auto_context", 0) == 4
    assert "tb:4:1:6" in {i for i in _queue(seeded)
                          if _queue(seeded)[i].status == STATUS_AUTO}
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
    """仅定字·不入库（admit:false）+ 同字位事件按 seq 后到覆盖。

    第一个字位原用 tb:4:1:6（那时是 near_form pending 的样例）——
    2026-08-27 起 near_form 不再单独拦上下文通道，该字位改为 seed 时
    就自动进库，不再有 pending 状态可供本测试模拟人工事件，换成第 7
    页另一个未被别的测试占用的字位（该页无语料锚定，seed 后必 pending）。"""
    db = seeded["db"]
    text = "\n".join([
        # 图块混残余：定字但字形不进库
        'GUJI-SEED-EVENT {"op": "confirm", "instance_id": "tb:7:1:2", '
        '"char": "草", "admit": false, "batch": "b2", "seq": 1}',
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
    it = q["tb:7:1:2"]
    assert it.status == "confirmed_label_only"
    assert it.decided_char == "草" and it.provenance is None
    assert q["tb:7:1:1"].status == STATUS_SKIPPED

    admitted = _admitted_ids(db)
    assert "tb:7:1:2" not in admitted and "tb:7:1:1" not in admitted


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
    # 形近家族放行（2026-08-24，75 条人裁回放 35/35）：**过闸对齐 ×
    # 库 top 一致**时 near_form 穿透 match_ref——「人」处处 100% 匹配
    # 还压给人点，是这条改掉的
    assert admission_decision(lo, "文", None,
                              [DOUBT_DEGRADED_CROP, DOUBT_NEAR_FORM],
                              vmap, match_char="文") == (True, "match_ref")
    # 免闸参考（无过闸对齐）零家族样本 → near_form 照拦
    assert admission_decision(lo, None, "文", [DOUBT_NEAR_FORM],
                              vmap, match_char="文")[0] is False
    # replace 层对齐（REPLACE_ALIGN 疑问在）→ 照拦
    assert admission_decision(lo, "文", None,
                              [DOUBT_NEAR_FORM, DOUBT_REPLACE_ALIGN],
                              vmap, match_char="文")[0] is False
    # db_inconsistent 全通道仍拦
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
    # 形近家族（2026-08-24 放行）：n=33 时保守拦过，累到 75 条人裁
    # 回放（命中 35/35 全对、反例全落在两路不一致侧）后定案——
    # **过闸对齐 × 库 top 一致**穿透 near_form
    assert admission_decision(lo, "日", None, [DOUBT_NEAR_FORM], vmap,
                              match_candidates=[("日", 0.96)]
                              ) == (True, "match_ref")
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
    # 有整理本参照的字位不走 match_solo——十七轮起这个组合改由
    # match_ref_weak 放行（参考 × 库 双证据，25/25 回放），通道名必须
    # 区分开：审计上 solo 是「库单独说了算」，ref_weak 是「两路互证」
    assert admission_decision(lo, None, "文", [DOUBT_WEAK_SINGLE], vmap,
                              match_candidates=[("文", 1.0)]
                              ) == (True, "match_ref_weak")
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


def test_recrop_geometry_and_decision_are_independent(tmp_path):
    """十七轮定案：重切是几何事件、选字是裁决事件，互不覆盖。

    实批实锤（14:9:18 出现 recrop→skip→confirm→skip→recrop 的反复）：
    旧「后到覆盖」会把重切框整个丢掉、进库存下错位的原图字形。
    """
    root = tmp_path
    book_dir, corpus_path, variants_path = build_book(root)
    # 页图：seed 合成书没有，造一张——第 1 页图块 bbox [0,0,80,80]，
    # 页图放大一点，让新 bbox 有处可挪
    import cv2
    page_img = np.full((200, 200), 245, dtype=np.uint8)
    page_img[10:74, 10:74] = np.where(_glyph("天") > 0, 20, 245)
    cv2.imwrite(str(book_dir / "1.png"), page_img)

    db = GlyphDB(root / "g.db")
    try:
        seed_book(book_dir, db, corpus_path, variants=variants_path)
        iid = "tb:1:1:0"

        # ① 先 confirm（进库存的是旧图块），后 recrop → 库里的真源要刷新
        ev1 = [{"op": "confirm", "instance_id": iid, "char": "天",
                "batch": "b", "seq": 1},
               {"op": "recrop", "instance_id": iid, "char": "忽略我",
                "bbox": [5, 5, 80, 80], "batch": "b", "seq": 2}]
        r = ingest_decisions(book_dir, db, ev1)
        assert r["recropped"] == 1 and r["recrop_refreshed_db"] == 1
        # 图块与 index 都换成了新框
        import json as _json
        idx = {_json.loads(l)["id"]: _json.loads(l) for l in
               (book_dir / "phase4_chars" / "index.jsonl")
               .read_text(encoding="utf-8").splitlines()}
        assert idx[iid]["bbox"] == [5.0, 5.0, 80.0, 80.0]
        assert "recropped" in (idx[iid].get("flags") or [])
        # recrop 事件里的 char 被忽略（那是首版 UI 的脏字段）
        q = {SeedItem.from_json(l).instance_id: SeedItem.from_json(l)
             for l in (book_dir / "phase9_seed" / "queue.jsonl")
             .read_text(encoding="utf-8").splitlines() if l.strip()}
        assert q[iid].decided_char == "天"          # 仍是 confirm 的字
        assert q[iid].note == "recropped"
        # 库里的 bbox 已刷新
        row = db.conn.execute(
            "SELECT bbox FROM instances WHERE instance_id=?", (iid,)).fetchone()
        assert _json.loads(row[0]) == [5.0, 5.0, 80.0, 80.0]

        # ② 只 recrop 不定字 → 字位保持待审（重切完仍可独立选字）
        iid2 = "tb:1:1:1"
        # 先把它退回 pending（fixture 里它是 auto——直接对 pending 页字位测）
        iid2 = "tb:7:1:0"                       # 第 7 页无对齐 → pending
        cv2.imwrite(str(book_dir / "7.png"), page_img)
        r2 = ingest_decisions(book_dir, db, [
            {"op": "recrop", "instance_id": iid2,
             "bbox": [5, 5, 80, 80], "batch": "b", "seq": 3}])
        assert r2["recropped"] == 1
        q = {SeedItem.from_json(l).instance_id: SeedItem.from_json(l)
             for l in (book_dir / "phase9_seed" / "queue.jsonl")
             .read_text(encoding="utf-8").splitlines() if l.strip()}
        assert q[iid2].status == STATUS_PENDING     # 没定字就还在队列
        assert q[iid2].note == "recropped"

        # ③ 重切后再 confirm → 进库读的就是重切后的图块字节
        r3 = ingest_decisions(book_dir, db, [
            {"op": "confirm", "instance_id": iid2, "char": "化",
             "batch": "b", "seq": 4}])
        assert r3["admitted"] == 1
        png = db.conn.execute(
            "SELECT patch_png FROM instances WHERE instance_id=?",
            (iid2,)).fetchone()[0]
        # 十九轮起真源统一 canonical：库里存的 = canonical(重切后的图块)
        from open_guji_cv.clustering.canonical import canonical_png
        disk = cv2.imread(str(book_dir / "phase4_chars" / q[iid2].patch_path),
                          cv2.IMREAD_GRAYSCALE)
        assert png == canonical_png(disk)
    finally:
        db.close()


def test_readjudicate_pending_near_form_corpus_db(tmp_path):
    """规则升级回填存量：readjudicate_pending 只动待审行。

    形近家族放行后，存证里「过闸对齐 × 库 top 一致」的 pending 行
    应复裁进库；免闸/无库证据的行原地不动；人裁行永不触碰。
    """
    from open_guji_cv.clustering.seeding import readjudicate_pending
    root = tmp_path
    book_dir, corpus_path, variants_path = build_book(root)
    db = GlyphDB(root / "g.db")
    try:
        seed_book(book_dir, db, corpus_path, variants=variants_path)
        qp = book_dir / "phase9_seed" / "queue.jsonl"
        rows = [json.loads(l) for l in
                qp.read_text(encoding="utf-8").splitlines() if l.strip()]
        # 4:1:6「大」：align 过闸 equal，doubts=[near_form]。2026-08-27
        # 起近形不再单独拦上下文通道，这一位 seed 时就直接自动进库了
        # （见 test_doubt_near_form）——本测试要单独钉住的是
        # readjudicate_pending 自己那条「规则升级回填存量」的窄口逻辑
        # （只动 pending/skipped 行，不重算证据），所以人工把它摆回
        # pending，模拟「规则升级前还没轮到复裁」的存量行；再补上库匹配
        # 快照（top 候选与 align 同字）——模拟库里已有大量「大」
        fired = "tb:4:1:6"
        for d in rows:
            if d["instance_id"] == fired:
                d["status"] = STATUS_PENDING
                d["decided_char"] = None
                d["provenance"] = None
                d["match"] = {"char": None, "verdict": "unsure",
                              "guard": "never_match", "wmax": 3.0,
                              "candidates": [["大", 0.98], ["太", 0.90]]}
        qp.write_text("".join(json.dumps(d, ensure_ascii=False) + "\n"
                              for d in rows), encoding="utf-8")
        n = readjudicate_pending(book_dir, db, variants=variants_path)
        assert n.get("auto_match_ref") == 1
        q = {SeedItem.from_json(l).instance_id: SeedItem.from_json(l)
             for l in qp.read_text(encoding="utf-8").splitlines()
             if l.strip()}
        it = q[fired]
        assert it.status == STATUS_AUTO
        assert it.decided_char == "大"
        assert it.note == "match_ref:readj"
        assert db.conn.execute(
            "SELECT 1 FROM admissions WHERE instance_id=?",
            (fired,)).fetchone()
        # 第 7 页（未锚定、无库证据）的行原地不动
        assert any(v.status == STATUS_PENDING for k, v in q.items()
                   if v.page == "7")
        # 幂等：再跑一遍不重复进库
        n2 = readjudicate_pending(book_dir, db, variants=variants_path)
        assert n2.get("auto_match_ref") is None
    finally:
        db.close()


def test_admission_decision_match_margin():
    """兜底通道：没有 competitor + 整理本一致 → 放行，不看绝对 cov。

    用户 2026-08-27 定：「有時即使庫內匹配率，未達到 0.99，但是沒有
    競爭者，且整理本一致，完全可以自動錄入。只有有相似競爭者，或整理本
    不一致時，需要人工」。全部历史人裁回放 margin≥0.05 触发 102 全对
    （0.04 档出第一错，阈留一档余量）。前面几条通道各自守着自己的
    doubt 组合与绝对阈；这条不管 doubts 是什么组合（db_inconsistent
    除外），只看 top1 与 top2 的 cov 差距。"""
    from open_guji_cv.clustering.seeding import admission_decision
    from open_guji_cv.clustering.variants import VariantMap
    vmap = VariantMap(mapping={})

    # weak_single 单独出现（无对齐、免闸参考也没有）——前面的通道
    # 一个都碰不到（match_ref_weak 要求 ref_char 存在），match_margin
    # 因为没有 corpus_char 同样不该放
    ok, _ = admission_decision(
        {"char": "允", "prob": 0.30}, None, None, ["weak_single"], vmap,
        match_candidates=[("允", 0.70)])
    assert not ok
    # 免闸参考 + 库单候选、cov 远低于 match_ref_weak 的 0.98，但没有
    # competitor——match_margin 兜底放行
    ok, ch = admission_decision(
        {"char": "允", "prob": 0.30}, None, "允", ["weak_single"], vmap,
        match_candidates=[("允", 0.70)])
    assert (ok, ch) == (True, "match_margin")
    # 同样场面但库里有个分数很接近的对手——margin 不够，人审
    ok, _ = admission_decision(
        {"char": "允", "prob": 0.30}, None, "允", ["weak_single"], vmap,
        match_candidates=[("允", 0.70), ("充", 0.67)])
    assert not ok
    # db_inconsistent 混进来——库本身已经不自洽，margin 再大也不该信
    ok, _ = admission_decision(
        {"char": "允", "prob": 0.30}, None, "允",
        ["weak_single", "db_inconsistent"], vmap,
        match_candidates=[("允", 0.70)])
    assert not ok
    # 库里压根没有这个字（corpus_char 无候选可查）——没法判自洽，人审
    # （用户裁定「如果庫內沒有，第一次肯定要人工」，本就是结构性保证：
    # 没有候选，match_margin/match_solo/match_ref 全都碰不到）
    ok, _ = admission_decision(
        {"char": "允", "prob": 0.30}, None, "允", ["weak_single"], vmap,
        match_candidates=None)
    assert not ok


def test_admission_decision_match_solo_ocr():
    """十八轮：无语料页 OCR 字符背书档（167 条人裁回放 81/81 定标）。

    形状 0.95~0.99 单独不够（历史 68.5%），加 OCR 字符同字即互证；
    形近家族与异语义竞争照禁，0.95 以下不外推。
    """
    from open_guji_cv.clustering.seeding import admission_decision
    from open_guji_cv.clustering.variants import VariantMap
    vmap = VariantMap({})
    ok = {"char": "文", "prob": 0.92}
    # 0.95~0.99 + OCR 同字 → 进（solo_cov=0.99 之下、新档之上）
    assert admission_decision(ok, None, None, [], vmap,
                              match_candidates=[("文", 0.96)]
                              ) == (True, "match_solo_ocr")
    # OCR 不同字 → 不进（形状证据单独 68.5%，不够）
    assert admission_decision({"char": "又", "prob": 0.92}, None, None, [],
                              vmap, match_candidates=[("文", 0.96)])[0] is False
    # 无 OCR → 不进
    assert admission_decision(None, None, None, [DOUBT_WEAK_SINGLE], vmap,
                              match_candidates=[("文", 0.96)])[0] is False
    # 形近家族（两侧任一）→ 禁：两路会同错的地方
    assert admission_decision({"char": "日", "prob": 0.95}, None, None,
                              [DOUBT_NEAR_FORM], vmap,
                              match_candidates=[("日", 0.97)])[0] is False
    # 异语义竞争到 0.95 档 → 禁
    assert admission_decision(ok, None, None, [], vmap,
                              match_candidates=[("文", 0.96), ("又", 0.955)]
                              )[0] is False
    # 0.95 以下 → 不外推
    assert admission_decision(ok, None, None, [], vmap,
                              match_candidates=[("文", 0.94)])[0] is False
    # 护栏触发 → 禁（solo 组整体前提）
    assert admission_decision(ok, None, None, [], vmap,
                              match_candidates=[("文", 0.96)],
                              match_guard="conflict")[0] is False
    # 有语料信号时轮不到本通道（那是 match_ref 的地盘；
    # 用 OCR≠语料的场景隔离，dual 零疑问会先走常规通道）
    assert admission_decision({"char": "又", "prob": 0.4}, "文", None,
                              [], vmap,
                              match_candidates=[("文", 0.96)]
                              ) == (True, "match_ref")


def test_exclusions_block_admission_and_review(tmp_path, monkeypatch):
    """排除名单：名单里的字位既不进库，也不出审查卡（用户 2026-08-25 口径）。

    钉死两条路：seed 自动通道、ingest 裁决通道。名单是「有意撤掉的」，
    重跑管线绝不能把它们悄悄填回来。
    """
    from open_guji_cv.clustering import seeding as S
    from open_guji_cv.clustering.review.seed_export import _REVIEWABLE
    from open_guji_cv.clustering.seed_queue import STATUS_EXCLUDED

    root = tmp_path
    book_dir, corpus_path, variants_path = build_book(root)
    victim = f"{BOOK}:1:1:0"          # 第 1 页首字，本该 auto 进库
    monkeypatch.setattr(S, "load_exclusions",
                        lambda *a, **k: {victim: {"reason": "rule_bar"}})
    db = GlyphDB(root / "g.db")
    try:
        summary = seed_book(book_dir, db, corpus_path, variants=variants_path)
        assert summary["n_excluded"] == 1
        q = {SeedItem.from_json(l).instance_id: SeedItem.from_json(l)
             for l in (book_dir / "phase9_seed" / "queue.jsonl")
             .read_text(encoding="utf-8").splitlines() if l.strip()}
        it = q[victim]
        assert it.status == STATUS_EXCLUDED          # 落账
        assert it.status not in _REVIEWABLE          # 不出审查卡
        assert not db.conn.execute(                  # 不进库
            "SELECT 1 FROM admissions WHERE instance_id=?",
            (victim,)).fetchone()

        # ingest 通道：哪怕来了一条 confirm 事件也顶回去
        r = ingest_decisions(book_dir, db, [
            {"op": "confirm", "instance_id": victim, "char": "天",
             "batch": "b", "seq": 1}])
        assert r.get("excluded") == 1
        assert not db.conn.execute(
            "SELECT 1 FROM admissions WHERE instance_id=?",
            (victim,)).fetchone()
    finally:
        db.close()


# ── 上下文条口径：pos 必须与「列内第几个 char 格」同源 ─────────────────

def test_context_pos_follows_index_not_carrier(tmp_path):
    """载体缺格时，上下文高亮位仍要对准图块本身。

    2026-08-25 用户实锤：``vol01:4:2:20`` 卡片是「第」，上下文条却高亮
    下一位的「一」。真因是列文按 **OCR 载体** 建——载体少一格，整列文本
    就短一位，``pos`` 与审查页按 index 数出来的「第几字」错开。列文改
    按 index 的 char 格位建（载体缺格补 □）之后，
    ``pos == 列内 char 位次 - 1`` 恒成立。
    """
    book_dir = tmp_path / BOOK
    chars_dir = book_dir / "phase4_chars"
    (chars_dir / "patches").mkdir(parents=True)
    text = PAGES["1"]
    missing = 3                      # 这一格故意不写进载体
    index_lines, carrier_lines = [], []
    for i, gold in enumerate(text):
        iid = f"{BOOK}:1:1:{i}"
        rel = f"patches/1_{i}.png"
        cv2.imwrite(str(chars_dir / rel), _patch(gold))
        index_lines.append(json.dumps(
            {"id": iid, "book": BOOK, "page": "1", "col": 1, "idx": i,
             "bbox": [0, 0, 80, 80], "cell_type": "char", "ocr_text": None,
             "ocr_confidence": 0.0, "patch_path": rel, "ink_ratio": 0.2,
             "height": 64, "width": 64, "flags": []}, ensure_ascii=False))
        if i != missing:
            carrier_lines.append(json.dumps(
                {"id": iid, "char": gold, "prob": 0.92}, ensure_ascii=False))
    (chars_dir / "index.jsonl").write_text(
        "".join(x + "\n" for x in index_lines), encoding="utf-8")
    (chars_dir / "ocr_carrier.jsonl").write_text(
        "".join(x + "\n" for x in carrier_lines), encoding="utf-8")
    corpus_path = tmp_path / "corpus.txt"
    corpus_path.write_text(text, encoding="utf-8")

    db = GlyphDB(tmp_path / "glyph.db")
    try:
        seed_book(book_dir, db, corpus_path)
    finally:
        db.close()

    rows = [SeedItem.from_json(x) for x in
            (book_dir / "phase9_seed" / "queue.jsonl")
            .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert rows
    for it in rows:
        ctx = it.context or {}
        # 列文长度 = 列内 char 格数（不是载体条数）
        assert len(ctx["col_ocr"]) == len(text)
        # 高亮位 = 该格在列内的 char 位次 - 1
        assert ctx["pos"] == it.idx
    # 载体缺的那一格占住位并补 □，后面的字因此没有整体前移
    it = {r.instance_id: r for r in rows}[f"{BOOK}:1:1:{missing}"]
    assert it.context["col_ocr"][missing] == "□"
    assert it.context["col_ocr"][missing + 1] == text[missing + 1]


# ── 十七轮：replace 层对齐 × 库 / 免闸参考 × 库 两条新通道 ─────────────

def test_admission_decision_match_replace_and_ref_weak():
    """756 条历史人裁回放标定的两条放行（都要求库 top 与文本证据同字）。

    - match_replace（@0.95，70/70）：OCR 认错产生 replace 层对齐 +
      signal_conflict，但 OCR 本不参与自动判断；整理本 × 库形状同指
      一字即放行，进库字取整理本字；
    - match_ref_weak（@0.98，25/25）：无对齐页 weak_single 必在场，
      此前把 参考 × 库 的路堵死；0.98 档放行（0.97 出 祗/祇 一错）。
    """
    from open_guji_cv.clustering.seeding import admission_decision
    from open_guji_cv.clustering.variants import VariantMap
    vmap = VariantMap(mapping={})

    # match_replace：够 0.95 放行
    ok, ch = admission_decision(
        {"char": "馬", "prob": 0.99}, "焉", None,
        ["signal_conflict", "replace_align"], vmap,
        match_candidates=[("焉", 0.96), ("烏", 0.90)])
    assert (ok, ch) == (True, "match_replace")
    # 库 top 与对齐不同字 → 拦
    ok, _ = admission_decision(
        {"char": "馬", "prob": 0.99}, "焉", None,
        ["signal_conflict", "replace_align"], vmap,
        match_candidates=[("烏", 0.99)])
    assert not ok
    # match_replace 自己那道 cov 阈不够，但 match_margin 兜底接住——
    # 单候选、没有第二名，corpus 一致就该放行（2026-08-27 用户定：
    # 「即使庫內匹配率未達到 0.99，但是沒有競爭者，且整理本一致，
    # 完全可以自動錄入」，全部历史人裁回放 margin≥0.05 触发 102 全对）
    ok, ch = admission_decision(
        {"char": "馬", "prob": 0.99}, "焉", None,
        ["signal_conflict", "replace_align"], vmap,
        match_candidates=[("焉", 0.94)])
    assert (ok, ch) == (True, "match_margin")
    # 但真有 competitor（第二名离得很近）时，match_margin 也不该放——
    # margin 不够，仍然人审
    ok, _ = admission_decision(
        {"char": "馬", "prob": 0.99}, "焉", None,
        ["signal_conflict", "replace_align"], vmap,
        match_candidates=[("焉", 0.94), ("烏", 0.91)])
    assert not ok
    # near_form 现在也放行 match_replace（2026-08-27，match_ref 早就放了
    # 的同一论证：整理本×库 zero-shared-source，与对齐层 equal/replace
    # 无关，全部历史人裁回放 143/143 全对）；db_inconsistent 仍然照拦
    # ——库本身对不上，margin/near_form 都救不了
    ok, ch = admission_decision(
        {"char": "馬", "prob": 0.99}, "焉", None,
        ["signal_conflict", "replace_align", "near_form"], vmap,
        match_candidates=[("焉", 0.99)])
    assert (ok, ch) == (True, "match_replace")
    ok, _ = admission_decision(
        {"char": "馬", "prob": 0.99}, "焉", None,
        ["signal_conflict", "replace_align", "db_inconsistent"], vmap,
        match_candidates=[("焉", 0.99)])
    assert not ok

    # match_ref_weak：无对齐 + 免闸参考 + 库 0.98
    ok, ch = admission_decision(
        {"char": "允", "prob": 0.30}, None, "允",
        ["weak_single"], vmap,
        match_candidates=[("允", 0.985)])
    assert (ok, ch) == (True, "match_ref_weak")
    # 0.98 之下 → 拦（祗/祇 档）
    ok, _ = admission_decision(
        {"char": "祇", "prob": 0.30}, None, "祗",
        ["weak_single"], vmap,
        match_candidates=[("祇", 0.97)])
    assert not ok


def test_db_inconsistent_about_ocr_char_does_not_block_ref_weak():
    """db_inconsistent 说的是 OCR 字时，不该拦「参考 × 库」通道。

    实锤 vol01:22:5:4：OCR 司 18%、整理本 詞、库 top 詞 cov 1.00。
    疑问 5「与库内已有同字刻例形状对不上」判的是 **proposed**（无对齐时
    退回 OCR 字 司）——这句话完全正确，且正是「它不该是司」的旁证，却把
    要进 詞 的通道拦死了。放行的字自己不可能 db_inconsistent：库里最像它
    的就是同字刻例，cov 还压着 0.98。回放 @0.98 触发 25 → 38 全对。
    """
    from open_guji_cv.clustering.seeding import admission_decision
    from open_guji_cv.clustering.variants import VariantMap
    vmap = VariantMap(mapping={})

    ok, ch = admission_decision(
        {"char": "司", "prob": 0.178}, None, "詞",
        ["weak_single", "db_inconsistent"], vmap,
        match_char="詞", match_candidates=[("詞", 1.0), ("請", 0.94)])
    assert (ok, ch) == (True, "match_ref_weak")

    # OCR 字与参考字**同字**时，db_inconsistent 说的就是要进的那个字 → 照拦
    ok, _ = admission_decision(
        {"char": "詞", "prob": 0.178}, None, "詞",
        ["weak_single", "db_inconsistent"], vmap,
        match_char="詞", match_candidates=[("詞", 1.0)])
    assert not ok
    # 没有 OCR 字可比对时保守：照拦
    ok, _ = admission_decision(
        None, None, "詞", ["weak_single", "db_inconsistent"], vmap,
        match_candidates=[("詞", 1.0)])
    assert not ok


def test_force_pages_runs_only_those_pages(tmp_path):
    """--force-pages 给了就只跑这几页，不把「所有没 seed 过的页」捎上。

    2026-08-26 实锤：用户要「再匹配十页」刷新 match 快照，旧语义是把
    force 页**追加**进待办——而待办本来就含全部未 seed 页，结果跑了
    108 页 12 分钟。库每轮都在长，后面页的快照迟早还要再刷，跑多了白烧。
    """
    book_dir, corpus_path, variants_path = build_book(tmp_path)
    db = GlyphDB(tmp_path / "glyph.db")
    try:
        # 先只跑第 1 页，其余留作未 done
        s1 = seed_book(book_dir, db, corpus_path, max_pages=1,
                       variants=variants_path)
        assert s1["pages_processed"] == 1
        # force 第 1 页：只重跑它，不捎上 2~7 页
        s2 = seed_book(book_dir, db, corpus_path, force_pages={"1"},
                       variants=variants_path)
        assert s2["pages_processed"] == 1
        assert set(s2["per_page"]) == {"1"}
        # force 两页（一页 done、一页没跑过）：正好这两页
        s3 = seed_book(book_dir, db, corpus_path, force_pages={"1", "3"},
                       variants=variants_path)
        assert set(s3["per_page"]) == {"1", "3"}
        # 不给 force：回到「跑所有未 done 页」的老behavior
        s4 = seed_book(book_dir, db, corpus_path, variants=variants_path)
        assert set(s4["per_page"]) >= {"2", "4", "5", "6", "7"}
    finally:
        db.close()
