"""`guji pipeline` 的步骤选择要套书级可选步骤开关（与控制台同参同输出）。

假引擎里的 `opt` 是一个虚构的可选步（原先用的是 Step5-c `ocr_candidates`，已于 2026-10-18 删除）。"""
from types import SimpleNamespace

from open_guji_cv.cli_v2 import cli_steps


class _Pipe:
    steps = ["a", "opt", "b"]

    def slice(self, f, t):
        s = self.steps
        i = s.index(f) if f else 0
        j = s.index(t) + 1 if t else len(s)
        return s[i:j]


class _Eng:
    def __init__(self, on: bool):
        self.pipeline = _Pipe()
        self.book = SimpleNamespace(id="x", opt_on=on)

    def _enabled(self, steps):
        return steps if self.book.opt_on else [s for s in steps if s != "opt"]


def test_pipeline_cli_skips_optional_step_when_book_switch_off():
    assert cli_steps(_Eng(False), None, None) == ["a", "b"]
    assert cli_steps(_Eng(False), "opt", None) == ["b"]       # --from 也套开关


def test_pipeline_cli_keeps_optional_step_when_switch_on_or_named_explicitly():
    assert cli_steps(_Eng(True), None, None) == ["a", "opt", "b"]
    assert cli_steps(_Eng(False), "opt", "opt") == ["opt"]   # guji step 点名


def test_rare_candidates_consumed_only_when_a_downstream_reads_it():
    """Step5-b 没有下游真在读（seed_admit.rare_ref / context_decide.rare_topk 都关）时，常规批量不跑它。"""
    import open_guji_cv.steps  # noqa: F401  注册 Step
    from open_guji_cv.core.engine import rare_candidates_consumed
    from open_guji_cv.core.step import STEPS

    pipe = ["glyph_match", "rare_candidates", "align_ref", "context_decide", "seed_admit"]

    def params_for(**over):
        def _p(sid):
            return STEPS[sid].spec.params(**over.get(sid, {}))
        return _p

    book = SimpleNamespace()
    off = {"rare_ref": False, "symbol_review": False}   # 两个都 2026-10-24 起缺省开，缺省就有下游在读
    assert rare_candidates_consumed(pipe, params_for(), book) is True
    assert rare_candidates_consumed(pipe, params_for(seed_admit=off), book) is False
    assert rare_candidates_consumed(pipe, params_for(seed_admit=off, context_decide={"rare_topk": 3}), book) is True
