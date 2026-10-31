# -*- coding: utf-8 -*-
"""换图源后，切线等非逐格事件的锚要带产物页表 rev（否则写入口 RevGate 整条拒写）。"""
from open_guji_cv.review.event_write import product_anchor


class _St:
    def __init__(self, rev):
        self._rev = rev

    def manifest(self, book, step):
        return None

    def source_rev(self, book):
        return self._rev


def test_anchor_carries_source_rev_without_manifest():
    a = product_anchor(_St(3), "row_segment", {"book": "vol01", "page": 68})
    assert a == {"source_rev": 3}


def test_anchor_none_when_no_rev_and_no_manifest():
    assert product_anchor(_St(None), "row_segment", {"book": "vol01", "page": 68}) is None
