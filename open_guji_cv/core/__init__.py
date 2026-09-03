"""四个抽象的核心层：Step / Product / Gold / Event（P0 先落 Step 与 Product）。

- spec.py      StepSpec / ProductKindSpec / 单位键
- step.py      Step 基类、注册表 STEPS、RunContext
- book.py      BookSpec（图源、dev_set、列数）
- pipeline.py  yaml → DAG
- engine.py    指纹、stale、执行
- anchor.py    坐标空间

设计文档：.claude/doc/console_architecture.md
"""
