"""Feedback 层：统一反馈事件（EventLog）+ 路由（routes）+ 收割（harvest）+ 消费者。

人裁一律是事件：只追加、带批次与序号、消费幂等。四种历史格式
（verdicts / GUJI-SEED-EVENT / GUJI-SEG-REVIEW / marks）在收割时映射成统一信封。

事件消费到落库反馈这一段，统称 **Step8**（`step8.py`）：路由表是它的配置，
`gold_add` / `glyphdb_admit` / `crop_exclude` 三个消费者是它的三个出口。

设计文档：.claude/doc/console_architecture.md §3.6
"""

from .events import Event, EventLog, EventTarget  # noqa: F401
from .step8 import STEP8, Outlet, Step8Spec  # noqa: F401
