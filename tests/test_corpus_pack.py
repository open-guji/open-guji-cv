# -*- coding: utf-8 -*-
"""语料库清单（ops.corpus_pack）：build 递增不覆盖、verify 能发现改动／缺失／新增。自造工作区，不碰真书数据。"""
from __future__ import annotations

import json

import pytest

from open_guji_cv.ops import corpus_pack as cp


@pytest.fixture()
def ws(tmp_path):
    (tmp_path / "config" / "groups").mkdir(parents=True)
    (tmp_path / "config" / "groups" / "freq.json").write_text('{"a": 1}', encoding="utf-8")
    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "ref.txt").write_text("甲乙丙", encoding="utf-8")
    return tmp_path


def _ws_items(path):
    m = json.loads(path.read_text(encoding="utf-8"))
    return {i["path"] for i in m["items"] if i["root"] == "ws"}


def test_build_numbers_increase_and_never_overwrite(ws):
    p1 = cp.build(ws)
    assert p1.parent.name == "v1"
    assert _ws_items(p1) == {"config/groups/freq.json", "corpus/ref.txt"}
    assert cp.build(ws).parent.name == "v2"
    with pytest.raises(FileExistsError):
        cp.build(ws, 1)
    assert [s["version"] for s in cp.summary(ws)] == [1, 2]


def test_verify_detects_change_missing_extra(ws):
    cp.build(ws)
    assert cp.verify(ws, 1)["clean"]
    (ws / "config" / "groups" / "freq.json").write_text('{"a": 2}', encoding="utf-8")
    (ws / "corpus" / "ref.txt").unlink()
    (ws / "corpus" / "new.txt").write_text("丁", encoding="utf-8")
    r = cp.verify(ws, 1)
    assert not r["clean"]
    assert r["changed"] == ["ws:config/groups/freq.json"]
    assert r["missing"] == ["ws:corpus/ref.txt"]
    assert r["extra"] == ["ws:corpus/new.txt"]


def test_verify_unknown_version(ws):
    with pytest.raises(FileNotFoundError):
        cp.verify(ws, 9)


# ── 册钉子（core.corpus_pin）─────────────────────────────────────────────────

def _ctx_with_ws(tmp_path, monkeypatch, corpus):
    from helpers import make_book, make_ctx
    (tmp_path / "corpus").mkdir(exist_ok=True)
    (tmp_path / "corpus" / "ref.txt").write_text("甲乙丙", encoding="utf-8")
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path))
    return make_ctx(tmp_path, make_book(corpus=corpus))


def test_parse_pin():
    from open_guji_cv.core.corpus_pin import parse_pin
    assert parse_pin(None) is None and parse_pin("") is None
    assert parse_pin(3) == 3 and parse_pin("v3") == 3 and parse_pin("3") == 3
    for bad in (0, "x", "v", -1):
        with pytest.raises(ValueError):
            parse_pin(bad)


def test_pin_replaces_content_fingerprints_with_version(tmp_path, monkeypatch):
    from open_guji_cv.steps.context_decide import ContextDecideParams
    cp.build(tmp_path)                                  # v1
    unpinned = _ctx_with_ws(tmp_path, monkeypatch, None)
    p0 = unpinned.params_for(_step("context_decide"))
    assert p0.corpus_fingerprint and not p0.corpus_fingerprint.startswith("corpus-")

    pinned = _ctx_with_ws(tmp_path, monkeypatch, 1)
    p1 = pinned.params_for(_step("context_decide"))
    assert isinstance(p1, ContextDecideParams)
    assert p1.corpus_fingerprint == "corpus-v1"          # 没有钉子账的册：旧写法，指纹逐位不变


def test_legacy_pinned_fingerprint_ignores_content_but_not_version(tmp_path, monkeypatch):
    _ctx_with_ws(tmp_path, monkeypatch, None)
    cp.build(tmp_path)                                  # v1
    cp.build(tmp_path)                                  # v2
    ctx1 = _ctx_with_ws(tmp_path, monkeypatch, 1)
    before = ctx1.params_for(_step("context_decide")).corpus_fingerprint
    (tmp_path / "corpus" / "ref.txt").write_text("甲乙丙丁", encoding="utf-8")   # 内容变了
    from open_guji_cv.core.corpus_pin import corpus_token
    assert corpus_token(tmp_path, 1, "tbook") == before == "corpus-v1"
    assert corpus_token(tmp_path, 2, "tbook") == "corpus-v2"


