"""受控重跑工具：前后对比（ops/products_diff.py）、产物包（datastore/packs.py）。"""
import json

import pytest

from open_guji_cv.ops import products_diff as PD


def _cell(page, col, pos, y, ch, state="admit", h=90):
    bb = [100.0 * col, float(y), 100.0 * col + 90, float(y + h)]
    ci = {"id": f"b:{page}:{col}:{pos}", "idx": pos, "cell_type": "char", "bbox_page": bb}
    sa = {"id": ci["id"], "char": ch, "admit": state == "admit"}
    if state == "human":
        sa["provenance"] = "human"
    return ci, sa


def _write(root, page, cols):
    ci_cols, sa_cols = [], []
    for col, cells in cols.items():
        ci_cols.append({"col": col, "ok": True, "chars": [c for c, _ in cells]})
        sa_cols.append({"col": col, "chars": [s for _, s in cells]})
    for step, kind, data in (("cell_shrink", "char_index", ci_cols), ("seed_admit", "seed_admit", sa_cols)):
        d = root / "b" / step
        d.mkdir(parents=True, exist_ok=True)
        (d / f"p{page:04d}.json").write_text(json.dumps({kind: {"page": page, "columns": data}}), encoding="utf-8")


def test_diff_classifies_and_counts(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    # 第 1 列：没变；第 2 列：一格切成两格（cells）；第 3 列：送审→放行（state）；第 4 列：放行字变（text）
    _write(a, 1, {1: [_cell(1, 1, 1, 0, "甲"), _cell(1, 1, 2, 100, "乙")],
                  2: [_cell(1, 2, 1, 0, "丙", h=190)],
                  3: [_cell(1, 3, 1, 0, "", "review")],
                  4: [_cell(1, 4, 1, 0, "己")]})
    _write(b, 1, {1: [_cell(1, 1, 1, 0, "甲"), _cell(1, 1, 2, 100, "乙")],
                  2: [_cell(1, 2, 1, 0, "丙"), _cell(1, 2, 2, 100, "丁", "review")],
                  3: [_cell(1, 3, 1, 0, "戊")],
                  4: [_cell(1, 4, 1, 0, "已")]})
    res = PD.diff_book(a, b, "b", [1, 2])
    s = res["summary"]
    assert s["columns"] == {"same": 1, "cells": 1, "state": 1, "text": 1}
    assert s["a"]["review"] == 1 and s["b"]["review"] == 1
    assert s["flips"]["review→admit"] == 1 and s["flips"]["放行字变"] == 1
    assert res["missing"] == {"a": [2], "b": [2]}
    rep = PD.write_report(res, tmp_path / "out", "A", "B")
    assert "人审率" in rep.read_text(encoding="utf-8")
    tsv = (tmp_path / "out" / "columns.tsv").read_text(encoding="utf-8").splitlines()
    assert tsv[1].startswith("1\t2\tcells")            # 切分变了的列排最前


class FakeSrc:
    branch = "main"

    def __init__(self):
        self.objs = {}

    def _call(self, method, path, query=None, data=None, raw=False, **kw):
        import urllib.parse
        if path == "/v1/packs":
            pre = query["prefix"]
            return {"packs": [{"key": k, "bytes": len(v)} for k, v in sorted(self.objs.items()) if k.startswith(pre)]}
        key = urllib.parse.unquote(path[len("/v1/packs/"):])
        if method == "PUT":
            assert key not in self.objs
            self.objs[key] = data
            return {"key": key}
        return self.objs[key]


def test_pack_roundtrip(tmp_path, monkeypatch):
    from open_guji_cv.datastore import packs as PK
    monkeypatch.setattr(PK, "_ws_name", lambda: "ws-x")
    monkeypatch.setattr(PK, "PART_BYTES", 300)             # 逼出多段
    root = tmp_path / "products"
    for step in ("cell_shrink", "seed_admit"):
        d = root / "vol04" / step
        (d / "_prev").mkdir(parents=True)
        for p in range(3):
            (d / f"p{p:04d}.json").write_text(json.dumps({"x": [step, p] * 50}))
        (d / "_prev" / "p0000.json").write_text("old")
        (d / "_manifest.jsonl").write_text("{}\n")
    src = FakeSrc()
    man = PK.push_products("vol04", root, label="t1", src=src, note="测")
    assert man["files"] == 8 and len(man["parts"]) >= 2
    assert [m["name"] for m in PK.list_packs("vol04", src=src)] == ["products/ws-x/vol04/t1"]
    out = tmp_path / "got"
    info = PK.fetch_products("vol04", out, src=src)
    assert info["files"] == 8
    assert (out / "vol04" / "seed_admit" / "p0002.json").read_text() == (root / "vol04" / "seed_admit" / "p0002.json").read_text()
    assert not (out / "vol04" / "seed_admit" / "_prev").exists()
    with pytest.raises(FileExistsError):
        PK.fetch_products("vol04", out, label="t1", src=src)
    k = "products/ws-x/vol04/t1/part-000.tgz"
    src.objs[k] = b"x" + src.objs[k][1:]
    with pytest.raises(ValueError):
        PK.fetch_products("vol04", out, label="t1", src=src, force=True)
    assert (out / "vol04" / "seed_admit" / "p0002.json").exists()     # 包坏了不动本机产物


def test_rare_index_roundtrip(tmp_path, monkeypatch):
    from open_guji_cv.datastore import packs as PK
    a, b = tmp_path / "a", tmp_path / "b"
    (a / "glyph_cnn_r5").mkdir(parents=True)
    (b / "glyph_cnn_r5").mkdir(parents=True)
    (a / "glyph_cnn_r5" / "emb_0123.npz").write_bytes(b"\x00" * 1000)
    monkeypatch.setattr(PK, "PART_BYTES", 300)
    src = FakeSrc()
    monkeypatch.setattr(PK, "_models_root", lambda: a)
    assert PK.push_rare_indexes(src=src) == ["rare-index/glyph_cnn_r5/emb_0123.npz"]
    assert PK.push_rare_indexes(src=src) == []
    monkeypatch.setattr(PK, "_models_root", lambda: b)
    assert len(PK.fetch_rare_indexes(src=src)) == 1
    assert (b / "glyph_cnn_r5" / "emb_0123.npz").read_bytes() == b"\x00" * 1000


def test_pack_label_must_be_ascii():
    from open_guji_cv.datastore import packs as PK
    PK.check_label("v0.4.7-layout-prior")
    for bad in ("v0.4.6-粗校", "", "-x", "a/b", "x" * 97):
        with pytest.raises(ValueError):
            PK.check_label(bad)
def test_pack_main_pointer(tmp_path, monkeypatch):
    from open_guji_cv.datastore import packs as PK
    monkeypatch.setattr(PK, "_ws_name", lambda: "ws-x")
    root = tmp_path / "products"
    (root / "vol04" / "seed_admit").mkdir(parents=True)
    src = FakeSrc()
    for lab, body in (("a1", "A"), ("b2", "B")):
        (root / "vol04" / "seed_admit" / "p0001.json").write_text(body)
        PK.push_products("vol04", root, label=lab, src=src)
    assert PK.main_label("vol04", src=src) is None
    got = PK.fetch_products("vol04", tmp_path / "x", src=src)          # 没标 main：取最新存的
    assert got["name"].endswith("/b2")
    PK.promote("vol04", "a1", src=src)
    assert PK.main_label("vol04", src=src) == "a1"
    assert [m["main"] for m in PK.list_packs("vol04", src=src)] == [True, False]
    got = PK.fetch_products("vol04", tmp_path / "y", src=src)          # 标了 main：缺省取 main
    assert got["name"].endswith("/a1")
    assert (tmp_path / "y" / "vol04" / "seed_admit" / "p0001.json").read_text() == "A"
    with pytest.raises(Exception):
        PK.promote("vol04", "nope", src=src)                          # 包不存在不许标
    with pytest.raises(ValueError):
        PK.check_label("main-ptr")


def test_version_label():
    from open_guji_cv.datastore import packs as PK
    assert PK.version_label({"cv": "0.4.7", "corpus": 1, "glyph_pin": 2}) == "cv0.4.7-c1-g2"
    assert PK.version_label({"cv": "0.4.7+3", "corpus": None, "glyph_pin": None,
                             "human_fp": "h1:812:3fa9c1d2e"}) == "cv0.4.7p3-c--g-3fa9c1"
    lab = PK.version_label({"cv": "0.4.7+dirty", "corpus": 1, "glyph_pin": None, "human_fp": "nodb"})
    assert lab == "cv0.4.7pdirty-c1-g-"
    PK.check_label(lab + "-x")


def test_unpacked_note(tmp_path, monkeypatch):
    """存包、取包之后不提醒；之后又跑过（manifest 追加了）就提醒；只打几步的包不算存过。"""
    from open_guji_cv.datastore import packs as PK
    monkeypatch.setattr(PK, "_ws_name", lambda: "ws-x")
    root = tmp_path / "products"
    d = root / "vol04" / "seed_admit"
    d.mkdir(parents=True)
    assert PK.unpacked_note(root, "vol04") is None                     # 没产物不提醒
    (d / "p0001.json").write_text("A")
    (d / "_manifest.jsonl").write_text('{"key": "p0001"}\n')
    assert "从没存过包" in PK.unpacked_note(root, "vol04")
    src = FakeSrc()
    PK.push_products("vol04", root, label="a1", src=src, steps=["seed_admit"])
    assert PK.unpacked_note(root, "vol04") is not None                 # 只打几步不算
    man = PK.push_products("vol04", root, label="a2", src=src)
    assert man["files"] == 2                                           # .pack.json 不进包
    assert PK.unpacked_note(root, "vol04") is None
    with open(d / "_manifest.jsonl", "a") as f:
        f.write('{"key": "p0001", "x": 1}\n')
    assert "a2" in PK.unpacked_note(root, "vol04")
    PK.fetch_products("vol04", tmp_path / "got", label="a2", src=src)
    assert PK.unpacked_note(tmp_path / "got", "vol04") is None


def test_exp_record(tmp_path):
    from open_guji_cv.ops import exp_record as ER
    rep = tmp_path / "diff"
    rep.mkdir()
    (rep / "report.md").write_text("# 前后对比 vol04\n\n| | 格 |\n\n## 小节\n")
    man = {"label": "cv0.4.7-c1-g2-x", "name": "products/ws/vol04/cv0.4.7-c1-g2-x", "created": "2026-10-20T01:00:00Z",
           "note": "测", "files": 3, "bytes": 2e6,
           "versions": {"cv": "0.4.7", "cv_commit": "23df9921abcdef", "corpus": 1, "glyph_pin": 2,
                        "db_revs": {"siku@main:9916": 200, "未记": 21}}}
    p = ER.write_record(tmp_path / "ws", "vol04", man, base_label="v0.4.6-cujiao", book_yaml="id: vol04\n",
                        report_dir=rep)
    assert p == tmp_path / "ws" / "experiments" / "vol04" / "cv0.4.7-c1-g2-x.md"
    t = p.read_text()
    assert "`v0.4.6-cujiao`" in t and "siku@main:9916（200 页）" in t and "id: vol04" in t
    assert "### 小节" in t and "前后对比 vol04" not in t
    assert (tmp_path / "ws" / "experiments" / "README.md").exists()
    assert ER.note_main(tmp_path / "ws", "vol04", "cv0.4.7-c1-g2-x", "验收过") == p
    assert "★ 标为 main：验收过" in p.read_text()
    assert ER.note_main(tmp_path / "ws", "vol04", "nope") is None


def test_central_rev(tmp_path, monkeypatch):
    from open_guji_cv.core import workspace as W
    monkeypatch.setattr(W, "data_root", lambda ws=None: tmp_path)
    assert W.central_rev() is None
    (tmp_path / ".central-state.json").write_text(json.dumps({"ws": "siku", "branch": "main", "rev": 9916}))
    assert W.central_rev() == "siku@main:9916"
