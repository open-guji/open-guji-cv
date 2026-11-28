"""第三步看图 `glyph_vis` 的离线 ask 导出／导入（`feedback/vis_queue`，入口 `llm_queue vis-export／vis-import`）。

导出去重、跳过已答、题图与在线送模型的同口径（sha 一致）、字块变了不出题、导入写回后 glyph_vis 再跑命中、
候选不符拒收、重复导入幂等。全部自造数据，不调任何外部服务。
"""
from __future__ import annotations

import base64
import hashlib
import json

import numpy as np
import pytest
from helpers import (
    make_book,
    make_ctx,
    page_chars,
    page_match,
    run_steps,
    write_product,
)

import open_guji_cv.steps  # noqa: F401  注册各步
from open_guji_cv.feedback import llm_queue as Q
from open_guji_cv.feedback import vis_queue as VQ
from open_guji_cv.feedback.vis_glyph import SUBDIR, VisGlyphStore
from open_guji_cv.groups import vis_img as V
from open_guji_cv.products.kinds.read import ColumnNear, NearRec, PageNear

ZY = {"chars": ["于", "千", "子", "干"]}
CANDS = V.sort_cands(ZY["chars"])


def _patch(seed):
    g = np.full((40, 36), 255, np.uint8)
    g[5 + seed:30, 10:20 + seed] = 0
    return g


@pytest.fixture
def fb(tmp_path, monkeypatch):
    d = tmp_path / "feedback"
    monkeypatch.setenv("GUJI_FEEDBACK_DIR", str(d))
    monkeypatch.delenv("GUJI_LLM_ONLINE", raising=False)
    return d


def _book(tmp_path, vis_params: dict, images: dict[int, int], page: int = 1, ctx=None):
    """一页：每格 3b 全弃权（都触发 near_abstain）、3a 于／千相持。`images={格: 图种子}`，种子相同＝同一张图。"""
    if ctx is None:
        book = make_book("tbook", params={"glyph_near": {"groups": {"zy": ZY}},
                                          "glyph_vis": {"enabled": True, "skip_half": False, **vis_params}})
        ctx = make_ctx(tmp_path, book)
    slots = sorted(images)
    recs = [{"slot": s, "verdict": "unsure", "candidates": [("于", 0.90), ("千", 0.80)]} for s in slots]
    write_product(ctx, "glyph_match", page, glyph_match=page_match(page=page, recs=recs))
    write_product(ctx, "cell_shrink", page, char_index=page_chars(page=page, recs=[
        {"slot": s, "bbox_page": (30.0, 10.0 + 50 * s, 70.0, 50.0 + 50 * s), "patch_key": f"p{page:04d}c01s{s}"}
        for s in slots]))
    for s, seed in images.items():
        ctx.cache.put("tbook", "char_patch", f"p{page:04d}c01s{s}", _patch(seed))
    chars = [NearRec(id=f"tbook:{page}:1:{s}", slot=s, group="zy", trigger="cands", methods=[]) for s in slots]
    write_product(ctx, "glyph_near", page, glyph_near=PageNear(page=page, columns=[ColumnNear(col=1, chars=chars)]))
    run_steps(ctx, page, ["glyph_vis"])
    return ctx


def _seed(fb, seed, model, char="千"):
    VisGlyphStore(fb).put(img_sha=V.img_sha(_patch(seed)), img_shape=(40, 36), patch="char_patch", prompt="vis-img-1",
                          prompt_sha=V.prompt_sha("vis-img-1"), cands=CANDS, char=char, conf="high", why="x", model=model)


def _events(fb):
    return [x for f in sorted((fb / SUBDIR).glob("*.jsonl")) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]


# ── 导出 ─────────────────────────────────────────────────────────────

