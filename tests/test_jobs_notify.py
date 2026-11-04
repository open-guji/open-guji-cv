"""任务库跑完通知：正文格式、无令牌静默、取消单不打扰（不连库、不发网络）。"""
from open_guji_cv.jobs import notify as N


def _j(i, status, error=None, book="vol01"):
    return {"id": i, "kind": "rerun", "book": book, "status": status, "error": error}


def test_message_summarizes_batch():
    t = N.message([_j(1, "succeeded"), _j(2, "failed", "run：boom\nmore"), _j(3, "blocked", "依赖 #2 没成功")])
    assert "3 条单已全部结束" in t and "1 成功" in t and "2 未成" in t
    assert "#2 vol01 ✗：run：boom" in t and "more" not in t
    assert "guji_jobs retry" in t


def test_message_all_cancelled_is_silent():
    assert N.message([_j(1, "cancelled")]) is None


def test_send_without_token_is_gone(monkeypatch, tmp_path):
    monkeypatch.delenv("CLAUDE_RELAY_TOKEN", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    assert N._send("A30", "x") == "gone"
