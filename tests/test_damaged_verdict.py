"""原图破损档（`v="damaged"`，2026-09-19 用户定）。

审阅台此前只有四档：定字 / 切分缺陷（truncated·contaminated）/ 非字 / 跳过。
bxgb:27:8:6 那种「原刻就残、认不出，但最像塊」无处可落——按 skip 记就永远挂在
待办里（实测全书唯一一条 skip 就是它），按 contaminated 记归因错了（切分没毛病）。
新档：文本层出 `□`，`guess` 记「最像哪个字」只作括注，不进字形库。
"""
from __future__ import annotations

from open_guji_cv.feedback.consumers import _expected_of, crop_exclude, gold_add
from open_guji_cv.feedback.events import Event, EventTarget, make_event
from open_guji_cv.feedback.routes import Destination, RouteTable
from open_guji_cv.review.verdict_view import review_verdicts

SHARD = "char-segmentation/instances"


def _ev(payload: dict, key: str = "bxgb:27:8:6", seq: int = 1) -> Event:
    return make_event("b", seq, "confirm",
                      EventTarget(step="seed_admit", unit="cell", key=key,
                                  book="bxgb", page=27, col=8, slot=6),
                      payload)


def test_expected_records_quality_and_guess():
    exp = _expected_of(_ev({"v": "damaged", "guess": "塊"}))
    assert exp["quality"] == "damaged", "要独立成第五档，不能混进 contaminated"
    assert exp["guess"] == "塊"


def test_guess_is_optional():
    assert _expected_of(_ev({"v": "damaged"})) == {"quality": "damaged"}


def test_guess_never_becomes_shape():
    """`guess` 不是 `shape`——进了库就把破损形钉死成那个字。"""
    exp = _expected_of(_ev({"v": "damaged", "guess": "塊"}))
    assert "shape" not in exp and "reading" not in exp


def test_routes_to_gold_and_exclusions_not_to_glyphdb():
    dests = RouteTable.load(None).destinations(_ev({"v": "damaged", "guess": "塊"}))
    names = {d.consumer for d in dests}
    assert "gold_add" in names and "crop_exclude" in names
    # glyphdb_admit 在路由里（confirm 那条规则给三个消费者），但它自己按
    # payload.v 过滤——下面那条测试钉的就是「真的没进库」。
    assert names == {"glyphdb_admit", "gold_add", "crop_exclude"}


def test_glyphdb_admit_skips_damaged():
    from open_guji_cv.feedback.consumers import glyphdb_admit
    res = glyphdb_admit([(_ev({"v": "damaged", "guess": "塊"}), None)], dry_run=True)
    assert res.added == 0, "破损图块绝不能进字形库"
    assert res.skipped == 1


def test_gold_add_keeps_damaged(tmp_path):
    from open_guji_cv.gold.store import GoldStore
    store = GoldStore(tmp_path)
    d = Destination(consumer="gold_add", shard=SHARD)
    res = gold_add([(_ev({"v": "damaged", "guess": "塊"}), d)], store=store)
    assert res.added == 1 and not res.errors
    item = store.list(SHARD)[0]
    assert item.expected["quality"] == "damaged" and item.expected["guess"] == "塊"
    assert item.anchor.page == 27 and item.anchor.col == 8 and item.anchor.slot == 6


def test_crop_exclude_takes_damaged(tmp_path):
    out = tmp_path / "crop_exclusions.jsonl"
    res = crop_exclude([(_ev({"v": "damaged", "guess": "塊"}), None)], list_path=str(out))
    assert res.added == 1, "破损图块要进排除名单，下轮不再出卡"
    assert "bxgb:27:8:6" in out.read_text(encoding="utf-8")


def test_verdict_readback_restores_guess(tmp_path):
    """刷新页面要能把 `guess` 读回来，否则人以为没填过、又填一遍。"""
    from open_guji_cv.feedback import EventLog
    log = EventLog(tmp_path)
    log.append([_ev({"v": "damaged", "guess": "塊"})])
    out = review_verdicts("b", log)["verdicts"]["bxgb:27:8:6"]
    assert out["done"] == "damaged" and out["guess"] == "塊"


def test_damaged_is_distinct_from_skip():
    """skip 是待办，damaged 是已了结——两者不能合并。"""
    assert _expected_of(_ev({"v": "damaged"})) == {"quality": "damaged"}
    # skip 压根不进金标（gold_add 只认 seg_defect / damaged）
    d = Destination(consumer="gold_add", shard=SHARD)
    res = gold_add([(_ev({"v": "skip"}), d)], dry_run=True)
    assert res.added == 0 and res.skipped == 1


def test_exclusion_record_carries_guess(tmp_path):
    """`guess` 要进排除名单——seed_admit 读的是名单，不是金标。"""
    import json
    out = tmp_path / "crop_exclusions.jsonl"
    crop_exclude([(_ev({"v": "damaged", "guess": "塊"}), None)], list_path=str(out))
    rec = json.loads(out.read_text(encoding="utf-8").strip())
    assert rec["reason"] == "damaged"
    assert "guess=塊" in rec["evidence"]
    assert "塊" in rec["note"]


def test_damaged_cell_keeps_its_slot_with_box(tmp_path, monkeypatch):
    """破损字位**占住**格：文本层出 □，不能消失——否则整列字数对不上。

    其余排除原因（切坏/非字）照旧 char=None。
    """
    import json
    from open_guji_cv.clustering.exclusions import load_exclusions
    out = tmp_path / "crop_exclusions.jsonl"
    crop_exclude([(_ev({"v": "damaged", "guess": "塊"}), None)], list_path=str(out))
    crop_exclude([(_ev({"v": "not_a_char"}, key="bxgb:3:1:18", seq=2), None)],
                 list_path=str(out))
    recs = load_exclusions(out)
    assert recs["bxgb:27:8:6"]["reason"] == "damaged"
    assert recs["bxgb:3:1:18"]["reason"] == "not_a_char"

    # seed_admit 的渲染判据：reason=="damaged" → char="□" + evidence.guess
    def render(iid):
        r = recs.get(iid, {})
        dmg = r.get("reason") == "damaged"
        g = next((t[6:] for t in (r.get("evidence") or [])
                  if isinstance(t, str) and t.startswith("guess=")), "")
        return ("□" if dmg else None), g

    assert render("bxgb:27:8:6") == ("□", "塊")
    assert render("bxgb:3:1:18") == (None, "")
