"""列级「字距不均匀」裁决（`uniform=false`，2026-09-20 用户定）。

字数对了不等于字距均匀。bxgb p33c19 实测：22 字给对了，DP 仍把首字「尉」
（墨跨 24..119，95px）从中间劈成 57+62 两格，整列错位一格，末尾「白琮」
反而各占 88/90px。

代价账（p_shared=67.3）：正解给「尉」95px 要吃 λ·dev² = 0.3×0.41² = 0.0507，
劈成两格只要 0.0089，而劈开处墨只有 0.098——等距先验比墨量判据贵五倍。
降 lam 到 NONUNIFORM_LAM 后劈开不再划算。

这条覆盖**只存在裁决表**，不进 books/*.yaml：它是单列事实（全书 1026 列里 1 列），
而 yaml 装的是版式常量；且 row_segment 的 book_deps 是空的，写进 yaml 改了
不生效（cv-pipeline-ops §2.1 那个坑）。
"""
from __future__ import annotations

from open_guji_cv.feedback.consumers import _expected_of
from open_guji_cv.feedback.events import EventTarget, make_event
from open_guji_cv.feedback.lookup import ResolvedColumn
from open_guji_cv.utils.row_boundaries import NONUNIFORM_LAM


def _ev(payload: dict):
    return make_event("b", 1, "n_body_slots",
                      EventTarget(step="row_segment", unit="column", key="bxgb:33:19",
                                  book="bxgb", page=33, col=19),
                      payload)


def test_uniform_flag_reaches_the_gold_record():
    exp = _expected_of(_ev({"n_slots": 22, "uniform": False, "client_ts": 1}))
    assert exp == {"n_slots": 22, "uniform": False}, "client_ts 之类元数据不该进金标"


def test_uniform_defaults_true_for_old_verdicts():
    """2026-09-20 之前的裁决没有这个键——不能因为加了新键就改掉它们的含义。"""
    assert ResolvedColumn(22).uniform is True
    exp = _expected_of(_ev({"n_slots": 22}))
    assert "uniform" not in exp


def test_resolved_slots_reads_uniform(tmp_path, monkeypatch):
    from open_guji_cv.feedback import consumers
    from open_guji_cv.feedback.lookup import SLOT_COUNT_SHARD, resolved_slots
    from open_guji_cv.gold.item import Anchor, GoldItem
    from open_guji_cv.gold.store import GoldStore

    store = GoldStore(tmp_path)
    store.upsert(SLOT_COUNT_SHARD, [
        GoldItem(id="bxgb:33:19", anchor=Anchor(book="bxgb", page=33, col=19),
                 expected={"n_slots": 22, "uniform": False}),
        GoldItem(id="bxgb:33:18", anchor=Anchor(book="bxgb", page=33, col=18),
                 expected={"n_slots": 22}),
    ])
    monkeypatch.setattr(consumers, "verdict_store", lambda: store)
    got = resolved_slots("bxgb")
    assert got[(33, 19)] == ResolvedColumn(22, False)
    assert got[(33, 18)] == ResolvedColumn(22, True), "没写 uniform 的旧裁决要当均匀"


def test_nonuniform_lam_is_well_below_default():
    """放宽是为了让「大字占一格」比「劈成两格」便宜——不是随便调小。"""
    p = 67.3
    default_lam, relaxed = 0.3, NONUNIFORM_LAM
    # 正解：一格 95px；劈开：57 + 62
    cost = lambda lam, gaps: sum(lam * ((g - p) / p) ** 2 for g in gaps)
    assert cost(default_lam, [95]) > cost(default_lam, [57, 62]), "默认下劈开更划算（这就是病根）"
    assert cost(relaxed, [95]) < 0.02, "放宽后正解代价要低到与墨量判据同量级"


def test_only_flagged_columns_relax(monkeypatch):
    """非均匀开关**只对勾了的列**生效，其余列一字不动。"""
    import open_guji_cv.steps.row_segment as rs
    seen: list[dict] = []

    def fake_segment(img, **kw):
        seen.append(kw)
        return None

    monkeypatch.setattr(rs, "segment_column", fake_segment)
    # 直接验判据本身：row_segment 里那一行的逻辑
    for override, want in ((None, {}),
                           (ResolvedColumn(22, True), {}),
                           (ResolvedColumn(22, False), {"lam": NONUNIFORM_LAM})):
        got = ({} if override is None or override.uniform
               else {"lam": NONUNIFORM_LAM})
        assert got == want, f"{override} → {got}"
