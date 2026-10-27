# -*- coding: utf-8 -*-
"""执行方的异常分类：连库断线算环境类（换会话重排），其他异常不算。"""
from __future__ import annotations

import pytest

from open_guji_cv.jobs import runner as R


class ConnectionClosedError(Exception):
    """模拟 websockets 的 ConnectionClosedError（类名对得上即可）。"""


class OperationalError(Exception):
    """模拟 psycopg.OperationalError。"""


@pytest.mark.parametrize("exc", [
    ConnectionClosedError("no close frame received or sent"),
    OperationalError("server closed the connection unexpectedly"),
])
def test_connection_errors_are_env(exc):
    assert R._is_conn_error(exc)


@pytest.mark.parametrize("exc", [
    RuntimeError("boom"),
    ValueError("bad spec"),
    R.StageError("failed", "glyph_match"),
])
def test_other_errors_are_not_env(exc):
    assert not R._is_conn_error(exc)
