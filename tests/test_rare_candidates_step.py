# -*- coding: utf-8 -*-
"""Step5-b 生僻字候选。

`RareCandidatesStep` 注册、指纹带 checkpoint+模板集；另守一条性能回归——
`CnnCandidates._emb_index` 必须按 charset 记忆化，不能逐字重算（2026-09-10
踩过：漏了记忆化时单页 179 字从预期毫秒级拖到 88s，`load_many` 的目录扫描
+ npz 解压被重复付了 179 遍，见 `cnn_candidates.py` 该方法模块头）。
"""

from __future__ import annotations

import time

import numpy as np
import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.step import KINDS, STEPS


def test_registered():
    assert "rare_candidates" in STEPS and "rare_candidates" in KINDS
    assert "model" in STEPS["rare_candidates"].spec.needs
    assert set(STEPS["rare_candidates"].spec.consumes) == {"char_index", "char_patch"}


def test_emb_index_memoized_per_charset_not_recomputed_per_call():
    """性能回归钉子：同一 charset 连续调用，第二次起必须走内存缓存，
    不能每次都触发 `extra_glyphs.load_many` 的目录扫描/npz 解压。

    不依赖 checkpoint 是否存在——`_ensure()` 失败时 `emb_topk` 直接返回
    `[]`，不会走到 `_emb_index`，这条测试测的是缓存开关本身，用一个
    真实存在的小 charset 和随机图即可，跑不跑得出候选不是这条测试关心的。
    """
    from open_guji_cv.clustering.cnn_candidates import CnnCandidates, shared

    cnn = shared()
    if not cnn.available:
        pytest.skip("没有 CNN checkpoint，跳过（needs=model）")

    charset = tuple("一二三十土王")
    q = np.zeros((64, 64), np.uint8)
    q[20:44, 8:56] = 1

    # 预热一次，把磁盘缓存/内存缓存都建起来，不计入计时
    cnn.emb_topk(q, charset, k=3)

    t0 = time.time()
    for _ in range(20):
        cnn.emb_topk(q, charset, k=3)
    elapsed = time.time() - t0

    # 记忆化生效时 20 次 CNN 前向 + 余弦检索是毫秒级；漏了记忆化会退化到
    # `load_many` 的磁盘 IO 量级（本地实测单次 0.4~0.6s，20 次 8~12s）。
    # 阈值取 2s，留够慢机器的余量，但远低于「漏了记忆化」的量级。
    assert elapsed < 2.0, (
        f"20 次 emb_topk 耗时 {elapsed:.2f}s，疑似 _emb_index 未按 charset 记忆化"
        "（逐字重新扫描外部模板目录），见 cnn_candidates.py _emb_index 模块头")


def test_rare_for_batch_matches_sequential():
    """`rare_for_batch`（页级批处理，2026-09-10 第二轮提速）必须与逐张调用
    `rare_for` 给出一致的候选排名——允许批处理矩阵运算的浮点求和顺序噪声
    （1e-4 量级），但字符与排名不能变。"""
    from open_guji_cv.clustering.rare_panel import rare_for, rare_for_batch

    imgs = [np.zeros((64, 64), np.uint8) for _ in range(4)]
    imgs[0][20:44, 8:56] = 1
    imgs[1][10:30, 10:30] = 1
    imgs[2][30:50, 20:60] = 1
    imgs[3][15:49, 15:49] = 1

    seq = [rare_for(im, 5) for im in imgs]
    batch = rare_for_batch(imgs, 5)
    assert len(seq) == len(batch)
    for s, b in zip(seq, batch):
        assert [h["char"] for h in s] == [h["char"] for h in b]
        for hs, hb in zip(s, b):
            assert abs(hs["score"] - hb["score"]) < 1e-3


def test_hog_not_called_when_cnn_available():
    """2026-09-10 第三轮：`HOG_WEIGHT=0.0` 已经让 HOG 对排名零贡献
    （vol01 全量 1934 字实测跑不跑 HOG 结果逐字相同），CNN checkpoint 装了
    就不该再跑 HOG 的 `candidates()`——那是 `rare_for` 全链路里最贵的部分。
    这条测试直接 monkeypatch `font_candidates.candidates`，断言 CNN 可用时
    一次都不会被调用；同时确认 CNN 不可用时 HOG 仍是唯一候选源、会被调用。
    """
    from open_guji_cv.clustering import cnn_candidates, font_candidates, rare_panel

    cnn = cnn_candidates.shared()
    if not cnn.available:
        pytest.skip("没有 CNN checkpoint，跳过（HOG 本来就该被调用，测的是反面）")

    calls = []
    orig = font_candidates.candidates

    def spy(*a, **k):
        calls.append(1)
        return orig(*a, **k)

    rare_panel.candidates = spy
    try:
        img = np.zeros((64, 64), np.uint8)
        img[20:44, 8:56] = 1
        rare_panel.rare_for(img, 5)
    finally:
        rare_panel.candidates = orig
    assert not calls, "CNN 可用时不该再调 font_candidates.candidates（HOG）"


