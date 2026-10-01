"""`guji pipeline` 的步骤选择要套书级可选步骤开关（与控制台同参同输出）。"""
from types import SimpleNamespace

from open_guji_cv.cli_v2 import cli_steps


class _Pipe:
    steps = ["a", "ocr_candidates", "b"]

    def slice(self, f, t):
        s = self.steps
        i = s.index(f) if f else 0
        j = s.index(t) + 1 if t else len(s)
        return s[i:j]


class _Eng:
    def __init__(self, on: bool):
        self.pipeline = _Pipe()
        self.book = SimpleNamespace(id="x", ocr_candidates=on)

    def _enabled(self, steps):
        return steps if self.book.ocr_candidates else [s for s in steps if s != "ocr_candidates"]


def test_pipeline_cli_skips_optional_step_when_book_switch_off():
    assert cli_steps(_Eng(False), None, None) == ["a", "b"]
    assert cli_steps(_Eng(False), "ocr_candidates", None) == ["b"]       # --from 也套开关


def test_pipeline_cli_keeps_optional_step_when_switch_on_or_named_explicitly():
    assert cli_steps(_Eng(True), None, None) == ["a", "ocr_candidates", "b"]
    assert cli_steps(_Eng(False), "ocr_candidates", "ocr_candidates") == ["ocr_candidates"]   # guji step 点名


def test_rare_candidates_consumed_only_when_a_downstream_reads_it():
    """Step5-b 没有下游真在读（seed_admit.rare_agree / context_decide.rare_topk 都关）时，常规批量不跑它。"""
    import open_guji_cv.steps  # noqa: F401  注册 Step
    from open_guji_cv.core.engine import rare_candidates_consumed
    from open_guji_cv.core.step import STEPS

    pipe = ["glyph_match", "rare_candidates", "align_ref", "context_decide", "seed_admit"]

    def params_for(**over):
        def _p(sid):
            return STEPS[sid].spec.params(**over.get(sid, {}))
        return _p

    book = SimpleNamespace(ocr_candidates=False)
    assert rare_candidates_consumed(pipe, params_for(), book) is False
    assert rare_candidates_consumed(pipe, params_for(seed_admit={"rare_agree": True}), book) is True
    assert rare_candidates_consumed(pipe, params_for(context_decide={"rare_topk": 3}), book) is True
