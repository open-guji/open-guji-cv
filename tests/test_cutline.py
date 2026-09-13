"""拖切线（cutline）事件 → touching-cuts 金标 的链路回归。

2026-09-05：粘连格线（R2s）的理想切点金标。事件 kind=cutline，路由到
char-segmentation/touching-cuts；expected 只留切点相关字段。
"""

from __future__ import annotations

from open_guji_cv.eval.touching import pick_cases
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


def test_pick_cases_spreads_over_pages_and_is_deterministic():
    cases = [dict(id=f"vol01:{p}:1:{s}", page=p) for p in (44, 71, 72) for s in range(1, 41)]
    cases += [dict(id=f"vol01:15:1:{s}", page=15) for s in range(1, 3)]
    a = pick_cases(cases, 30)
    b = pick_cases(cases, 30)
    assert [c["id"] for c in a] == [c["id"] for c in b]
    by_page = {}
    for c in a:
        by_page[c["page"]] = by_page.get(c["page"], 0) + 1
    # 轮转：只有 2 条的页全进；三个大页各拿到接近 1/3，而不是一页包场
    assert by_page[15] == 2
    assert all(8 <= by_page[p] <= 10 for p in (44, 71, 72)), by_page


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


def test_polyline_to_seam_interpolates_and_extends_ends():
    from open_guji_cv.eval.touching import polyline_to_seam, seam_deviation
    seam = polyline_to_seam([[10, 100], [20, 110], [30, 100]], x0=5, x1=36)
    assert len(seam) == 31
    assert seam[0] == 100 and seam[-1] == 100          # 两端水平延伸
    assert seam[20 - 5] == 110                          # 顶点 x=20
    assert seam[15 - 5] == 105                          # x=15：10→20 的中点线性插值
    mx, mean = seam_deviation(seam, [100] * 31)
    assert mx == 10 and 0 < mean < 10


def test_seam_ok_verdict_keeps_polyline_and_routes_like_cutline():
    e = _evt({"y": 1980, "y_old": 1986, "verdict": "seam_ok", "polyline": [[20, 1975], [26, 1979]]})
    ex = _expected_of(e)
    assert ex["verdict"] == "seam_ok" and ex["polyline"] == [[20, 1975], [26, 1979]]
    assert "char-segmentation/touching-cuts" in {d.shard for d in RouteTable.load().destinations(e)}


# ── 2026-09-08：「切进字里」候选的绝对墨量判据（47 条人裁金标标定）──
def test_split_char_ink_mass_separates_flat_chars_from_split_halves():
    """矮格里装的是扁字（一/二）还是被劈的半个字——只有绝对墨量分得开。

    金标实测：格高比例两组几乎完全重合（moved 0.70~0.79 / ok 0.66~0.80），
    而绝对墨量（墨像素 ÷ 中位格高×格宽）ok 0.034~0.066、moved 0.105~0.195。
    """
    import numpy as np

    from open_guji_cv.eval.touching import _cell_ink_mass

    class _Cell:
        def __init__(self, y0, y1, x0, x1):
            self.y0, self.y1, self.x0, self.x1 = y0, y1, x0, x1

    class _Cache:
        def __init__(self, img): self.img = img
        def get(self, *a, **k): return self.img

    med, w = 115.0, 150
    # 扁字「一」：矮格 85px，墨只有中间一条横（约 12px 高、满宽）
    flat = np.full((300, w), 255, np.uint8)
    flat[40:52, 20:130] = 0
    # 被劈的半个字：同样 85px 的格，墨铺满大半格
    half = np.full((300, w), 255, np.uint8)
    half[8:80, 20:130] = 0
    import cv2, tempfile, os
    out = []
    for img in (flat, half):
        fd, path = tempfile.mkstemp(suffix='.png'); os.close(fd)
        cv2.imwrite(path, img)
        import open_guji_cv.products.cache as _c
        orig = _c.ImageCache
        _c.ImageCache = lambda: _Cache(path)
        try:
            out.append(_cell_ink_mass(None, 'vol01', 1, 1, _Cell(0, 85, 10, 140), med))
        finally:
            _c.ImageCache = orig
            os.unlink(path)
    flat_mass, half_mass = out
    assert flat_mass < 0.100, f"扁字墨量 {flat_mass:.3f} 不该超阈值"
    assert half_mass >= 0.100, f"半个字墨量 {half_mass:.3f} 该超阈值"


