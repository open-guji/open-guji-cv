"""反色带送审：人点「是」→ 裁决表 → Step0 读修好的图；点「否」不修（2026-10-22）。"""
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from open_guji_cv.feedback.consumers import route_and_consume
from open_guji_cv.feedback.events import EventLog, EventTarget, make_event
from open_guji_cv.feedback.lookup import resolved_inverted
from open_guji_cv.feedback.questions import INVERTED_BAND_SHARD
from open_guji_cv.feedback.routes import RouteTable
from open_guji_cv.gold.store import GoldStore
from open_guji_cv.utils.preclean import effective_raw_path

RULE = {"kind": "inverted_rect", "x0": 40, "x1": 359, "y0": 120, "y1": 169}


def _page(tmp_path):
    g = np.full((300, 400), 255, np.uint8)
    g[40:260, 60:66] = 0
    g[120:170, 40:360] = 255 - g[120:170, 40:360]
    p = tmp_path / "raw" / "7.png"
    p.parent.mkdir(parents=True)
    cv2.imwrite(str(p), g)
    return SimpleNamespace(id="volx", preclean={}, raw_path=lambda page: tmp_path / "raw" / f"{page}.png")


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_VERDICTS_DIR", str(tmp_path / "verdicts"))
    monkeypatch.setenv("GUJI_CACHE_DIR", str(tmp_path / "cache"))
    return tmp_path


def _decide(ws, page, verdict, seq):
    log = EventLog(ws / "feedback")
    log.append([make_event("b1", seq, "inverted_band", EventTarget(step="invert_detect", unit="page", key=f"invert:volx:{page}"),
                           {"verdict": verdict, "rules": [RULE], "question": "invert_detect.page.is_inverted"})])
    route_and_consume(log, "b1", RouteTable.load(None), GoldStore(ws / "verdicts"))


def test_yes_routes_to_shard_and_step0_reads_fixed_image(ws):
    book = _page(ws)
    assert effective_raw_path(book, 7) == book.raw_path(7)        # 没审过：原图
    _decide(ws, 7, "yes", 1)
    items = GoldStore(ws / "verdicts").list(INVERTED_BAND_SHARD, legacy=False)
    assert [i.expected for i in items] == [{"verdict": "yes", "rules": [RULE]}]
    assert resolved_inverted("volx") == {7: {"verdict": "yes", "rules": [RULE]}}
    p = effective_raw_path(book, 7)
    assert p != book.raw_path(7) and p.exists()
    fixed = cv2.imread(str(p), 0)
    assert (fixed[125:165, 100:300] > 128).mean() > 0.9            # 黑条翻回白纸
    assert (fixed[125:165, 60:66] < 128).all()                     # 笔画还原成黑


def test_no_keeps_raw(ws):
    book = _page(ws)
    _decide(ws, 7, "no", 1)
    assert resolved_inverted("volx")[7]["verdict"] == "no"
    assert effective_raw_path(book, 7) == book.raw_path(7)
