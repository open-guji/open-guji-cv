# -*- coding: utf-8 -*-
"""收尾步 seed_admit→char_decide 改名的兼容读口（CV4 P3a-1，2026-11-28）：
页键、ask／vis_ctx 位置不变，新旧事件名查询结果相同，参数新旧键并认（并存报错），迁移命令只改名不删。"""
import json
from pathlib import Path

import pytest

from open_guji_cv.core import decide_names as dn
from open_guji_cv.core.pipeline import rehome_params
from open_guji_cv.core.page_kinds import kinds_from_params, merge_into_params
from open_guji_cv.feedback.decide_events import decided_view, invalidate_final, ruling_by_u
from open_guji_cv.feedback.events import EventTarget, make_event
from open_guji_cv.feedback.pending_cells import machine_pending, pending_cells
from open_guji_cv.products.final_read import read_final_store
from open_guji_cv.products.kinds.recog import AdmitRec, ColumnAdmit, PageAdmit
from open_guji_cv.products.manifest import ManifestEntry
from open_guji_cv.products.migrate_final import ARCHIVE_NAME, migrate, plan
from open_guji_cv.products.store import ProductStore

BOOK = "vol01"


def _page(page=1) -> PageAdmit:
    ev = {"ask": {"group": "日曰", "left": "子", "right": "云"}, "vis_ctx": {"v": 1, "cand": ["曰"]}}
    return PageAdmit(page=page, n_auto=1, n_review=1, columns=[ColumnAdmit(col=1, chars=[
        AdmitRec(id=f"{BOOK}:{page}:1:1", slot=1, admit=True, char="曰", channel="match_ref", provenance="match", evidence=ev),
        AdmitRec(id=f"{BOOK}:{page}:1:2", slot=2, admit=False, doubts=["abstain:group"], evidence=ev)])])


def _write_old(root: Path, pages=(1, 2)) -> ProductStore:
    st = ProductStore(root)
    for p in pages:
        _, sha = st.write(BOOK, "seed_admit", f"p{p:04d}", {"seed_admit": _page(p)})
        st.manifest(BOOK, "seed_admit").put(ManifestEntry(key=f"p{p:04d}", fingerprint=f"fp{p}", sha256=sha, params_hash="ph",
                                                          upstream={"glyph_match": "g"}))
    return st


# ── 常量与参数 ────────────────────────────────────────────────────────

def test_names_and_helpers():
    assert dn.ADMIT_STEPS == ("char_decide", "seed_admit") and dn.LEGACY_ADMIT_STEP == "seed_admit"
    assert dn.is_admit_step("seed_admit") and dn.is_admit_step("char_decide") and not dn.is_admit_step("align_ref")
    assert dn.same_admit_step("seed_admit", "char_decide") and not dn.same_admit_step("seed_admit", "align_ref")
    assert dn.canonical_step("seed_admit") == "char_decide" and dn.canonical_step("align_ref") == "align_ref"


def test_fold_params_identity_rename_and_conflict():
    only_old = {"seed_admit": {"x": 1}, "row_segment": {"y": 2}}
    assert dn.fold_admit_params(only_old) == {"char_decide": {"x": 1}, "row_segment": {"y": 2}}   # 旧键写的：并成生效名 char_decide（改名版）
    only_new = {"char_decide": {"x": 1}, "row_segment": {"y": 2}}
    assert dn.fold_admit_params(only_new) is only_new                      # 已是生效名：原对象零影响
    with pytest.raises(ValueError, match="同时写"):
        dn.fold_admit_params({"char_decide": {}, "seed_admit": {}})
    assert dn.admit_params_of({"char_decide": {"x": 1}}) == {"x": 1} and dn.admit_params_of({"seed_admit": {"x": 2}}) == {"x": 2}
    assert dn.admit_params_of({}) is None and dn.fold_admit_params(None) is None


def test_fold_params_follows_active_name(monkeypatch):
    monkeypatch.setattr(dn, "ADMIT_STEP_ACTIVE", "char_decide")           # 改名那一版：只翻这一个常量
    assert dn.fold_admit_params({"seed_admit": {"x": 1}}) == {"char_decide": {"x": 1}}
    assert dn.fold_admit_params({"char_decide": {"x": 1}}) == {"char_decide": {"x": 1}}


