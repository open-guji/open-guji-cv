# -*- coding: utf-8 -*-
"""scripts/zhengli/rebase_book_yaml.py：换图源后册 yaml 钉新 rev、像素量按比例换算（造表造 yaml，不碰真书数据）。"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

_P = Path(__file__).resolve().parent.parent / "scripts" / "zhengli" / "rebase_book_yaml.py"
_spec = importlib.util.spec_from_file_location("rebase_book_yaml", _P)
R = importlib.util.module_from_spec(_spec)
sys.modules["rebase_book_yaml"] = R
_spec.loader.exec_module(R)

K = 2.0
H = [[K, 0, 10], [0, K, 20], [0, 0, 1]]


def table(rev=4, k_pages=(1, 2)):
    pages = [{"page": p, "w": 410, "h": 620, "from_rev": {"rev": rev - 1, "sha256": "x", "w": 200, "h": 300, "H": H},
              "frame": {"pad": {"t": 30, "b": 36, "o": 20}}} for p in k_pages]
    return {"rev": rev, "pages": pages}


YAML = """\
# 册说明
id: vol43
source_rev: 3   # 页表 rev
bottom_gap: 226.0   # 旧
period_prior: 80.1
outer_gap:
  top: 25.5
  bottom: 19.1
outer_shift:
  top: -8.5
  bottom: -14.1
dev_set: [1, 2]
params:
  border_detect:
    head_raise_scale: 0.5
    grid_col_pitch: 129
    vline_overrides:
      1: [100, 150]
  seed_admit:
    fold_groups: [jys]
"""


def test_scale_and_pad():
    t = table()
    assert R.scale_of(t) == pytest.approx(2.0)
    assert R.pad_bottom(t) == 36.0
    # 右上原点：旧 x=100 → 旧左上 99 → 新左上 2·99+10＝208 → 新右上 409−208＝201
    assert R.map_x(t, 1, 100) == pytest.approx(201.0)
    assert R.map_x(t, 1, 150) == pytest.approx(301.0)   # 升序（右→左）不变


def test_rebase_text():
    new, ch = R.rebase_yaml_text(YAML, "43", table())
    d = yaml.safe_load(new)
    assert d["source_rev"] == 4 and d["bottom_gap"] == 36.0 and d["period_prior"] == 160.2
    assert d["outer_gap"] == {"top": 51.0, "bottom": 38.2} and d["outer_shift"] == {"top": -17.0, "bottom": -28.2}
    b = d["params"]["border_detect"]
    assert b["head_raise_scale"] == 1.0 and b["grid_col_pitch"] == 258 and b["vline_overrides"][1] == [201, 301]
    assert d["dev_set"] == [1, 2] and d["params"]["seed_admit"] == {"fold_groups": ["jys"]}   # 别的不动
    assert "原注：页表 rev" in new and new.startswith("# 换新图（A20 11-07）")
    assert any(c.startswith("source_rev 3 → 4") for c in ch)


def test_idempotent_and_no_key_untouched():
    new, _ = R.rebase_yaml_text(YAML, "43", table())
    again, ch = R.rebase_yaml_text(new, "43", table())
    assert ch == [] and again == new
    plain = "id: vol01\nsource_rev: 3\nperiod_prior: 80\n"
    out, ch = R.rebase_yaml_text(plain, "01", table())
    assert "bottom_gap" not in out and yaml.safe_load(out)["period_prior"] == 160.0


def test_unpinned_yaml_rejected():
    with pytest.raises(ValueError):
        R.rebase_yaml_text("id: vol01\n", "01", table())


def test_main_apply_with_tables_dir(tmp_path):
    import json
    books = tmp_path / "books"
    books.mkdir()
    (books / "vol43.yaml").write_text(YAML, encoding="utf-8")
    tabs = tmp_path / "tabs"
    tabs.mkdir()
    (tabs / "43.r004.json").write_text(json.dumps(table()), encoding="utf-8")
    assert R.main([str(books), "--tables", str(tabs)]) == 0
    assert "source_rev: 3" in (books / "vol43.yaml").read_text(encoding="utf-8")        # 不加 --apply 不写
    assert R.main([str(books), "--tables", str(tabs), "--apply"]) == 0
    assert yaml.safe_load((books / "vol43.yaml").read_text(encoding="utf-8"))["source_rev"] == 4
