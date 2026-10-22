"""粗校出口 R4 异常表（GUJI-666）：结构化 JSON，格式错报具体行号，md 老格式照读。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ZL = Path(__file__).resolve().parents[1] / "scripts" / "zhengli"
spec = importlib.util.spec_from_file_location("zl_collect_exit", ZL / "collect_exit.py")
ce = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ce)

MD = """# vol04 异常表

| # | 现象 | 原因 | 结论 | 去向 |
|---|---|---|---|---|
| 1 | p79 col3 圈号被切成两格 | 切分 | 已重切 | — |
| 2 | p80 整列缺字 | 版框线 | 交 M10 | seg_bad |
"""


def test_md_still_parses_and_headers_are_not_problems(tmp_path):
    f = tmp_path / "a.md"
    f.write_text(MD, encoding="utf-8")
    rows, problems = ce.load_anomaly(f)
    assert problems == [] and [(r["n"], r["concl"]) for r in rows] == [("1", "已重切"), ("2", "交 M10")]
    assert ce.parse_anomaly(f) == rows


def test_md_format_errors_carry_line_numbers(tmp_path):
    f = tmp_path / "a.md"
    f.write_text(MD + "| 3 | 只有两格 |\n| 4. | 序号写错 | x | y |\n| 别的表 | 不管 |\n", encoding="utf-8")
    rows, problems = ce.load_anomaly(f)
    assert len(rows) == 2
    assert problems[0].startswith("第 7 行：只有 2 格") and problems[1].startswith("第 8 行：序号格要写纯数字")
    assert len(problems) == 2


def test_json_rows_and_explicit_pages_cols(tmp_path):
    f = tmp_path / "a.json"
    f.write_text(json.dumps({"book": "vol04", "rows": [
        {"n": 1, "text": "圈号被切", "cause": "切分", "concl": "已重切", "pages": [79], "cols": [[79, 3]]},
        {"n": 2, "text": "p80 整列缺字", "concl": ""}]}), encoding="utf-8")
    rows, problems = ce.load_anomaly(f)
    assert problems == [] and rows[0]["cols"] == [(79, 3)] and rows[1]["concl"] == ""
    pages, cols = ce._coverage(rows)
    assert pages == {79} and cols == {(79, 3)}            # 第 2 行没结论，不算有去向；第 1 行用显式页列


def test_json_errors_are_specific(tmp_path):
    f = tmp_path / "a.json"
    f.write_text('{"rows": [\n {"n": 1,\n', encoding="utf-8")
    assert "JSON 第 3 行" in ce.load_anomaly(f)[1][0]
    f.write_text(json.dumps({"rows": [{"n": 1, "text": "a", "concl": "b"}, {"n": 1, "text": "", "concl": "x"},
                                      {"n": "x"}, "oops", {"n": 5, "text": "t", "pages": ["7"]}]}), encoding="utf-8")
    rows, problems = ce.load_anomaly(f)
    joined = "\n".join(problems)
    assert "第 1 行（rows[2]） 序号重复" in joined and "没有 text" in joined and "rows[3] 的 n 要是数字" in joined
    assert "rows[4] 不是对象" in joined and "的 pages 要是整数数组" in joined


def test_r4_fails_with_all_problems_named(tmp_path):
    f = tmp_path / "vol04-异常表.md"
    f.write_text(MD + "| 3 | 只有两格 |\n", encoding="utf-8")
    res, _ = ce._r4(f)
    assert res["result"] == "FAIL" and "第 7 行" in res["number"]
    f.write_text(MD, encoding="utf-8")
    assert ce._r4(f)[0]["result"] == "PASS"