def test_params_funnels_accept_both_keys():
    assert rehome_params({"seed_admit": {"use_context": False}}) == {"char_decide": {"use_context": False}}
    assert rehome_params({"char_decide": {"use_context": False}}) == {"char_decide": {"use_context": False}}
    with pytest.raises(ValueError):
        rehome_params({"char_decide": {"a": 1}, "seed_admit": {"b": 2}})
    # 页型表（no_ref_pages）：新键写的也读得出
    assert kinds_from_params({"char_decide": {"no_ref_pages": [3, 4]}}) == {"no_ref": [3, 4]}
    out = merge_into_params({"char_decide": {"no_ref_pages": [3]}}, {"no_ref": [3]})
    assert out["char_decide"]["no_ref_pages"] == [3]


def test_book_params_loader_folds():
    from open_guji_cv.core.book import _load_book_params
    assert _load_book_params({"char_decide": {"a": 1}}) == {"char_decide": {"a": 1}}
    assert _load_book_params({"seed_admit": {"a": 1}}) == {"char_decide": {"a": 1}}
    with pytest.raises(ValueError):
        _load_book_params({"char_decide": {"a": 1}, "seed_admit": {"a": 1}})


# ── 产物读口：页键、ask／vis_ctx 位置不变 ────────────────────────────

def test_final_page_dict_prefers_new_key():
    assert dn.final_page_dict({"seed_admit": {"p": 1}}) == {"p": 1}
    assert dn.final_page_dict({"char_decide": {"p": 2}}) == {"p": 2}
    assert dn.final_page_dict({"char_decide": {"p": 2}, "seed_admit": {"p": 1}}) == {"p": 2}
    with pytest.raises(KeyError):
        dn.final_page_dict({"other": {}})
    inner = {"columns": []}
    assert dn.final_page_dict(inner, strict=False) is inner


def test_read_final_old_and_new_layout_same_content(tmp_path):
    st = _write_old(tmp_path / "old")
    old = read_final_store(st, BOOK, "p0001")
    # 手工造一份新名布局：目录 char_decide、页键 char_decide、内层逐字相同
    new_root = tmp_path / "new"
    (new_root / BOOK / "char_decide").mkdir(parents=True)
    raw = json.loads((tmp_path / "old" / BOOK / "seed_admit" / "p0001.json").read_text(encoding="utf-8"))
    (new_root / BOOK / "char_decide" / "p0001.json").write_text(json.dumps({"char_decide": raw["seed_admit"]}), encoding="utf-8")
    new = read_final_store(ProductStore(new_root), BOOK, "p0001")
    assert old is not None and old.model_dump() == new.model_dump()
    for obj in (old, new):                                                # ask／vis_ctx／doubts 的位置与含义不变
        ch = obj.columns[0].chars
        assert ch[0].evidence["ask"]["group"] == "日曰" and ch[0].evidence["vis_ctx"]["cand"] == ["曰"]
        assert ch[1].doubts == ["abstain:group"] and obj.n_review == 1
    assert read_final_store(st, BOOK, "p0099") is None


def test_both_dirs_new_wins_and_warn_helper(tmp_path):
    st = _write_old(tmp_path)
    d_new = tmp_path / BOOK / "char_decide"
    d_new.mkdir()
    p = _page(1)
    p.n_auto = 77
    (d_new / "p0001.json").write_text(json.dumps({"char_decide": p.model_dump(mode="json")}), encoding="utf-8")
    assert read_final_store(st, BOOK, "p0001").n_auto == 77               # 并存：新目录为准
    assert read_final_store(st, BOOK, "p0002").n_auto == 1                # 新目录没有的页：旧目录兜底
    assert dn.both_dirs_exist(tmp_path, BOOK) and dn.final_dir(tmp_path, BOOK) == d_new


