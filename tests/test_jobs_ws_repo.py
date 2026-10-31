"""执行方的工作区仓：单子存的 ws_repo 为空时，按册 ID 现查 WS_REPOS（#1558：提交时没映射上，prep 找不到工作区）。"""
from open_guji_cv.jobs import runner as R
from open_guji_cv.jobs import spec as SP


def test_empty_ws_repo_falls_back_to_book_id_table():
    sp = {"ws_glob": "988g3f0wsu-*", "ws_repo": None, "book": "09"}
    assert R.resolve_ws_repo(sp) == SP.WS_REPOS["988g3f0wsu"]


def test_explicit_ws_repo_wins():
    sp = {"ws_glob": "988g3f0wsu-*", "ws_repo": "owner/other", "book": "09"}
    assert R.resolve_ws_repo(sp) == "owner/other"


def test_unknown_book_returns_none_so_prep_uses_glob():
    sp = {"ws_glob": "96mid1ogzk-*", "ws_repo": None, "book": "01"}
    assert R.resolve_ws_repo(sp) == SP.WS_REPOS["96mid1ogzk"]
    sp = {"ws_glob": "zzzzzzzzzz-*", "ws_repo": None, "book": "01"}
    assert R.resolve_ws_repo(sp) is None
