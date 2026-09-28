# -*- coding: utf-8 -*-
"""Step7「切分裁决」默认选中 U-Net 与 verdict 口径（overview#188，2026-09-28）。

三层：
- `review/cutline_default.py`：书级开关 `params.review.cutline_default` 与每卡默认项；
- `/api/cutline/cases`：把 `default_idx`／`default_pick`／`cutline_default` 下发给前端；
- 前端 `components/cutline/cutlineVerdict.ts`：落定时 ok/moved 跟默认项比，另记
  `picked_source`／`default_pick`。这层用 node 的 `--experimental-strip-types` 直接跑源码
  （node ≥ 22.6；没有 node 的机器 skip——前端构建本来就要 node，缺的是可选件不是数据）。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from open_guji_cv.gold.atomic import CUTLINE_KEYS
from open_guji_cv.review.cutline_default import (attach_default_pick, cutline_default_mode,
                                                 default_pick)

CANDS = [{"kind": "straight"}, {"kind": "seam_narrow"}, {"kind": "unet_seam"}]


def _book(review: dict | None):
    return SimpleNamespace(params={} if review is None else {"review": review})


# ── 书级开关 ─────────────────────────────────────────────────────────

def test_mode_defaults_to_unet():
    assert cutline_default_mode(_book(None)) == "unet"
    assert cutline_default_mode(_book({})) == "unet"
    assert cutline_default_mode(SimpleNamespace()) == "unet"      # 老 BookSpec 没有 params


def test_mode_reads_book_param():
    assert cutline_default_mode(_book({"cutline_default": "chosen"})) == "chosen"
    assert cutline_default_mode(_book({"cutline_default": "unet"})) == "unet"


def test_mode_rejects_typo():
    with pytest.raises(ValueError, match="cutline_default"):
        cutline_default_mode(_book({"cutline_default": "engine"}))


# ── 每卡默认项 ───────────────────────────────────────────────────────

def test_default_pick_prefers_unet():
    assert default_pick(CANDS, 0, "unet") == (2, "unet")


def test_default_pick_falls_back_to_chosen_without_unet():
    assert default_pick(CANDS[:2], 1, "unet") == (1, "chosen")
    assert default_pick([], None, "unet") == (None, "chosen")


def test_default_pick_chosen_mode_ignores_unet():
    assert default_pick(CANDS, 0, "chosen") == (0, "chosen")


def test_attach_default_pick_in_place():
    cases = [{"candidates": CANDS, "chosen": 0}, {"candidates": [], "chosen": None}]
    attach_default_pick(cases, "unet")
    assert [(c["default_idx"], c["default_pick"]) for c in cases] == [(2, "unet"), (None, "chosen")]


def test_new_event_fields_reach_touching_cuts_gold():
    """来源字段要进金标（`_expected_of` 只留 CUTLINE_KEYS），且与 y/cand 同组整组替换。"""
    from open_guji_cv.feedback.consumers import _expected_of
    from open_guji_cv.feedback.events import EventTarget, make_event
    assert {"picked_source", "default_pick"} <= set(CUTLINE_KEYS)
    e = make_event("b", 1, "cutline",
                   EventTarget(step="row_segment", unit="boundary", key="vol02:3:4:17",
                               book="vol02", page=3, col=4, slot=17),
                   {"y": 10, "y_old": 10, "verdict": "ok", "cand": "unet_seam",
                    "picked_source": "unet", "default_pick": "unet"})
    ex = _expected_of(e)
    assert ex["picked_source"] == "unet" and ex["default_pick"] == "unet"


# ── 接口 ─────────────────────────────────────────────────────────────

def _call_cases(monkeypatch, review: dict | None, candidates: list[dict], chosen: int | None):
    import open_guji_cv.eval.touching as T
    import open_guji_cv.review.cards as cards
    from open_guji_cv.console import deps
    from open_guji_cv.console.routers import cutline as R

    case = {"id": "vol02:3:4:17", "page": 3, "col": 4, "y": 100, "y0": 80, "y1": 120,
            "col_h": 2000, "slot_above": 17, "slot_below": 18}
    monkeypatch.setattr(R, "load_book", lambda b: _book(review))
    monkeypatch.setattr(deps, "product_store", lambda: None)
    monkeypatch.setattr(cards, "blocking_cutline_cases", lambda book, pg, st: [dict(case)])
    monkeypatch.setattr(T, "std_grid_pages", lambda book: [3])
    monkeypatch.setattr(T, "attach_expected", lambda picked, book, st: None)
    R._cutline_expected_cache.clear()

    def fake_attach(st, book, picked):
        for c in picked:
            c["candidates"], c["chosen"] = [dict(x) for x in candidates], chosen
    monkeypatch.setattr(R, "_attach_candidates", fake_attach)
    return R.api_cutline_cases(book="vol02", pages="body", scope="blocking", batch=None)


def test_api_sends_unet_default(monkeypatch):
    d = _call_cases(monkeypatch, None, CANDS, 0)
    assert d["cutline_default"] == "unet"
    c = d["cases"][0]
    assert (c["default_idx"], c["default_pick"], c["chosen"]) == (2, "unet", 0)


def test_api_respects_book_switch(monkeypatch):
    d = _call_cases(monkeypatch, {"cutline_default": "chosen"}, CANDS, 0)
    assert d["cutline_default"] == "chosen"
    assert (d["cases"][0]["default_idx"], d["cases"][0]["default_pick"]) == (0, "chosen")


def test_api_bad_switch_is_400(monkeypatch):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        _call_cases(monkeypatch, {"cutline_default": "nope"}, CANDS, 0)
    assert ei.value.status_code == 400


# ── 前端口径（node 跑 cutlineVerdict.ts）────────────────────────────

TS = (Path(__file__).resolve().parents[1]
      / "open_guji_cv/console/frontend/src/components/cutline/cutlineVerdict.ts")


def _node_ok() -> bool:
    node = shutil.which("node")
    if not node:
        return False
    r = subprocess.run([node, "--experimental-strip-types", "-e", "0"], capture_output=True)
    return r.returncode == 0


needs_node = pytest.mark.skipif(not _node_ok(), reason="没有支持 --experimental-strip-types 的 node（≥22.6）")


def _run_ts(tmp_path, calls: list) -> list:
    """每个 call = [case, pick, drawn, verdict]，返回 decideFields 的结果。"""
    mod = tmp_path / "cutlineVerdict.mts"      # .mts：按 ES 模块加载，不依赖 package.json 的 type
    shutil.copy(TS, mod)
    runner = tmp_path / "run.mts"
    runner.write_text(
        "import { decideFields, defaultPick } from './cutlineVerdict.mts'\n"
        f"const calls = {json.dumps(calls)}\n"
        "console.log(JSON.stringify(calls.map(([c, k, d, v]) => ({ ...decideFields(c, k, d, v), _def: defaultPick(c).idx }))))\n",
        encoding="utf-8")
    r = subprocess.run([shutil.which("node"), "--experimental-strip-types", "--no-warnings", str(runner)],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


@needs_node
def test_ts_verdict_is_relative_to_default(tmp_path):
    unet_card = {"candidates": CANDS, "chosen": 0, "default_idx": 2, "default_pick": "unet"}
    plain_card = {"candidates": CANDS[:2], "chosen": 1, "default_idx": 1, "default_pick": "chosen"}
    out = _run_ts(tmp_path, [
        [unet_card, 2, False, "confirmed"],    # 一路 Enter 认可 U-Net
        [unet_card, 0, False, "confirmed"],    # 改回引擎 chosen
        [unet_card, 1, False, "confirmed"],    # 改选别的候选
        [unet_card, 2, True, "confirmed"],     # 自己画
        [unet_card, 2, False, "idk"],
        [plain_card, 1, False, "confirmed"],   # 没 U-Net：确认引擎
    ])
    assert out[0] == {"verdict": "ok", "picked_source": "unet", "default_pick": "unet", "_def": 2}
    assert out[1] == {"verdict": "moved", "picked_source": "engine", "default_pick": "unet", "_def": 2}
    assert out[2] == {"verdict": "moved", "picked_source": "alt", "default_pick": "unet", "_def": 2}
    assert out[3] == {"verdict": "moved", "picked_source": "hand", "default_pick": "unet", "_def": 2}
    assert out[4] == {"verdict": "idk", "default_pick": "unet", "_def": 2}
    assert out[5] == {"verdict": "ok", "picked_source": "engine", "default_pick": "chosen", "_def": 1}


@needs_node
def test_ts_falls_back_when_backend_omits_default(tmp_path):
    """老后端没下发 default_idx 时前端自己算同一口径。"""
    out = _run_ts(tmp_path, [
        [{"candidates": CANDS, "chosen": 0}, 2, False, "confirmed"],
        [{"candidates": CANDS[:2], "chosen": 1}, 1, False, "confirmed"],
    ])
    assert out[0]["verdict"] == "ok" and out[0]["_def"] == 2 and out[0]["default_pick"] == "unet"
    assert out[1]["verdict"] == "ok" and out[1]["_def"] == 1 and out[1]["default_pick"] == "chosen"


@needs_node
def test_ts_engine_wins_when_engine_also_picked_unet(tmp_path):
    """引擎自己也选了 U-Net：认可它 = 认可引擎（picked_source=engine，引擎没错）。"""
    card = {"candidates": CANDS, "chosen": 2, "default_idx": 2, "default_pick": "unet"}
    out = _run_ts(tmp_path, [[card, 2, False, "confirmed"]])
    assert out[0]["verdict"] == "ok" and out[0]["picked_source"] == "engine"