def test_blocking_gate_reads_all_event_batches(monkeypatch, tmp_path):
    """裁过的切线要**立刻**退出顺序闸，不必等 harvest 收进金标。

    2026-09-12 回归：原先 `blocking_cutline_cases` 里写的是无参
    `deps.event_log().read()`，而 `EventLog.read(batch)` 是必填参数——
    抛的 `TypeError` 被裸 `except Exception: pass` 吞掉，事件去重从未生效。
    这里断言的是**行为**（事件里的 id 不再出现在待裁集合里），不是调用形式，
    所以换实现也不会误报。
    """
    from open_guji_cv.console import deps
    from open_guji_cv.eval import touching as T
    from open_guji_cv.review import cards as C

    case = {"id": "volX:7:3:5", "page": 7, "col": 3, "bi": 5,
            "slot_above": 5, "slot_below": 6}

    monkeypatch.setattr(T, "r2s_boundaries", lambda *a, **k: [dict(case)])
    monkeypatch.setattr(T, "split_char_boundaries", lambda *a, **k: [])
    monkeypatch.setattr(T, "gold_ids", lambda *a, **k: set())

    class _CP:
        slot_above, chosen = 5, 0
        candidates = [object(), object()]          # 多候选 → 该挡
    class _Col:
        col, cut_candidates = 3, [_CP()]
    class _Cells:
        columns = [_Col()]
    class _St:
        def read(self, *a, **k): return _Cells()

    class _Log:
        def __init__(self, keys): self.keys = keys
        def iter_all(self):
            for k in self.keys:
                yield type("E", (), {"kind": "cutline",
                                     "target": type("T", (), {"key": k})()})()
        def read(self, batch):                      # 有 batch 才给，模拟真实签名
            raise AssertionError("不该按单批次读——要跨所有批次去重")

    monkeypatch.setattr(deps, "event_log", lambda: _Log([]))
    assert len(C.blocking_cutline_cases("volX", [7], _St())) == 1, "没裁过时应当挡住"

    monkeypatch.setattr(deps, "event_log", lambda: _Log(["volX:7:3:5"]))
    assert C.blocking_cutline_cases("volX", [7], _St()) == [], "裁过之后应立刻放行"


def _gold_item(page, col, slot, verdict, cand, status="active", book="vol02"):
    from open_guji_cv.gold.item import Anchor, GoldItem
    return GoldItem(id=f"{book}:{page}:{col}:{slot}",
                    anchor=Anchor(book=book, page=page, col=col, slot=slot),
                    expected={"verdict": verdict, "cand": cand}, status=status)


def test_resolved_cuts_only_keeps_ok_and_moved_with_a_known_kind(monkeypatch):
    """人裁回流的数据源：只收 `verdict in (ok, moved)` 且 `cand` 是候选池
    认识的 kind——`overlap`（切哪都伤字）、`idk`（拿不准）是真难例，不收敛，
    见 `.claude/doc/row_boundaries_design.md`「5 条都不对」节。"""
    from open_guji_cv.eval.touching import resolved_cuts
    from open_guji_cv.gold.store import GoldStore

    items = [
        _gold_item(5, 8, 14, "ok", "seam_narrow"),
        _gold_item(6, 4, 17, "moved", "straight"),
        _gold_item(9, 1, 3, "overlap", None),
        _gold_item(9, 1, 9, "idk", None),
        _gold_item(20, 2, 2, "ok", "seam_narrow", status="retired"),
    ]
    monkeypatch.setattr(GoldStore, "list", lambda self, shard: items)

    out = resolved_cuts("vol02")
    assert out == {(5, 8, 14): "seam_narrow", (6, 4, 17): "straight"}


def test_resolved_cuts_scopes_to_the_requested_book(monkeypatch):
    from open_guji_cv.eval.touching import resolved_cuts
    from open_guji_cv.gold.store import GoldStore

    items = [_gold_item(5, 8, 14, "ok", "seam_narrow", book="vol01"),
             _gold_item(5, 8, 14, "ok", "seam_wide", book="vol02")]
    monkeypatch.setattr(GoldStore, "list", lambda self, shard: items)

    assert resolved_cuts("vol01") == {(5, 8, 14): "seam_narrow"}
    assert resolved_cuts("vol02") == {(5, 8, 14): "seam_wide"}


def test_resolved_cuts_empty_when_store_unavailable(monkeypatch):
    """没有金标数据集（新工作区/取不到）时返回空表，不炸——与 `gold_ids()`
    同一容错口径。"""
    from open_guji_cv.eval.touching import resolved_cuts
    from open_guji_cv.gold.store import GoldStore

    def boom(self, shard):
        raise FileNotFoundError

    monkeypatch.setattr(GoldStore, "list", boom)
    assert resolved_cuts("vol02") == {}
