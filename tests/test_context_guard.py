# -*- coding: utf-8 -*-
"""overview#274 D 道：context 通道护栏 + 三件小修。全部自己造数据，不依赖真书。"""
from __future__ import annotations

import warnings

import cv2
import numpy as np
import pytest

import open_guji_cv.steps  # noqa: F401
from helpers import make_book, make_ctx, page_decision, page_match, write_product
from open_guji_cv.clustering import context_guard as cg
from open_guji_cv.core.book import load_book, yaml_comment_truncations
from open_guji_cv.core.step import STEPS
from open_guji_cv.report.collate import classify

BOOK, PAGE, COL = "tbook", 1, 1


# ── 合成图块 ────────────────────────────────────────────────────────────
def _char_like(n=96):
    """笔画交织的「字」：横竖撇捺若干，几块连通域，占比 ~15%。"""
    g = np.full((n, n), 235, np.uint8)
    cv2.line(g, (12, 30), (84, 30), 20, 5)
    cv2.line(g, (12, 60), (84, 60), 20, 5)
    cv2.line(g, (48, 10), (48, 88), 20, 5)
    cv2.line(g, (20, 80), (44, 66), 20, 4)
    cv2.line(g, (56, 66), (80, 82), 20, 4)
    return g


def test_patch_accepts_char_like():
    assert cg.patch_looks_like_char(_char_like())


def test_patch_rejects_blank_thin_line_black_block_noise_none():
    blank = np.full((96, 96), 235, np.uint8)
    thin = blank.copy()
    cv2.line(thin, (48, 0), (48, 95), 20, 4)              # 界行残段：又细又长
    black = np.full((96, 96), 30, np.uint8)               # 满黑（印章块）
    black[:6] = 235
    rng = np.random.default_rng(0)
    noise = blank.copy()
    ys, xs = rng.integers(0, 96, 300), rng.integers(0, 96, 300)
    noise[ys, xs] = 20                                    # 散点噪声
    for name, img in [("blank", blank), ("thin", thin), ("black", black), ("noise", noise),
                      ("none", None)]:
        assert not cg.patch_looks_like_char(img), name


def test_head_cell_ok_prefers_library_signal():
    blank = np.full((96, 96), 235, np.uint8)
    assert cg.head_cell_ok("same", None) and cg.head_cell_ok("unsure", blank)
    assert not cg.head_cell_ok("diff", blank)
    assert cg.head_cell_ok("diff", _char_like())


def test_page_guarded():
    assert cg.page_guarded(49, [49, 107]) and not cg.page_guarded(50, [49, 107])
    assert not cg.page_guarded(49, []) and not cg.page_guarded(49, None)


# ── seed_admit 集成 ─────────────────────────────────────────────────────
def _run(tmp_path, monkeypatch, *, book=None, patches=None, n=4, verdict="diff"):
    ctx = make_ctx(tmp_path, book or make_book(BOOK), monkeypatch=monkeypatch)
    recs = [dict(slot=i, verdict=verdict, cov=0.5, wmax=0.0,
                 candidates=[("甲乙丙丁"[i - 1], 0.5)]) for i in range(1, n + 1)]
    write_product(ctx, "glyph_match", PAGE, glyph_match=page_match(PAGE, BOOK, recs=recs, col=COL))
    write_product(ctx, "context_decide", PAGE, context_decision=page_decision(
        PAGE, BOOK, col=COL,
        recs=[dict(slot=i, char="甲乙丙丁"[i - 1], margin=0.9, source="context")
              for i in range(1, n + 1)]))
    for slot, img in (patches or {}).items():
        ctx.cache.put(BOOK, "char_patch", f"p{PAGE:04d}c{COL:02d}s{slot}", img)
    sa = STEPS["seed_admit"].run_page(ctx, PAGE)["seed_admit"]
    return {r.slot: r for cc in sa.columns for r in cc.chars}


def test_baseline_context_admits_everything(tmp_path, monkeypatch):
    """没配护栏、没关列首检查 → 与旧行为一致（这条守住「缺省不变」的边界：
    列首检查默认开，所以这里给列首格真字图块）。"""
    by = _run(tmp_path, monkeypatch, patches={1: _char_like(), 2: _char_like()})
    assert {s: r.channel for s, r in by.items()} == {1: "context", 2: "context",
                                                     3: "context", 4: "context"}


def test_guard_page_blocks_context_channel(tmp_path, monkeypatch):
    book = make_book(BOOK, context_guard_pages=[PAGE])
    by = _run(tmp_path, monkeypatch, book=book, patches={1: _char_like(), 2: _char_like()})
    for r in by.values():
        assert not r.admit and "context_guard_page" in r.doubts, r