def test_export_dedups_and_skips_answered(tmp_path, fb):
    ctx = _book(tmp_path, {"model": "cfg-model", "accept_models": ["session:A24"]}, {1: 1, 2: 2, 3: 1, 4: 4})
    _book(tmp_path, {}, {1: 1, 2: 5}, page=2, ctx=ctx)                         # 第 2 页格 1 与第 1 页格 1、3 同图
    _seed(fb, 2, "cfg-model")                                                 # 跑完才有答案：产物仍 pending，导出要跳过
    _seed(fb, 4, "session:A24")                                               # accept_models 认的也算已答
    _seed(fb, 5, "session:B99")                                               # 本书不认：照出题
    rows, pngs, rep = VQ.collect([(ctx, None)])
    assert [r["cells"] for r in rows] == [["tbook:1:1:1", "tbook:1:1:3", "tbook:2:1:1"], ["tbook:2:1:2"]]
    assert [r["id"] for r in rows] == ["q0001", "q0002"] and sorted(pngs) == ["q0001", "q0002"]
    assert rep["pending_cells"] == 6 and rep["answered_cells"] == 2 and rep["questions"] == 2 and rep["cells"] == 4
    r = rows[0]
    assert (r["img_sha"], r["prompt"], r["prompt_sha"], r["cands"]) == (V.img_sha(_patch(1)), "vis-img-1",
                                                                          V.prompt_sha("vis-img-1"), CANDS)
    assert r["models"] == ["cfg-model", "session:A24"] and r["img_shape"] == [40, 36] and r["img"] == "img/q0001.png"
    assert r["key"] == VQ.qkey(r["img_sha"], r["prompt_sha"], r["cands"])
    # 只扫第 2 页
    rows2, _, _ = VQ.collect([(ctx, [2])])
    assert [x["cells"] for x in rows2] == [["tbook:2:1:1"], ["tbook:2:1:2"]]


def test_export_png_same_as_online(tmp_path, fb):
    """题图就是在线送模型的那张：与 `vis_img.user_content` 里的图逐字节相同，候选行也相同。"""
    ctx = _book(tmp_path, {}, {1: 3})
    rows, pngs, _ = VQ.collect([(ctx, None)])
    online = V.user_content(_patch(3), CANDS, "vis-img-1")
    assert pngs["q0001"] == base64.b64decode(online[0]["source"]["data"])
    assert rows[0]["png_sha"] == hashlib.sha256(pngs["q0001"]).hexdigest()[:16]
    assert rows[0]["options"] == online[1]["text"]
    out = tmp_path / "out"
    VQ.write_export(out, rows, pngs)
    assert (out / "img" / "q0001.png").read_bytes() == pngs["q0001"]
    assert [json.loads(x) for x in (out / VQ.MANIFEST).read_text(encoding="utf-8").splitlines()] == rows
    md = (out / VQ.PROMPT_FILE).read_text(encoding="utf-8")
    assert V.SYSTEM_IMG_1 in md and V.USER_TMPL_1 in md


def test_export_skips_changed_or_missing_patch_and_stale_prompt(tmp_path, fb, monkeypatch):
    ctx = _book(tmp_path, {}, {1: 1, 2: 2, 3: 3})
    ctx.cache.put("tbook", "char_patch", "p0001c01s2", _patch(7))              # 跑完后字块变了
    ctx.cache.path("tbook", "char_patch", "p0001c01s3").unlink()               # 字块没了（也现算不出：没有上游）
    rows, _, rep = VQ.collect([(ctx, None)])
    assert [r["cells"] for r in rows] == [["tbook:1:1:1"]]
    assert rep["img_changed"] == 1 and rep["patch_missing"] == 1
    monkeypatch.setattr(V, "RENDER_VER", "r2:test")                           # 渲染口径改了：旧 ask 的 prompt_sha 作废
    rows, _, rep = VQ.collect([(ctx, None)])
    assert rows == [] and rep["stale_prompt"] == 3


# ── 导入 ─────────────────────────────────────────────────────────────

def _answers(rows, **kw):
    return [{**r, "char": "千", "conf": "high", "why": "竖出头", **kw} for r in rows]


def test_import_then_glyph_vis_hits_and_idempotent(tmp_path, fb):
    ctx = _book(tmp_path, {"accept_models": ["session:A24"]}, {1: 1, 2: 2})
    rows, _, _ = VQ.collect([(ctx, None)])
    ans = _answers(rows[:1]) + [{**rows[1], "char": V.OTHER, "conf": "low", "why": "残"}]
    rep = VQ.import_answers(ans, rows, name="A24")
    assert (rep["model"], rep["written"], rep["rejected"], rep["not_accepted"]) == ("session:A24", 2, [], False)
    n = len(_events(fb))
    assert n == 2 and all(json.loads(x)["payload"]["model"] == "session:A24" for x in _events(fb))
    by = run_steps(ctx, 1, ["glyph_vis"])["glyph_vis"].by_id()
    a, b = by["tbook:1:1:1"], by["tbook:1:1:2"]
    assert (a.status, a.char, a.conf, a.model, a.cache_hit) == ("hit", "千", "high", "session:A24", True)
    assert b.status == "hit" and b.other is True and b.char is None
    assert VQ.collect([(ctx, None)])[0] == []                                  # 都答了：再导出为空
    rep = VQ.import_answers(ans, rows, name="session:A24")                    # 幂等：不再写
    assert (rep["written"], rep["updated"], rep["unchanged"]) == (0, 0, 2) and len(_events(fb)) == n
    rep = VQ.import_answers(_answers(rows[:1], char="于"), rows, name="A24")   # 改了答案：追加一条，后到覆盖
    assert rep["updated"] == 1 and len(_events(fb)) == n + 1
    assert run_steps(ctx, 1, ["glyph_vis"])["glyph_vis"].by_id()["tbook:1:1:1"].char == "于"


