# -*- coding: utf-8 -*-
"""准备拉库的读超时算瞬时：带瞬时前缀、不计入连续环境失败；其余环境错仍按原样。"""
from __future__ import annotations

from open_guji_cv.jobs import runner as R
from open_guji_cv.jobs import store as S


def test_read_timeout_is_transient():
    msg = "准备「db-pull」段失败：TimeoutError: The read operation timed out"
    assert R._is_transient_timeout(msg)
    assert R._is_transient_timeout("socket.timeout: timed out")


def test_central_5xx_is_transient():
    for code in ("500", "502", "503", "504"):
        msg = f"准备「db-pull」段失败：bash rerun_prep.sh vol03 退出码 1：open_guji_cv.datastore.client.CentralError: {code} http: {{\"error\":\"internal\"}}"
        assert R._is_transient_timeout(msg), code


def test_other_env_errors_are_not_transient():
    assert not R._is_transient_timeout("准备「db-pull」段失败：HTTP 403 Forbidden（Cloudflare）")
    assert not R._is_transient_timeout("准备「db-pull」段失败：中心库 500")
    assert not R._is_transient_timeout("准备「base」段失败：CentralError: 404 not_found: 包不存在")
    assert not R._is_transient_timeout("")


def test_transient_prefix_is_distinct_and_delay_is_sane():
    assert S.TRANSIENT != "环境："
    assert not "环境：".startswith(S.TRANSIENT)
    lo, hi = S.TRANSIENT_DELAY_S
    assert 0 < lo < hi