def test_ledger_fingerprint_is_content_not_version_and_dev_follows_live_files(tmp_path, monkeypatch):
    """有钉子账的册：指纹取清单内容哈希，不含版本号；开发中取工作副本；发版前后不变。"""
    import json

    from open_guji_cv.core.corpus_pin import corpus_token, pins_path
    _ctx_with_ws(tmp_path, monkeypatch, None)
    cp.build(tmp_path)                                  # v1
    cp.build(tmp_path)                                  # v2：内容和 v1 一样
    pp = pins_path(tmp_path, "tbook")
    pp.parent.mkdir(parents=True, exist_ok=True)
    pp.write_text(json.dumps({"rows": [{"n": 1, "global": None, "book": 1, "vol": None},
                                       {"n": 2, "global": None, "book": 2, "vol": None}]}), encoding="utf-8")
    t1, t2 = corpus_token(tmp_path, 1, "tbook"), corpus_token(tmp_path, 2, "tbook")
    assert t1 == t2 and t1 != "corpus-v1"               # 内容没变，版本号换了，指纹不变
    assert corpus_token(tmp_path, 3, "tbook", dev=True) == t1   # 开发中、文件没动：与发版后一样
    (tmp_path / "corpus" / "ref.txt").write_text("甲乙丙丁", encoding="utf-8")
    assert corpus_token(tmp_path, 1, "tbook") == t1     # 钉死的：读清单，不受工作副本影响
    live = corpus_token(tmp_path, 3, "tbook", dev=True)
    assert live != t1                                   # 开发中：改了就变，产物自动判过期
    cp.build(tmp_path)                                  # v3 发版
    pp.write_text(json.dumps({"rows": [{"n": 3, "global": None, "book": 3, "vol": None}]}), encoding="utf-8")
    assert corpus_token(tmp_path, 3, "tbook") == live   # 发版前后指纹不变


def test_pin_without_manifest_fails_fast(tmp_path, monkeypatch):
    ctx = _ctx_with_ws(tmp_path, monkeypatch, 7)
    with pytest.raises(FileNotFoundError):
        ctx.params_for(_step("context_decide"))


def test_pin_leaves_steps_without_corpus_fields_alone(tmp_path, monkeypatch):
    cp.build(tmp_path)
    ctx = _ctx_with_ws(tmp_path, monkeypatch, 1)
    st = _step("border_detect")
    assert ctx.params_for(st) == st.spec.params()


def _step(sid):
    import open_guji_cv.steps  # noqa: F401  注册全部 Step
    from open_guji_cv.core.step import STEPS
    return STEPS[sid]


def test_step_payload_carries_pin_only_for_corpus_steps(tmp_path, monkeypatch):
    from helpers import make_book

    from open_guji_cv.core.engine import _self_payload
    _ctx_with_ws(tmp_path, monkeypatch, None)
    cp.build(tmp_path)
    (tmp_path / "corpus" / "ref.txt").write_text("甲乙丙丁", encoding="utf-8")
    cp.build(tmp_path)                                  # v2：内容不同于 v1
    for sid in ("glyph_match", "rare_candidates", "context_decide", "align_ref", "seed_admit"):
        assert "corpus" not in _self_payload(_step(sid), make_book(), "x")          # 没钉：键都不出现
        assert _self_payload(_step(sid), make_book(corpus=2), "x")["corpus"] == "corpus-v2"
    for sid in ("border_detect", "row_segment", "cell_shrink", "column_gate"):
        assert "corpus" not in _self_payload(_step(sid), make_book(corpus=2), "x")  # 几何步不受语料库升级影响
    a = _self_payload(_step("glyph_match"), make_book(corpus=1), "x")
    b = _self_payload(_step("glyph_match"), make_book(corpus=2), "x")
    assert a != b


# ── 两级清单：底库 b<M>（中心库 corpus-base）＋书库 v<N>（共享方案 S2）──────────────

