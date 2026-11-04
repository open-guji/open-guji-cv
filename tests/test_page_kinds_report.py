"""`guji pagekinds` 页型对账（ops/page_kinds_report.py）：造闸产物，核对账项。"""
from __future__ import annotations

import json

from helpers import make_book
from open_guji_cv.core.step import page_key
from open_guji_cv.ops import page_kinds_report as R
from open_guji_cv.products.store import ProductStore


def _put(store, book, page, **m):
    base = {"page": page, "admitted": True, "reject": [], "flags": [], "n_cols": 9, "expected_cols": 9,
            "page_type": "body", "page_type_policy": "standard"}
    p = store.path(book, "border_detect_gate", page_key(page))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"border_detect_gate_manifest": {**base, **m}}), encoding="utf-8")


def test_fmt_pages():
    assert R.fmt_pages([5, 3, 4, 9, 9, 12, 13]) == "3-5,9,12-13"
    assert R.fmt_pages([]) == ""


def test_judge_handling_and_auto():
    assert R.judge(None)["handling"] == "无产物"
    assert R.judge({"page_type": "body", "page_type_policy": "standard"})["handling"] == "正文"
    j = R.judge({"page_type": "body", "page_type_policy": "standard",
                 "flags": ["page_type_forced：页型规则判「cover/skip」，册配置 body_pages 点名按正文走"]})
    assert (j["handling"], j["auto"]) == ("点名正文", "cover/skip")
    j = R.judge({"page_type": "table", "page_type_policy": "skip",
                 "flags": ["page_type_table：页型规则判「body/standard」，册配置 table_pages 点名为表格页，整页暂不整理"]})
    assert (j["handling"], j["auto"]) == ("点名表格", "body/standard")
    j = R.judge({"page_type": "cover", "page_type_policy": "skip", "reject": ["page_type_skip：页型判定为「cover」"]})
    assert j["handling"] == "自动跳过"


def test_judge_cover():
    j = R.judge({"page_type": "cover", "page_type_policy": "skip", "reject": ["page_type_skip：页型判定为「cover」"],
                 "flags": ["page_type_cover：页型规则判「body/standard」，册配置 cover_pages 点名为书衣／封面页，整页跳过"]})
    assert (j["handling"], j["auto"]) == ("点名封面", "body/standard")


def test_build_issues(tmp_path):
    store = ProductStore(tmp_path)
    book = make_book("t1", page_kinds={"body": [2, 3], "table": [4, 5]})
    forced = ["page_type_forced：页型规则判「cover/skip」，册配置 body_pages 点名按正文走"]
    _put(store, "t1", 1)                                                           # 正文
    _put(store, "t1", 2, flags=forced)                                             # 点名正文，对上
    _put(store, "t1", 3)                                                           # 点名正文但本来就是正文 → 多余
    _put(store, "t1", 4, page_type="table", page_type_policy="skip",
         flags=["page_type_table：页型规则判「body/standard」，册配置 table_pages 点名为表格页，整页暂不整理"])
    # 5 号点名表格但产物还是正文 → 没反映
    _put(store, "t1", 5)
    _put(store, "t1", 6, page_type="cover", page_type_policy="skip", n_cols=0,
         reject=["page_type_skip：页型判定为「cover」，无正文栏格"])               # 自动跳过（正常）
    _put(store, "t1", 7, page_type="cover", page_type_policy="skip", n_cols=9,
         reject=["page_type_skip：页型判定为「cover」，无正文栏格"])               # 自动跳过但满栏格 → 疑似误判
    res = R.build(book, store, [1, 2, 3, 4, 5, 6, 7, 8])
    assert res["handling"] == {"正文": 3, "点名正文": 1, "点名表格": 1, "自动跳过": 2, "无产物": 1}
    assert res["issues"]["redundant_body"] == [3]
    assert res["issues"]["not_reflected"] == [{"page": 5, "kind": "table", "handling": "正文"}]
    assert [x["page"] for x in res["issues"]["auto_skip"]] == [6]
    assert [x["page"] for x in res["issues"]["auto_skip_suspect"]] == [7]
    json.dumps(res, ensure_ascii=False)                                            # 可 JSON 化
    R.print_report(res)


def test_out_of_scope_and_clean(tmp_path, capsys):
    store = ProductStore(tmp_path)
    book = make_book("t2", page_kinds={"roster": ["5-9"]})
    _put(store, "t2", 1)
    res = R.build(book, store, [1, 2])
    assert res["configured_out_of_scope"] == {"roster": [5, 6, 7, 8, 9]}
    book = make_book("t3")
    _put(store, "t3", 1)
    R.print_report(R.build(book, store, [1]))
    assert "✓" in capsys.readouterr().out
