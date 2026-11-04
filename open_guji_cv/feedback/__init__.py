"""（拆分 P4 第六批，2026-11-04：本包的 vision 已搬去 guji-manager `guji_manager.feedback`。）

（拆分 P2 第四批，2026-11-04：本包的 auto_admit, border_class_route, candidates, cell_migrate, cell_review, collate_state, exclusion_check, figures, harvest, lint, migrate_dedupe, migrate_v1, questions, replay, step8, web_votes 已搬去 guji-manager `guji_manager.feedback`。）

Feedback 层：统一反馈事件（EventLog）+ 路由（routes）+ 收割（harvest）+ 消费者。

人裁一律是事件：只追加、带批次与序号、消费幂等。四种历史格式
（verdicts / GUJI-SEED-EVENT / GUJI-SEG-REVIEW / marks）在收割时映射成统一信封。

事件消费到落库反馈这一段，统称 **Step8**（`step8.py`）：路由表是它的配置，
`gold_add` / `glyphdb_admit` / `crop_exclude` 三个消费者是它的三个出口。

设计文档：doc/console_architecture.md §3.6
"""

from .events import Event, EventLog, EventTarget  # noqa: F401
from .consumers import CONSUMERS, route_and_consume  # noqa: F401,E402  原经 step8 带起（Step8 已搬去 guji-manager）
from .routes import RouteTable  # noqa: F401,E402