def test_guard_pages_change_the_params_hash(tmp_path, monkeypatch):
    plain = make_ctx(tmp_path, make_book(BOOK), monkeypatch=monkeypatch)
    guarded = make_ctx(tmp_path, make_book(BOOK, context_guard_pages=[49]), monkeypatch=monkeypatch)
    step = STEPS["seed_admit"]
    assert plain.params_for(step).context_guard_pages == []
    assert guarded.params_for(step).context_guard_pages == [49]


def test_head_cells_without_char_evidence_go_to_review(tmp_path, monkeypatch):
    blank = np.full((96, 96), 235, np.uint8)
    by = _run(tmp_path, monkeypatch, patches={1: blank, 2: _char_like(), 3: blank, 4: blank})
    assert not by[1].admit and "context_head_nonchar" in by[1].doubts   # 列首、空白
    assert by[2].admit and by[2].channel == "context"                    # 列首但像字
    assert by[3].admit and by[4].admit                                   # 非列首不查图


def test_head_cells_without_any_patch_are_conservative(tmp_path, monkeypatch):
    by = _run(tmp_path, monkeypatch)                     # 缓存里没有图块
    assert not by[1].admit and not by[2].admit and by[3].admit


def test_head_library_signal_counts_as_evidence(tmp_path, monkeypatch):
    by = _run(tmp_path, monkeypatch, verdict="unsure")   # 无图但库 unsure
    assert by[1].channel == "context" and by[2].channel == "context"


# ── (a) yaml `#` 截断 ───────────────────────────────────────────────────
def test_yaml_hash_truncation_detected_and_warned(tmp_path):
    text = ("id: v\nraw_dir: x\nreferences:\n"
            "  - label: daizhige逐列本（P #195：某某）\n    file: a.txt\n"
            "  - label: \"引号里的 #195 没事\"\n"
            "  - label: 正常（无井号）  # 行尾注释，括号是配平的\n")
    hits = yaml_comment_truncations(text)
    assert [h[0] for h in hits] == [4] and "P" in hits[0][2] and "195" in hits[0][3]
    (tmp_path / "v.yaml").write_text(text, encoding="utf-8")
    with pytest.warns(UserWarning, match="截断"):
        load_book("v", books_dir=tmp_path)


def test_yaml_clean_file_no_warning(tmp_path):
    (tmp_path / "v.yaml").write_text("id: v\nraw_dir: x  # 注释\ncontext_guard_pages: [49, 107]\n",
                                     encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        b = load_book("v", books_dir=tmp_path)
    assert b.context_guard_pages == [49, 107]


# ── (b) scipy ───────────────────────────────────────────────────────────
def test_scipy_is_a_core_dependency():
    import pathlib
    t = (pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    core = t.split("dependencies = [", 1)[1].split("]", 1)[0]
    assert "scipy" in core


def test_missing_scipy_fails_loudly(monkeypatch):
    import builtins, importlib, sys
    real = builtins.__import__

    def fake(name, *a, **k):
        if name.startswith("scipy"):
            raise ImportError("no scipy")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    monkeypatch.delitem(sys.modules, "open_guji_cv.utils.preclean", raising=False)
    with pytest.raises(ImportError, match="缺 scipy"):
        importlib.import_module("open_guji_cv.utils.preclean")
    monkeypatch.undo()
    importlib.import_module("open_guji_cv.utils.preclean")


# ── (c) classify 读书级码位 ──────────────────────────────────────────────
def test_classify_honours_book_codepoints():
    assert classify("𠮓", "變").startswith("sub")                       # 旧行为：认错字
    assert classify("𠮓", "變", {"變": "𠮓"}) == "same"
    assert classify("別", "别", {"别": "別"}) == "same"
    assert classify("甲", "乙", {"變": "𠮓"}).startswith("sub")          # 无关配置不影响
    assert classify("甲", "甲", {"變": "𠮓"}) == "same"


# ── p110 印章：遮挡闸为什么盖不到小印（合成数据复现判据）─────────────────
def _dens(hot_cells, cols=range(1, 10), n_slots=21, hot=10.0, base=0.5):
    d = {(c, s, ""): base for c in cols for s in range(1, n_slots + 1)}
    for c, s in hot_cells:
        d[(c, s, "")] = hot
    return d


def test_small_seal_below_min_cells_is_not_flagged_by_default():
    """6 格（3 列 × 2 行）的小印：密度、峰值、对比都够，但块 < `min_cells=12` → 漏。
    这就是 vol03 p110 那 6 格没被 `occluded_gate` 盖到的原因（判据里块大小是硬门槛）。"""
    from open_guji_cv.steps.occlusion import occluded_cells
    d = _dens([(c, s) for c in (3, 4, 5) for s in (2, 3)])
    assert occluded_cells(d) == {}
    hit = occluded_cells(d, min_cells=6)
    assert len(hit) == 6
    # 大印（≥12 格）默认就能抓：说明不是别的闸在拦
    big = _dens([(c, s) for c in (3, 4, 5, 6) for s in (2, 3, 4)])
    assert len(occluded_cells(big)) == 12
