# -*- coding: utf-8 -*-
"""每请求的工作区：从 `X-Guji-Workspace` 头取，塞进 contextvar。

## 为什么工作区不能是服务端的状态

用户 2026-09-15 定的形态：**工作区这个值只存在于浏览器**，每个请求带着走。
这样才能「开两个标签页，各自在不同工作区上干活」——一个看四庫、一个看北行日錄，
互不影响。服务端一旦存「当前工作区」，两个标签页就会互相打架：A 切一下，
B 的下一次请求就跟着变了。

于是：
- 前端每次请求带 `X-Guji-Workspace: <工作区 id>`（`api/client.ts` 统一注入，
  值存在 `localStorage`，每个标签页可以不同）；
- 这个中间件把它塞进 `core/workspace._WORKSPACE_OVERRIDE`，该请求内所有
  路径解析（products / cache / glyph_db / feedback …）都跟着走；
- 请求结束还原，不留痕。`contextvars` 按请求隔离，并发请求之间不会串。

**跑批不走这条路**：任务的工作区是工单的一部分（`JobSpec.workspace`，入队时
写死），子进程按工单拼 `GUJI_WORKSPACE`。看板怎么切都影响不到已入队的任务。

## 白名单

只接受**已知的工作区目录**——请求头是浏览器来的，不能拿它当任意路径用
（否则等于开放了「让服务端读写任意目录」）。白名单来自 `discover_workspaces()`，
即「跟当前工作区放在一起、且有 books/ 的目录」，与下拉框里能选的那些一致。
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware

from ..core.workspace import reset_workspace_override, set_workspace_override

HEADER = "X-Guji-Workspace"
QUERY = "ws"       # 图片类 URL 走查询参数（<img src> 带不了头）


class WorkspaceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        # 头优先；`?ws=` 是给**图片类出口**用的后路——`<img src>` 发不出自定义
        # 请求头，叠图/原图/字块只能把工作区放查询串里（api/client.ts 的
        # `withWorkspace()`）。两边同名同义，认哪个都一样。
        raw = request.headers.get(HEADER)
        if raw is None:
            raw = request.query_params.get(QUERY)
        token = None
        if raw is not None:
            from .routers.workspace import allowed_workspaces, resolve_workspace_id
            # 传的是**工作区 id**（URL 上露出来的那个，如 `beixingrilu`）。
            # 兼容绝对路径：早先的前端传的是路径，浏览器里可能还留着。
            path = "" if raw == "" else (resolve_workspace_id(raw)
                                         or (raw if raw in allowed_workspaces() else None))
            # 认不出就忽略（退回环境变量），不报错——换了机器、改了目录名、
            # 或者手敲错 id 时，页面还能打开，只是落在默认工作区。
            if path is not None:
                token = set_workspace_override(path)
        try:
            return await call_next(request)
        finally:
            if token is not None:
                reset_workspace_override(token)
