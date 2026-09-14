"""裁决表 ⇄ 测试集的两个显式动作（gold/transfer.py）+ 三仓边界的运行时默认。

2026-09-13 用户裁定：管线运行时只读写 workspace；人裁先落 workspace 裁决表
（feedback/verdicts/），只有显式 `guji gold import` 才进 open-guji-dataset。
"""

from __future__ import annotations

import pytest

from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
from open_guji_cv.feedback.routes import RouteTable
from open_guji_cv.gold.item import Anchor, GoldItem
from open_guji_cv.gold.store import GoldStore
from open_guji_cv.gold.transfer import (ImportFilter, import_to_dataset, parse_pages,
                                        rebuild_verdicts)

SHARD = "char-segmentation/touching-cuts"


def _item(page, col, slot, book="vol02", status="active", stratum=None, **expected):
    return GoldItem(id=f"{book}:{page}:{col}:{slot}",
                    anchor=Anchor(book=book, page=page, col=col, slot=slot),
                    expected=expected or {"verdict": "ok"}, status=status, stratum=stratum)


@pytest.fixture
def stores(tmp_path):
    src = GoldStore(tmp_path / "ws" / "feedback" / "verdicts")
    dst = GoldStore(tmp_path / "dataset")
    return src, dst


def test_parse_pages():
    assert parse_pages("1-3,7, 10-11") == {1, 2, 3, 7, 10, 11}
    assert parse_pages("") is None and parse_pages(None) is None


def test_import_copies_only_selected_active_items(stores):
    src, dst = stores
    src.upsert(SHARD, [
        _item(5, 8, 14, stratum="flip_unique_top1"),
        _item(6, 4, 17, stratum="flip_unique_top1"),
        _item(9, 1, 3, stratum="other"),
        _item(9, 1, 9, status="uncertain", stratum="flip_unique_top1"),
        _item(20, 2, 2, status="retired", stratum="flip_unique_top1"),
        _item(3, 3, 3, book="vol01", stratum="flip_unique_top1"),
    ])
    res = import_to_dataset(SHARD, src, dst, ImportFilter(book="vol02", stratum="flip_unique_top1"))
    assert (res.n_source, res.n_selected, res.added) == (6, 2, 2)
    assert {i.id for i in dst.list(SHARD)} == {"vol02:5:8:14", "vol02:6:4:17"}
    # uncertain 要显式放行才导
    res2 = import_to_dataset(SHARD, src, dst, ImportFilter(stratum="flip_unique_top1", include_uncertain=True))
    assert "vol02:9:1:9" in {i.id for i in dst.list(SHARD)}
    assert res2.unchanged == 2


def test_import_filters_by_pages_and_ids(stores):
    src, dst = stores
    src.upsert(SHARD, [_item(p, 1, 1) for p in (1, 2, 3, 50, 51)])
    res = import_to_dataset(SHARD, src, dst, ImportFilter(pages=parse_pages("1-3,51")))
    assert {i.anchor.page for i in dst.list(SHARD)} == {1, 2, 3, 51}
    assert res.added == 4
    res = import_to_dataset(SHARD, src, GoldStore(dst.root / "b"), ImportFilter(ids={"vol02:50:1:1"}))
    assert res.n_selected == 1 and res.sample_ids == ["vol02:50:1:1"]


def test_import_merges_expected_instead_of_replacing(stores):
    """目标分片里的旧字段（v1 时代的 layout / defect 等）不能被导入抹掉——与 gold_add 同口径。"""
    src, dst = stores
    dst.upsert(SHARD, [_item(5, 8, 14, verdict="moved", legacy_field="keep-me")])
    src.upsert(SHARD, [_item(5, 8, 14, verdict="ok", cand="seam_narrow")])
    res = import_to_dataset(SHARD, src, dst)
    assert res.updated == 1 and res.added == 0
    got = dst.get(SHARD, "vol02:5:8:14")
    assert got.expected == {"verdict": "ok", "cand": "seam_narrow", "legacy_field": "keep-me"}


