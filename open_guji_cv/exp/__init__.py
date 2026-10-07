# -*- coding: utf-8 -*-
"""A/B 实验框架（overview#457，E1）：两份配置各跑各的输出目录，再统一比较。

一个实验 = 一份 yaml，只写与基线不同的参数（覆盖层），不改代码、不改书的正式 `books/*.yaml`。
框架是**外挂**：只用 `Engine(params=…)` 的调用方覆盖层和可改指的产物根，**不碰任何 Step 模块
与它的 `code_deps`**，所以不会让各书产物判过期。

- `config`   实验 yaml → `ExpConfig`（含 issue 原定的 `--base/--var` 短写法）
- `runner`   准备共享上游（硬链接快照）、各变体在自己的产物根上跑 `--from…--to`
- `cells`    读各变体的 `seed_admit` 产物与页型（正文／非正文）
- `labels`   标签：人裁事件、看图结论 jsonl、金标分片；每条带 `source` 与 `selection`
- `stats`    页簇配对自助法、McNemar 精确检验
- `compare`  总体／分层／逐格翻转／判准 → `report.json`
- `report_md` 人看的 `report.md`
- `flips`    翻转格抽样，出审查页数据

**绝不写书的正式 `products/`**：exp 根落在工作区 `products/` 之内直接拒跑（`runner.guard_root`）。
"""
