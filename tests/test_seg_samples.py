"""切分样页单与对比命令（切分模块化第 4 步）：每套书都有一份能读的样页单，牵动判断按套书分得开。"""

import importlib.util
from pathlib import Path

import pytest

from open_guji_cv.core.seg_set import SEG_SETS
from open_guji_cv.jobs import spec as SP

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


def test_modules_are_split_by_seg_set():
    siku, shiji, free = (S.set_modules(s) for s in ("siku_zongmu", "shiji_wyg", "zengguang_youxue"))
    assert {P + "books.siku_zongmu.border", P + "seg.lines", P + "seg.grid"} <= siku
    assert P + "books.siku_zongmu.roster_segment" in siku and P + "books.shiji_wyg.roster_segment" not in siku
    assert P + "books.shiji_wyg.roster_segment" in shiji and P + "books.siku_zongmu.roster_segment" not in shiji
    assert not any(m.startswith(P + "books.siku_zongmu") for m in free)
    assert not any(m.startswith(P + "books.zengguang_youxue") for m in siku | shiji)


def test_job_specs_normalize():
    for seg_set in SEG_SETS:
        for old, new in S.job_specs(seg_set, "a" * 40, "b" * 40, "单测"):
            o = SP.normalize(old, resolve=lambda r: r)
            n = SP.normalize({**new, "compare_to": {"job": 1}}, resolve=lambda r: r)
            assert o["kind"] == "rerun" and o["output"]["pack"] and o["force"]
            assert n["kind"] == "ab" and n["pages"] == o["pages"] and n["steps"] == o["steps"]
            assert SP.spec_hash(o) != SP.spec_hash(n)
