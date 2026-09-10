# -*- coding: utf-8 -*-
"""领域层的错误信号。**不 import fastapi。**

## 为什么要有这个模块

叠图画法、生僻字引擎、定字卡装配这些**领域逻辑**原先长在 `console/app.py` 的
路由旁边，出错时直接 `raise HTTPException(404, "原图缺失")`——于是 fastapi
渗进了领域逻辑，这些代码搬出 `console/` 给 CLI 与云端道用时就得先把 HTTP 摘掉
（控制台重构方案 §四·2：全文 26 处 `HTTPException`，11 处落在要搬走的代码里）。

现在领域层抛这里的异常，`console/errors.py` 把它们统一映射成 HTTP 码。
命令行则直接 `except NotFound` 打一行人话——**同一份领域代码，两个前台。**

新增异常的规矩：**只表达「什么东西不在/不认识」，不表达 HTTP 语义**。
状态码归 `console/errors.py` 管，领域层不该知道 404 长什么样。
"""
from __future__ import annotations


class GujiError(Exception):
    """本项目领域层异常的根。捕获它就等于「业务上没成」。"""


class NotFound(GujiError):
    """要的东西不在：产物、原图、图块、列图、账本、批次、任务……"""


class ProductMissing(NotFound):
    """某步某页的数值产物没有——多半是这一步还没跑，或参数换了导致过期。"""


class ImageMissing(NotFound):
    """图像不在：原图、缓存图块、列图。"""


class Unsupported(GujiError):
    """认得这个请求，但没有对应的做法（如某个 Step 还没写叠图画法）。"""


class BadRequest(GujiError):
    """调用方给错了：页号表达式不合法、参数 JSON 解析不了、步骤范围不对。"""


class Conflict(GujiError):
    """与既有状态冲突（如批次 id 已存在）。"""


class EncodeFailed(GujiError):
    """图像编码失败——这是真的坏了，不是「没有」。"""