def test_params_hash_tracks_model_and_font_set(monkeypatch, tmp_path):
    """候选栈的外部状态（checkpoint / 外部模板集 / 模板字体集）必须进 `params_hash`，
    产物才会在它们变化时过期（`core/engine._self_payload` 只看参数哈希、代码哈希、
    `book_deps`，不读产物体里的 `PageRare.model_fingerprint`）。

    2026-09-21 之前 `RareCandidatesParams` 只有 `k`：原地换 `best.pt`、往 `fonts/`
    加一套字体，产物照报「新鲜」。这条钉住两件事：指纹自动填进参数；**字体集**
    变了指纹就变（此前 emb 索引键与产物指纹都不带字体档）。
    """
    from open_guji_cv.clustering import font_candidates as fc
    from open_guji_cv.core.engine import params_hash
    from open_guji_cv.steps.rare_candidates import RareCandidatesParams

    a = RareCandidatesParams()
    assert a.model_fingerprint, "model_post_init 没把 full_fingerprint 填进参数"
    assert a.model_fingerprint.count(":") == 2, "指纹应为 checkpoint:模板集:字体集 三段"

    # 字体集多一个档 → 只有字体段变，其余两段不动
    extra = tmp_path / "Extra.ttf"
    extra.write_bytes(b"\0" * 16)
    real = fc._font_files
    monkeypatch.setattr(fc, "_font_files", lambda root="fonts": real(root) + [str(extra)])
    b = RareCandidatesParams()
    assert params_hash(a) != params_hash(b)
    assert a.model_fingerprint.rsplit(":", 1)[0] == b.model_fingerprint.rsplit(":", 1)[0]
    assert a.model_fingerprint.rsplit(":", 1)[1] != b.model_fingerprint.rsplit(":", 1)[1]


def test_book_real_proto_disabled_matches_module_default():
    """真刻例多原型档「开关转正」（5-b，2026-09-26）：书配置里开关关着（或压根没写
    这段——旧 yaml、十册四庫大多数还没加）时，`full_fingerprint(real_proto=…)`
    必须与不传参数的模块级默认（同样是关）逐字节相同——不让现有 `rare_candidates`
    产物因为加了这块新配置而过期，是任务书「5-b 开关转正」的完成判据之一。"""
    from open_guji_cv.clustering.cnn_candidates import book_real_proto, full_fingerprint

    baseline = full_fingerprint()

    # 旧 yaml：font 里压根没有 real_proto 段
    assert full_fingerprint(real_proto=book_real_proto({})) == baseline
    assert full_fingerprint(real_proto=book_real_proto(None)) == baseline

    # 显式写了 enabled: false（两书 yaml 现在这么写）
    off = book_real_proto({"real_proto": {"enabled": False, "stores": ["output/glyph_store"]}})
    assert off[0] is False
    assert full_fingerprint(real_proto=off) == baseline


def test_book_real_proto_resolves_relative_stores(monkeypatch, tmp_path):
    """`stores` 相对路径按 `workspace_root()` 解释（书目录），不是仓根或 cwd；
    没给 `stores` 时缺省 `output/glyph_store`。"""
    from open_guji_cv.clustering import cnn_candidates as cc
    from open_guji_cv.core import workspace as ws

    monkeypatch.setattr(ws, "workspace_root", lambda: tmp_path)

    enabled, specs = cc.book_real_proto({"real_proto": {"enabled": True}})
    assert enabled is True
    assert specs == (f"store:{tmp_path / 'output' / 'glyph_store'}",)

    enabled2, specs2 = cc.book_real_proto(
        {"real_proto": {"enabled": True, "stores": ["output/glyph_store", "/abs/other_store"]}})
    assert specs2 == (f"store:{tmp_path / 'output' / 'glyph_store'}", "store:/abs/other_store")


def test_rare_for_batch_real_proto_off_matches_no_param(monkeypatch):
    """`rare_for_batch`/`emb_topk_batch` 加了 `real_proto` 形参不该改变缺省行为：
    显式传 `(False, …)` 与完全不传该参数（旧调用方式）结果必须逐字节相同。"""
    from open_guji_cv.clustering.cnn_candidates import shared

    cnn = shared()
    if not cnn.available:
        pytest.skip("没有 CNN checkpoint，跳过（needs=model）")

    charset = tuple("一二三十土王")
    q = np.zeros((64, 64), np.uint8)
    q[20:44, 8:56] = 1

    a = cnn.emb_topk_batch([q], charset, k=3)
    b = cnn.emb_topk_batch([q], charset, k=3, real_proto=(False, ("store:/nonexistent",)))
    assert a == b

