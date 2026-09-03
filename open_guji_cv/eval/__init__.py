"""Eval 层：把 `scripts/eval_*.py` 统一包进控制台。

**先包后改**：现有 27 个评测脚本一行不动，这里只做三件事——
1. `registry.py` 把各脚本的调用契约（位置参数叫什么、报告选项是哪个、金标传哪个路径）
   记成数据，抹平「--out / --json-out / --report 三种写法、位置参数四种名字」的差异；
2. `runner.py` 起子进程跑它、抓 stdout、解析出指标；
3. `report.py` 统一报告格式，带上手册要求的分母、分层、stale 金标数、跳过的 uncertain 数。

**报告必须带分母**（手册踩过：精确率从 0.71 掉到 0.52 不是退步，是缺陷基数变小了），
**分层的分层报**（确定层与疑似层用途不同，合成一个数会同时掩盖两件事），
**先查漂移再谈数字**（stale 金标数必须露出来）。

设计文档：.claude/doc/console_architecture.md §3.7
"""

from .registry import EVALS, EvalSpec, find_eval  # noqa: F401
from .report import EvalReport  # noqa: F401
from .runner import run_eval  # noqa: F401
