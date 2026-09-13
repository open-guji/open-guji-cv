# -*- coding: utf-8 -*-
"""P2 金标层：四种旧载体适配器、分片枚举、迁移、冲突处理。

真实数据集在隔壁仓，缺了就跳过；合成用例覆盖每种载体的形态分支，
尤其是**报告式** expected.json（阈值 + 嵌套条目）——第一版就是在这里把阈值名
当成了条目 id。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from open_guji_cv.gold.adapters import detect, load_shard
from open_guji_cv.gold.adapters.base import Adapter
from open_guji_cv.gold.store import GoldStore

REPO_ROOT = Path(__file__).resolve().parent.parent
DATASET = REPO_ROOT.parent / "open-guji-dataset"
needs_dataset = pytest.mark.skipif(not DATASET.exists(), reason="需要 open-guji-dataset")


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


# ── 载体识别 ─────────────────────────────────────────────────────────
def test_detect_carriers(tmp_path):
    a = tmp_path / "a"
    _write(a / "samples" / "001" / "expected.json", {"layout": "cut_half"})
    assert detect(a).name == "samples_dir"

    b = tmp_path / "b"
    _write(b / "expected.json", [{"book": "vol01", "page": 1, "quality": "clean"}])
    assert detect(b).name == "flat_expected"

    c = tmp_path / "c"
    (c).mkdir()
    (c / "verdicts_r1.jsonl").write_text('{"id":"x","verdict":"ok","t":1}\n', encoding="utf-8")
    assert detect(c).name == "verdicts"

    d = tmp_path / "d"
    _write(d / "cases.json", {"cases": [{"id": "q1"}]})
    assert detect(d).name == "cases"

    # 已迁的不需要适配器
    e = tmp_path / "e"
    e.mkdir()
    (e / "items.jsonl").write_text("", encoding="utf-8")
    assert detect(e) is None


# ── samples_dir 的三种形态 ───────────────────────────────────────────
def test_samples_dir_numbered_and_flat(tmp_path):
    sh = tmp_path / "s"
    _write(sh / "samples" / "001" / "expected.json", {"layout": "cut_half", "lines_per_page": 9})
    _write(sh / "samples" / "001" / "info.json", {"source": "book1", "tags": ["bw"]})
    (sh / "samples" / "001" / "image.png").write_bytes(b"\x89PNG")
    items = load_shard(sh)[1]
    assert [i.id for i in items] == ["001"]
    assert items[0].expected["lines_per_page"] == 9
    assert items[0].input["info"]["source"] == "book1"
    assert items[0].input["images"] == ["image.png"]

    sh2 = tmp_path / "s2"
    _write(sh2 / "samples" / "vol01_11_c1.json",
           {"book": "vol01", "page": 11, "col": 1, "verdict": "clean", "label_origin": "human"})
    items = load_shard(sh2)[1]
    assert items[0].id == "vol01_11_c1"
    assert items[0].anchor.book == "vol01" and items[0].anchor.col == 1
    assert items[0].expected == {"verdict": "clean"}      # book/page/col 是锚点不是金标


def test_samples_dir_case_json_and_single_table(tmp_path):
    """cells 用 case.json；cell-truncation 的 samples/ 下只有一个汇总表。"""
    sh = tmp_path / "cells"
    _write(sh / "samples" / "001" / "case.json", {"n_components": 3})
    assert load_shard(sh)[1][0].expected == {"n_components": 3}

    sh2 = tmp_path / "trunc"
    _write(sh2 / "samples" / "edges.json",
           {"edges": [{"id": "vol02_109_col8_b0", "cut": True},
                      {"id": "vol02_109_col8_b1", "cut": False}]})
    items = load_shard(sh2)[1]
    assert [i.id for i in items] == ["vol02_109_col8_b0", "vol02_109_col8_b1"]


# ── flat_expected 的三种结构 ─────────────────────────────────────────
def test_flat_expected_array_and_object(tmp_path):
    sh = tmp_path / "arr"
    _write(sh / "expected.json", [{"book": "vol01", "page": 4, "col": 1, "idx": 3,
                                   "quality": "clean", "label_origin": "human",
                                   "stratum": "control", "stratum_weight": 0.1}])
    it = load_shard(sh)[1][0]
    assert it.id == "vol01:4:1:3"
    assert it.expected == {"quality": "clean"}
    assert it.stratum == "control" and it.stratum_weight == 0.1
    assert it.anchor.slot == 3

    sh2 = tmp_path / "obj"
    _write(sh2 / "expected.json", {"vol01:21:9:20": {"residue": 0.1}})
    assert load_shard(sh2)[1][0].id == "vol01:21:9:20"


def test_flat_expected_report_shaped(tmp_path):
    """报告式：阈值在顶层、条目在嵌套字段里。阈值名不许变成条目 id。"""
    sh = tmp_path / "seam"
    _write(sh / "expected.json", {
        "heavy_threshold": 0.7, "n_seams": 44627, "median": 0.0388,
        "pages": {"vol01/47": {"n_heavy": 3}, "vol01/87": {"n_heavy": 1}}})
    items = load_shard(sh)[1]
    assert sorted(i.id for i in items) == ["vol01/47", "vol01/87"]
    assert items[0].input["report_header"]["heavy_threshold"] == 0.7
    assert "heavy_threshold" not in {i.id for i in items}

    sh2 = tmp_path / "drop"
    _write(sh2 / "expected.json", {"cover": 0.5, "n_dropped": 2,
                                   "dropped": [["vol01", "33", 5, 297], ["vol01", "40", 2, 100]]})
    items = load_shard(sh2)[1]
    assert [i.id for i in items] == ["vol01:33:5:297", "vol01:40:2:100"]
    assert items[0].expected["row"] == ["vol01", "33", 5, 297]


def test_flat_expected_samples_jsonl(tmp_path):
    sh = tmp_path / "col"
    sh.mkdir()
    (sh / "samples.jsonl").write_text(
        '{"id":"col:vol01:9:1","layout":"rigid"}\n{"id":"col:vol01:9:2","layout":"elastic"}\n',
        encoding="utf-8")
    items = load_shard(sh)[1]
    assert [i.id for i in items] == ["col:vol01:9:1", "col:vol01:9:2"]


# ── verdicts / cases ─────────────────────────────────────────────────
def test_verdicts_later_round_wins_and_idk_uncertain(tmp_path):
    sh = tmp_path / "v"
    sh.mkdir()
    (sh / "verdicts_r1.jsonl").write_text(
        '{"id":"a","verdict":"ok","t":1}\n{"id":"b","verdict":"idk","t":2}\n', encoding="utf-8")
    (sh / "verdicts_r2.jsonl").write_text('{"id":"a","verdict":"miss","t":3}\n', encoding="utf-8")
    items = {i.id: i for i in load_shard(sh)[1]}
    assert items["a"].expected["verdict"] == "miss"        # 后一轮覆盖
    assert items["a"].input["round"] == "verdicts_r2"
    assert items["b"].status == "uncertain"                # idk 不进分类指标


def test_cases_joins_answer_key(tmp_path):
    sh = tmp_path / "cc"
    _write(sh / "cases.json", {"mask": "…", "cases": [{"id": "q1", "text": "题面"},
                                                      {"id": "q2", "text": "无答案"}]})
    _write(sh / "answer_key.json", {"q1": "會"})
    items = {i.id: i for i in load_shard(sh)[1]}
    assert items["q1"].expected == {"answer": "會"}
    assert items["q1"].input["case"]["text"] == "题面"
    assert items["q2"].status == "uncertain"               # 没答案的不进指标


# ── 文档字段不进 expected ────────────────────────────────────────────
def test_doc_fields_go_to_input_not_expected():
    meta, inp, exp = Adapter.split_meta({
        "book": "vol01", "coord_space": "一大段口径说明", "profile": {"x": 1},
        "verdict": "clean", "label_origin": "human"})
    assert exp == {"verdict": "clean"}
    assert "coord_space" in inp and "profile" in inp
    assert meta["label_origin"] == "human"


# ── 分片枚举 ─────────────────────────────────────────────────────────
def test_shards_skips_sample_subdirs(tmp_path):
    """samples/NNN 是分片内的样本，不是分片——曾经每个样本都冒充一个分片。"""
    root = tmp_path / "ds"
    _write(root / "book-profile" / "metadata.json", {"name": "book-profile"})
    _write(root / "book-profile" / "samples" / "001" / "expected.json", {"layout": "x"})
    _write(root / "book-profile" / "samples" / "002" / "expected.json", {"layout": "y"})
    store = GoldStore(root)
    assert store.shards() == ["book-profile"]
    assert len(store.list("book-profile")) == 2


# ── 迁移 ─────────────────────────────────────────────────────────────
def test_migrate_preserves_content_and_keeps_old_files(tmp_path):
    root = tmp_path / "ds"
    _write(root / "sh" / "expected.json",
           [{"book": "vol01", "page": 1, "col": 2, "idx": 3, "quality": "clean"}])
    store = GoldStore(root)
    before = {i.id: i.expected for i in store.list("sh")}

    dry = store.migrate("sh", dry_run=True)
    assert dry["n"] == 1 and not store.items_path("sh").exists()

    r = store.migrate("sh")
    assert r["n"] == 1 and r["carrier"] == "flat_expected"
    assert store.carrier("sh") == "items"
    assert {i.id: i.expected for i in store.list("sh")} == before
    assert (root / "sh" / "expected.json").exists()        # 旧文件不删
    assert store.migrate("sh")["skipped"]                   # 幂等


def test_migrate_flags_conflicting_duplicates(tmp_path):
    """同 id 内容冲突时保留后者、标 uncertain、记 history——不许静默丢。"""
    root = tmp_path / "ds"
    _write(root / "sh" / "expected.json", [
        {"book": "vol01", "page": 9, "col": 9, "idx": 20, "quality": "contaminated"},
        {"book": "vol01", "page": 9, "col": 9, "idx": 20, "quality": "not_text"},
        {"book": "vol01", "page": 1, "col": 1, "idx": 1, "quality": "clean"},
        {"book": "vol01", "page": 1, "col": 1, "idx": 1, "quality": "clean"},   # 相同重复，静默合并
    ])
    store = GoldStore(root)
    r = store.migrate("sh")
    assert r["n_source"] == 4 and r["n"] == 2
    assert r["conflicts"] == ["vol01:9:9:20"]
    it = store.get("sh", "vol01:9:9:20")
    assert it.status == "uncertain" and it.expected["quality"] == "not_text"
    assert any("conflict" in h.change for h in it.history)
    assert store.get("sh", "vol01:1:1:1").status == "active"


# ── 漂移检查 ─────────────────────────────────────────────────────────
def test_drift_keep_recheck_nofp_missing(tmp_path):
    """沿用 migrate_column_warp_gold 的指纹判据：平移容忍、内容变则重看、无指纹一律重看。"""
    import numpy as np
    from open_guji_cv.gold.drift import (COL_FP_SIZE, check_shard, fingerprint, fp_diff,
                                         mark_drifted)
    from open_guji_cv.gold.item import GoldItem

    # 用**结构化**的图（像真实列图：白底 + 若干墨块），不是随机噪声——
    # 指纹先缩到 24×96 再比，噪声图缩放后每个像素都独立随机，平移必然大幅变化，
    # 那测的是噪声不是判据。真实列图平移 1~3px 时指纹差 ≈0，这才是要容忍的场景。
    img = np.full((400, 120), 255, dtype=np.uint8)
    for y in range(20, 380, 40):
        img[y:y + 24, 30:90] = 20            # 一列字
    fp = fingerprint(img, COL_FP_SIZE)

    same = GoldItem(id="same", input={"column_fingerprint": fp})
    shifted = GoldItem(id="shifted", input={"column_fingerprint": fp})
    changed = GoldItem(id="changed", input={"column_fingerprint": fp})
    nofp = GoldItem(id="nofp")
    gone = GoldItem(id="gone", input={"column_fingerprint": fp})

    other = np.full((400, 120), 255, dtype=np.uint8)
    other[:, :] = 0                                   # 整幅变黑：内容真的变了
    imgs = {
        "same": img,
        "shifted": np.roll(img, 2, axis=1),           # 横向平移 2px：图其实没变
        "changed": other,
        "gone": None,
    }
    rep = check_shard("s", [same, shifted, changed, nofp, gone], lambda it: imgs.get(it.id))
    assert set(rep.keep) == {"same", "shifted"}      # 平移必须留用
    assert [i for i, _ in rep.recheck] == ["changed"]
    assert rep.nofp == ["nofp"] and rep.missing == ["gone"]
    assert fp_diff(fp, img, COL_FP_SIZE) == 0.0

    root = tmp_path / "ds"
    store = GoldStore(root)
    store.upsert("s", [same, shifted, changed, nofp, gone])
    assert mark_drifted(store, "s", rep) == 2        # changed + gone
    assert store.get("s", "changed").status == "stale"
    assert store.get("s", "same").status == "active"


# ── 真实数据集 ───────────────────────────────────────────────────────
@needs_dataset
def test_real_dataset_all_shards_readable():
    store = GoldStore(DATASET)
    shards = store.shards()
    assert len(shards) >= 30
    empty = []
    for sh in shards:
        items = store.list(sh)
        if not items:
            empty.append(sh)
        else:
            assert all(i.id for i in items), f"{sh} 有空 id"
    # truncation 是全自动统计型分片，本就没有条目级金标
    assert empty == ["char-segmentation/truncation"], empty


@needs_dataset
def test_real_migrated_shards_are_items():
    """已迁分片的条数与各自 README / metadata 记载对得上。"""
    store = GoldStore(DATASET)
    # ⚠️ 这些数字随上游扩金标、人裁回流而变，**不是常量**。改动时要说清
    # 增量从哪来：
    #   column-warp 114 → 115：main 那边新增 vol01_42_c9（Step1 最外线次候选轮）
    #   instances   559 → 571：控制台定字裁决回流的 12 条切分缺陷
    #                （9 truncated + 3 contaminated，2026-09-04 用户实裁）
    #   instances   600 → 614：p44-56 裁决回流 14 条（其中 14 条 seg_defect
    #                集中在列尾 slot 19~21——那批页字距极挤，字与字物理相连，
    #                属图像极限而非算法缺陷，见 review_loop_sop.md 判据 C2）
    #   instances   582 → 600：p15-29 新页裁决回流 18 条（用户 2026-09-04 审
    #                完 12 页新正文页，其中 9 条 seg_defect 集中在 slot 2
    #                ——那批正是暴露「版框钉桩切字顶」的证据）
    #   instances   571 → 582：第二轮裁决再回流 11 条
    #                （10 truncated + 1 contaminated，页 11/151/137/60/70）
    #                核实办法：带 source_events 的条目共 23 条，其中
    #                只挂 1 个事件的 11 条就是本轮新增——不是迁移漏条。
    #   instances   614 → 1024：不是一次性跳变，是 open-guji-dataset 里 16 条
    #                已提交历史（commit db01e024 起到 bf168364）逐批累积——
    #                vol01/vol02 大批正文人审事件回流、rand_human 分片新增
    #                （Step4 随机层真人核校）、多轮标注账复核（愈合/保留改判）。
    #                核实办法：`git log --oneline -- char-segmentation/instances/items.jsonl`
    #                能看到全部落地的提交，且该文件在 dataset 仓 `git status`
    #                里干净（无未提交改动）——是已经定档的金标，不是迁移漏条。
    #   column-split 60 → 130：**不是本轮改坏，是 dataset 仓有 70 条未提交的
    #                新增**（`git status` 在 open-guji-dataset 里能看到
    #                `border-detection/column-split/items.jsonl` 有本地改动未
    #                commit）。新增的 70 条 id 前缀全是 `head:`（如
    #                `head:vol01:26`），是 2026-09-12～13 新上线的「抬头列级
    #                标注台」（commit 3ecd2e07b8 附近，overview 任务卡
    #                「Step1 抬头检测」）产出的人裁金标（label_origin=human，
    #                source_events 指向 `evt_vol0{1,2}-head-review_*`），verdict
    #                取值是 yes/no（8 yes / 62 no），与原来 60 条 `cols:` 前缀
    #                的 ok/extra/miss verdict 体系是两套并存的判据，不冲突。
    #                原 60 条 `cols:` 条目内容与分布完全未变（仍是
    #                ok 56 / extra 2 / miss 2，见下方断言）。数字对不上先查
    #                是「金标长大了」还是「迁移漏了」，别直接改数——这次两条
    #                都是长大：一条是已提交的真实历史演进，一条是同仓另一
    #                功能刚产出、还没来得及 commit 的真实新金标。
    expect = {"border-detection/column-split": 130,
              "char-segmentation/column-warp": 115,
              "char-segmentation/instances": 1024,
              "page-type": 394,
              "column-layout": 36}
    for sh, n in expect.items():
        if not store.items_path(sh).exists():
            pytest.skip(f"{sh} 还没迁")
        assert store.carrier(sh) == "items"
        assert len(store.list(sh)) == n
    # 第一轮界行裁决（id 前缀 cols:，60 条）：ok 56 / extra 2 / miss 2。
    # 2026-09-13 起同一分片里并存第二套判据——抬头列级标注台产出的
    # id 前缀 head:（70 条，verdict 取 yes/no）——按前缀分开统计，
    # 不然两套 verdict 词表混在一个 dist 里对不上任何一边的账。
    dist: dict[str, int] = {}
    head_dist: dict[str, int] = {}
    for i in store.list("border-detection/column-split"):
        v = i.expected.get("verdict")
        if i.id.startswith("head:"):
            head_dist[v] = head_dist.get(v, 0) + 1
        else:
            dist[v] = dist.get(v, 0) + 1
    assert dist == {"ok": 56, "extra": 2, "miss": 2}
    assert head_dist == {"yes": 8, "no": 62}


@needs_dataset
def test_real_migration_is_lossless():
    """**迁移无损**：items.jsonl 还原回旧格式后，与旧文件逐条相同。

    这是迁移的核心保证——载体变了、内容不许变。校验器与
    `scripts/verify_gold_migration.py` 同源。
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "verify_gold_migration", REPO_ROOT / "scripts" / "verify_gold_migration.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    store = GoldStore(DATASET)
    migrated = [s for s in store.shards() if store.items_path(s).exists()]
    if not migrated:
        pytest.skip("还没有迁过的分片")
    bad = []
    for sh in migrated:
        ok, msgs = mod.compare(sh, store)
        if not ok:
            bad.append((sh, msgs))
    assert not bad, "\n".join(m for _, ms in bad for m in ms)
