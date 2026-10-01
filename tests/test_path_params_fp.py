# -*- coding: utf-8 -*-
"""路径参数不进指纹（K238，2026-09-29）+ manifest 指纹迁移。

云端算好的整包导入服务器，`glyph_match.db_path` 留空时填的是本机绝对路径——进了
`params_hash` 就是全书判过期。合成步骤、纯 tmp 数据，不碰真书。"""
from __future__ import annotations

import dataclasses
import json

import cv2
import numpy as np
import pytest
from pydantic import BaseModel

import open_guji_cv.steps  # noqa: F401

from open_guji_cv.core.book import BookSpec
from open_guji_cv.core.engine import FRESH, STALE, Engine, params_hash
from open_guji_cv.core.pipeline import Pipeline
from open_guji_cv.core.spec import ProductKindSpec, StepSpec
from open_guji_cv.core.step import KINDS, STEPS, Step, register_kind, register_step
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.fp_migrate import diff_upstream, format_diff, migrate_book, parse_old_paths
from open_guji_cv.products.store import ProductStore


# ── 真步骤的登记 ─────────────────────────────────────────────────────
def test_registered_path_params_exist_and_leave_hash():
    expect = {
        "glyph_match": ("db_path",),
        "seed_admit": ("db_path", "variants", "note_lexicon", "exclusions", "shadow_model"),
        "context_decide": ("corpus", "general_corpus_dir", "ai_evidence", "llm_log_dir"),
        "align_ref": ("corpus",),
    }
    for sid, fields in expect.items():
        spec = STEPS[sid].spec
        assert spec.path_params == fields
        for f in fields:
            assert f in spec.params.model_fields, (sid, f)


def test_glyph_match_hash_ignores_db_path_but_not_other_params():
    from open_guji_cv.steps.glyph_match import GlyphMatchParams
    sp = STEPS["glyph_match"].spec
    a = GlyphMatchParams(db_path="/cloud/ws/glyph.db", db_fingerprint="x")
    b = GlyphMatchParams(db_path="/server/ws/glyph.db", db_fingerprint="x")
    h = lambda p: params_hash(p, sp.soft_params, sp.path_params)  # noqa: E731
    assert h(a) == h(b)
    assert params_hash(a, sp.soft_params) != params_hash(b, sp.soft_params)   # 老公式确实带路径
    assert h(a) != h(GlyphMatchParams(db_path="/cloud/ws/glyph.db", db_fingerprint="x", knn_k=3))


def test_corpus_path_out_but_corpus_content_in():
    from open_guji_cv.steps.context_decide import ContextDecideParams
    sp = STEPS["context_decide"].spec
    h = lambda p: params_hash(p, sp.soft_params, sp.path_params)  # noqa: E731
    a = ContextDecideParams(corpus="/a/x.txt", corpus_fingerprint="f1")
    b = ContextDecideParams(corpus="/b/x.txt", corpus_fingerprint="f1")
    c = ContextDecideParams(corpus="/a/x.txt", corpus_fingerprint="f2")
    assert h(a) == h(b) and h(a) != h(c)
    # 没有内容指纹的 `variants` 不许出指纹
    assert h(a) != h(ContextDecideParams(corpus="/a/x.txt", corpus_fingerprint="f1", variants="/v.json"))


def test_no_unregistered_path_like_defaults():
    """新增路径类参数必须表态：进 `path_params`（旁边有内容指纹）或写进例外并说明。
    扫每步参数默认值：绝对路径 / 带目录的相对路径 / 文件后缀的字符串 = 路径。"""
    allowed_in_hash: set[tuple[str, str]] = set()
    bad = []
    for sid, st in STEPS.items():
        if sid.startswith("t_"):          # 别的测试文件注册的合成步
            continue
        try:
            d = st.spec.params().model_dump(mode="json")
        except Exception:
            continue
        for k, v in d.items():
            if (isinstance(v, str) and ("/" in v or "\\" in v or v.endswith((".json", ".db", ".tsv", ".txt")))
                    and k not in st.spec.path_params and (sid, k) not in allowed_in_hash):
                bad.append((sid, k, v))
    assert not bad, f"路径类参数没登记 path_params：{bad}"


# ── 合成步骤：迁移 ────────────────────────────────────────────────────
class _Out(BaseModel):
    page: int
    v: float


