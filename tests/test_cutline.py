"""拖切线（cutline）事件 → touching-cuts 金标 的链路回归。

2026-09-05：粘连格线（R2s）的理想切点金标。事件 kind=cutline，路由到
char-segmentation/touching-cuts；expected 只留切点相关字段。
"""

from __future__ import annotations

from open_guji_cv.feedback.consumers import _expected_of
from open_guji_cv.feedback.events import EventTarget, make_event
from open_guji_cv.feedback.routes import RouteTable


def _evt(payload: dict):
    return make_event("vol01-cutline", 1, "cutline",
                      EventTarget(step="row_segment", unit="boundary", key="vol01:44:2:17",
                                  book="vol01", page=44, col=2, slot=17),
                      payload)


def test_cutline_routes_to_touching_cuts():
    e = _evt({"y": 1980, "y_old": 1986, "verdict": "moved"})
    dests = RouteTable.load().destinations(e)
    assert any(d.consumer == "gold_add" and d.shard == "char-segmentation/touching-cuts" for d in dests), dests


def test_cutline_expected_keeps_only_cut_fields():
    e = _evt({"y": 1980, "y_old": 1986, "verdict": "moved", "bi": 17, "slot_above": 17, "slot_below": 18,
              "col_h": 2449, "char_above": "官", "char_below": "道", "client_ts": 1, "dwell_ms": 900})
    ex = _expected_of(e)
    assert ex["y"] == 1980 and ex["y_old"] == 1986 and ex["verdict"] == "moved"
    assert ex["slot_above"] == 17 and ex["slot_below"] == 18 and ex["col_h"] == 2449
    assert "client_ts" not in ex and "dwell_ms" not in ex


def test_cutline_with_border_tag_also_feeds_side_rule():
    """标了「界行/版框」的切线事件要同时反馈上游：side-rule 正样本（用户 2026-09-05）。"""
    e = _evt({"y": 1980, "y_old": 1980, "verdict": "ok", "tags": ["border"]})
    dests = RouteTable.load().destinations(e)
    shards = {d.shard for d in dests if d.consumer == "gold_add"}
    assert "char-segmentation/touching-cuts" in shards and "char-segmentation/side-rule" in shards, shards
    plain = _evt({"y": 1980, "y_old": 1980, "verdict": "ok"})
    assert "char-segmentation/side-rule" not in {d.shard for d in RouteTable.load().destinations(plain)}


def test_cutline_expected_keeps_polyline():
    e = _evt({"y": 1980, "y_old": 1986, "verdict": "moved", "polyline": [[20, 1975], [90, 1990], [170, 1978]]})
    ex = _expected_of(e)
    assert ex["polyline"] == [[20, 1975], [90, 1990], [170, 1978]] and ex["y"] == 1980


def test_seam_ok_verdict_keeps_polyline_and_routes_like_cutline():
    e = _evt({"y": 1980, "y_old": 1986, "verdict": "seam_ok", "polyline": [[20, 1975], [26, 1979]]})
    ex = _expected_of(e)
    assert ex["verdict"] == "seam_ok" and ex["polyline"] == [[20, 1975], [26, 1979]]
    assert "char-segmentation/touching-cuts" in {d.shard for d in RouteTable.load().destinations(e)}


# ── 2026-09-08：「切进字里」候选的绝对墨量判据（47 条人裁金标标定）──


# ── 人裁回流：Step3 从 workspace 裁决表取已裁决的切点 ─────────────────

def _verdict(page, col, slot, verdict, cand, status="active", book="vol02", **extra):
    from open_guji_cv.gold.item import Anchor, GoldItem
    exp = {"verdict": verdict, **extra}
    if cand is not None:
        exp["cand"] = cand
    return GoldItem(id=f"{book}:{page}:{col}:{slot}",
                    anchor=Anchor(book=book, page=page, col=col, slot=slot),
                    expected=exp, status=status)


def _patch_verdicts(monkeypatch, items):
    from open_guji_cv.gold.store import GoldStore
    monkeypatch.setattr(GoldStore, "list", lambda self, shard, legacy=True: items)


def test_resolved_cuts_reads_workspace_verdicts_not_dataset(monkeypatch, tmp_path):
    """数据源是 workspace 的裁决表（feedback/verdicts）——生产管线运行时不读测试集仓。"""
    from open_guji_cv.feedback import lookup
    from open_guji_cv.gold.store import GoldStore
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path))
    for k in ("GUJI_VERDICTS_DIR", "GUJI_FEEDBACK_DIR"):
        monkeypatch.delenv(k, raising=False)
    seen = {}

    def spy(self, shard, legacy=True):
        seen["root"], seen["shard"] = self.root, shard
        return []

    monkeypatch.setattr(GoldStore, "list", spy)
    assert lookup.resolved_cuts("vol02") == {}
    assert seen["root"] == tmp_path / "feedback" / "verdicts"
    assert seen["shard"] == lookup.TOUCHING_CUTS_SHARD
    assert "open-guji-dataset" not in str(seen["root"])


