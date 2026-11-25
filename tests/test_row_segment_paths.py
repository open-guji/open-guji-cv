"""Step3 读表路径口径：`corpus/…` 走整理本目录，其余相对路径按工作区根。

逐列字数先验 colgold_prior、YOLO 并格 yolo_merge（doc/design/19 块 C/D）缺省关、没有书开，2026-11-14 删，
原测试随之删；格位表 layout_prior 还用同一个路径函数。
"""


def test_colgold_path_follows_corpus_dir(tmp_path, monkeypatch):
    # corpus/… 走 corpus_path：工作区根的 corpus/ 在就读它；其他相对路径按工作区根
    from open_guji_cv.steps.row_segment import _colgold_path
    (tmp_path / "corpus" / "daizhige").mkdir(parents=True)
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path))
    assert _colgold_path("corpus/daizhige/colgold.jsonl") == tmp_path / "corpus" / "daizhige" / "colgold.jsonl"
    assert _colgold_path("models/yolo") == tmp_path / "models" / "yolo"
    assert _colgold_path(str(tmp_path / "x.jsonl")) == tmp_path / "x.jsonl"
