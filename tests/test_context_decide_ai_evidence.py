# -*- coding: utf-8 -*-
"""Step6 词典+AI 证据导回（2026-09-27，D-Step6）。

方案：overview 进度/Step6-上下文裁决/方案-词典加AI接入管线.md §三、§七。
- 没接 AI 的书：参数 dump 不多任何键，`params_hash` 与加字段前逐位相同；
- 接了：指纹随证据文件内容变（换文件 → 产物判过期）；
- `run_page` 只把 groups/ai 挂上去，char/margin/source/ranked 一概不动（只进产物、不改放行）；
- 书级 `step6_ai:` 经 `params_for` 填进参数（指纹与 run_page 同一份）。
不训 LM：`_decider` 换成固定打分的假裁决器。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import open_guji_cv.steps  # noqa: F401
from open_guji_cv.core.engine import params_hash
from open_guji_cv.steps.context_decide import (ContextDecideParams, ContextDecideStep,
                                               load_ai_evidence)
from tests.helpers import make_book, make_ctx, page_match, write_product

AI_KEYS = {"ai_evidence", "ai_evidence_fingerprint"}


def _evidence_line(key: str) -> dict:
    return {"key": key,
            "img": {"consensus": None, "lib_top": "甲", "ocr_top": "乙"},   # 核对用，导回时忽略
            "groups": [{"id": "A", "members": ["甲", "𤰔"], "why": "異體（測試）"},
                       {"id": "B", "members": ["乙"], "why": ""}],
            "ai": {"runs": 2, "drop": [], "drop_why": [],
                   "rank": [{"group": "A", "p": 0.9, "why": "上下文"}, {"group": "B", "p": 0.1, "why": ""}],
                   "confidence": "高", "need_human": "", "conflict_with_img": False,
                   "runs_top": ["甲", "甲"], "fingerprint": {"model": "muse", "prompt": "v4n"}}}


def _write_evidence(path, keys):
    path.write_text("".join(json.dumps(_evidence_line(k), ensure_ascii=False) + "\n" for k in keys),
                    encoding="utf-8")
    return path


def test_no_ai_keeps_params_dump_and_hash(tmp_path):
    corpus = tmp_path / "c.txt"
    corpus.write_text("甲乙丙", encoding="utf-8")
    p = ContextDecideParams(corpus=str(corpus))
    d = p.model_dump(mode="json")
    assert not AI_KEYS & set(d)
    # 显式传空值与不传完全等价
    assert params_hash(ContextDecideParams(corpus=str(corpus), ai_evidence="")) == params_hash(p)


def test_fingerprint_tracks_evidence_content(tmp_path):
    corpus = tmp_path / "c.txt"
    corpus.write_text("甲乙丙", encoding="utf-8")
    ev = _write_evidence(tmp_path / "ai.jsonl", ["tbook:1:1:2"])
    p1 = ContextDecideParams(corpus=str(corpus), ai_evidence=str(ev))
    assert p1.ai_evidence_fingerprint not in ("", "missing")
    assert AI_KEYS <= set(p1.model_dump(mode="json"))
    _write_evidence(ev, ["tbook:1:1:2", "tbook:1:1:3"])
    p2 = ContextDecideParams(corpus=str(corpus), ai_evidence=str(ev))
    assert p2.ai_evidence_fingerprint != p1.ai_evidence_fingerprint
    assert params_hash(p2) != params_hash(p1)


def test_missing_evidence_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_ai_evidence(str(tmp_path / "nope.jsonl"), "fp-missing-test")


class _FakeDecider:
    """固定选「甲」、margin 0.9，看 AI 证据挂上去以后裁决字段是否原样。"""

    def decide(self, priors, context=()):
        ranked = sorted(priors.items(), key=lambda kv: -kv[1])
        return SimpleNamespace(margin=0.9, surface="甲",
                               decision=SimpleNamespace(ranked=ranked, used_context=True))


def _run(tmp_path, monkeypatch, ai_path: str):
    corpus = tmp_path / "c.txt"
    corpus.write_text("甲乙丙", encoding="utf-8")
    ctx = make_ctx(tmp_path / ("with" if ai_path else "without"))
    write_product(ctx, "glyph_match", 1, glyph_match=page_match(recs=[
        {"slot": 1, "verdict": "same", "char": "丙", "cov": 0.99},
        {"slot": 2, "verdict": "unsure", "candidates": [("甲", 0.95), ("乙", 0.94)]},
    ]))
    ctx.params["context_decide"] = ContextDecideParams(corpus=str(corpus), ai_evidence=ai_path)
    step = ContextDecideStep()
    monkeypatch.setattr(step, "_decider", lambda p: _FakeDecider())
    return step.run_page(ctx, 1)["context_decision"]


def test_run_page_attaches_evidence_without_touching_decision(tmp_path, monkeypatch):
    ev = _write_evidence(tmp_path / "ai.jsonl", ["tbook:1:1:2", "tbook:9:9:9"])   # 后一格不在本页
    base = _run(tmp_path, monkeypatch, "")
    got = _run(tmp_path, monkeypatch, str(ev))
    b = {r.id: r for c in base.columns for r in c.chars}
    g = {r.id: r for c in got.columns for r in c.chars}
    assert b.keys() == g.keys()
    for k in b:
        assert (g[k].char, g[k].margin, g[k].source, g[k].ranked) == \
               (b[k].char, b[k].margin, b[k].source, b[k].ranked)
        assert b[k].groups == [] and b[k].ai is None
    assert g["tbook:1:1:1"].ai is None and g["tbook:1:1:1"].groups == []
    rec = g["tbook:1:1:2"]
    assert [x.id for x in rec.groups] == ["A", "B"]
    assert rec.ai is not None and rec.ai.runs_top == ["甲", "甲"] and rec.ai.rank[0].group == "A"


def test_book_step6_ai_fills_params(tmp_path, monkeypatch):
    monkeypatch.setenv("GUJI_WORKSPACE", str(tmp_path))
    _write_evidence(tmp_path / "ai.jsonl", ["tbook:1:1:2"])
    corpus = tmp_path / "c.txt"
    corpus.write_text("甲乙丙", encoding="utf-8")
    step = ContextDecideStep()

    ctx = make_ctx(tmp_path / "a", book=make_book(step6_ai="ai.jsonl"))
    ctx.params["context_decide"] = ContextDecideParams(corpus=str(corpus))
    p = ctx.params_for(step)
    assert p.ai_evidence == str(tmp_path / "ai.jsonl")
    assert p.ai_evidence_fingerprint not in ("", "missing")

    ctx0 = make_ctx(tmp_path / "b")                                   # 书没配 step6_ai
    ctx0.params["context_decide"] = ContextDecideParams(corpus=str(corpus))
    p0 = ctx0.params_for(step)
    assert p0.ai_evidence == "" and not AI_KEYS & set(p0.model_dump(mode="json"))
    assert params_hash(p0) != params_hash(p)
