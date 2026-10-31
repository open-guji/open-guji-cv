"""文意 L2：编码器加载失败要报出来（2026-10-31）。后面的 CtxOnline 会覆盖 no_encoder 的理由，不报就看不见。"""
import logging


def test_missing_encoder_warns_once(monkeypatch, caplog):
    from open_guji_cv.groups import ctx_l2
    monkeypatch.setattr(ctx_l2, "_encoder", lambda name, rev: None)
    ctx_l2._ENC_WARNED.discard("test/no-such-encoder")
    head = {"encoder": {"name": "test/no-such-encoder"}}
    with caplog.at_level(logging.WARNING, logger="open_guji_cv.groups.ctx_l2"):
        v1 = ctx_l2.judge(head, "左", "右", "日")
        v2 = ctx_l2.judge(head, "左", "右", "日")
    assert v1.why == v2.why == "abstain:no_encoder"
    assert sum("编码器加载失败" in r.getMessage() for r in caplog.records) == 1
