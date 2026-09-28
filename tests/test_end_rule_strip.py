# -*- coding: utf-8 -*-
"""列首／列尾贴边内框细线剥离（`clustering/end_rule_strip.py`，书级开关 `end_rule_strip`）。

用的是 `tests/fixtures/qtw_colend/` 里冻结的全唐文真样本（overview#66，S 道 2026-09-28）：
每个用例是 extractor 走到剥线这一步时**原样**的图块（`*.patch.png`，剥线前）加上同几行的
列图文字窗（`*.colrows.png`，给「横贯文字窗」那条判据用）。标签：

- `residue`：改前紧框压着内框线（`scripts/eval_end_rule.py` 口径 + 人眼逐张核过）——剥完后线外不许
  再有像样的墨，线内的字一个像素都不许动；
  （`fixed: false` 的是这版没救回的已知漏检，记着不删——测试集量的是现实，不是只收会过的）；
- `clean`：改前紧框本来就没碰线（线距末字 3–80px）——图块必须原样返回。含「二/三/之/旦」这类
  底部有宽横笔的难负例；
- `frame_bar` / `raised_fragment`：抬头位的整组雙邊框条 vs. 抬头格压进了下一格字身上半截——前者
  书级放宽 `raised_bar_max_h` 后判框，后者不许判框（判框等于把那截字墨藏起来）。
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from open_guji_cv.clustering import extractor as EX
from open_guji_cv.clustering.end_rule_strip import make_col_cov, strip_end_rule
from open_guji_cv.steps.cell_shrink import CellShrinkStep, _bar_like, _is_raised_frame_bar

FIX = Path(__file__).parent / "fixtures" / "qtw_colend"
CASES = [json.loads(l) for l in (FIX / "cases.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
STRIP = [c for c in CASES if c["label"] in ("residue", "clean")]
RAISED = [c for c in CASES if c["label"] in ("frame_bar", "raised_fragment")]
#: 「线以内」判定的余量（行），见 _glyph_rows
SLANT = 12


def _load(c):
    patch = cv2.imread(str(FIX / f"{c['fixture']}.patch.png"), cv2.IMREAD_GRAYSCALE)
    rows = cv2.imread(str(FIX / f"{c['fixture']}.colrows.png"), cv2.IMREAD_GRAYSCALE)
    return patch, make_col_cov(rows, 0, 0, rows.shape[1])


def _glyph_rows(c, h):
    """图块里「线以内」的行。线的内沿是列图坐标 `rule`（尺子在文字窗 5%–95% 上量的），图块顶在
    `patch_row_off`。留 SLANT 行余量：线是斜的，一端会比尺子量的内沿高出 8–9 行（v009 p72c9、
    v010 p62c2 实测，改的全是线本身）。"""
    r = c["rule"] - c["patch_row_off"]
    if c["end"] == "tail":
        return slice(0, max(0, r - SLANT))
    return slice(min(h, r + SLANT + 1), h)


def _id(c):
    return f"{c['book']}-p{c['page']}c{c['col']}-{c['end']}-{c['label']}"


def test_fixture_set_shape():
    """测试集的构成钉住：坏例好例都在，五册都有，难负例在。"""
    labels = [c["label"] for c in CASES]
    assert labels.count("residue") >= 40 and labels.count("clean") >= 40
    assert {c["book"] for c in CASES} == {"v006", "v007", "v008", "v009", "v010"}
    assert any(c.get("hard") == "wide_bottom" for c in CASES)
    assert any(c.get("hard") == "yi_above_rule" for c in CASES)


@pytest.mark.parametrize("c", STRIP, ids=_id)
def test_strip_end_rule(c):
    if c["label"] == "residue" and not c.get("fixed", True):
        pytest.xfail("已知漏检（斜线/粗线半峰宽>9、或列图里线断到覆盖<0.8），见 cases.jsonl 的 miss")
    patch, cov = _load(c)
    out, seg = strip_end_rule(patch, c["cell_h"], bottom=(c["end"] == "tail"), col_cov=cov)
    g = _glyph_rows(c, patch.shape[0])
    # 线以内的字：一个像素都不许动
    assert np.array_equal(out[g], patch[g])
    if c["label"] == "clean":
        assert np.array_equal(out, patch)
        return
    assert seg is not None
    # 线以外（含线本身）：只许留笔画接在线上的桩
    r = c["rule"] - c["patch_row_off"]
    outer = out[r + 1:] if c["end"] == "tail" else out[:max(0, r)]
    assert int((outer < 128).sum()) <= 80
    if c.get("hard") == "yi_above_rule":
        # 剥掉线后单剩一个「一」：不能被当成「只装着框线」的格判空
        n_pre, n_now = int((patch < 128).sum()), int((out < 128).sum())
        assert not (n_now < min(EX.END_RULE_LEFT_PX, EX.END_RULE_LEFT_FRAC * n_pre))


@pytest.mark.parametrize("c", RAISED, ids=_id)
def test_raised_frame_bar(c):
    tight = cv2.imread(str(FIX / f"{c['fixture']}.tight.png"), cv2.IMREAD_GRAYSCALE)
    cc = SimpleNamespace(period=c["period"], content_x=tuple(c["content_x"]),
                         cells=[SimpleNamespace(slot=-1, sub=None, y0=c.get("cell_y0", 0.0))])
    bbox = tuple(c["bbox"])
    new = _is_raised_frame_bar(-1, "char", bbox, cc, 0.65, tight)
    if c["label"] == "frame_bar":
        assert _bar_like(tight) and new
        # 四庫口径（0.4 格高）放它当字——这正是要书级放宽的原因
        assert not _is_raised_frame_bar(-1, "char", bbox, cc, None, tight)
    else:
        assert not _bar_like(tight) and not new


def test_default_off_and_fingerprinted():
    """缺省关（四庫各册行为不变）；开关进了 Step4 指纹，改了会重跑。"""
    from open_guji_cv.core.book import BookSpec
    import dataclasses
    f = {x.name: x.default for x in dataclasses.fields(BookSpec)}
    assert f["end_rule_strip"] is False and f["raised_bar_max_h"] is None
    deps = CellShrinkStep.spec.book_deps
    assert "end_rule_strip" in deps and "raised_bar_max_h" in deps