def test_pending_cells_reads_both_dirs_and_has_reason_fields(tmp_path):
    _write_old(tmp_path)
    cells, n_review, every = machine_pending(tmp_path, BOOK)
    assert [c["cell"] for c in cells] == ["1:1:2", "2:1:2"] and n_review == 2
    for c in cells:                                                       # 值本版一律 None，字段在（P3a-1）
        assert c["pending_reason"] is None and c["pending_reason_detail"] is None and c["form_src"] is None
    (tmp_path / BOOK / "seed_admit").rename(tmp_path / BOOK / "char_decide")
    for f in (tmp_path / BOOK / "char_decide").glob("p*.json"):           # 页键也换新名
        f.write_text(json.dumps({"char_decide": json.loads(f.read_text(encoding="utf-8"))["seed_admit"]}), encoding="utf-8")
    cells2, n2, every2 = machine_pending(tmp_path, BOOK)
    assert cells2 == cells and n2 == n_review and every2 == every


# ── 事件读口：新旧事件名查询结果相同 ─────────────────────────────────

def _ev(batch, seq, step, cell, ts, u=None, v="a"):
    return make_event(batch, seq, "confirm", EventTarget(step=step, unit="cell", key=cell, book=BOOK), {"v": v, **({"u": u} if u else {})}, ts=ts)


def test_event_queries_same_for_old_and_new_step_name():
    old = [_ev("b1", 1, "seed_admit", f"{BOOK}:1:1:1", "2026-11-01T00:00:00", u=5, v="x"),
           _ev("b1", 2, "seed_admit", f"{BOOK}:1:1:2", "2026-11-01T00:00:01", v="y")]
    new = [_ev("b1", 1, "char_decide", f"{BOOK}:1:1:1", "2026-11-01T00:00:00", u=5, v="x"),
           _ev("b1", 2, "char_decide", f"{BOOK}:1:1:2", "2026-11-01T00:00:01", v="y")]
    flat = lambda d: {k: (e.payload, e.ts) for k, e in d.items()}
    assert flat(decided_view(old)) == flat(decided_view(new)) and len(decided_view(old)) == 2
    assert flat(ruling_by_u(old)) == flat(ruling_by_u(new)) == flat(ruling_by_u(old + new)) and (BOOK, 5) in ruling_by_u(old)


def test_later_wins_across_names_both_directions():
    cell = f"{BOOK}:1:1:1"
    a = _ev("b1", 1, "seed_admit", cell, "2026-11-01T00:00:00", v="old")
    b = _ev("b2", 1, "char_decide", cell, "2026-11-02T00:00:00", v="new")
    assert decided_view([a, b])[cell].payload["v"] == "new"                # 后到的新名盖旧名
    assert decided_view([b, a])[cell].payload["v"] == "new"                # 与到达顺序无关，按 ts
    c = _ev("b3", 1, "seed_admit", cell, "2026-11-03T00:00:00", v="newest")
    assert decided_view([a, b, c])[cell].payload["v"] == "newest"          # 后到的旧名也盖新名
    other = _ev("b4", 1, "align_ref", cell, "2026-11-09T00:00:00", v="zzz")
    assert decided_view([a, b, other])[cell].payload["v"] == "new"         # 别的步的事件不混进来


def test_invalidate_hits_both_dirs(tmp_path):
    st = _write_old(tmp_path)
    st.manifest(BOOK, "char_decide").put(ManifestEntry(key="p0001", fingerprint="f", sha256="s"))
    assert invalidate_final(st, BOOK, "p0001", "人裁") == ["char_decide", "seed_admit"]
    assert st.manifest(BOOK, "seed_admit").get("p0001").invalidated and st.manifest(BOOK, "char_decide").get("p0001").invalidated
    assert invalidate_final(st, BOOK, "p0009", "x") == []                  # 没产物的页：没什么可失效


# ── 迁移命令 ──────────────────────────────────────────────────────────

