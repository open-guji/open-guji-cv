# -*- coding: utf-8 -*-
"""读不到图必须报错、不许降级（overview#407）。

vol02 本地重算（10-05）：Windows 中文路径工作区上 `glyph_match` 打了 8,980 条
`imread_(...char_patch...): can't open/read file`，p20「魏王弼撰」配成「理玉朝鑿」。
钉四件事：

1. `image_io.imread` 直接字节读入，不再先碰 `cv2.imread`（那一步在中文路径上必失败、
   必打假警告，真失败淹在里面）；`strict=True` 时解不出来也抛错。
2. `RunContext.image` 读不出来抛错，不返回 None。
3. `glyph_match` 字块读不到 → 整页抛错（引擎记 failed），不再记成 diff+`no_patch` 往下走。
4. `seed_admit` 读本页字块的四处（铁证尺度/铁证判定/CNN 背书/组内检索）读不到 → 抛错，
   不再 `return None` 把那一路悄悄关掉。

全部自造数据（tmp 目录 + 内存图），不碰工作区。
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from open_guji_cv.utils.image_io import ImageReadError, imread, imwrite

CN_DIR = "96mid1ogzk-欽定四庫全書總目武英殿刻本"


def _cn_png(tmp_path, name="p0020c01s1.png", img=None):
    d = tmp_path / CN_DIR / "cache" / "vol02" / "char_patch"
    d.mkdir(parents=True)
    f = d / name
    img = np.full((16, 12), 200, np.uint8) if img is None else img
    assert imwrite(str(f), img)
    return f, img


# ── 1. image_io.imread ────────────────────────────────────────────────

def test_imread_reads_non_ascii_path_without_touching_cv2_imread(tmp_path, monkeypatch):
    """中文路径读得出来，且全程不调 `cv2.imread`（它在 Windows 中文路径上必打假警告）。"""
    f, img = _cn_png(tmp_path)

    def _boom(*a, **k):
        raise AssertionError("imread 不该再调 cv2.imread")
    monkeypatch.setattr(cv2, "imread", _boom)

    got = imread(str(f), cv2.IMREAD_GRAYSCALE)
    assert got is not None and got.shape == img.shape
    assert np.array_equal(got, img)
    assert np.array_equal(imread(str(f), cv2.IMREAD_GRAYSCALE, strict=True), img)
    assert imread(f, cv2.IMREAD_COLOR).shape == (*img.shape, 3), "Path 对象、彩色口径也要能读"


@pytest.mark.parametrize("strict", [False, True])
def test_imread_missing_file_raises_in_both_modes(tmp_path, strict):
    """文件不存在：两种口径都抛 FileNotFoundError（老口径本来就这样，调用方靠它）。"""
    with pytest.raises(FileNotFoundError):
        imread(str(tmp_path / CN_DIR / "nope.png"), cv2.IMREAD_GRAYSCALE, strict=strict)


@pytest.mark.parametrize("content", [b"", b"not a png at all"])
def test_imread_undecodable_none_by_default_raises_when_strict(tmp_path, content):
    """文件在但解不出来：默认返回 None（老调用方靠它判断），strict 抛 ImageReadError。"""
    d = tmp_path / CN_DIR
    d.mkdir()
    f = d / "bad.png"
    f.write_bytes(content)
    assert imread(str(f), cv2.IMREAD_GRAYSCALE) is None
    with pytest.raises(ImageReadError):
        imread(str(f), cv2.IMREAD_GRAYSCALE, strict=True)
    assert issubclass(ImageReadError, OSError)


# ── 2. RunContext.image ───────────────────────────────────────────────

def test_runcontext_image_raises_on_undecodable_cache(tmp_path):
    """缓存里有文件、但解不出来 → 抛错，不返回 None。"""
    from open_guji_cv.core.step import RunContext

    bad = tmp_path / CN_DIR / "p0020c01s1.png"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"\x89PNG\r\n\x1a\n truncated")

    class _Fake:
        def materialize(self, kind_id, key):
            return bad

    with pytest.raises(FileNotFoundError, match="缓存图像读不出来"):
        RunContext.image(_Fake(), "char_patch", "p0020c01s1")


def test_runcontext_image_reads_non_ascii_cache(tmp_path):
    from open_guji_cv.core.step import RunContext

    f, img = _cn_png(tmp_path)

    class _Fake:
        def materialize(self, kind_id, key):
            return f

    assert np.array_equal(RunContext.image(_Fake(), "char_patch", "p0020c01s1"), img)


# ── 3. glyph_match：读不到字块整页失败 ─────────────────────────────────

def test_glyph_match_page_fails_when_patch_unreadable(tmp_path, monkeypatch, ws, fixture_page):
    """跑真 Step1→Step4 出字块，再让读字块失败：run_page 必须抛错，
    不能产出一页 diff+`no_patch` 的记录（那正是 10-05 回滚的那种「状态正常、内容变质」）。"""
    from dataclasses import dataclass

    import open_guji_cv.steps  # noqa: F401
    from helpers import run_keben_from_raw
    from open_guji_cv.clustering.match import MatchResult
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.step import STEPS
    from open_guji_cv.steps.glyph_match import GlyphMatchParams, PatchUnavailable

    @dataclass
    class _StubMatcher:
        def match(self, img, exclude_id=None):
            return MatchResult(verdict="diff", char=None, matched_id=None, cov=0.5,
                               wmax=30.0, candidates=[], n_verified=0)

    bk = load_book("keben")
    ctx, _ = run_keben_from_raw(tmp_path, monkeypatch, book=bk, gray=fixture_page)
    step = STEPS["glyph_match"]
    monkeypatch.setattr(type(step), "_matcher", lambda self, p: _StubMatcher())
    ctx.params["glyph_match"] = GlyphMatchParams(db_fingerprint="testfp")

    # 对照：图读得到时这一页正常出产物
    ok = step.run_page(ctx, 1)["glyph_match"]
    assert any(cc.chars for cc in ok.columns), "样页一个字块都没切出来，本测试失去前提"
    assert not any((r.guard or "").startswith("no_patch")
                   for cc in ok.columns for r in cc.chars)

    real_image = type(ctx).image

    def _unreadable(self, kind_id, key):
        raise FileNotFoundError(f"缓存图像读不出来: {kind_id} {key}")
    monkeypatch.setattr(type(ctx), "image", _unreadable)
    with pytest.raises(PatchUnavailable, match="p1 字块"):
        step.run_page(ctx, 1)

    # 候选试切的键（`…_L0`）按设计不可再生：缓存里没有（KeyError/ValueError）只跳过这一路，
    # 但文件在却读不出来（OSError）照样停页。
    def _cand_unrenderable(self, kind_id, key):
        if "_" in key:
            raise ValueError(f"非法单位键: {key!r}")
        return real_image(self, kind_id, key)
    monkeypatch.setattr(type(ctx), "image", _cand_unrenderable)
    d = step.run_page(ctx, 1)["glyph_match"]
    assert all(not r.cand_variants for cc in d.columns for r in cc.chars)

    chars = ctx.product("char_index", 1)
    if any(r.cand_variants for cc in chars.columns for r in cc.chars):
        def _cand_unreadable(self, kind_id, key):
            if "_" in key:
                raise FileNotFoundError(f"缓存图像读不出来: {kind_id} {key}")
            return real_image(self, kind_id, key)
        monkeypatch.setattr(type(ctx), "image", _cand_unreadable)
        with pytest.raises(FileNotFoundError):
            step.run_page(ctx, 1)


# ── 4. seed_admit：读本页字块的四处 ───────────────────────────────────

class _CtxNoPatch:
    """有 `image` 的假 ctx：一律读不到。"""
    def image(self, kind_id, key):
        raise FileNotFoundError(f"缓存图像读不出来: {kind_id} {key}")


class _CtxPatch:
    def __init__(self, img):
        self.img = img
        self.keys = []

    def image(self, kind_id, key):
        assert kind_id == "char_patch"
        self.keys.append(key)
        return self.img


def test_seed_admit_page_patch_raises_instead_of_none(monkeypatch):
    from open_guji_cv.clustering import cnn_candidates
    from open_guji_cv.steps.seed_admit import PatchUnavailable, _cnn_top, _image_ranks, _page_patch

    class _Cnn:                     # CNN 通道开着（有 checkpoint）——这时才会去读图
        available = True
    monkeypatch.setattr(cnn_candidates, "shared", lambda *a, **k: _Cnn())

    with pytest.raises(PatchUnavailable, match="p0020c03s5a"):
        _page_patch(_CtxNoPatch(), 20, 3, 5, "a")
    # CNN 背书 / 组内检索：以前没图 → None（这一路悄悄关掉），现在没图 → 抛错
    with pytest.raises(PatchUnavailable):
        _cnn_top(_CtxNoPatch(), 20, 3, 5, None)
    with pytest.raises(PatchUnavailable):
        _image_ranks(_CtxNoPatch(), 20, 3, 5, None, ["甲", "乙"])


def test_seed_admit_cnn_top_skips_image_when_channel_off(monkeypatch):
    """没 checkpoint / 没 torch：CNN 通道本来就不触发，不去读图、不报错。"""
    from open_guji_cv.clustering import cnn_candidates
    from open_guji_cv.steps.seed_admit import _cnn_top

    class _Cnn:
        available = False
    monkeypatch.setattr(cnn_candidates, "shared", lambda *a, **k: _Cnn())
    assert _cnn_top(_CtxNoPatch(), 20, 3, 5, None) is None


def test_seed_admit_page_patch_uses_ctx_image_with_patch_key():
    """管线里走 `ctx.image`（验页戳、缺了现算），键与 `feedback.anchor.patch_key` 同口径。"""
    from open_guji_cv.feedback.anchor import patch_key
    from open_guji_cv.steps.seed_admit import _page_patch

    img = np.zeros((8, 8), np.uint8)
    c = _CtxPatch(img)
    assert _page_patch(c, 20, 3, 5, "b") is img
    assert _page_patch(c, 7, 12, 1, None) is img
    assert c.keys == [patch_key(20, 3, 5, "b"), patch_key(7, 12, 1, "")]


def test_seed_admit_iron_page_scale_raises_on_missing_patch():
    from open_guji_cv.products.kinds.recog import ColumnMatch, MatchRec, PageMatch
    from open_guji_cv.steps.seed_admit import PatchUnavailable, _iron_page_scale

    pm = PageMatch(page=20, db_fingerprint="x", columns=[ColumnMatch(col=1, ok=True, chars=[
        MatchRec(id="b:20:1:1", slot=1, verdict="diff")])])
    with pytest.raises(PatchUnavailable):
        _iron_page_scale(_CtxNoPatch(), 20, pm)


def test_seed_admit_page_patch_book_id_mode(tmp_path, monkeypatch):
    """离线审计脚本传册 id 字符串：缓存里有就读（中文路径），没有/坏了抛错。"""
    from open_guji_cv.products import cache as cache_mod
    from open_guji_cv.steps.seed_admit import PatchUnavailable, _page_patch

    root = tmp_path / CN_DIR / "cache"
    monkeypatch.setattr(cache_mod, "default_cache_root", lambda: root)
    img = np.full((10, 9), 77, np.uint8)
    cache_mod.ImageCache(root).put("vol02", "char_patch", "p0020c01s1", img)

    assert np.array_equal(_page_patch("vol02", 20, 1, 1, None), img)
    with pytest.raises(PatchUnavailable, match="缓存里没有"):
        _page_patch("vol02", 20, 1, 2, None)
    (root / "vol02" / "char_patch" / "p0020c01s3.png").write_bytes(b"")
    with pytest.raises(PatchUnavailable, match="ImageReadError"):
        _page_patch("vol02", 20, 1, 3, None)


# ── 5. seed_admit 的 `patch_missing` 开关（云端快照沙箱，CV 总管 10-05 验收意见）──

_SA_BOOK, _SA_PAGE, _SA_COL = "tbook", 1, 1


def _seed_admit_page(tmp_path, monkeypatch, *, patch_missing, cnn_on=True, logs=None):
    """一页两格、缓存里一张字块都没有（= 快照沙箱）：
    slot 18 match_replace 放行（整理本「𠮓」，库首位「變」，D #178 那组）后走组内定形 → 要读图；
    slot 19 没整理本、库在灰区 → CNN 背书要读图。"""
    from helpers import make_book, make_ctx, page_match, write_product

    import open_guji_cv.steps  # noqa: F401
    from open_guji_cv.clustering import cnn_candidates
    from open_guji_cv.core.step import STEPS
    from open_guji_cv.products.kinds.recog import AlignRec, PageAlignRef
    from open_guji_cv.steps.seed_admit import SeedAdmitParams

    class _Cnn:
        available = cnn_on

        def emb_topk(self, *a, **k):
            return [("甲", 0.9)]
    monkeypatch.setattr(cnn_candidates, "shared", lambda *a, **k: _Cnn())

    ctx = make_ctx(tmp_path, make_book(_SA_BOOK), monkeypatch=monkeypatch)
    if logs is not None:
        ctx.log = logs.append
    write_product(ctx, "glyph_match", _SA_PAGE, glyph_match=page_match(
        _SA_PAGE, _SA_BOOK, col=_SA_COL, recs=[
            dict(slot=18, verdict="unsure", cov=0.9549, wmax=45.31,
                 candidates=[("變", 0.9549), ("泊", 0.95)]),
            dict(slot=19, verdict="unsure", cov=0.97, wmax=20.0,
                 candidates=[("甲", 0.97), ("乙", 0.90)])]))
    write_product(ctx, "align_ref", _SA_PAGE, align_ref=PageAlignRef(
        page=_SA_PAGE, anchored=True,
        chars=[AlignRec(id=f"{_SA_BOOK}:{_SA_PAGE}:{_SA_COL}:18", col=_SA_COL, slot=18,
                        align_char="𠮓", align_op="replace")]))
    ctx.params["seed_admit"] = SeedAdmitParams(patch_missing=patch_missing)
    return STEPS["seed_admit"].run_page(ctx, _SA_PAGE)["seed_admit"]


def test_seed_admit_patch_missing_error_is_default_and_stops_page(tmp_path, monkeypatch):
    from open_guji_cv.steps.seed_admit import PatchUnavailable, SeedAdmitParams

    assert SeedAdmitParams().patch_missing == "error"
    with pytest.raises(PatchUnavailable):
        _seed_admit_page(tmp_path, monkeypatch, patch_missing="error")


def test_seed_admit_patch_missing_skip_finishes_and_counts(tmp_path, monkeypatch):
    """skip：页跑得完；跳过的格逐格记在 evidence.patch_missing，日志一行汇总，数对得上。"""
    logs: list[str] = []
    d = _seed_admit_page(tmp_path, monkeypatch, patch_missing="skip", logs=logs)
    recs = {r.slot: r for cc in d.columns for r in cc.chars}
    assert set(recs) == {18, 19}
    assert recs[18].evidence["patch_missing"] == ["form"]
    assert recs[19].evidence["patch_missing"] == ["cnn"]
    n_missing = sum(1 for r in recs.values() if "patch_missing" in r.evidence)
    summary = [s for s in logs if "patch_missing=skip" in s]
    assert len(summary) == 1 and f"{n_missing} 格读不到字块" in summary[0], logs
    assert "'form': 1" in summary[0] and "'cnn': 1" in summary[0]


def test_seed_admit_patch_missing_skip_quiet_when_lane_off(tmp_path, monkeypatch):
    """CNN 通道没开（没 checkpoint）时根本不读图，不算「读不到」。"""
    d = _seed_admit_page(tmp_path, monkeypatch, patch_missing="skip", cnn_on=False)
    recs = {r.slot: r for cc in d.columns for r in cc.chars}
    assert "patch_missing" not in recs[19].evidence


def test_seed_admit_patch_missing_param_validation_and_hash():
    """只收 error/skip；缺省值不进 dump（params_hash 与加字段前逐位相同）。"""
    from open_guji_cv.steps.seed_admit import SeedAdmitParams

    with pytest.raises(ValueError):
        SeedAdmitParams(patch_missing="ignore")
    assert "patch_missing" not in SeedAdmitParams().model_dump()
    assert SeedAdmitParams(patch_missing="skip").model_dump()["patch_missing"] == "skip"


def test_seed_admit_iron_page_scale_skip_records_missing():
    from open_guji_cv.products.kinds.recog import ColumnMatch, MatchRec, PageMatch
    from open_guji_cv.steps.seed_admit import _iron_page_scale

    pm = PageMatch(page=20, db_fingerprint="x", columns=[ColumnMatch(col=1, ok=True, chars=[
        MatchRec(id="b:20:1:1", slot=1, verdict="diff"),
        MatchRec(id="b:20:1:2", slot=2, verdict="diff")])])
    seen: list[str] = []
    scale = _iron_page_scale(_CtxNoPatch(), 20, pm, on_missing=seen.append)
    assert seen == ["b:20:1:1", "b:20:1:2"] and scale > 0