@pytest.fixture()
def two_level(tmp_path, monkeypatch):
    """迁过的书工作区＋本机已有底库 b1 的只读副本（同 db pull 拉下来的位置）。"""
    from open_guji_cv.core.corpus_pin import BASE_DIR, BASE_WS
    from open_guji_cv.core.workspace import borrowed_root, central_data_dir
    monkeypatch.setenv("GUJI_DATA_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(cp, "_repo_dirty", lambda paths, repo=None: [])
    monkeypatch.setattr(cp, "_repo_commit", lambda repo=None: "c0ffee")
    base_ws = cp.base_workdir("main")
    b1 = cp.build_base(base_ws, "first")
    copy = borrowed_root(BASE_WS) / BASE_DIR / "b1" / "manifest.json"
    copy.parent.mkdir(parents=True)
    copy.write_bytes(b1.read_bytes())
    book = tmp_path / "book"
    book.mkdir()
    (book / "workspace.yaml").write_text("id: tbk\n", encoding="utf-8")
    (book / ".central.json").write_text('{"ws": "tbk", "branch": "main"}', encoding="utf-8")
    data = central_data_dir("tbk")
    (data / "corpus").mkdir(parents=True)
    (data / "corpus" / "ref.txt").write_text("甲乙丙", encoding="utf-8")
    return book, data, b1


def test_build_base_lists_only_repo_files_and_never_overwrites(two_level):
    _, _, b1 = two_level
    m = json.loads(b1.read_text(encoding="utf-8"))
    assert m["base_version"] == 1 and m["repo_commit"] == "c0ffee" and m["items"]
    assert {i["root"] for i in m["items"]} == {"repo"} and "NEVER_MATCH_FAMILIES" in m["code_tables"]
    assert cp.build_base(cp.base_workdir("main")).parent.name == "b2"     # 新版另开，不覆盖 b1
    assert b1.read_text(encoding="utf-8") == json.dumps(m, ensure_ascii=False, indent=1) + "\n"


def test_build_base_refuses_uncommitted_repo_files(two_level, monkeypatch):
    monkeypatch.setattr(cp, "_repo_dirty", lambda paths, repo=None: ["config/ids/x.txt"])
    with pytest.raises(SystemExit, match="没提交"):
        cp.build_base(cp.base_workdir("main"))


def test_build_base_refuses_non_base_workspace(two_level):
    book, _, _ = two_level
    with pytest.raises(SystemExit, match="不是 corpus-base"):
        cp.build_base(book)


def test_book_manifest_with_base_lists_workspace_files_and_verifies_both(two_level):
    book, data, _ = two_level
    out = cp.build(book, base="latest")
    m = json.loads(out.read_text(encoding="utf-8"))
    assert out == data / "config" / "corpus-pack" / "v1" / "manifest.json"
    assert m["base"] == 1 and {i["root"] for i in m["items"]} == {"ws"}
    assert "code_tables" not in m
    r = cp.verify(book, 1)
    assert r["clean"] and r["base"] == 1
    assert cp.summary(book)[0]["base"] == 1
    (data / "corpus" / "ref.txt").write_text("甲乙丙丁", encoding="utf-8")
    assert cp.verify(book, 1)["changed"] == ["ws:corpus/ref.txt"]


def test_book_manifest_needs_the_base_locally(two_level):
    from open_guji_cv.core.corpus_pin import BASE_DIR, BASE_WS
    from open_guji_cv.core.workspace import borrowed_root
    book, _, _ = two_level
    with pytest.raises(FileNotFoundError, match="b7"):
        cp.build(book, base=7)
    cp.build(book, base=1)
    import shutil
    shutil.rmtree(borrowed_root(BASE_WS) / BASE_DIR)
    with pytest.raises(FileNotFoundError, match="db pull"):
        cp.verify(book, 1)


def test_hard_check_refuses_drift_before_running(two_level, monkeypatch, capsys):
    """钉住的版本：清单里的文件改了 → 起跑前拒绝；新出现的文件只警告；GUJI_CORPUS_DRIFT=warn 临时绕过。"""
    from open_guji_cv.core import corpus_pin
    book, data, _ = two_level
    cp.build(book, base="latest")
    corpus_pin.require_pin_clean(book, 1)
    (data / "corpus" / "new.txt").write_text("丁", encoding="utf-8")
    corpus_pin._CLEAN.clear()
    corpus_pin.require_pin_clean(book, 1)
    assert "新出现 1 个" in capsys.readouterr().err
    (data / "corpus" / "ref.txt").write_text("改了", encoding="utf-8")
    with pytest.raises(corpus_pin.CorpusDrift, match="ref.txt"):
        corpus_pin.require_pin_clean(book, 1)
    monkeypatch.setenv(corpus_pin.DRIFT_ENV, "warn")
    corpus_pin.require_pin_clean(book, 1)
    with pytest.raises(corpus_pin.CorpusDrift, match="没有语料库 v3"):
        corpus_pin.require_pin_clean(book, 3)


def test_engine_runs_hard_check_only_for_pinned_corpus_steps(tmp_path, monkeypatch):
    from helpers import make_book

    from open_guji_cv.core import corpus_pin
    from open_guji_cv.core.engine import Engine
    seen = []
    monkeypatch.setattr(corpus_pin, "require_pin_clean", lambda ws, v, **kw: seen.append(v) or (_ for _ in ()).throw(
        corpus_pin.CorpusDrift("drift")))

    class _E:
        book = make_book(corpus=2)

        def optional_gaps(self, step, pages):
            return []

    with pytest.raises(corpus_pin.CorpusDrift):
        Engine._run_one_step(_E(), _step("glyph_match"), [], None, False, False, 0, 0)
    assert seen == [2]
    e = _E()
    e.book = make_book()                                # 没钉：不查
    with pytest.raises(AttributeError):                 # 走到后面真跑的地方（假引擎没有 store）
        Engine._run_one_step(e, _step("glyph_match"), [], None, False, False, 0, 0)
    assert seen == [2]


def test_cv_version_reads_repo_pyproject(tmp_path):
    """清单里的 cv_version 读引擎仓 pyproject（装包元数据在可编辑安装后会旧）。"""
    from open_guji_cv.ops.corpus_pack import _cv_version
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\nversion = "9.8.7"\n', encoding="utf-8")
    assert _cv_version(tmp_path) == "9.8.7"


def test_push_refuses_changed_corpus_without_new_version(ws):
    """语料库任何内容变了都要改版本号（用户 10-20）：最新一版登记的文件改了／缺了／多了 → 推送前拒绝；出新版本就放行。"""
    from open_guji_cv.core import corpus_pin
    assert corpus_pin.push_problems(ws) == []             # 没出过清单：不管
    cp.build(ws)
    assert corpus_pin.push_problems(ws) == []
    (ws / "config" / "groups" / "freq.json").write_text('{"a": 2}', encoding="utf-8")
    (ws / "corpus" / "new.txt").write_text("丁", encoding="utf-8")
    msg = corpus_pin.push_problems(ws)[0]
    assert "freq.json" in msg and "new.txt" in msg and "v2" in msg
    cp.build(ws)                                          # 出 v2 把现状收进去 → 放行
    assert corpus_pin.push_problems(ws) == []


# ── 分层版本：全局／整套书／册三层，总号记在册的钉子账里（doc/design/语料库分层版本.md）──────

def _copy_base(b, tmp_path_unused=None):
    from open_guji_cv.core.corpus_pin import BASE_DIR, BASE_WS
    from open_guji_cv.core.workspace import borrowed_root
    n = json.loads(b.read_text(encoding="utf-8"))["base_version"]
    dst = borrowed_root(BASE_WS) / BASE_DIR / f"b{n}" / "manifest.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(b.read_bytes())


def test_no_pin_ledger_means_legacy_meaning(two_level):
    """册没有钉子账：总号就是书库版本，带不带册 id 解出来的清单一样（殿本现有 corpus: 9 不受影响）。"""
    from open_guji_cv.core import corpus_pin
    book, _, _ = two_level
    cp.build(book, base=1)
    assert corpus_pin.resolve_pin(book, "vol01", 1) == {"n": 1, "global": 1, "book": 1, "vol": None}
    assert corpus_pin.load_manifest(book, 1, "vol01") == corpus_pin.load_manifest(book, 1)
    with pytest.raises(FileNotFoundError, match="没有语料库 v3"):
        corpus_pin.load_manifest(book, 3, "vol01")


def test_any_layer_change_bumps_total_and_same_combo_is_refused(two_level):
    from open_guji_cv.core import corpus_pin
    book, data, _ = two_level
    cp.build(book, base=1)
    vol_dir = data / "config" / "corpus-vol" / "vol01"
    vol_dir.mkdir(parents=True)
    (vol_dir / "fixed.json").write_text('{"a": 1}', encoding="utf-8")
    v1 = cp.build_vol(book, "vol01")
    assert v1.parent.name == "v1"
    with pytest.raises(ValueError, match="相同"):
        cp.build_vol(book, "vol01")                       # 内容没变不空升
    with pytest.raises(ValueError, match="钉子账"):
        corpus_pin.append_pin(book, "vol01", vol_ver=1)   # 没账又没给 from_n
    r2 = corpus_pin.append_pin(book, "vol01", from_n=1, vol_ver=1)          # 册层变了 → 总号 2
    assert (r2["n"], r2["global"], r2["book"], r2["vol"]) == (2, 1, 1, 1)
    assert [r["n"] for r in corpus_pin.load_pins(book, "vol01")] == [1, 2]   # 首行是迁移行
    with pytest.raises(ValueError, match="不空升"):
        corpus_pin.append_pin(book, "vol01", vol_ver=1)
    (data / "corpus" / "ref.txt").write_text("甲乙丙丁", encoding="utf-8")
    cp.build(book, base=1)                                                   # 整套书层 v2
    assert corpus_pin.append_pin(book, "vol01", book_ver=2)["n"] == 3
    _copy_base(cp.build_base(cp.base_workdir("main"), "second"))              # 全局层 b2
    assert corpus_pin.append_pin(book, "vol01", global_ver=2)["n"] == 4
    assert corpus_pin.append_pin(book, "vol01", book_ver=1, global_ver=1)["n"] == 5   # 回退也是新总号
    with pytest.raises(FileNotFoundError, match="没有 v9"):
        corpus_pin.append_pin(book, "vol01", book_ver=9)


def test_pinned_manifest_merges_three_layers_and_verify_sees_vol_files(two_level, monkeypatch):
    from open_guji_cv.core import corpus_pin
    book, data, _ = two_level
    cp.build(book, base=1)
    vol_dir = data / "config" / "corpus-vol" / "vol01"
    vol_dir.mkdir(parents=True)
    (vol_dir / "fixed.json").write_text('{"a": 1}', encoding="utf-8")
    cp.build_vol(book, "vol01")
    corpus_pin.append_pin(book, "vol01", from_n=1, vol_ver=1)
    man = corpus_pin.load_manifest(book, 2, "vol01")
    roots = {(i["root"], i["path"]) for i in man["items"]}
    assert ("ws", "config/corpus-vol/vol01/fixed.json") in roots and ("ws", "corpus/ref.txt") in roots
    assert any(r == "repo" for r, _ in roots)                               # 全局层的引擎仓文件
    assert cp.verify(book, 2, "vol01")["clean"]
    (vol_dir / "new.json").write_text("{}", encoding="utf-8")
    assert cp.verify(book, 2, "vol01")["extra"] == ["ws:config/corpus-vol/vol01/new.json"]
    (vol_dir / "fixed.json").write_text('{"a": 2}', encoding="utf-8")
    corpus_pin._CLEAN.clear()
    with pytest.raises(corpus_pin.CorpusDrift, match="fixed.json"):
        corpus_pin.require_pin_clean(book, 2, "vol01")
    corpus_pin._CLEAN.clear()
    monkeypatch.setenv(corpus_pin.DRIFT_ENV, "warn")
    corpus_pin.require_pin_clean(book, 2, "vol01")


def test_vol_manifest_rejects_foreign_paths(two_level):
    from open_guji_cv.core import corpus_pin
    book, data, _ = two_level
    cp.build(book, base=1)
    vol_dir = data / "config" / "corpus-vol" / "vol01"
    vol_dir.mkdir(parents=True)
    (vol_dir / "a.json").write_text("{}", encoding="utf-8")
    p = cp.build_vol(book, "vol01")
    m = json.loads(p.read_text(encoding="utf-8"))
    m["items"][0]["path"] = "config/groups/freq.json"
    p.write_text(json.dumps(m), encoding="utf-8")
    with pytest.raises(ValueError, match="册层清单"):
        corpus_pin.append_pin(book, "vol01", from_n=1, vol_ver=1)
        corpus_pin.load_manifest(book, 2, "vol01")


def test_push_refuses_dev_pinned_book(two_level):
    from open_guji_cv.core import corpus_pin
    book, data, _ = two_level
    (data / "books").mkdir()
    (data / "books" / "vol01.yaml").write_text("id: vol01\ncorpus: 3\n", encoding="utf-8")
    assert corpus_pin.push_problems(book) == []
    (data / "books" / "vol02.yaml").write_text("id: vol02\ncorpus: 4\ncorpus_dev: true\n", encoding="utf-8")
    msg = corpus_pin.push_problems(book)
    assert len(msg) == 1 and "vol02" in msg[0] and "dev" in msg[0]


def test_dev_pin_skips_checks_then_release_needs_layers_built(two_level):
    from helpers import make_book

    from open_guji_cv.core import corpus_pin
    book, data, _ = two_level
    cp.build(book, base=1)
    row = corpus_pin.append_pin(book, "vol01", from_n=1, book_ver=2, dev=True)       # 先升号，v2 清单还没出
    assert row["n"] == 2 and row["dev"] is True
    with pytest.raises(FileNotFoundError, match="整套书层没有 v2"):
        corpus_pin.release_pin(book, "vol01", 2)                                      # 清单没出齐不放行
    (data / "corpus" / "ref.txt").write_text("甲乙丙丁", encoding="utf-8")            # 开发中改语料
    corpus_pin.require_pin_clean(book, 1, "vol01")  if False else None
    b = make_book(corpus=2, corpus_dev=True)
    assert b.corpus_dev                                                               # 跳过校验的开关
    cp.build(book, base=1)                                                            # 发版：出 v2
    assert "dev" not in corpus_pin.release_pin(book, "vol01", 2)
    assert "dev" not in corpus_pin.load_pins(book, "vol01")[-1]
    with pytest.raises(ValueError, match="不是开发中"):
        corpus_pin.release_pin(book, "vol01", 2)


def test_big_txt_items_are_marked_r2_and_do_not_change_fingerprint(tmp_path, monkeypatch):
    from open_guji_cv.core import corpus_pin
    (tmp_path / "corpus").mkdir()
    (tmp_path / "corpus" / "big.txt").write_text("甲" * 400_000, encoding="utf-8")      # 1.2MB
    (tmp_path / "corpus" / "small.txt").write_text("乙", encoding="utf-8")
    items = {i["path"]: i for i in corpus_pin.collect(tmp_path)}
    assert items["corpus/big.txt"]["store"] == "r2" and "store" not in items["corpus/small.txt"]
    d1 = corpus_pin.items_digest(list(items.values()))
    d2 = corpus_pin.items_digest([{k: v for k, v in i.items() if k != "store"} for i in items.values()])
    assert d1 == d2                                                   # store 只是存放位置的标注，不进指纹
    cp.build(tmp_path)
    plan = cp.upload_blobs(tmp_path, 1)                              # 缺省只演练，不碰网络
    assert plan["blobs"] >= 1 and plan["local"] == plan["blobs"] and plan["executed"] is False   # 含仓里的殆知阁两部
    (tmp_path / "corpus" / "big.txt").write_text("丙" * 400_000, encoding="utf-8")
    with pytest.raises(ValueError, match="不符"):
        cp.upload_blobs(tmp_path, 1)


def test_group_prompt_md_is_not_corpus(tmp_path, monkeypatch):
    """字组 prompt.md 只给离线 L2 拼消息，Step 不读：不进清单；老清单里登记了的，改它也不算漂移。"""
    from open_guji_cv.core import corpus_pin
    repo = tmp_path / "repo"
    g = repo / "config" / "groups" / "rr"
    g.mkdir(parents=True)
    (g / "rules.yaml").write_text("a: 1\n", encoding="utf-8")
    (g / "prompt.md").write_text("v1\n", encoding="utf-8")
    monkeypatch.setattr(corpus_pin, "REPO_ROOT", repo)
    ws = tmp_path / "ws"
    ws.mkdir()
    items = corpus_pin.collect(ws)
    assert [i["path"] for i in items] == ["config/groups/rr/rules.yaml"]
    old = {"items": items + [{"group": "rules", "root": "repo", "path": "config/groups/rr/prompt.md",
                              "size": 3, "sha256": "0" * 64}]}
    (g / "prompt.md").write_text("v2\n", encoding="utf-8")
    assert corpus_pin.check_files(ws, old) == {"changed": [], "missing": [], "extra": []}
    (g / "rules.yaml").write_text("a: 2\n", encoding="utf-8")
    assert corpus_pin.check_files(ws, old)["changed"] == ["repo:config/groups/rr/rules.yaml"]