def test_migrate_renames_without_deleting_and_archives_sha(tmp_path):
    st = _write_old(tmp_path)
    # 下游一步，upstream 里挂着 seed_admit
    st.manifest(BOOK, "decide_gate").put(ManifestEntry(key="p0001", fingerprint="gfp", sha256="gs",
                                                       upstream={"seed_admit": st.sha(BOOK, "seed_admit", "p0001")}))
    before = {p.name: p.read_bytes() for p in (tmp_path / BOOK / "seed_admit").glob("p*.json")}
    assert plan(tmp_path, BOOK)["state"] == "ready" and plan(tmp_path, BOOK)["downstream"] == ["decide_gate"]
    assert migrate(tmp_path, BOOK, dry_run=True)["state"] == "ready" and (tmp_path / BOOK / "seed_admit").is_dir()   # dry-run 不动

    seen = []
    def convert(step_id, key, e):
        seen.append((step_id, key))
        return {"fingerprint": f"new-{step_id}-{key}"}
    rep = migrate(tmp_path, BOOK, convert=convert)
    assert rep["state"] == "migrated" and rep["pages"] == 2 and rep["pages_changed"] == 2 and rep["fingerprint_converted"] == 2
    assert not (tmp_path / BOOK / "seed_admit").exists() and (tmp_path / BOOK / "char_decide").is_dir()
    for name, raw in before.items():                                      # 只改了顶层键，内层逐字不动
        now = json.loads((tmp_path / BOOK / "char_decide" / name).read_text(encoding="utf-8"))
        assert list(now) == ["char_decide"] and now["char_decide"] == json.loads(raw)["seed_admit"]
    st2 = ProductStore(tmp_path)
    m = st2.manifest(BOOK, "char_decide").get("p0001")
    assert m.fingerprint == "new-char_decide-p0001" and m.sha256 == st2.sha(BOOK, "char_decide", "p0001")   # 指纹换算、sha 换成新文件的
    assert (tmp_path / BOOK / "char_decide" / "_manifest.jsonl.pre-rename").exists()                       # 原 manifest 留一份
    g = st2.manifest(BOOK, "decide_gate").get("p0001")
    assert list(g.upstream) == ["char_decide"] and g.upstream["char_decide"] == m.sha256 and g.fingerprint == "new-decide_gate-p0001"
    arch = json.loads((tmp_path / BOOK / ARCHIVE_NAME).read_text(encoding="utf-8"))
    assert set(arch["sha_before"]) == {"p0001.json", "p0002.json", "_manifest.jsonl"}                      # 清单记全：页＋manifest
    assert set(arch["sha_after"]) == set(arch["sha_before"])
    assert arch["sha_before"]["p0001.json"] != arch["sha_after"]["p0001.json"]                             # 键名变了，sha 清单记两头
    assert read_final_store(st2, BOOK, "p0001").model_dump() == _page(1).model_dump()                      # 读口照读
    assert plan(tmp_path, BOOK)["state"] == "done" and migrate(tmp_path, BOOK)["state"] == "done"          # 幂等


def test_migrate_refuses_when_both_dirs_have_pages(tmp_path):
    _write_old(tmp_path)
    d = tmp_path / BOOK / "char_decide"
    d.mkdir()
    (d / "p0001.json").write_text(json.dumps({"char_decide": {}}), encoding="utf-8")
    with pytest.raises(RuntimeError, match="并存"):
        migrate(tmp_path, BOOK)
    assert (tmp_path / BOOK / "seed_admit" / "p0001.json").exists()


def test_migrate_name_command_registered_and_step_renamed():
    from open_guji_cv import cli_v2
    assert "migrate-name" in cli_v2.COMMANDS_V2 and "migrate-name" in cli_v2.STAGE_COMMANDS["decide"]
    from open_guji_cv.core.step import STEPS
    import open_guji_cv.steps  # noqa: F401
    assert "char_decide" in STEPS and list(STEPS).count("seed_admit") == 0   # 改名版：Step 叫 char_decide
    assert "seed_admit" in STEPS and STEPS["seed_admit"] is STEPS["char_decide"]   # 旧名按键仍查得到（过渡期）


def test_step_import_shim_is_same_class():
    from open_guji_cv.steps import char_decide, seed_admit
    assert char_decide.CharDecideStep is seed_admit.SeedAdmitStep and char_decide.CharDecideParams is seed_admit.SeedAdmitParams
