# -*- coding: utf-8 -*-
"""影子放行闸（shadow gate）：可选的「降级不升级」第二意见。

第一阶段（用户 2026-09-30 批准，overview#305）：影子模型只能把现行规则**已放行**的格降回待审，
绝不把待审格放行。代码分三块：

- `signals`：逐格信号抽取（带版本号 `SIGNAL_VERSION`，口径与训练一致）；
- `model`：模型文件（元数据 + 指纹）读写；
- `gate`：对一页已放行的格出 veto 决定，`seed_admit` 的 `shadow_veto` 参数调它。
"""
