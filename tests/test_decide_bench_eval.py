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
