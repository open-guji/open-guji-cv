"""scripts/eval_match_pool.py 的计数（A23，2026-11-23）。数据手造。"""
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
_spec = importlib.util.spec_from_file_location(
    "eval_match_pool", Path(__file__).resolve().parents[1] / "scripts" / "eval_match_pool.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)


def test_rank1_accept_false_same():
    items = [
        dict(query_id="q1", gold="部", kind="残笔", candidates=[dict(id="a", char="部", same=True),
                                                               dict(id="b", char="而", same=False)]),
        dict(query_id="q2", gold="士", kind="对照", candidates=[dict(id="c", char="士", same=True),
                                                               dict(id="d", char="十", same=False)]),
    ]
    ways = {"cov": [[(False, 0.90), (True, 0.997)], [(True, 0.999), (False, 0.8)]]}
    res, flips = ev.report(items, ways)
    r = res["cov"]
    assert r["全部"]["rank1"] == 1 and r["全部"]["accept"] == 1 and r["全部"]["false_same"] == 1
    assert r["残笔"]["rank1"] == 0 and r["对照"]["accept"] == 1
    assert flips["cov"] == ["q1|部→而（误放）"]
