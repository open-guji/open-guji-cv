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


def test_config_is_compact_and_book_name_short():
    sp = {"cv_ref": "cbcd76f82eba8769b9a4d", "steps": {"from": "seed_admit", "to": None}, "pages": "all",
          "book_overrides": {"cv_version": "0.6.1.dev37pg3773155662f9"}, "force": True}
    c = board._config({"kind": "rerun", "spec": sp})
    assert c.startswith("cv cbcd76f · seed_admit→尾") and c.endswith("强制") and "全册" not in c and len(c) < 70
    plain = {"cv_ref": "17a80598fe8624a8", "steps": {"from": None, "to": None}, "pages": "all"}
    assert board._config({"kind": "rerun", "spec": plain}) == "cv 17a8059"
    assert board._book_name("988g3f0wsu", {}) == "史记"
    assert board._book_name("zzz", {"zzz": "某书某书某书某书某书某书"}) == "某书某书某书某书某书某书"[:10]
    assert board._book_name("zzz", {}) == "zzz"
