"""scripts/eval_advset.py 的分层计数（A23，2026-11-23）。数据手造，不碰 dataset。"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "eval_advset", Path(__file__).resolve().parents[1] / "scripts" / "eval_advset.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)


def test_report_layers_and_flips():
    items = [
        dict(query_id="q1", held="廬", candidates=[dict(id="c1", char="盧", partner=True, variant=False),
                                                  dict(id="c2", char="慮", partner=False, variant=False)]),
        dict(query_id="q2", held="歳", candidates=[dict(id="c3", char="歲", partner=True, variant=True),
                                                  dict(id="c4", char="蔵", partner=False, variant=False)]),
    ]
    ways = {"cov": [[(True, 0.998), (False, 0.9)], [(True, 0.999), (False, 0.8)]]}
    res, flips = ev._report(items, ways)
    near, var = res["cov"]["形近"], res["cov"]["异体"]
    assert (near["n_query"], near["false_same"], near["partner_false_same"]) == (2, 1, 1)
    assert (var["n_query"], var["false_same"]) == (1, 1)
    assert flips["cov|形近"] == ["q1|廬→盧|c1"]
    assert flips["cov|异体"] == ["q2|歳→歲|c3"]


def test_split_by_volume_parity():
    assert ev.split_of("v2:008:156:9:9") == "test"
    assert ev.split_of("v2:vol01:88:1:16a") == "dev"
    assert ev.split_of("v2:05:77:1:1") == "dev"
