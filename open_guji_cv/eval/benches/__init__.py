"""各 bench 的登记与实现（`eval/bench.py` 的 `register`）。新 bench 在这里加一个模块并在下面 import。

现有：`cut`（cut-2d，CV2 cut-bench）、`cut_parts`（cut-gate、cut-2e-frame、cut-2e-ink、cut-2b-band、cut-rulers，CV2）、
`cut_legacy`（切字旧集里 deprecated 的，CV2）、`decide`、`decide-gate`（CV4 decide-bench）、`near_form_admit`、
`cands`（read-3c-cands、decide-4b-ctx，CV3）。各线接入见 ai-team `domain/CV/规范/bench统一接口-2026-11-28.md`。
"""
from . import cands, cut, cut_legacy, cut_parts, decide, decide_context, decide_gate, near_form_admit  # noqa: F401
