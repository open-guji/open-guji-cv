# -*- coding: utf-8 -*-
"""领域异常 → HTTP 状态码的**唯一映射处**。

领域层（`render/`、`review/`、`eval/`、`clustering/`）抛 `open_guji_cv.errors`
里的自有异常，不认识 fastapi；HTTP 语义只在这里出现一次。这样同一份领域代码
既能给控制台用，也能给 CLI 与云端道用（控制台重构方案 §四·2）。

用法：给路由加 `@maps_http`（在 `@router.get(...)` 下面一层），
或在别处直接 `raise http(exc)`。

**为什么不用 fastapi 的 exception handler**：那条路只在真发 HTTP 时才生效，
而这些实现体的另一半用户是 CLI 与云端道——它们直接调函数、不经过 ASGI。
用装饰器的话，「直调」与「走 HTTP」拿到的是同一个结果，快照测试量到的
也就是真行为（控制台重构 §九 的 46 条快照正是直调的）。
"""
from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypeVar

from fastapi import HTTPException

from ..errors import (BadRequest, Conflict, EncodeFailed, GujiError, NotFound,
                      Unsupported)

# 顺序有意义：先匹配到的先用，所以子类要排在父类前面
_CODES: tuple[tuple[type[GujiError], int], ...] = (
    (Conflict, 409),
    (BadRequest, 400),
    (Unsupported, 404),     # 「没有这个 Step 的叠图画法」对调用方来说就是「没有」
    (NotFound, 404),
    (EncodeFailed, 500),
)


def status_of(exc: GujiError) -> int:
    for cls, code in _CODES:
        if isinstance(exc, cls):
            return code
    return 500


def http(exc: GujiError) -> HTTPException:
    return HTTPException(status_of(exc), str(exc))


F = TypeVar("F", bound=Callable[..., Any])


def maps_http(fn: F) -> F:
    """把领域异常翻成 `HTTPException`，其余异常原样放行。

    `functools.wraps` 会带上 `__wrapped__`，fastapi 取签名时跟着它走，
    所以路径参数、查询参数、请求体模型的解析都不受影响。
    """
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except GujiError as e:
            raise http(e) from e
    return wrapper  # type: ignore[return-value]
