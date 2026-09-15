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