def test_import_dry_run_writes_nothing(stores):
    src, dst = stores
    src.upsert(SHARD, [_item(5, 8, 14)])
    res = import_to_dataset(SHARD, src, dst, dry_run=True)
    assert res.n_selected == 1 and res.added == 1
    assert dst.list(SHARD) == []


def test_export_copies_dataset_shard_into_workspace_verdicts(stores):
    """反向：书的事实类分片（page-type）从测试集仓复制到 workspace，出卡时不再读 dataset。"""
    from open_guji_cv.gold.transfer import export_to_workspace
    src, dst = stores              # 这里 dst 当 dataset、src 当 workspace
    dst.upsert("page-type", [_item(1, 0, 0, page_type="body"), _item(2, 0, 0, page_type="toc"),
                             _item(3, 0, 0, status="retired", page_type="body")])
    res = export_to_workspace("page-type", dst, src)
    assert (res.n_source, res.n_selected, res.added) == (3, 2, 2)
    assert {i.anchor.page for i in src.list("page-type")} == {1, 2}
    assert export_to_workspace("page-type", dst, src).unchanged == 2


def test_rebuild_verdicts_replays_events_into_the_verdict_store(tmp_path):
    """裁决表是事件日志的派生物：从事件重放能重建，且不看 consumed 记账、重放幂等。"""
    log = EventLog(tmp_path / "feedback")
    log.append([
        make_event("vol02-cutline", 1, "cutline",
                   EventTarget(step="row_segment", unit="boundary", key="vol02:5:8:14",
                               book="vol02", page=5, col=8, slot=14),
                   {"y": 100, "y_old": 100, "verdict": "ok", "cand": "seam_narrow", "bi": 14}),
        make_event("vol02-cutline", 2, "cutline",
                   EventTarget(step="row_segment", unit="boundary", key="vol02:6:4:17",
                               book="vol02", page=6, col=4, slot=17),
                   {"y": 90, "y_old": 100, "verdict": "moved", "bi": 17}),
    ])
    store = GoldStore(tmp_path / "feedback" / "verdicts")
    out = rebuild_verdicts(log, store, table=RouteTable.load(None))
    assert out["events"] == 2 and out["added"] == 2
    got = {i.id: i.expected for i in store.list(SHARD)}
    assert got["vol02:5:8:14"]["cand"] == "seam_narrow"
    assert got["vol02:6:4:17"]["verdict"] == "moved"
    again = rebuild_verdicts(log, store, table=RouteTable.load(None))
    assert again["added"] == 0 and again["updated"] == 0
    assert "open-guji-dataset" not in str(store.root)


def test_gold_add_defaults_to_workspace_verdicts_not_dataset(monkeypatch, tmp_path):
    """运行时消费的默认落点是 workspace 裁决表；测试集仓 GoldStore() 默认根不变（给评测用）。"""
    from open_guji_cv.feedback.consumers import verdict_store
    from open_guji_cv.gold.store import default_dataset_root
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("GUJI_VERDICTS_DIR", raising=False)
    monkeypatch.delenv("GUJI_FEEDBACK_DIR", raising=False)
    assert verdict_store().root == tmp_path / "feedback" / "verdicts"
    assert default_dataset_root().name == "open-guji-dataset"


def test_console_verdict_store_follows_feedback_root(monkeypatch, tmp_path):
    from open_guji_cv.console import deps
    deps.set_roots(feedback=tmp_path / "fb", dataset=tmp_path / "ds")
    try:
        assert deps.verdict_store().root == tmp_path / "fb" / "verdicts"
        assert deps.gold_store().root == tmp_path / "ds"
    finally:
        deps.set_roots()
        deps._roots.update({"feedback": None, "dataset": None})
        deps._log = deps._batches = deps._gold = deps._verdicts = None
