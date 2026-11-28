"""decide-bench 评测脚本（open_guji_cv/eval/decide_bench）在干净环境能起、cell-state 分片构建可重复（验收标准 S11、S12）。"""
import json
import subprocess
import sys

import pytest

MODS = ["run", "score", "dyn", "gate_bench"]


@pytest.mark.parametrize("m", MODS)
def test_help_runs(m):
    r = subprocess.run([sys.executable, "-m", f"open_guji_cv.eval.decide_bench.{m}", "--help"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-500:]


def test_build_cell_state_synthetic(tmp_path):
    ds = tmp_path
    (ds / "decide-bench/small").mkdir(parents=True)
    (ds / "char-segmentation/instances").mkdir(parents=True)
    small = [
        {"id": "w1:03:1:1:1", "anchor": {"ws": "w1", "book": "03", "page": 1, "bbox": [0, 0, 1, 1]}, "expected": {"char": "字"},
         "label_origin": "human", "status": "active", "source_events": ["e1"]},
        {"id": "w1:03:1:1:2", "anchor": {"ws": "w1", "book": "03", "page": 1, "bbox": [0, 0, 1, 1]}, "expected": {"char": ""},
         "label_origin": "human", "status": "active"},
    ]
    inst = [{"id": "vol01:4:1:20", "anchor": {"book": "vol01", "page": 4, "col": 1, "slot": 20}, "expected": {"quality": "not_text"},
             "status": "active", "label_origin": "human"}]
    (ds / "decide-bench/small/items.jsonl").write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in small) + "\n", encoding="utf-8")
    (ds / "char-segmentation/instances/items.jsonl").write_text(json.dumps(inst[0]) + "\n", encoding="utf-8")
    cmd = [sys.executable, "-m", "open_guji_cv.eval.decide_bench.build_cell_state", "--dataset", str(ds)]
    assert subprocess.run(cmd, capture_output=True, text=True).returncode == 0
    a = (ds / "decide-bench/cell-state/w1/items.jsonl").read_bytes()
    rows = [json.loads(x) for x in a.decode().splitlines()]
    assert [r["expected"]["state"] for r in rows] == ["char"]          # 空字的格不收
    other = [d for d in (ds / "decide-bench/cell-state").iterdir() if d.is_dir() and d.name != "w1"]   # instances 的 non_char 归到殿本子目录
    assert len(other) == 1
    assert json.loads((other[0] / "items.jsonl").read_text())["expected"]["state"] == "non_char"
    subprocess.run(cmd, check=True, capture_output=True)
    assert (ds / "decide-bench/cell-state/w1/items.jsonl").read_bytes() == a   # 重跑逐字节相同


# ---------------------------------------------------------------- score.py：缺格率与退出码（11-28 CV4 修）
def _make_run(tmp_path, n_gold, n_cells):
    """自造：n_gold 个金标格，产物只有前 n_cells 格，都放行、字对。"""
    root = tmp_path / "run" / "v1"
    (root / "char_decide").mkdir(parents=True)
    chars = [{"id": f"v1:1:1:{i}", "char": "字", "admit": True, "channel": "match_ref", "evidence": {}} for i in range(1, n_cells + 1)]
    (root / "char_decide" / "p0001.json").write_text(json.dumps({"char_decide": {"page": 1, "columns": [{"col": 1, "chars": chars}]}}), encoding="utf-8")
    items = [{"id": f"w:v1:1:1:{i}", "anchor": {"ws": "w", "book": "v1", "page": 1, "key_at_freeze": f"v1:1:1:{i}"},
              "expected": {"char": "字"}, "status": "active", "book_title": "书"} for i in range(1, n_gold + 1)]
    ip = tmp_path / "items.jsonl"
    ip.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in items) + "\n", encoding="utf-8")
    return ip, root


def _score(ip, root, *extra):
    cmd = [sys.executable, "-m", "open_guji_cv.eval.decide_bench.score", "--items", str(ip), "--run", f"v1={root}", "--no-substeps", *extra]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_score_large_missing_is_not_a_pass(tmp_path):
    ip, root = _make_run(tmp_path, n_gold=10, n_cells=2)         # 缺格 80%：wrong_admit=0 不能算通过
    r = _score(ip, root)
    assert r.returncode == 3, r.stdout + r.stderr
    assert "不算通过" in r.stdout and "✓" not in r.stdout.split("wrong_admit")[1].splitlines()[0]
    assert _score(ip, root, "--max-missing", "1.0").returncode == 0


def test_score_complete_run_passes(tmp_path):
    ip, root = _make_run(tmp_path, n_gold=10, n_cells=10)
    r = _score(ip, root)
    assert r.returncode == 0 and "wrong_admit = 0  ✓" in r.stdout


# ---------------------------------------------------------------- 统一接口里的 decide／decide-gate
def test_decide_registered_and_sections(tmp_path, monkeypatch):
    from open_guji_cv.eval import bench as B
    from open_guji_cv.eval.benches import decide as D
    assert B.get("decide").primary == "wrong_admit" and B.get("decide-gate").owner == "CV4"
    assert {g.metric for g in B.get("decide").guards} >= {"wrong_admit", "missing_rate", "flip_worse"}
    rows = [{"id": "a", "book": "书", "truth": "字", "algo": "字", "rule": "admit:x", "outcome": "放对", "a4": "对", "group_mode": None,
             "c4_flag": False, "c4_mark": False, "c4_excl": False, "ctx_char": "字", "ctx_src": "context", "errloc": "—"},
            {"id": "b", "book": "书", "truth": "字", "algo": "他", "rule": "admit:group", "outcome": "放错字", "a4": "错位",
             "group_mode": "lift", "c4_flag": True, "c4_mark": True, "c4_excl": False, "ctx_char": None, "ctx_src": None, "errloc": "4c"},
            {"id": "c", "book": "书", "truth": "字", "algo": None, "rule": None, "outcome": "缺格", "a4": "—", "group_mode": None,
             "c4_flag": False, "c4_mark": False, "c4_excl": False, "ctx_char": None, "ctx_src": None, "errloc": "切分"}]
    pred = tmp_path / "p.jsonl"
    pred.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in rows) + "\n", encoding="utf-8")
    ctx = B.BenchCtx(book="w", vols=[], work=tmp_path, res={})
    monkeypatch.setattr(D, "_vols", lambda c: ["v1"])          # 不读 dataset
    r = D.score(ctx, pred)
    m = r.metrics
    assert m["wrong_admit"] == 1 and m["missing"] == 1 and m["a4_misaligned"] == 1 and m["c4_missed_char"] == 1
    assert m["d4_group_wrong_admit"] == 1 and m["b4_context_precision"] == 1.0 and m["errloc"] == {"4c": 1, "切分": 1}
    B.apply_guards(B.get("decide"), r)
    assert r.status == "regressed"      # 放错字 1、缺格率 33%


def test_decide_dianben_id_alias(tmp_path):
    from open_guji_cv.eval.benches import decide as D
    old = D.DATASET_WS["96mid1ogzk"]                      # dataset 分片里殿本的旧写法
    assert "96mid1ogzk" in D.BOOKS and old not in D.BOOKS
    (tmp_path / "bench.yaml").write_text(f"books:\n  - {{ws: {old}, vol: vol01}}\n  - {{ws: 988g3f0wsu, vol: '03'}}\n", encoding="utf-8")
    assert D._book_vols(tmp_path, "96mid1ogzk", []) == ["vol01"]
    assert D._book_vols(tmp_path, "988g3f0wsu", []) == ["03"]
