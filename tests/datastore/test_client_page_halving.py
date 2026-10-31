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
