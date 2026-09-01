"""M6 人工审查 Web 界面。

- state.py  : ReviewSession —— 数据装配 + 标签事件（纯逻辑，可单测）
- server.py : 本地 HTTP 服务（API + 静态页 + 图块服务）
- static/   : 单页前端（原生 JS，无外部依赖）
"""

from .state import ReviewSession

__all__ = ["ReviewSession"]
