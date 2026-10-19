"""中心库导入的纯逻辑：文件归属、逐行解析、差分（不连数据库）。数据全部在测试里造。"""

from __future__ import annotations

import json

from open_guji_cv.datastore.importer import diff
from open_guji_cv.datastore.scope import (
    classify,
    file_kind,
    r2_key,
    scan_files,
    sha256,
    split_lines,
)


def _line(**kw) -> str:
    return json.dumps(kw, ensure_ascii=False, sort_keys=True)


def _ws(extra: dict[str, bytes]) -> list[tuple[str, object]]:
    files = {"workspace.yaml": b"id: tws\n", **extra}
    return [(k, (lambda v=v: v)) for k, v in files.items()]


def test_classify_routes_files_to_tables():
    assert classify("workspace.yaml") == "workspaces"
    assert classify("books/vol01.yaml") == "books"
    assert classify("feedback/events/a.jsonl") == "events"
    assert classify("feedback/vision/a.jsonl") == "events"
    assert classify("feedback/consumed/glyphdb_admit.jsonl") == "consumed"
    assert classify("feedback/anchors/vol02.jsonl") == "anchors"
    assert classify("feedback/anchor_patches/vol02/x.png") == "anchor_patches_meta"
    assert classify("feedback/verdicts/page-type/items.jsonl") == "verdicts"
    assert classify("feedback/lists/x.txt") == "files"
    assert classify("review/batches/b.json") == "files"
    assert classify("config/crop_exclusions.jsonl") == "files"
    assert classify("config/corpus-pack/v1/manifest.json") == "files"
    assert classify("corpus/zongmu_wenyuange_wikisource.txt") == "corpus_files"
    assert classify("corpus/daizhige/0001.jsonl") == "corpus_files"
    assert classify("corpus-pack/v1/manifest.json") is None        # 旧位置不进库，migrate 补迁到 config/
    assert classify("corpus/daizhige/columns.jsonl") is None           # 可重生成的大文件不进库
    assert classify("output/glyph_store/glyphs.jsonl") == "glyphs"
    assert classify("output/glyph_store/instances/v2.jsonl") == "glyph_instances"
    assert classify("output/glyph_store/patches/v2_a_1_2.png") == "patch"
    assert classify("output/glyph_store/events/v2.jsonl") == "glyph_events"
    assert classify("output/glyph_store/_snapshot.json") == "files"
    assert file_kind("feedback/lists/x.txt") == "list"
    assert file_kind("review/batches/b.json") == "batch"


def test_classify_skips_backups_and_products():
    assert classify("feedback/verdicts.bak-20260918-110344/page-type/items.jsonl") is None
    assert classify("feedback/consumed_bak_20260904/a.jsonl") is None
    assert classify("feedback/_backup_20260916/a.jsonl") is None
    assert classify("feedback/events/.gitkeep") is None
    assert classify("data_full/zongmu/vol01/1.png") is None
    assert classify("output/vol01/x.json") is None


def test_split_lines_keeps_final_newline_flag():
    assert split_lines(b"") == ([], False)
    assert split_lines(b"a\nb\n") == (["a", "b"], True)
    assert split_lines(b"a\nb") == (["a", "b"], False)
    assert split_lines("甲\r\n".encode()) == (["甲\r"], True)


def test_scan_builds_rows_with_patch_sha_and_problems():
    png = b"\x89PNG fake"
    ev1 = _line(id="evt_a_1", batch="a", seq=1, kind="confirm", actor="user",
                payload={"v": "師"}, target={"book": "vol03", "key": "vol03:1:1:1"}, ts="t")
    inst = _line(instance_id="v2:vol03:1:1:1", source_id="v2", page="1", col=1, idx=1,
                 label="師", updated_at="t")
    inst_nopng = _line(instance_id="v2:vol03:1:1:2", source_id="v2", page="1", col=1, idx=2,
                       updated_at="t")
    res = scan_files(_ws({
        "feedback/events/a.jsonl": (ev1 + "\n").encode(),
        "feedback/events/b.jsonl": (ev1 + "\n").encode(),       # 同 id 在两个文件里
        "feedback/consumed/c.jsonl": ((_line(event="evt_a_1", ts="t", note="n") + "\n") * 2
                                      ).encode(),
        "output/glyph_store/instances/v2.jsonl": (inst + "\n" + inst_nopng + "\n").encode(),
        "output/glyph_store/patches/v2_vol03_1_1_1.png": png,
        "output/glyph_store/patches/orphan.png": b"x",
        "feedback/verdicts.bak-1/x.jsonl": b"{}\n",
    }), "dir-tws")
    assert res.ws == "tws"
    by = {}
    for r in res.rows:
        by.setdefault(r.tbl, []).append(r)
    assert len(by["events"]) == 2
    assert {r.key for r in by["events"]} == {("feedback/events/a.jsonl", "evt_a_1"),
                                            ("feedback/events/b.jsonl", "evt_a_1")}
    assert by["events"][0].cols["book"] == "vol03"
    # 整行重复的台账两行都留，主键是行号
    assert [r.key for r in by["consumed"]] == [("c", 0), ("c", 1)]
    insts = {r.key[0]: r for r in by["glyph_instances"]}
    assert insts["v2:vol03:1:1:1"].cols["patch_sha"] == sha256(png)
    assert insts["v2:vol03:1:1:2"].cols["patch_sha"] is None
    text = "\n".join(res.problems)
    assert "不止一个文件" in text and "没有刻例图" in text and "orphan.png" in text
    assert "feedback/verdicts.bak-1/x.jsonl" in res.skipped
    files = {r.key[0]: r for r in by["source_files"]}
    assert files["feedback/consumed/c.jsonl"].cols["n_lines"] == 2


def test_diff_is_idempotent_and_classifies_changes():
    rows = scan_files(_ws({
        "output/glyph_store/glyphs.jsonl": (
            _line(edition_tag="e", char="師", status="sparse", n_confirmed=1, updated_at="t") + "\n"
            + _line(edition_tag="e", char="所", status="sparse", n_confirmed=1, updated_at="t")
            + "\n").encode()}), "d").rows
    glyphs = [r for r in rows if r.tbl == "glyphs"]
    existing = {r.key: (sha256(r.raw.encode()), r.src_line) for r in glyphs}
    assert diff(glyphs, existing).n_changes == 0

    # 改一行、删一行、加一行、另一行只是挪了位置
    new = scan_files(_ws({
        "output/glyph_store/glyphs.jsonl": (
            _line(edition_tag="e", char="別", status="sparse", n_confirmed=1, updated_at="t") + "\n"
            + _line(edition_tag="e", char="師", status="stable", n_confirmed=3, updated_at="u")
            + "\n").encode()}), "d").rows
    plan = diff([r for r in new if r.tbl == "glyphs"], existing)
    assert [r.key for r in plan.inserts] == [("e", "別")]
    assert [r.key for r in plan.updates] == [("e", "師")]
    assert plan.deletes == [("e", "所")]
    assert plan.moves == []
    assert plan.n_changes == 3

    moved = scan_files(_ws({
        "output/glyph_store/glyphs.jsonl": (
            "\n" + glyphs[0].raw + "\n" + glyphs[1].raw + "\n").encode()}), "d").rows
    plan = diff([r for r in moved if r.tbl == "glyphs"], existing)
    assert plan.n_changes == 0 and len(plan.moves) == 2


def test_r2_key_is_content_addressed():
    s = sha256(b"x")
    assert r2_key(s) == f"sha256/{s[:2]}/{s}.png"
