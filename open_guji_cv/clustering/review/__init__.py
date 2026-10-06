"""审查数据装配：state.ReviewSession（纯逻辑）；persist_js 供 scripts/audit_glyph_db.py 的审查页用。

2026-10-06 cv 大清理（overview#413）：v1 的本地审查 HTTP 服务（server.py + static/）与 artifact_export 随 v1 `review` 命令一起删除；
审阅一律走控制台。
"""

from .state import ReviewSession

__all__ = ["ReviewSession"]
