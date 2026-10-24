"""`guji db sync` 顺带落库（`feedback/auto_admit.py`）：只跑字形库两个消费者、逐条记账、报错的留着、落了再推。"""

from __future__ import annotations

from contextlib import nullcontext

from open_guji_cv import cli_db
from open_guji_cv.datastore import workcopy
from open_guji_cv.feedback.auto_admit import admit_pending, touched
from open_guji_cv.feedback.consumers import ConsumeResult
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event

ROUTES = """\
- match: {kind: confirm}
  to:
  - {consumer: glyphdb_admit}
  - {consumer: gold_add, shard: char-recognition/confirm}
- match: {kind: glyph_audit}
  to:
  - {consumer: glyph_audit}
"""


def _confirm(seq: int, key: str, ch: str = "甲"):
    return make_event("rev", seq, "confirm", EventTarget(step="glyph_match", unit="char", key=key, book="vol01"),
                      {"shape": ch}, ts=f"2026-10-24T00:00:0{seq}Z")


def _log(tmp_path) -> EventLog:
    fb = tmp_path / "feedback"
    (fb / "events").mkdir(parents=True)
    (fb / "routes.yaml").write_text(ROUTES, encoding="utf-8")
    log = EventLog(fb)
    log.append([_confirm(1, "vol01:1:1:1"), _confirm(2, "vol01:1:1:2"), _confirm(3, "vol01:1:1:3")])
    return log


def _fake(errors_for=()):
    calls = []

    def run(pairs, **kw):
        calls.append([e.id for e, _ in pairs])
        res = ConsumeResult(consumer="glyphdb_admit", n_events=len(pairs), added=len(pairs) - len(errors_for))
        res.errors = [f"{k}: 缓存里没有字块" for k in errors_for]
        return res
    return run, calls


def test_only_glyph_consumers_run_and_failed_events_stay_pending(tmp_path):
    log = _log(tmp_path)
    run, calls = _fake(errors_for=["vol01:1:1:2"])
    out = admit_pending(log, consumers={"glyphdb_admit": run})
    assert calls == [["evt_rev_000001", "evt_rev_000002", "evt_rev_000003"]]
    assert out["glyphdb_admit"]["marked"] == 2 and out["glyphdb_admit"]["left"] == ["evt_rev_000002"]
    assert log.consumed_ids("glyphdb_admit") == {"evt_rev_000001", "evt_rev_000003"}
    assert not log.consumed_ids("gold_add")          # 金标那条去向不归落库管
    assert touched(out)
    # 第二轮只剩那一条
    run2, calls2 = _fake()
    admit_pending(log, consumers={"glyphdb_admit": run2})
    assert calls2 == [["evt_rev_000002"]]


def test_dry_run_counts_only(tmp_path):
    log = _log(tmp_path)
    run, calls = _fake()
    out = admit_pending(log, dry_run=True, consumers={"glyphdb_admit": run})
    assert out == {"glyphdb_admit": {"events": 3, "dry_run": True}} and not calls
    assert not log.consumed_ids("glyphdb_admit") and not touched(out)


def test_nothing_pending_is_untouched(tmp_path):
    log = _log(tmp_path)
    admit_pending(log, consumers={"glyphdb_admit": _fake()[0]})
    out = admit_pending(log, consumers={"glyphdb_admit": _fake()[0]})
    assert out == {} and not touched(out) and not touched({"error": "boom"})


def _wire(tmp_path, monkeypatch, admitted):
    syncs, admits = [], []
    monkeypatch.delenv("GUJI_DATA_BRANCH", raising=False)
    monkeypatch.delenv("GUJI_AUTO_ADMIT", raising=False)
    monkeypatch.setenv("GUJI_DATA_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(cli_db, "_pg_conn", lambda branch=None: nullcontext())
    monkeypatch.setattr(cli_db, "glyph_hooks", lambda ws: None)
    monkeypatch.setattr(workcopy, "sync", lambda *a, **kw: syncs.append(kw["dry_run"]) or {"action": "push"})
    monkeypatch.setattr(cli_db, "_admit_pending", lambda ws, dry: admits.append(dry) or admitted)
    return syncs, admits


def test_sync_pushes_again_after_admitting(tmp_path, monkeypatch):
    syncs, admits = _wire(tmp_path, monkeypatch, {"glyphdb_admit": {"marked": 2, "left": []}})
    res = cli_db.sync_workspace(tmp_path, src=object())
    assert syncs == [False, False] and admits == [False]
    assert res["glyph_admit"]["glyphdb_admit"]["marked"] == 2 and res["after_admit"] == {"action": "push"}


def test_sync_without_new_admissions_pushes_once(tmp_path, monkeypatch):
    syncs, _ = _wire(tmp_path, monkeypatch, {})
    assert "after_admit" not in cli_db.sync_workspace(tmp_path, src=object())
    assert syncs == [False]
    syncs, admits = _wire(tmp_path, monkeypatch, {"glyphdb_admit": {"events": 3, "dry_run": True}})
    cli_db.sync_workspace(tmp_path, src=object(), dry_run=True)
    assert syncs == [True] and admits == [True]


def test_sync_admit_can_be_switched_off(tmp_path, monkeypatch):
    syncs, admits = _wire(tmp_path, monkeypatch, {"glyphdb_admit": {"marked": 1}})
    assert "glyph_admit" not in cli_db.sync_workspace(tmp_path, src=object(), admit=False)
    monkeypatch.setenv("GUJI_AUTO_ADMIT", "0")
    cli_db.sync_workspace(tmp_path, src=object())
    assert syncs == [False, False] and admits == []
