"""各 bench 的登记与实现（`eval/bench.py` 的 `register`）。新 bench 在这里加一个模块并在下面 import。

现有：`cut`（cut-2d，CV2 cut-bench）、`decide`、`decide-gate`（CV4 decide-bench）。各线接入见 ai-team
`domain/CV/规范/bench统一接口-2026-11-28.md`。
"""
from . import cut, decide, decide_gate, near_form_admit  # noqa: F401