def test_import_rejects_and_reports(tmp_path, fb):
    ctx = _book(tmp_path, {}, {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6})
    rows, _, _ = VQ.collect([(ctx, None)])
    q = {r["id"]: r for r in rows}
    ans = [{**q["q0001"], "char": "言", "conf": "high"},                      # 不在候选里
           {**q["q0002"], "char": "千", "conf": "high", "cands": ["于", "千"]},  # 候选集合与 manifest 不符
           {**q["q0003"], "char": "千", "conf": "sure"},                       # conf 不认
           {**q["q0004"], "char": "千", "conf": "high", "key": "nope"},        # manifest 里没有
           {**q["q0005"]},                                                     # 没答
           {**q["q0006"], "char": "千", "conf": "mid", "img_sha": "x" * 24}]   # 图对不上
    rep = VQ.import_answers(ans, rows, name="A24")
    assert rep["written"] == 0 and rep["unanswered"] == 1 and rep["not_accepted"] is False
    assert [r["id"] for r in rep["rejected"]] == ["q0001", "q0002", "q0003", "q0004", "q0006"]
    assert "不在候选里" in rep["rejected"][0]["why"]
    assert not (fb / SUBDIR).exists()
    rep = VQ.import_answers(_answers([q["q0005"]]), rows, name="A24")         # 本书没认 session:A24：照写，但提示
    assert rep["written"] == 1 and rep["not_accepted"] is True


def test_import_rejects_stale_prompt(tmp_path, fb, monkeypatch):
    ctx = _book(tmp_path, {}, {1: 1})
    rows, _, _ = VQ.collect([(ctx, None)])
    monkeypatch.setattr(V, "RENDER_VER", "r2:test")
    rep = VQ.import_answers(_answers(rows), rows, name="A24")
    assert rep["written"] == 0 and "提示词" in rep["rejected"][0]["why"]


def test_session_model_needs_name():
    assert VQ.session_model("A24") == VQ.session_model("session:A24") == "session:A24"
    with pytest.raises(ValueError):
        VQ.session_model(" ")


def test_parse_pages():
    assert VQ.parse_pages(None) is None and VQ.parse_pages("all") is None
    assert VQ.parse_pages("3,1-2,2") == [1, 2, 3]


# ── 命令行（llm_queue 同一命令组） ────────────────────────────────────

def test_cli_vis_export_import_roundtrip(tmp_path, fb, monkeypatch, capsys):
    ctx = _book(tmp_path, {"accept_models": ["session:A24"]}, {1: 1, 2: 1})
    monkeypatch.setattr(VQ, "book_ctx", lambda b, products=None: ctx)
    out = tmp_path / "q"
    assert Q.main(["vis-export", "tbook", "--out", str(out)]) == 0
    rows = VQ.read_jsonl(out / VQ.MANIFEST)
    assert len(rows) == 1 and rows[0]["cells"] == ["tbook:1:1:1", "tbook:1:1:2"] and (out / "img" / "q0001.png").exists()
    assert Q.main(["vis-export", "tbook", "--out", str(out)]) == 2               # 已有 manifest：不覆盖
    (out / "answers.jsonl").write_text("".join(json.dumps(a, ensure_ascii=False) + "\n" for a in _answers(rows)),
                                       encoding="utf-8")
    assert Q.main(["vis-import", str(out / "answers.jsonl"), "--name", "A24"]) == 0
    assert "--from glyph_vis --force" in capsys.readouterr().err
    by = run_steps(ctx, 1, ["glyph_vis"])["glyph_vis"].by_id()
    assert {v.status for v in by.values()} == {"hit"}
    bad = [{**rows[0], "char": "言", "conf": "high"}]
    (out / "bad.jsonl").write_text(json.dumps(bad[0], ensure_ascii=False) + "\n", encoding="utf-8")
    assert Q.main(["vis-import", str(out / "bad.jsonl"), "--name", "A24"]) == 1   # 有拒收：非零退出
