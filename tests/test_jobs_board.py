"""任务看板：只测整理逻辑（假连接），不连库。"""
import datetime as dt

from open_guji_cv.jobs import board


def test_helpers():
    assert board._mins(59 * 60) == "59分"
    assert board._mins(3725) == "1小时02分"
    t = dt.datetime(2026, 10, 25, 22, 0, tzinfo=dt.timezone.utc)
    assert board._la(t) == "10-25 15:00"
    assert board._la(None) == "—"


def test_kind_groups_same_steps_and_page_range():
    base = {"kind": "rerun", "spec": {"steps": {"from": "seed_admit", "to": None}, "pages": "all"}}
    part = {"kind": "rerun", "spec": {"steps": {"from": "seed_admit", "to": None}, "pages": "1,2"}}
    assert board._kind(base) != board._kind(part)
    assert board._kind(base) == board._kind({**base})
