"""收尾步新名 `char_decide` 的导入入口（CV4 P3a-1，2026-11-28）。

收尾步从 `seed_admit` 改名 `char_decide`，分两版发：本版（兼容读口）**Step 本体仍是 `steps/seed_admit.py`**（Step id、产物、
指纹都不动，各书产物不过期），这里只给新名一个能 import 的地方：`from open_guji_cv.steps.char_decide import CharDecideStep`
拿到的就是同一个类。改名那一版把代码搬到本模块、`steps/seed_admit.py` 反过来留垫片（原名 `SeedAdmitParams`、`SeedAdmitStep`
照旧可导入，指向新类），撤垫片前通知。本模块**不在** `seed_admit` 的 `code_deps` 里。
"""

from __future__ import annotations

from .seed_admit import SeedAdmitParams, SeedAdmitStep

CharDecideParams = SeedAdmitParams
CharDecideStep = SeedAdmitStep

__all__ = ["CharDecideParams", "CharDecideStep", "SeedAdmitParams", "SeedAdmitStep"]
