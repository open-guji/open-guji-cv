"""形近字组的统一接口（S0，设计见 doc/design/形近字组统一接口设计.md）。

四件事，各一个文件：

- `registry`  字组注册表：每组的成员字、判别后端、升降策略（单一真源）；
- `protocol`  判别输入 `JudgeInput`、判别输出 `GroupVerdict`、后端协议 `GroupBackend`；
- `backends`  适配器：**包住**现有的判别函数（规则／语料决策表／离线答案表／图像模型），不改其算法；
- `apply`     `apply_group_verdicts`：唯一的升降执行函数（抬升待审、降级放行），语义逐条对齐
  `seed_admit` 里现有的 `_ry_group_pass`／`_rr_clf_pass`／`_ji_yi_si_clf_cell`。

**本包 S0 阶段不被任何 Step 引用**，也不在任何 `code_deps` 里——加它不改任何一步的 `code_hash`、不让任何册的产物过期。
分层：L2（见 doc/module_map.md），只许 import L0／L1（`utils` 等）；不许 import `steps`／`clustering`／`feedback`。
"""
from .apply import ApplyResult, apply_group_verdicts  # noqa: F401
from .protocol import GroupBackend, GroupVerdict, JudgeInput, PatchUnavailable, window_from_text  # noqa: F401
from .registry import GROUPS, FlowSpec, GroupPolicy, GroupSpec, get_group, groups_of  # noqa: F401
