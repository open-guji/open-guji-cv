"""切分样页单与对比命令（切分模块化第 4 步）：每套书都有一份能读的样页单，牵动判断按套书分得开。"""

import importlib.util
from pathlib import Path

import pytest

from open_guji_cv.core.seg_set import SEG_SETS

_spec = importlib.util.spec_from_file_location(
    "seg_samples", Path(__file__).resolve().parents[1] / "scripts" / "seg_samples.py")
S = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S)

P = "open_guji_cv."


@pytest.mark.parametrize("seg_set", SEG_SETS)
def test_every_seg_set_has_a_sample_list(seg_set):
    d = S.load_samples(seg_set)
    assert d["books"], f"{seg_set} 的样页单是空的"
    assert d["step_ids"][0] == d["steps"]["from"] and d["step_ids"][-1] == d["steps"]["to"]
    for b in d["books"]:
        assert all(isinstance(p, int) and p > 0 and why.strip() for p, why in b["pages"].items()), b
        if not d["local_only"]:
            assert b["ws_glob"] or b["ws_repo"], f"{seg_set} {b['book']} 没写工作区，任务库执行方找不到这册"


def test_modules_are_split_by_seg_set(tmp_path):
    """书仓 code/ 覆盖了职名页：这套书的模块表换成书级模块，殿本那套不受影响（2026-11-09 史記搬去书仓后改成造一个书仓）。"""
    from open_guji_cv.core import book_code as BC
    from open_guji_cv.core.workspace import reset_workspace_override, set_workspace_override
    siku, free = (S.set_modules(s) for s in ("siku_zongmu", "zengguang_youxue"))
    assert {P + "impl.keben.border", P + "seg.lines", P + "seg.grid"} <= siku
    assert P + "impl.keben.roster_segment" in siku
    assert not any(m.startswith(P + "impl.keben") for m in free)
    assert not any(m.startswith(P + "impl.free") for m in siku)
    code = tmp_path / "code"
    code.mkdir()
    (code / "code.yaml").write_text("name: sjtest\nbase: keben\noverrides:\n  keben.roster_segment: roster_segment\n",
                                    encoding="utf-8")
    (code / "roster_segment.py").write_text("from open_guji_cv.seg import seam  # noqa: F401\n", encoding="utf-8")
    (code / "samples.yaml").write_text(S.sample_path("siku_zongmu").read_text(encoding="utf-8"), encoding="utf-8")
    tok = set_workspace_override(str(tmp_path))
    try:
        assert S.all_sets()[-1] == "sjtest"
        mine = S.set_modules("sjtest")
        assert "guji_book.sjtest.roster_segment" in mine and P + "impl.keben.roster_segment" not in mine
        assert P + "seg.seam" in mine
    finally:
        reset_workspace_override(tok)
        BC._CACHE.clear()


