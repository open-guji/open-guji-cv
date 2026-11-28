"""收尾步新名 `char_decide` 的导入入口（CV4 P3a-1，2026-11-28）。

收尾步从 `seed_admit` 改名 `char_decide`（P3a-3，2026-11-28）：**Step id、产物种类、产物目录、页顶层键、参数键已是 `char_decide`**
（`core/decide_names.ADMIT_STEP_ACTIVE`），旧名按键仍查得到（`STEPS["seed_admit"]`、`--from/--to seed_admit`、参数与产物读口）。
Step 类的**代码仍在 `steps/seed_admit.py`**（含它拆出去的各 `seed_admit_*` 块，没有搬文件：模块名是指纹块表与 SPLITS 的键，
搬文件会无谓动指纹；类名 `SeedAdmitStep`／`SeedAdmitParams` 不变，这里给新名 `CharDecideStep`／`CharDecideParams`）。
撤旧名前先通知 GM2–GM4（ZM、QTW、SJ 在途脚本要换）。本模块**不在** `seed_admit` 的 `code_deps` 里。
"""

from __future__ import annotations

from .seed_admit import SeedAdmitParams, SeedAdmitStep

CharDecideParams = SeedAdmitParams
CharDecideStep = SeedAdmitStep

__all__ = ["CharDecideParams", "CharDecideStep", "SeedAdmitParams", "SeedAdmitStep"]
