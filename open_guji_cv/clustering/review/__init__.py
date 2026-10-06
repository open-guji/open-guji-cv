"""审查数据装配：state.ReviewSession（纯逻辑），以及种子／对勘审查材料导出（seed_export、collation_export）。

2026-10-06 cv 大清理（overview#413）：v1 的本地审查 HTTP 服务（server.py + static/）与 artifact_export 随 v1 `review` 命令一起删除；
审阅一律走控制台。
"""

from .state import ReviewSession

__all__ = ["ReviewSession"]
