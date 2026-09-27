"""任务书-R-rare冷启动内存与索引预建（2026-09-27）三件事的回归：

1. `cnn_candidates.fingerprint()` 改内容指纹——同内容换 mtime 命中同一份缓存，
   换机器（云端建、服务器用）才不会白建一次。
2. `build_emb_matrix()` 的进度回调、`_emb_index()` 落盘改 float16 后查询路
   立刻转回 float32（与从未碰过磁盘的现算结果只差浮点尾数，不改变字符排序）。
3. `guji cache build-rare-index` 与产线用**同一个** `book_charsets()`/
   `emb_index_key()`，预建的文件产线必然能命中。

不跑真书规模（27,584 / 70,304 字，单核要几十分钟）——那部分的实测数字记在
任务书 done 单里；这里只用几个字验证机制本身对不对，重的是「逻辑」不是「I/O」，
遵守 `tests/conftest.py` 的口径（不依赖仓外数据、不跑真书）。
"""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import numpy as np
import pytest

from open_guji_cv.clustering.cnn_candidates import (DEFAULT_CKPT, CnnCandidates,
                                                     build_emb_matrix, fingerprint)

CNN_OK = CnnCandidates().available
needs_cnn = pytest.mark.skipif(
    not CNN_OK, reason=f"没有 checkpoint（{DEFAULT_CKPT}）或没装 torch")


# ── 1. 内容指纹 ──────────────────────────────────────────────────
def test_fingerprint_missing_file():
    assert fingerprint(Path("/tmp/does-not-exist-xyz.pt")) == "nockpt"


def test_fingerprint_survives_mtime_change(tmp_path):
    """同内容、改 mtime → 指纹不变（2026-09-27 起按内容算，不按 (路径,大小,mtime)）。"""
    p = tmp_path / "ckpt.pt"
    p.write_bytes(b"hello world" * 100)
    fp1 = fingerprint(p)
    import os
    import time
    time.sleep(0.01)
    os.utime(p, (time.time() + 1000, time.time() + 1000))  # 未来的 mtime，模拟换机器 checkout
    fp2 = fingerprint(p)
    assert fp1 == fp2


def test_fingerprint_changes_with_content(tmp_path):
    p = tmp_path / "ckpt.pt"
    p.write_bytes(b"aaaa")
    fp1 = fingerprint(p)
    p.write_bytes(b"bbbb")
    fp2 = fingerprint(p)
    assert fp1 != fp2


# ── 2. build_emb_matrix：进度回调 + 只算能渲染出来的字 ────────────
@needs_cnn
def test_build_emb_matrix_progress_callback():
    from open_guji_cv.clustering.synth import render_char

    cnn = CnnCandidates()
    cnn._ensure()
    cs = ("一", "二", "三", "十", "土", "王")
    seen: list[str] = []
    mat, names = build_emb_matrix(cnn._net, cnn._dev, cs, {}, render_char,
                                  log=seen.append, log_every=2)
    assert mat.shape == (len(names), 256)
    assert set(names) <= set(cs)
    # log_every=2，6 个字 → 至少在第 2/4/6 字各打一行，外加收尾一行
    assert len(seen) >= 3
    assert "完成" in seen[-1]


@needs_cnn
def test_build_emb_matrix_skips_unrenderable_char_without_crashing():
    """字体都渲不出的字（这里拿一个多半没覆盖的 PUA 字试）：直接跳过，不进
    矩阵、不报错——`_emb_index` 靠这个行为在真实字表里滤掉少数渲染失败的字。"""
    from open_guji_cv.clustering.synth import render_char

    cnn = CnnCandidates()
    cnn._ensure()

    def _never_renders(ch, font_path, size=64):
        raise RuntimeError("boom")

    cs = ("一", "二")
    mat, names = build_emb_matrix(cnn._net, cnn._dev, cs, {}, _never_renders, log=None)
    assert mat.shape == (0, 256)
    assert names == []


