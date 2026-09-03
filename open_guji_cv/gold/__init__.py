"""Gold 层：统一金标信封 + 分片仓 + 旧格式适配器。

P1 只落到「事件能自动进 items.jsonl」这一步；完整的 GoldStore（采样器、重键、
四个适配器读全部旧分片）是 P2。

设计文档：.claude/doc/console_architecture.md §3.5
"""

from .item import GoldItem  # noqa: F401
from .store import GoldStore  # noqa: F401