def test_resolved_cuts_accepts_any_verdict_word_with_a_known_cand(monkeypatch):
    """判据是 cand（人选中了候选池里哪一条），不是 verdict 的具体词：Step7 裁决台发
    `confirmed`，切线卡发 `ok`/`moved`，都认；`overlap`/`idk`、retired、无 cand 的不收。"""
    from open_guji_cv.feedback.lookup import resolved_cuts
    _patch_verdicts(monkeypatch, [
        _verdict(5, 8, 14, "confirmed", "seam_narrow"),
        _verdict(6, 4, 17, "ok", "straight"),
        _verdict(7, 1, 1, "moved", "seam_wide"),
        _verdict(9, 1, 3, "overlap", None),
        _verdict(9, 1, 9, "idk", None),
        _verdict(9, 2, 2, "confirmed", "seam_narrow", status="uncertain"),
        _verdict(20, 2, 2, "confirmed", "seam_narrow", status="retired"),
        _verdict(21, 2, 2, "moved", None),                 # 人自己拖的位置，不在候选池里
        _verdict(22, 2, 2, "confirmed", "polyline"),       # 自画折线，不是候选 kind
        _verdict(5, 8, 14, "confirmed", "seam_narrow", book="vol01"),
    ])
    got = {k: v.kind for k, v in resolved_cuts("vol02").items()}
    assert got == {(5, 8, 14): "seam_narrow", (6, 4, 17): "straight", (7, 1, 1): "seam_wide"}
    assert {k: v.kind for k, v in resolved_cuts("vol01").items()} == {(5, 8, 14): "seam_narrow"}


def test_resolved_cuts_ok_and_seam_ok_resolve_with_y_guard(monkeypatch):
    """切线卡的 `ok`（现役直线就对）→ straight，`seam_ok`（现役折线就对）→ 现役折线；
    两者都带当时的 y 当护栏（`_apply_resolved_cut` 里比）。`moved` 无 cand 收不了。"""
    from open_guji_cv.feedback.lookup import resolved_cuts
    from open_guji_cv.books.siku_zongmu.row_boundaries import RESOLVED_CHOSEN
    _patch_verdicts(monkeypatch, [
        _verdict(1, 1, 1, "ok", None, y=1980, y_old=1980),
        _verdict(1, 1, 2, "seam_ok", None, y=1990, y_old=1986, polyline=[[0, 1990], [60, 1992]]),
        _verdict(1, 1, 3, "seam_ok", None, y=1995),
        _verdict(1, 1, 4, "moved", None, y=1970, y_old=1986),
        _verdict(1, 1, 5, "ok", None),                       # 老事件没 y_old：没护栏不敢收
        _verdict(1, 1, 6, "confirmed", "seam_narrow", y_old=1200),
    ])
    r = resolved_cuts("vol02")
    assert (r[(1, 1, 1)].kind, r[(1, 1, 1)].y_ref) == ("straight", 1980.0)
    assert (r[(1, 1, 2)].kind, r[(1, 1, 2)].y_ref) == (RESOLVED_CHOSEN, 1986.0)
    assert (r[(1, 1, 3)].kind, r[(1, 1, 3)].y_ref) == (RESOLVED_CHOSEN, 1995.0)
    assert (1, 1, 4) not in r and (1, 1, 5) not in r
    assert (r[(1, 1, 6)].kind, r[(1, 1, 6)].y_ref) == ("seam_narrow", 1200.0)


def test_resolved_cuts_empty_when_store_unavailable(monkeypatch):
    from open_guji_cv.feedback.lookup import resolved_cuts
    from open_guji_cv.gold.store import GoldStore

    def boom(self, shard, legacy=True):
        raise FileNotFoundError

    monkeypatch.setattr(GoldStore, "list", boom)
    assert resolved_cuts("vol02") == {}


def test_cutline_relabel_drops_stale_geometry_from_previous_verdict(tmp_path):
    """2026-09-14 drift 重标实锤：第一次判 seam_ok 带折线（旧坐标系），重矫正后重裁判 ok
    （事件不带 polyline / tags），gold_add 按旧 expected 打底合并，旧折线原样留下——评测优先
    读折线，等于金标没修（24 条）。切线几何字段是一次判定的整体，重裁要整组换掉；
    非切线的遗留字段（v1 的 layout 之类）照旧保留。"""
    from open_guji_cv.feedback.consumers import route_and_consume
    from open_guji_cv.feedback.events import EventLog
    from open_guji_cv.gold.store import GoldStore

    log = EventLog(tmp_path / "feedback")
    store = GoldStore(tmp_path / "dataset")
    shard = "char-segmentation/touching-cuts"
    tgt = EventTarget(step="row_segment", unit="boundary", key="vol02:153:7:8",
                      book="vol02", page=153, col=7, slot=8)
    e1 = make_event("b1", 1, "cutline", tgt,
                    {"y": 816, "y_old": 782, "verdict": "seam_ok", "col_h": 2295,
                     "polyline": [[5, 821], [183, 815]], "tags": ["stain"], "slot_above": 8, "slot_below": 9})
    log.append([e1])
    route_and_consume(log, "b1", RouteTable.load(None), store)
    it = store.get(shard, "vol02:153:7:8")
    it.expected["layout"] = "v1-legacy"                # 非切线遗留字段
    store.upsert(shard, [it], "test")

    e2 = make_event("b2", 1, "cutline", tgt,
                    {"y": 927, "y_old": 927, "verdict": "ok", "col_h": 2458, "slot_above": 8, "slot_below": 9})
    log.append([e2])
    route_and_consume(log, "b2", RouteTable.load(None), store)
    ex = store.get(shard, "vol02:153:7:8").expected
    assert ex["verdict"] == "ok" and ex["y"] == 927 and ex["col_h"] == 2458
    assert "polyline" not in ex and "tags" not in ex, ex
    assert ex["layout"] == "v1-legacy"


