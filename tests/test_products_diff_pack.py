"""受控重跑工具：前后对比（ops/products_diff.py）、产物包（datastore/packs.py）。"""
import json

import pytest



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
    for lab, body, cv in (("a1", "A", "0.4.7"), ("b2", "B", "0.4.8.dev3+gabcdef123456")):
        (root / "vol04" / "seed_admit" / "p0001.json").write_text(body)
        PK.push_products("vol04", root, label=lab, src=src,
                         vers={"cv": cv, "cv_commit": "c" * 40, "corpus": None, "glyph_pin": None, "human_fp": None})
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
    with pytest.raises(ValueError, match="不是正式版"):                 # dev 出的包不能标 main
        PK.promote("vol04", "b2", src=src)
    assert PK.main_label("vol04", src=src) == "a1"
    PK.promote("vol04", "b2", src=src, why="A30 急用，0.4.8 发版后重跑")  # 写了理由可以，记进指针
    assert PK.main_label("vol04", src=src) == "b2"
    ptr = [json.loads(v) for k, v in src.objs.items() if "/main-ptr/" in k and k.endswith("-b2.json")]
    assert ptr[0]["cv_override"].startswith("A30") and ptr[0]["cv_version"].startswith("0.4.8.dev3")


def test_version_label():
    from open_guji_cv.datastore import packs as PK
    assert PK.version_label({"cv": "0.4.7", "corpus": 1, "glyph_pin": 2}) == "cv0.4.7-c1-g2"
    assert PK.version_label({"cv": "0.4.7+3", "corpus": None, "glyph_pin": None,
                             "human_fp": "h1:812:3fa9c1d2e"}) == "cv0.4.7p3-c--g-3fa9c1"
    lab = PK.version_label({"cv": "0.4.7+dirty", "corpus": 1, "glyph_pin": None, "human_fp": "nodb"})
    assert lab == "cv0.4.7pdirty-c1-g-"
    PK.check_label(lab + "-x")
    lab = PK.version_label({"cv": "0.5.10.dev12+g1a2b3c4d5e6f", "corpus": 3, "glyph_pin": 2})
    assert lab == "cv0.5.10.dev12pg1a2b3c4d5e6f-c3-g2"
    PK.check_label(lab + "-20261023T1730")
    assert len(lab + "-20261023T1730") <= PK.LABEL_MAX_MAIN


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


def test_central_rev(tmp_path, monkeypatch):
    from open_guji_cv.core import workspace as W
    monkeypatch.setattr(W, "data_root", lambda ws=None: tmp_path)
    assert W.central_rev() is None
    (tmp_path / ".central-state.json").write_text(json.dumps({"ws": "siku", "branch": "main", "rev": 9916}))
    assert W.central_rev() == "siku@main:9916"


def test_ws_name_marker_then_yaml_then_error(tmp_path, monkeypatch):
    """包键的工作区名：标记优先，其次 workspace.yaml 的 id；都没有就报错，不回退成目录名或 ws（GUJI-671）。"""
    from open_guji_cv.datastore import packs as PK
    ws = tmp_path / "96mid1ogzk-某書"
    ws.mkdir()
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    monkeypatch.delenv("GUJI_DATA_BRANCH", raising=False)
    with pytest.raises(SystemExit):
        PK._ws_name()
    (ws / "workspace.yaml").write_text("id: demo-ws\n", encoding="utf-8")
    assert PK._ws_name() == "demo-ws"
    (ws / ".central.json").write_text(json.dumps({"ws": "from-marker", "branch": "main"}), encoding="utf-8")
    assert PK._ws_name() == "from-marker"
    monkeypatch.delenv("GUJI_WORKSPACE")
    with pytest.raises(SystemExit):
        PK._ws_name()
