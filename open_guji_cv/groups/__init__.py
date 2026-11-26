"""字组的统一接口（设计见 doc/design/形近字组统一接口设计.md、M7-字组统一流程-variant-tie改造方案.md）。

- `registry`  字组注册表：每组的成员字、判法 `FlowSpec`（单一真源，判法＝方法数组）；
- `methods`   八类方法（码位归一、字频、上下文固定匹配、LLM、HOG＋岭回归、IDS、复合、自定义函数）与方法输入 `MethodInput`；
- `protocol`  判别输入 `JudgeInput`、判别输出 `GroupVerdict`、后端协议 `GroupBackend`；
- `flow`      字组统一流程（`seed_admit.group_flow`）：进入、跑解法、合并、补放／复核、留证据；
- `backends`  离线评测（`eval/groups.py`）用的适配器，包住现有判别函数。

`seed_admit` 的 `code_deps` 收了 `flow`／`methods`／`freq`／`registry`／`ctx_l1`／`ctx_l3`／`context`／`bars`，改它们会让该步过期。
分层：L2（见 doc/module_map.md），只许 import L0／L1（`utils` 等）；不许 import `steps`／`clustering`／`feedback`。
"""
from .protocol import GroupBackend, GroupVerdict, JudgeInput, PatchUnavailable, window_from_text  # noqa: F401
from .registry import GROUPS, FlowSpec, GroupSpec, get_group, groups_of  # noqa: F401
