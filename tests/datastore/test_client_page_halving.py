"""WorkerSource 分页读：整页太大 Worker 回 500／503 时页减半再试（史記 988g3f0wsu db-pull，2026-10-31）。"""
import pytest

from open_guji_cv.datastore.client import CentralError, WorkerSource


def _src(fail_above: int, status: int):
    src = WorkerSource(url="https://example.invalid", token="x", branch="main")
    calls = []

    def fake_call(method, path, *, query=None, **kw):
        calls.append(query["limit"])
        if query["limit"] > fail_above:
            raise CentralError(status, "internal", "too big")
        return {"rows": [{"n": query["limit"]}], "next": None}

    src._call = fake_call
    return src, calls


@pytest.mark.parametrize("status", [500, 503])
def test_rows_halve_page_on_500_or_503(status):
    src, calls = _src(fail_above=300, status=status)
    rows = list(src._rows("files", "ws1", None, {}))
    assert calls == [2000, 1000, 500, 250] and rows == [{"n": 250}]


def test_rows_other_errors_raise():
    src, _ = _src(fail_above=0, status=404)
    with pytest.raises(CentralError):
        list(src._rows("files", "ws1", None, {}))


def test_rows_halve_down_to_one_then_grow_back():
    """大行挨着时一页只取 1 行也要能过；过了大行页长按倍数放回（siku-zongmu glyph-pack 清单，2026-11-01）。"""
    src = WorkerSource(url="https://example.invalid", token="x", branch="main")
    calls = []

    def fake_call(method, path, *, query=None, **kw):
        calls.append(query["limit"])
        after = int(query.get("after") or 0)
        if after == 0 and query["limit"] > 1:
            raise CentralError(500, "internal", "too big")
        return {"rows": [{"n": after}], "next": str(after + 1) if after < 2 else None}

    src._call = fake_call
    rows = list(src._rows("files", "ws1", None, {}))
    assert rows == [{"n": 0}, {"n": 1}, {"n": 2}]
    assert calls[-3:] == [1, 2, 4] and calls[0] == 2000


def test_rows_raise_when_single_row_still_fails():
    src, _ = _src(fail_above=0, status=500)
    with pytest.raises(CentralError):
        list(src._rows("files", "ws1", None, {}))
