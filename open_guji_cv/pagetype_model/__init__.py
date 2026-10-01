# -*- coding: utf-8 -*-
"""页型「正文/非正文」二分的学习模型（可选件，默认关；P1 道 2026-10-01）。

只能把页判成「非正文」让 border_detect 闸拦下，**绝不**升级；模型只在很有把握时才判非正文，
其余一律走现行规则（`classify_page_type`）。代码分三块：

- `signals`：页级信号抽取（带版本号 `SIGNAL_VERSION`）；
- `model`：模型文件（元数据 + 指纹）读写；
- `gate`：对一页出「非正文」判决，`border_detect_gate` 的 `pagetype_model` 参数调它。
"""
