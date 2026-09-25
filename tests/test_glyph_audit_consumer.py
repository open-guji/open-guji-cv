# -*- coding: utf-8 -*-
"""字形库体检裁决：ok 记账 / evict 撤库 / relabel 按人裁改字重进库。"""

from __future__ import annotations

import json
import sqlite3

import cv2
import numpy as np

from open_guji_cv.clustering.glyph_db import GlyphDB
from open_guji_cv.feedback.events import EventTarget, make_event
from open_guji_cv.feedback.glyph_audit import glyph_audit


def _png(k):
    img = np.full((64, 64), 255, np.uint8)
    cv2.rectangle(img, (10 + k, 10), (50, 50 - k), 0, 3)
    return cv2.imencode(".png", img)[1].tobytes()


def _ev(seq, payload):
    return (make_event("glyphlib-audit", seq, "glyph_audit",
                       EventTarget(step="glyph_audit", unit="cell", key=payload["instance_id"]),
                       payload), None)


def test_decisions(tmp_path):
    p = tmp_path / "output" / "glyph.db"
    p.parent.mkdir()
    g = GlyphDB(p)
    g.admit_instance("bk:1:1:1", "王", _png(0), provenance="align", page="1", col=1, idx=1)
    g.admit_instance("bk:1:1:2", "王", _png(1), provenance="align", page="1", col=1, idx=2)
    g.admit_instance("bk:1:1:3", "干", _png(2), provenance="align", page="1", col=1, idx=3)
    g.close()
    r = glyph_audit([
        _ev(1, {"v": "ok", "key": "k1", "instance_id": "bk:1:1:2"}),
        _ev(2, {"v": "evict", "key": "k2", "instance_id": "bk:1:1:1", "target": "bk:1:1:3"}),
        _ev(3, {"v": "relabel", "key": "k3", "instance_id": "bk:1:1:1", "char": "干"}),
        _ev(4, {"v": "relabel", "key": "k4", "instance_id": "bk:1:1:2", "char": "x"}),
    ], db_path=str(p))
    assert r.added == 3 and r.skipped == 1, r.errors
    c = sqlite3.connect(p)
    assert c.execute("select count(*) from instances where instance_id='bk:1:1:3'").fetchone()[0] == 0
    lab, prov = c.execute("select i.label, a.provenance from instances i join admissions a "
                          "using(instance_id) where instance_id='bk:1:1:1'").fetchone()
    assert (lab, prov) == ("干", "human")
    assert c.execute("select g.char from exemplars e join glyphs g using(glyph_id) "
                     "where e.instance_id='bk:1:1:1'").fetchone()[0] == "干"
    c.close()
    dec = [json.loads(l) for l in open(p.parent / "glyph_selfcheck" / "decisions.jsonl")]
    assert [d["key"] for d in dec] == ["k1", "k2", "k3"]
    assert dec[1]["old_char"] == "干" and dec[2]["old_char"] == "王"
