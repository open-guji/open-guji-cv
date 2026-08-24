"""对勘复审页：分类口径、批次装配、渲染契约、与种子页共用持久化核心。"""

import json

import pytest

from open_guji_cv.clustering.review.collation_export import (
    KIND_LABELS, KIND_ORDER, build_collation_batch, classify,
    render_collation_html)
from open_guji_cv.clustering.seed_queue import SeedItem
from open_guji_cv.clustering.variants import VariantMap

VM = VariantMap({"珎": "珍"})


def _it(**kw):
    base = dict(instance_id="tb:1:1:0", book="tb", page="1", col=1, idx=0,
                patch_path="p.png", tier="clean", status="confirmed")
    base.update(kw)
    return SeedItem(**base)


def test_classify_four_kinds_and_same():
    ctx = {"ref_char": "文", "ref_op": "equal", "col_ref": "文", "pos": 0}
    assert classify(_it(decided_char="文", context=ctx), VM) is None
    assert classify(_it(decided_char="又", context=ctx), VM) == "substitution"
    # 异体：正规化后同字
    v = {"ref_char": "珍", "col_ref": "珍", "pos": 0}
    assert classify(_it(decided_char="珎", context=v), VM) == "variant"
    # 添字：整理本此位无字
    assert classify(_it(decided_char="文", context={"col_ref": "·"}),
                    VM) == "insertion"
    # 删字：整理本有字而判非字
    assert classify(_it(status="not_a_char", context=ctx), VM) == "deletion"
    # 判非字且整理本也无字 → 不是差异
    assert classify(_it(status="not_a_char", context={}), VM) is None


def test_classify_uses_gated_align_first():
    """过闸对齐字优先于免闸参考——两者不一致时以过闸的为准。"""
    it = _it(decided_char="文", align={"char": "文", "op": "equal"},
             context={"ref_char": "又"})
    assert classify(it, VM) is None


def test_pending_slots_are_not_classified():
    assert classify(_it(status="pending_review", decided_char=None,
                        context={"ref_char": "文"}), VM) is None


@pytest.fixture
def book(tmp_path):
    """两页：第 1 页锚定（含各类差异），第 2 页无语料（整页应被排除）。"""
    import cv2
    import numpy as np
    root = tmp_path / "tb" / "phase4_chars"
    (root / "patches").mkdir(parents=True)
    img = np.full((40, 40), 240, np.uint8)
    img[10:30, 10:30] = 30
    cv2.imwrite(str(root / "patches" / "a.png"), img)

    rows = [
        # 第 1 页：同 / 改字 / 异体 / 添字 / 删字
        _it(instance_id="tb:1:1:0", idx=0, decided_char="天",
            patch_path="patches/a.png",
            context={"ref_char": "天", "col_ref": "天地珍玄", "pos": 0}),
        _it(instance_id="tb:1:1:1", idx=1, decided_char="言",
            patch_path="patches/a.png",
            context={"ref_char": "地", "col_ref": "天地珍玄", "pos": 1}),
        _it(instance_id="tb:1:1:2", idx=2, decided_char="珎",
            patch_path="patches/a.png", status="confirmed_label_only",
            context={"ref_char": "珍", "col_ref": "天地珍玄", "pos": 2}),
        _it(instance_id="tb:1:1:3", idx=3, decided_char="衍",
            patch_path="patches/a.png",
            context={"col_ref": "天地珍玄", "pos": 3}),
        _it(instance_id="tb:1:1:4", idx=4, status="not_a_char",
            patch_path="patches/a.png",
            context={"ref_char": "玄", "col_ref": "天地珍玄", "pos": 3}),
        # 第 2 页：整页无 ref_char → 不该出现在批次里
        _it(instance_id="tb:2:1:0", page="2", idx=0, decided_char="孤",
            patch_path="patches/a.png", context={}),
    ]
    q = tmp_path / "tb" / "phase9_seed"
    q.mkdir(parents=True)
    (q / "queue.jsonl").write_text(
        "".join(r.to_json() + "\n" for r in rows), encoding="utf-8")
    return tmp_path / "tb", q / "queue.jsonl"


def test_batch_counts_and_excludes_unanchored_page(book, tmp_path):
    book_dir, queue = book
    b = build_collation_batch(book_dir, queue,
                              variants=_variants_file(tmp_path))
    assert b["counts"] == {"substitution": 1, "variant": 1,
                           "insertion": 1, "deletion": 1}
    assert b["n_same"] == 1
    assert b["anchored_pages"] == ["1"]
    # 未锚定页整页排除：那不是「差异」，是没得比
    assert all(e["page"] == "1" for e in b["entries"])
    assert "tb:2:1:0" not in {e["instance_id"] for e in b["entries"]}


def _variants_file(tmp_path):
    p = tmp_path / "variants.tsv"
    p.write_text("珎\t珍\n", encoding="utf-8")
    return p


def test_entries_carry_review_context(book, tmp_path):
    book_dir, queue = book
    b = build_collation_batch(book_dir, queue,
                              variants=_variants_file(tmp_path))
    e = next(x for x in b["entries"] if x["kind"] == "substitution")
    assert e["mine"] == "言" and e["ref"] == "地"
    assert e["page"] == "1" and e["col"] == 1 and e["idx"] == 1
    assert e["patch"] and e["strip"]          # 原图 + 整列条图都在
    assert e["col_ref"] == "天地珍玄" and e["pos"] == 1
    lo = next(x for x in b["entries"] if x["kind"] == "variant")
    assert lo["label_only"] is True


def test_kinds_filter_keeps_counts_but_trims_entries(book, tmp_path):
    book_dir, queue = book
    b = build_collation_batch(book_dir, queue, kinds=("substitution",),
                              variants=_variants_file(tmp_path))
    assert b["counts"]["variant"] == 1          # 统计仍是全量
    assert [e["kind"] for e in b["entries"]] == ["substitution"]


def test_render_is_self_contained_and_printable(book, tmp_path):
    book_dir, queue = book
    b = build_collation_batch(book_dir, queue,
                              variants=_variants_file(tmp_path))
    html = render_collation_html(b)
    assert "<title>tb 对勘复审</title>" in html
    assert "data:image/png;base64," in html      # 图内嵌，不外链
    assert "@media print" in html                # 可打印成 PDF
    assert 'id="guji-log"' in html
    assert "换回整理本" in html and "手输正字" in html and "不入库" in html
    for k in KIND_ORDER:
        if b["counts"].get(k):
            assert KIND_LABELS[k] in html
    # 事件协议与种子页同源 → seed-ingest 能直接回收
    assert "GUJI-SEED-EVENT" in html


def test_persist_core_shared_with_seed_page():
    """两个审查页必须用同一份持久化核心（改一处漏一处是真实风险）。"""
    from open_guji_cv.clustering.review import collation_export, seed_export
    from open_guji_cv.clustering.review.persist_js import PERSIST_JS
    assert PERSIST_JS in seed_export._JS
    assert PERSIST_JS in collation_export._JS
