# -*- coding: utf-8 -*-
"""下版框「带内多候选峰选哪条」的学习模型（可选件，默认关；S1 道 2026-10-02）。

现行规则是 `peak_line_search.find_horizontal_border(side="bottom")` 里一串写死的补丁
（primary → 边界锁死 → 角度护栏 → 次选纠偏 → 跨页先验救援 → 落到墨条下沿）。这里把带内全部峰
显式列成候选，每个算一组信号，由模型排序选一条；硬护栏在模型外。代码分三块：

- `signals`：候选枚举 + 信号（带版本号 `SIGNAL_VERSION`）；
- `model`：模型文件（元数据 + 内容指纹）读写；
- `chooser`：选峰回调（`BottomPeakModel.bind(top_pos)`），含硬护栏，接在 `find_horizontal_border` 的
  `bottom_chooser` 钩子上；`detect_borders(bottom_model=...)` 传入，不传 = 与旧行为逐位相同。
"""
