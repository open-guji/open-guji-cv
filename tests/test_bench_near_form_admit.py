"""near-form-admit：用自造小数据守住打分口径（GM3）。"""
import json
from pathlib import Path

from open_guji_cv.eval import bench

HEAD = "书\t册\t格\t类\t参校字\t库首位\t库候选前3\t真字(人裁)\t真字=参校\t真字=库首位\n"


def _ctx(tmp_path, rows):
    g = tmp_path / "gold"
    g.mkdir()
    (g / "gold.tsv").write_text(HEAD + "".join(rows), encoding="utf-8")
    w = tmp_path / "work"
    w.mkdir()
    return bench.BenchCtx("x", [], w, {"gold": str(g)}, args={"rule": "R1"})


def test_score_counts(tmp_path):
    rows = ["书\t01\t1:1:1\tB\t太\t太\t太0.9\t太\t1\t1\n",       # B 类放对
            "书\t01\t1:1:2\tB\t大\t太\t大0.9\t太\t0\t1\n",       # B 类放错
            "书\t01\t1:1:3\tA\t人\t入\t入0.9\t入\t0\t1\n"]       # 非 B 类不放
    r = bench.execute(bench.get("near-form-admit"), _ctx(tmp_path, rows))
    assert (r.metrics["released"], r.metrics["wrong_admit"]) == (2, 1)
    assert r.metrics["rules"]["R4"]["released"] == 3 and r.metrics["rules"]["R4"]["wrong"] == 0
    assert [x["ok"] for x in r.items] == [True, False, True]


def test_zero_error_upper_bound(tmp_path):
    rows = [f"书\t01\t1:1:{i}\tB\t太\t太\t太0.9\t太\t1\t1\n" for i in range(1, 7)]
    r = bench.execute(bench.get("near-form-admit"), _ctx(tmp_path, rows))
    assert r.metrics["wrong_admit"] == 0 and r.metrics["ub95"] == 0.5
