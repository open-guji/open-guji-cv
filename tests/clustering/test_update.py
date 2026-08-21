"""run_update（M7）与 bench 报告的集成测试。"""

import json

from open_guji_cv.clustering.feedback import (append_event, derive_truth,
                                              replay_events, run_update)
from open_guji_cv.clustering.glyph_library import GlyphLibrary
from open_guji_cv.clustering.review.state import ReviewSession


def test_derive_truth():
    state = replay_events([
        {"op": "confirm", "cluster": "c1", "char": "通"},
        {"op": "relabel", "instance": "i2", "char": "遇"},
        {"op": "split", "cluster": "c1", "moved": ["i3"]},
    ])
    truth = derive_truth(state, {"c1": ["i1", "i2", "i3"]})
    assert truth["i1"] == "通"
    assert truth["i2"] == "遇"     # 改判覆盖簇标签
    assert "i3" not in truth       # 被移出


def test_run_update_full_cycle(synth_book, tmp_path):
    """确认若干簇 → update：字形库入库 + 标定 + 用字习惯 + 语料。"""
    store = tmp_path / "glyph_store"
    session = ReviewSession(synth_book)

    # 用 phase3 text 弱先验作"人工"标签：给最大的 4 个簇确认
    big = sorted(session.clusters.values(), key=lambda c: -c["size"])[:4]
    for c in big:
        inst = session.instances[c["members"][0]]
        session.post_event({"op": "confirm", "cluster": c["cluster_id"],
                            "char": inst.ocr_text})

    summary = run_update(synth_book, store, edition_tag="ed1")
    assert summary["labeled_instances"] >= sum(c["size"] for c in big)
    assert summary["glyphs_added"] >= 1
    assert "calibration" in summary

    # 字形库可检索且带 edition_tag
    lib = GlyphLibrary(store)
    assert len(lib) == summary["glyphs_added"]
    assert all(e.edition_tag == "ed1" for e in lib.entries)

    # 标定文件存在且满足纯度约束字段
    calib = json.loads((store / "calib" / "thresholds.json")
                       .read_text(encoding="utf-8"))
    assert 0.0 < calib["theta_high"] <= 1.0

    # variant_prefs 文件存在
    assert (store / "lm" / "variant_prefs" / "ed1.json").exists()


def test_run_update_dedup(synth_book, tmp_path):
    """重复 update：同字同版字形不重复入库。"""
    store = tmp_path / "glyph_store"
    run_update(synth_book, store, edition_tag="ed1", calibrate=False)
    n1 = len(GlyphLibrary(store))
    summary2 = run_update(synth_book, store, edition_tag="ed1",
                          calibrate=False)
    assert summary2["glyphs_added"] == 0
    assert summary2["glyphs_skipped_dup"] >= 1
    assert len(GlyphLibrary(store)) == n1


def test_corpus_export_only_full_columns(synth_book, tmp_path):
    """语料导出：只导出全列已确认的列。"""
    store = tmp_path / "glyph_store"
    # synth_book 的事件在前面测试中已确认了部分簇（module 级 fixture 共享）
    summary = run_update(synth_book, store, calibrate=False)
    corpus = (store / "lm" / "corpus_confirmed" /
              f"{synth_book.name}.txt").read_text(encoding="utf-8")
    lines = [l for l in corpus.split("\n") if l]
    assert len(lines) == summary["corpus_columns"]
    for line in lines:
        assert len(line) == 6    # 每列 6 字，全部已确认


def test_bench_reports(tmp_path):
    from open_guji_cv.clustering.bench import (bench_cluster, bench_verify,
                                               write_report)
    rv = bench_verify(n_chars=6, n_per_char=3, wear=0.4)
    assert rv["metrics"]["false_same"] == 0        # 硬指标
    assert rv["metrics"]["same_recall"] > 0.5
    rc = bench_cluster(n_chars=8, n_per_char=4, wear=0.4, feature="raw")
    assert rc["metrics"]["purity"] >= 0.999        # 硬指标
    path = write_report(rc, tmp_path / "results")
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8"))["module"] == "cluster"


def test_impure_flag_feeds_hard_negatives(synth_book, tmp_path):
    """impure 簇标记 → 簇内成员对进入标定的难负样本（不被采样截断）。"""
    import json
    from open_guji_cv.clustering.feedback import append_event, run_update
    from open_guji_cv.clustering.review.state import ReviewSession

    s = ReviewSession(synth_book)
    multi = [c for c in s.clusters.values() if c["size"] >= 2]
    if not multi:
        pytest.skip("合成书没有多成员簇")
    big = max(multi, key=lambda c: c["size"])
    labels = s.labels_path
    # 至少要有确认标签，标定才会启动（same 对来源）
    for cid, ch in [(c["cluster_id"], ch) for c, ch in
                    zip(sorted(s.clusters.values(),
                               key=lambda c: -c["size"])[:3], "甲乙丙")]:
        append_event(labels, {"op": "confirm", "cluster": cid, "char": ch})
    append_event(labels, {"op": "flag", "cluster": big["cluster_id"],
                          "flag": "impure"})
    summary = run_update(synth_book, tmp_path / "store")
    n = big["size"]
    assert summary["hard_diff_pairs"] == n * (n - 1) // 2


def test_remap_requires_quorum():
    """重绑法定人数：得票不足原成员半数 → 保留原簇号（事件失效）。"""
    from open_guji_cv.clustering.feedback import remap_events
    ev = {"op": "flag", "cluster": "cOLD", "flag": "impure",
          "members": ["a", "b", "c", "d", "e", "f"]}
    # 6 成员只有 2 个还在，且都落在大簇 cBIG → 不足半数，拒绑
    out, n = remap_events([ev], {"a": "cBIG", "b": "cBIG"})
    assert n == 0 and out[0]["cluster"] == "cOLD"
    # 4/6 落在同簇 → 过半，重绑
    out, n = remap_events([ev], {m: "cNEW" for m in "abcd"})
    assert n == 1 and out[0]["cluster"] == "cNEW"