class _P(BaseModel):
    gain: float = 1.0
    lib_path: str = "/cloud/lib.db"
    lib_fp: str = "L1"


if "t_fp_out" not in KINDS:
    register_kind(ProductKindSpec(id="t_fp_out", title="o", storage="numeric", unit="page", schema=_Out))
    register_kind(ProductKindSpec(id="t_fp_out2", title="o2", storage="numeric", unit="page", schema=_Out))


def _register(path_params):
    """同一个测试里换 `path_params` 要重登（登记表是进程级的）。"""
    STEPS.pop("t_fp_step", None)

    @register_step
    class _S(Step):
        spec = StepSpec(id="t_fp_step", title="路径步", version="1", unit="page",
                        consumes=("raw_page",), produces=("t_fp_out",), params=_P,
                        path_params=path_params)

        def run_page(self, ctx, page):
            return {"t_fp_out": _Out(page=page, v=1.0)}


@pytest.fixture
def world(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    for pg in (1, 2):
        cv2.imwrite(str(raw / f"{pg}.png"), np.full((20, 20), 200, np.uint8))
    book = BookSpec(id="tfp", title="t", raw_dir=raw, dev_set=[1, 2])
    _register(())
    pl = Pipeline(id="tfp", title="t", steps=["t_fp_step"])
    pl.validate()
    return book, pl, ProductStore(tmp_path / "products"), ImageCache(tmp_path / "cache")


def _eng(w, params=None):
    book, pl, store, cache = w
    return Engine(book, pl, store=store, cache=cache, params=params, log=lambda s: None)


def _old_world(w):
    """按老公式（路径在指纹里）跑一遍 → manifest 是「升级前」的样子。"""
    _register(())
    _eng(w, {"t_fp_step": {"lib_path": "/cloud/lib.db"}}).run()
    _register(("lib_path",))


def test_path_change_no_longer_stales(world):
    _register(("lib_path",))
    _eng(world, {"t_fp_step": {"lib_path": "/cloud/lib.db"}}).run()
    st = _eng(world, {"t_fp_step": {"lib_path": "/server/lib.db"}}).status()
    assert st["steps"]["t_fp_step"]["counts"][FRESH] == 2
    st = _eng(world, {"t_fp_step": {"lib_fp": "L2"}}).status()      # 内容指纹变了照样过期
    assert st["steps"]["t_fp_step"]["counts"][STALE] == 2


def test_migrate_dry_run_then_apply_with_old_path(world):
    _old_world(world)
    eng = _eng(world, {"t_fp_step": {"lib_path": "/server/lib.db"}})
    assert eng.status()["steps"]["t_fp_step"]["counts"][STALE] == 2      # 升级后先全过期
    m = world[2].manifest("tfp", "t_fp_step")
    before = {k: dataclasses.asdict(e) for k, e in m.all().items()}
    old = parse_old_paths(["t_fp_step.lib_path=/cloud/lib.db"])

    rep = migrate_book(eng, [1, 2], old_paths=old, apply=False)          # 干跑：不写
    assert rep["t_fp_step"]["migrated"] == 2
    assert eng.status()["steps"]["t_fp_step"]["counts"][STALE] == 2
    assert {k: dataclasses.asdict(e) for k, e in world[2].manifest("tfp", "t_fp_step").all().items()} == before

    rep = migrate_book(eng, [1, 2], old_paths=old, apply=True)
    assert rep["t_fp_step"]["migrated"] == 2
    st = _eng(world, {"t_fp_step": {"lib_path": "/server/lib.db"}}).status()
    assert st["steps"]["t_fp_step"]["counts"][FRESH] == 2
    # 只动指纹三件：产物 sha、上游、soft 等原样
    after = world[2].manifest("tfp", "t_fp_step").get("p0001")
    b = before["p0001"]
    assert (after.sha256, after.upstream, after.status) == (b["sha256"], b["upstream"], b["status"])
    assert after.fingerprint != b["fingerprint"]
    # 幂等
    rep = migrate_book(eng, [1, 2], old_paths=old, apply=True)
    assert rep["t_fp_step"] == {"migrated": 0, "already": 2, "skipped": {}}


def test_migrate_refuses_when_more_than_path_changed(world):
    """指纹不只因路径而变（这里是 gain 也变了）→ 按老路径重算对不上 → 不改写。"""
    _old_world(world)
    eng = _eng(world, {"t_fp_step": {"lib_path": "/server/lib.db", "gain": 2.0}})
    rep = migrate_book(eng, [1, 2], old_paths=parse_old_paths(["t_fp_step.lib_path=/cloud/lib.db"]),
                       apply=True)
    assert rep["t_fp_step"]["migrated"] == 0
    assert sum(rep["t_fp_step"]["skipped"].values()) == 2
    assert eng.status()["steps"]["t_fp_step"]["counts"][STALE] == 2


def test_migrate_wrong_old_path_and_no_evidence(world):
    _old_world(world)
    eng = _eng(world, {"t_fp_step": {"lib_path": "/server/lib.db"}})
    rep = migrate_book(eng, [1, 2], old_paths=parse_old_paths(["t_fp_step.lib_path=/nope.db"]), apply=True)
    assert rep["t_fp_step"]["migrated"] == 0
    rep = migrate_book(eng, [1, 2], apply=True)                       # 既没老路径也没 --trust
    assert rep["t_fp_step"]["migrated"] == 0
    assert "无法证明" in next(iter(rep["t_fp_step"]["skipped"]))
    rep = migrate_book(eng, [1, 2], trust=True, apply=True)           # 显式信任
    assert rep["t_fp_step"]["migrated"] == 2


def test_migrate_skips_changed_product_and_keeps_invalidated(world):
    _old_world(world)
    eng = _eng(world, {"t_fp_step": {"lib_path": "/server/lib.db"}})
    store = world[2]
    store.manifest("tfp", "t_fp_step").invalidate("p0002", "人裁")
    store.path("tfp", "t_fp_step", "p0001").write_text('{"page": 1, "v": 9.0}')   # 产物被动过
    rep = migrate_book(eng, [1, 2], trust=True, apply=True)
    e2 = store.manifest("tfp", "t_fp_step").get("p0002")
    assert e2.invalidated and "人裁" in e2.invalidated              # 显式失效不被洗掉
    assert rep["t_fp_step"]["migrated"] == 1
    assert list(rep["t_fp_step"]["skipped"]) == ["产物文件缺失或与条目记的 sha 不符"]


def test_parse_old_paths_rejects_garbage():
    with pytest.raises(ValueError):
        parse_old_paths(["no_equals"])
    with pytest.raises(ValueError):
        parse_old_paths(["nodot=/x"])
    assert parse_old_paths(["a.b=/x=y"]) == {"a": {"b": "/x=y"}}


def test_old_path_must_be_a_path_param(world):
    _old_world(world)
    eng = _eng(world)
    with pytest.raises(ValueError):
        migrate_book(eng, [1, 2], old_paths={"t_fp_step": {"gain": "3"}})


def test_cli_fp_migrate_dry_run_prints(world, monkeypatch, capsys):
    from open_guji_cv import cli_v2
    _old_world(world)
    eng = _eng(world, {"t_fp_step": {"lib_path": "/server/lib.db"}})
    monkeypatch.setattr(cli_v2, "_engine", lambda *a, **k: eng)
    args = type("A", (), {"book": "tfp", "pipeline": "tfp", "pages": "dev_set", "steps": None,
                          "old_path": ["t_fp_step.lib_path=/cloud/lib.db"], "trust": False,
                          "apply": False, "json": True})()
    monkeypatch.setattr("open_guji_cv.core.runlock.book_run_lock",
                        lambda *a, **k: __import__("contextlib").nullcontext())
    cli_v2.cmd_fp_migrate(args)
    out = json.loads(capsys.readouterr().out)
    assert out["t_fp_step"]["migrated"] == 2


# ── K238b：--explain / 点名无路径步 / 同名上游来源不同 ─────────────────
class _Cells(BaseModel):
    page: int
    v: float


if "t_fp_cells" not in KINDS:
    register_kind(ProductKindSpec(id="t_fp_cells", title="c", storage="numeric", unit="page", schema=_Cells))


def _register_two_producers():
    """`t_fp_cells` 有两个产出者（像 row_segment 与另一条链的同名产物）；下游只认管线里排前的。"""
    for sid in ("t_fp_ca", "t_fp_cb", "t_fp_down"):
        STEPS.pop(sid, None)

    @register_step
    class _A(Step):
        spec = StepSpec(id="t_fp_ca", title="a", version="1", unit="page",
                        consumes=("raw_page",), produces=("t_fp_cells",), params=_P)

        def run_page(self, ctx, page):
            return {"t_fp_cells": _Cells(page=page, v=1.0)}

    @register_step
    class _B(Step):
        spec = StepSpec(id="t_fp_cb", title="b", version="1", unit="page",
                        consumes=("raw_page",), produces=("t_fp_cells",), params=_P)

        def run_page(self, ctx, page):
            return {"t_fp_cells": _Cells(page=page, v=2.0)}

    @register_step
    class _D(Step):
        spec = StepSpec(id="t_fp_down", title="d", version="1", unit="page",
                        consumes=("t_fp_cells",), produces=("t_fp_out",), params=_P,
                        path_params=("lib_path",))

        def run_page(self, ctx, page):
            return {"t_fp_out": _Out(page=page, v=1.0)}


def test_same_named_upstream_from_different_producer_is_not_washed(world):
    """记录的 cells 来自 A，现算的 cells 来自 B（同名键、不同产出步）：不许迁，
    --explain 要指出记录的 sha 现在对应 A、现算由 B 产出。"""
    book, _, store, cache = world
    _register_two_producers()
    pa = Pipeline(id="pa", title="a", steps=["t_fp_ca", "t_fp_down"])
    pb = Pipeline(id="pb", title="b", steps=["t_fp_cb", "t_fp_down"])
    for pl in (pa, pb):
        pl.validate()
    Engine(book, pa, store=store, cache=cache, log=lambda s: None,
           params={"t_fp_down": {"lib_path": "/cloud/x"}}).run()
    Engine(book, pb, store=store, cache=cache, log=lambda s: None).run(steps=["t_fp_cb"])
    eng = Engine(book, pb, store=store, cache=cache, log=lambda s: None,
                 params={"t_fp_down": {"lib_path": "/server/x"}})
    before = dataclasses.asdict(world[2].manifest("tfp", "t_fp_down").get("p0001"))
    rep = migrate_book(eng, [1, 2], trust=True, apply=True, explain=True)
    r = rep["t_fp_down"]
    assert r["migrated"] == 0 and r["skipped"] == {"上游产物变了": 2}
    d = r["detail"][1]["diffs"]
    assert len(d) == 1 and d[0]["kind"] == "t_fp_cells" and d[0]["how"] == "sha 不同"
    assert d[0]["producer_now"] == "t_fp_cb" and d[0]["recorded_from"] == ["t_fp_ca"]
    assert "t_fp_ca" in format_diff(d[0])
    # 没洗：manifest 条目原样
    assert dataclasses.asdict(world[2].manifest("tfp", "t_fp_down").get("p0001")) == before
    # 同一批记录在「来源对得上」的管线里不跳过
    eng_a = Engine(book, pa, store=store, cache=cache, log=lambda s: None,
                   params={"t_fp_down": {"lib_path": "/server/x"}})
    ok = migrate_book(eng_a, [1, 2], trust=True, apply=False)["t_fp_down"]
    assert ok["skipped"] == {} and ok["migrated"] + ok["already"] == 2   # 记录本就是新公式 → already


def test_named_step_without_path_params_is_reported(world):
    eng = _eng(world)
    rep = migrate_book(eng, [1, 2], steps=["t_fp_step", "nope"], trust=True)
    assert rep["t_fp_step"] == {"na": "无路径参数，不适用"}
    assert rep["nope"] == {"na": "不在本管线里"}
    assert migrate_book(eng, [1, 2], trust=True) == {}      # 没点名：仍然不列无路径步


def test_explain_missing_upstream_and_only_one_side(world):
    _register(("lib_path",))
    eng = _eng(world, {"t_fp_step": {"lib_path": "/cloud/lib.db"}})
    eng.run()
    eng2 = _eng(world, {"t_fp_step": {"lib_path": "/server/lib.db"}})
    d = diff_upstream(eng2, STEPS["t_fp_step"], 1, {"raw_page": "aaaa", "extra": "bbbb"},
                      {"raw_page": "cccc"})
    hows = {x["kind"]: x["how"] for x in d}
    assert hows == {"raw_page": "sha 不同", "extra": "仅记录有"}