# ── 3. _emb_index 落盘 float32（09-27 CV 总管定，不用 float16）────────
@needs_cnn
def test_emb_index_disk_roundtrip_is_float32_and_close(tmp_path, monkeypatch):
    """建一次（现算）→ 新实例重新读盘（命中缓存）→ 两次矩阵**逐位相同**、都是
    float32（落盘不降精度，候选与从未落过盘的现算结果完全一致）。"""
    ckpt_copy = tmp_path / "best.pt"
    ckpt_copy.write_bytes(DEFAULT_CKPT.read_bytes())

    cs = ("一", "二", "三", "十", "土", "王", "人", "之")
    inst1 = CnnCandidates(ckpt=ckpt_copy)
    inst1._ensure()
    mat1, names1 = inst1._emb_index(cs)
    assert mat1.dtype == np.float32

    key, f, _extra = inst1.emb_index_key(cs)
    assert f.exists()
    with np.load(f) as z:
        assert z["mat"].dtype == np.float32

    inst2 = CnnCandidates(ckpt=ckpt_copy)
    inst2._ensure()
    mat2, names2 = inst2._emb_index(cs)
    assert names2 == names1
    assert mat2.dtype == np.float32
    assert np.array_equal(mat1, mat2)


@needs_cnn
def test_emb_index_key_stable_for_equal_charset_tuples():
    """`emb_index_key` 只看内容（不看对象身份）——两个内容相同、身份不同的
    元组必须算出同一把 key，`guji cache build-rare-index` 预建的文件才能被
    产线的另一次 `book_charsets()` 调用命中（两边字表元组不是同一个 tuple
    对象，但内容相同）。"""
    inst = CnnCandidates(ckpt=DEFAULT_CKPT)
    a = tuple("一二三")
    b = tuple(list("一二三"))  # 内容相同，另建一个元组对象
    assert a is not b
    key_a, f_a, _ = inst.emb_index_key(a)
    key_b, f_b, _ = inst.emb_index_key(b)
    assert key_a == key_b
    assert f_a == f_b


# ── CLI：guji cache build-rare-index 走的是产线同一个 book_charsets ──
@needs_cnn
def test_cli_build_rare_index_uses_book_charsets_and_dedupes(monkeypatch, tmp_path):
    """打桩 `book_charsets` 回一个几个字的小表，只验证 CLI 把它接到
    `emb_index_key`/`_emb_index` 的路径没接错、文件写到了预期位置、
    第二次调用（缓存已在）不重建。不碰真实 27,584/70,304 字规模。"""
    from open_guji_cv import cli_v2
    from open_guji_cv.clustering import cnn_candidates as cc
    from open_guji_cv.clustering import rare_panel as rare_panel_mod

    ckpt_copy = tmp_path / "best.pt"
    ckpt_copy.write_bytes(DEFAULT_CKPT.read_bytes())
    monkeypatch.setattr(cc, "DEFAULT_CKPT", ckpt_copy)

    cs_base = tuple("一二三十土王")
    cs_esc = tuple("人之")

    def _fake_book_charsets(book, corpus):
        return cs_base, cs_esc, {"base": "fake-base", "escalate": "fake-esc"}

    monkeypatch.setattr(rare_panel_mod, "book_charsets", _fake_book_charsets)
    monkeypatch.setattr("open_guji_cv.steps.align_ref.book_corpus", lambda book: None)

    args = Namespace(book="keben")
    cli_v2._cmd_cache_build_rare_index(args)

    inst = cc.CnnCandidates(ckpt=ckpt_copy)
    key_base, f_base, _ = inst.emb_index_key(cs_base)
    key_esc, f_esc, _ = inst.emb_index_key(cs_esc)
    assert f_base.exists(), "CLI 应该已经把基集索引建出来了"
    assert f_esc.exists(), "CLI 应该已经把升级档索引也建出来了"

    # 第二次调用：文件已在，不该重建（用 mtime 没变来判断——重建会改 mtime）
    mtime_before = f_base.stat().st_mtime_ns
    cli_v2._cmd_cache_build_rare_index(args)
    assert f_base.stat().st_mtime_ns == mtime_before
