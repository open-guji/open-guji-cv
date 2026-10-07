# -*- coding: utf-8 -*-
"""A/B 实验框架（`open_guji_cv/exp/`，overview#457）的单元测试。数据全部自造：

- 跑批那段用两步合成 Step（上游 `t_exp_up` → 下游 `t_exp_down`），只测编排：上游复用不重算、
  快照不被写、各变体落各自的根、参数覆盖层生效、拒写正式 products/；
- 比较那段直接造 `seed_admit` 形状的格与标签，测翻转分类、picked 不出错率、分母 0 记无检验力、
  判准、自助法可复现。真书上的数字归评测报告，不进这里。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import BaseModel

import open_guji_cv.steps  # noqa: F401
from helpers import make_book
from open_guji_cv.core.pipeline import Pipeline
from open_guji_cv.core.spec import ProductKindSpec, StepSpec
from open_guji_cv.core.step import KINDS, STEPS, Step, register_kind, register_step
from open_guji_cv.errors import BadRequest
from open_guji_cv.exp import compare as C
from open_guji_cv.exp import config as EC
from open_guji_cv.exp import flips as FL
from open_guji_cv.exp import labels as LB
from open_guji_cv.exp import report as RP
from open_guji_cv.exp import runner as RN
from open_guji_cv.exp import stats as S
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore


# ── 合成两步 ─────────────────────────────────────────────────────────────
class _Up(BaseModel):
    page: int
    v: float


class _Down(BaseModel):
    page: int
    v: float


if "t_exp_up" not in KINDS:
    register_kind(ProductKindSpec(id="t_exp_up", title="up", storage="numeric", unit="page", schema=_Up))
    register_kind(ProductKindSpec(id="t_exp_down", title="down", storage="numeric", unit="page", schema=_Down))


class _UpParams(BaseModel):
    k: float = 1.0


class _DownParams(BaseModel):
    gain: float = 1.0
    flag: bool = False


CALLS = {"up": 0, "down": 0}

if "t_exp_up_step" not in STEPS:
    @register_step
    class _UpStep(Step):
        spec = StepSpec(id="t_exp_up_step", title="up", version="1", unit="page",
                        consumes=(), produces=("t_exp_up",), params=_UpParams)

        def run_page(self, ctx, page):
            CALLS["up"] += 1
            return {"t_exp_up": _Up(page=page, v=float(page))}

    @register_step
    class _DownStep(Step):
        spec = StepSpec(id="t_exp_down_step", title="down", version="1", unit="page",
                        consumes=("t_exp_up",), produces=("t_exp_down",), params=_DownParams)

        def run_page(self, ctx, page):
            CALLS["down"] += 1
            p = ctx.params_for(self)
            up = ctx.store.read(ctx.book.id, "t_exp_up_step", f"p{page:04d}", "t_exp_up")
            return {"t_exp_down": _Down(page=page, v=up.v * p.gain + (100 if p.flag else 0))}

PL = Pipeline(id="t_exp", title="", steps=["t_exp_up_step", "t_exp_down_step"])


def _snapshot(tmp_path: Path) -> Path:
    """先用引擎把上游跑进一个快照根（模拟 `guji snapshot` 出来的目录）。"""
    from open_guji_cv.core.engine import Engine
    snap = tmp_path / "snap"
    eng = Engine(make_book("tb"), PL, store=ProductStore(snap), cache=ImageCache(tmp_path / "cache"),
                 log=lambda s: None)
    eng.run(steps=["t_exp_up_step"], pages=[1, 2, 3])
    return snap


def _tree_sha(root: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(root.rglob("*")):
        if f.is_file():
            h.update(str(f.relative_to(root)).encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def _cfg(**kw) -> EC.ExpConfig:
    d = {"name": "t1", "books": ["tb"], "from": "t_exp_down_step", "to": "t_exp_down_step",
         "pipeline": "t_exp", "base": {}, "variants": {"B": {"params": {"t_exp_down_step": {"gain": 2.0}}}},
         "eval": {"params": {"t_exp_down_step": {"flag": False}}}}
    d.update(kw)
    return EC.from_dict(d)


# ── 配置 ─────────────────────────────────────────────────────────────────
def test_config_overlay_and_eval_defaults():
    cfg = _cfg()
    assert [v.name for v in cfg.variants] == ["A", "B"]
    assert cfg.run_params(cfg.base) == {"t_exp_down_step": {"flag": False},
                                        "seed_admit": {"use_human_verdicts": False}}
    assert cfg.run_params(cfg.variant("B"))["t_exp_down_step"] == {"flag": False, "gain": 2.0}
    # 变体压过评测口径
    cfg2 = _cfg(variants={"B": {"params": {"t_exp_down_step": {"flag": True}}}})
    assert cfg2.run_params(cfg2.variant("B"))["t_exp_down_step"]["flag"] is True
    # round trip（exp.yaml 里存的那份能读回同一个配置）
    back = EC.from_dict(cfg.to_dict())
    assert back.run_params(back.variant("B")) == cfg.run_params(cfg.variant("B"))


def test_config_rejects_unknown_param():
    """pydantic 缺省吞掉多余字段——不在这里拦，开关写错名两边就跑成一样。"""
    cfg = _cfg(variants={"B": {"params": {"seed_admit": {"no_such_switch": True}}}})
    with pytest.raises(BadRequest, match="no_such_switch"):
        EC.validate_params(cfg)
    cfg = _cfg(variants={"B": {"params": {"seed_admit": {"shadow_veto": True, "shadow_conf": 0.8}}}})
    EC.validate_params(cfg)


@pytest.mark.parametrize("bad", [
    {"variants": {}}, {"books": []}, {"variants": {"B": {"code": "abc"}}}, {"nope": 1},
    {"variants": {"A": {}}},
])
def test_config_rejects_bad(bad):
    with pytest.raises(BadRequest):
        _cfg(**bad)


def test_config_short_form(tmp_path):
    (tmp_path / "veto.yaml").write_text("seed_admit: {shadow_veto: true}\n", encoding="utf-8")
    cfg = EC.from_pair(None, [tmp_path / "veto.yaml"], books=["vol05"])
    assert [v.name for v in cfg.variants] == ["A", "veto"]
    assert cfg.variant("veto").params == {"seed_admit": {"shadow_veto": True}}


# ── 跑批编排 ─────────────────────────────────────────────────────────────
def test_run_reuses_upstream_and_isolates_variants(tmp_path):
    snap = _snapshot(tmp_path)
    before = _tree_sha(snap)
    CALLS.update(up=0, down=0)
    cfg = _cfg()
    st = RN.run(cfg, snapshot=snap, root=tmp_path / "exps", pipeline=PL,
                book_loader=lambda b: make_book(b), cache=ImageCache(tmp_path / "cache"), log=lambda s: None)
    edir = tmp_path / "exps" / "t1"
    assert CALLS == {"up": 0, "down": 6}            # 上游一次没跑；两个变体各 3 页
    assert _tree_sha(snap) == before                # 快照一个字节没动
    a = ProductStore(edir / "A").read("tb", "t_exp_down_step", "p0002", "t_exp_down")
    b = ProductStore(edir / "B").read("tb", "t_exp_down_step", "p0002", "t_exp_down")
    assert (a.v, b.v) == (2.0, 4.0)
    assert not (snap / "tb" / "t_exp_down_step").exists()
    up = edir / "A" / "tb" / "t_exp_up_step" / "p0001.json"
    assert up.stat().st_ino == (snap / "tb" / "t_exp_up_step" / "p0001.json").stat().st_ino   # 硬链接
    assert st["steps"] == ["t_exp_down_step"] and set(st["runs"]) == {"A/tb", "B/tb"}
    assert (edir / "exp.yaml").exists()
    # 再跑一次：指纹新鲜，一页不重算
    RN.run(cfg, snapshot=snap, root=tmp_path / "exps", pipeline=PL, book_loader=lambda b: make_book(b),
           cache=ImageCache(tmp_path / "cache"), log=lambda s: None)
    assert CALLS["down"] == 6


def test_run_refuses_official_products(tmp_path, monkeypatch):
    snap = _snapshot(tmp_path)
    ws = tmp_path / "ws"
    (ws / "products").mkdir(parents=True)
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    with pytest.raises(BadRequest, match="受保护"):
        RN.run(_cfg(), snapshot=snap, root=ws / "products" / "exp", pipeline=PL,
               book_loader=lambda b: make_book(b), log=lambda s: None)
    with pytest.raises(BadRequest, match="受保护"):
        RN.run(_cfg(), snapshot=snap, root=snap, pipeline=PL, book_loader=lambda b: make_book(b),
               log=lambda s: None)
    assert not (ws / "products" / "exp").exists()


# ── 比较 ─────────────────────────────────────────────────────────────────
def _cell(page, state, char, channel="match_ref", doubts=()):
    return {"page": page, "book": "vb", "state": state, "char": char, "channel": channel, "doubts": list(doubts)}


def _pair():
    """基线 A 与变体 B（像 shadow_veto：B 把 A 放行的几格拦回送审）。"""
    A, B = {}, {}
    for p in range(1, 11):
        for s in range(10):
            k = f"vb:{p}:1:{s}"
            A[k] = _cell(p, "admit", "甲")
            B[k] = _cell(p, "admit", "甲")
    A["vb:1:1:0"] = _cell(1, "admit", "日")       # 错放行，B 拦回（拦对）
    B["vb:1:1:0"] = _cell(1, "review", "日", doubts=["shadow_veto"])
    B["vb:2:1:0"] = _cell(2, "review", "甲", doubts=["shadow_veto"])   # 误拦
    A["vb:3:1:0"] = _cell(3, "review", "乙", doubts=["low_cov"])       # B 放出去，放对
    B["vb:3:1:0"] = _cell(3, "admit", "乙", channel="rare_ref")
    A["vb:4:1:0"] = _cell(4, "admit", "丙")                            # 改字：A 对 B 错
    B["vb:4:1:0"] = _cell(4, "admit", "丁")
    return A, B


def _labels(sel_err=LB.PICKED):
    L = {
        "vb:1:1:0": LB.Label("vb:1:1:0", "human", sel_err, truth="曰"),
        "vb:2:1:0": LB.Label("vb:2:1:0", "vision", LB.PICKED, truth="甲"),
        "vb:3:1:0": LB.Label("vb:3:1:0", "human", LB.PICKED, truth="乙"),
        "vb:4:1:0": LB.Label("vb:4:1:0", "gold", LB.RANDOM, truth="丙"),
    }
    for p in range(5, 11):                           # 随机抽检：放行都对
        L[f"vb:{p}:1:5"] = LB.Label(f"vb:{p}:1:5", "gold", LB.RANDOM, truth="甲")
    return L


EQ = staticmethod(lambda a, b: bool(a) and a == b)


def _pt(book, page):
    return "nonbody" if page == 10 else "body"


def test_compare_flips_and_rates():
    A, B = _pair()
    rep = C.compare({"A": A, "B": B}, "A", _labels(), _pt, same=lambda a, b: bool(a) and a == b,
                    n_boot=200, guardrails=[
                        {"metric": "review_rate", "scope": "body", "op": "<=", "ref": "base", "delta": 0.05},
                        {"metric": "flips.right_to_wrong", "op": "==", "value": 0},
                        {"metric": "admit_err_rate", "scope": "all", "op": "<=", "ref": "base"},
                        {"metric": "nope"}])["B"]
    f = rep["flips"]
    assert (f["admit_to_review"]["n"], f["admit_to_review"]["caught"], f["admit_to_review"]["wrongly_blocked"]) == (2, 1, 1)
    assert (f["review_to_admit"]["n"], f["review_to_admit"]["admit_ok"]) == (1, 1)
    assert (f["char_changed"]["n"], f["char_changed"]["a_ok_b_err"]) == (1, 1)
    assert [c["cell"] for c in f["right_to_wrong"]["cells"]] == ["vb:4:1:0"]
    assert [c["cell"] for c in f["wrong_to_right"]["cells"]] == ["vb:1:1:0"]
    body = rep["overall"]["body"]
    assert body["cells"] == 90 and rep["overall"]["nonbody"]["cells"] == 10
    assert body["admit_rate"]["A_k"] == 89 and body["admit_rate"]["B_k"] == 88
    # picked 标签（vb:1/2/3）不进错率：分母只有 random 的放行格
    e = rep["overall"]["all"]["admit_err_rate"]
    assert (e["A_k"], e["A_n"], e["B_k"], e["B_n"]) == (0, 7, 1, 7)
    assert e["B_ci"][0] < 1 / 7 < e["B_ci"][1]
    g = {x["metric"]: x["verdict"] for x in rep["guardrails"]}
    assert g == {"review_rate": "pass", "flips.right_to_wrong": "fail", "admit_err_rate": "fail", "nope": "error"}
    m = rep["mcnemar"]
    assert (m["random"]["a_ok_b_err"], m["random"]["a_err_b_ok"]) == (1, 0)
    assert (m["all"]["a_ok_b_err"], m["all"]["a_err_b_ok"]) == (1, 1)
    ch = {r["channel"]: r for r in rep["by_channel"]}
    assert ch["rare_ref"]["B"] == 1 and ch["rare_ref"]["A"] == 0
    dz = {r["doubt"]: r for r in rep["by_doubt"]}
    assert dz["shadow_veto"]["diff"] == 2 and dz["low_cov"]["diff"] == -1


def test_no_power_when_no_random_labels():
    """标签全是被挑的（审查队列、请审单）→ 不出错率，判准判不了。"""
    A, B = _pair()
    picked = {k: LB.Label(k, v.source, LB.PICKED, truth=v.truth) for k, v in _labels().items()}
    rep = C.compare({"A": A, "B": B}, "A", picked, _pt, same=lambda a, b: a == b, n_boot=100,
                    guardrails=[{"metric": "admit_err_rate", "scope": "body", "op": "<=", "ref": "base"}])["B"]
    e = rep["overall"]["body"]["admit_err_rate"]
    assert e["no_power"] and e["A"] is None and e["ci"] is None
    assert rep["guardrails"][0]["verdict"] == "unknown"


def test_human_channel_never_scored():
    """人裁通道是 Step7 抄人裁——拿人裁考它是循环，不进任何错率。"""
    A = {"vb:1:1:0": _cell(1, "human", "甲")}
    lab = {"vb:1:1:0": LB.Label("vb:1:1:0", "human", LB.RANDOM, truth="乙")}
    assert C.admit_err(A["vb:1:1:0"], lab["vb:1:1:0"], lambda a, b: a == b) is None


def test_stats_deterministic_and_sane():
    rows = [(1, 10, 2, 10)] * 20 + [(0, 10, 1, 10)] * 20
    ci1 = S.paired_bootstrap(rows, n_boot=300, seed=7)
    assert ci1 == S.paired_bootstrap(rows, n_boot=300, seed=7)
    assert ci1[0] <= 0.1 <= ci1[1]
    assert S.paired_bootstrap([(0, 0, 1, 1)], n_boot=50) is None
    assert S.mcnemar_exact(0, 0) is None
    assert S.mcnemar_exact(5, 5) == 1.0
    assert S.mcnemar_exact(0, 10) < 0.01
    lo, hi = S.wilson(0, 10)
    assert lo == 0 and 0.2 < hi < 0.35


# ── 标签读取 ─────────────────────────────────────────────────────────────
def test_label_loaders(tmp_path):
    ev = tmp_path / "events"
    ev.mkdir()
    rows = [
        {"target": {"step": "seed_admit", "unit": "cell", "book": "vb", "key": "vb:1:1:1"}, "kind": "confirm",
         "actor": "user", "ts": "2026-10-01", "payload": {"v": "confirm", "reading": "甲"}},
        {"target": {"step": "seed_admit", "unit": "cell", "book": "vb", "key": "vb:1:1:1"}, "kind": "confirm",
         "actor": "user", "ts": "2026-10-02", "payload": {"v": "confirm", "reading": "乙"}},   # 后到覆盖
        {"target": {"step": "seed_admit", "unit": "cell", "book": "vb", "key": "vb:1:1:2"}, "kind": "verdict",
         "actor": "user", "payload": {"v": "seg_defect"}},
        {"target": {"step": "seed_admit", "unit": "cell", "book": "vb", "key": "vb:1:1:3"}, "kind": "confirm",
         "actor": "model", "payload": {"v": "confirm", "reading": "丙"}},                         # 模型不算
    ]
    (ev / "vb-decide-01.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                           encoding="utf-8")
    (ev / "vb-step7-audit-1007.jsonl").write_text(json.dumps(
        {"target": {"step": "seed_admit", "unit": "cell", "book": "vb", "key": "vb:2:1:1"}, "kind": "confirm",
         "actor": "user", "payload": {"v": "confirm", "reading": "丁"}}, ensure_ascii=False) + "\n", encoding="utf-8")
    vis = tmp_path / "看图结论.jsonl"
    vis.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in [
        {"cell": "vb:3:1:1", "v": "ok", "shown": "戊"},
        {"cell": "vb:3:1:2", "v": "wrong", "shown": "日"},
        {"cell": "vb:3:1:3", "v": "unsure", "shown": "日"},
        {"cell": "vb:1:1:1", "v": "wrong", "char": "己", "shown": "甲"},
        {"cell": "zz:1:1:1", "v": "ok", "shown": "甲"},
    ]), encoding="utf-8")
    labs, counts = LB.load_all([{"source": "human_events", "path": str(ev)},
                                {"source": "vision", "path": str(vis)}], ["vb"])
    merged, conflicts = LB.merge(labs)
    assert merged["vb:1:1:1"].truth == "乙" and merged["vb:1:1:1"].selection == LB.PICKED
    assert merged["vb:1:1:2"].defect
    assert "vb:1:1:3" not in merged
    assert merged["vb:2:1:1"].selection == LB.RANDOM          # 批名带 audit → 抽检
    assert merged["vb:3:1:1"].truth == "戊" and merged["vb:3:1:2"].wrong == {"日"}
    assert "vb:3:1:3" not in merged and "zz:1:1:1" not in merged
    assert conflicts == [{"cell": "vb:1:1:1", "human": "乙", "vision": "己"}]
    assert [c["n"] for c in counts] == [3, 3]
    with pytest.raises(BadRequest):
        LB.load_all([{"source": "vision", "path": str(vis), "selection": "whatever"}], ["vb"])


# ── 报告 + 翻转页（端到端，产物直接造成 seed_admit 的形状）─────────────────
def _write_seed_admit(root: Path, book: str, cells: dict):
    by_page: dict[int, list] = {}
    for k, c in cells.items():
        st = c["state"]
        by_page.setdefault(c["page"], []).append(
            {"id": k, "char": c["char"], "admit": st in ("admit", "human"), "channel": c["channel"],
             "provenance": "human" if st == "human" else "auto", "doubts": c["doubts"]})
    for p, chars in by_page.items():
        f = root / book / "seed_admit" / f"p{p:04d}.json"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"seed_admit": {"columns": [{"chars": chars}]}}, ensure_ascii=False), encoding="utf-8")


def _fake_exp(tmp_path) -> Path:
    A, B = _pair()
    edir = tmp_path / "exps" / "e1"
    _write_seed_admit(edir / "A", "vb", A)
    _write_seed_admit(edir / "B", "vb", B)
    for p in range(1, 11):
        g = edir / RN.UPSTREAM / "vb" / "border_detect_gate" / f"p{p:04d}.json"
        g.parent.mkdir(parents=True, exist_ok=True)
        g.write_text(json.dumps({"border_detect_gate": {"page_type": "toc" if p == 10 else "body"}}), encoding="utf-8")
    vis = tmp_path / "vis.jsonl"
    vis.write_text(json.dumps({"cell": "vb:1:1:0", "v": "wrong", "char": "曰", "shown": "日"}, ensure_ascii=False),
                   encoding="utf-8")
    cfg = EC.from_dict({"name": "e1", "books": ["vb"], "variants": {"B": {"params": {"seed_admit": {"shadow_veto": True}}}},
                        "labels": [{"source": "vision", "path": str(vis)}], "bootstrap": 100,
                        "guardrails": [{"metric": "review_rate", "scope": "body", "op": "<=", "ref": "base"}]})
    st = {"config": cfg.to_dict(), "steps": ["seed_admit"], "code_rev": "abc", "snapshot": "s", "runs": {}}
    import yaml
    (edir / "exp.yaml").write_text(yaml.safe_dump(st, allow_unicode=True), encoding="utf-8")
    return edir


def test_report_end_to_end(tmp_path):
    edir = _fake_exp(tmp_path)
    rep = RP.build(edir, same=lambda a, b: bool(a) and a == b)
    comp = rep["comparisons"]["B"]
    assert comp["overall"]["body"]["cells"] == 90
    assert comp["flips"]["admit_to_review"]["caught"] == 1
    assert comp["guardrails"][0]["verdict"] == "fail"      # B 多送审 1 格
    md = (edir / "report.md").read_text(encoding="utf-8")
    assert "picked 是被挑过的样本" in md and "无检验力" in md and "不达标" in md
    assert json.loads((edir / "report.json").read_text(encoding="utf-8"))["name"] == "e1"
    assert len(LB.read_jsonl(edir / "labels.jsonl")) == 1
    for f in ("charts/B-forest.svg", "charts/B-channels.svg"):
        svg = (edir / f).read_text(encoding="utf-8")
        assert svg.startswith("<svg") and "prefers-color-scheme:dark" in svg and f"]({f})" in md


def test_flips_sample_page_harvest(tmp_path):
    edir = _fake_exp(tmp_path)
    RP.build(edir, same=lambda a, b: bool(a) and a == b)
    cards = FL.sample(edir, n=10)
    ids = {c["id"] for c in cards}
    assert "vb:1:1:0" not in ids                           # 已有标签的不出题
    assert ids == {"vb:2:1:0", "vb:3:1:0", "vb:4:1:0"}
    assert FL.sample(edir, n=1) == cards                   # id 冻住：不 --resample 就不重抽
    html = FL.build_page(edir, image_fn=lambda c: None).read_text(encoding="utf-8")
    assert 'id="data"' in html and "B 把" not in html and "shadow_veto" not in html   # 卡上不印机器判断
    c4 = next(c for c in cards if c["id"] == "vb:4:1:0")
    vj = tmp_path / "v.jsonl"
    vj.write_text("\n".join(json.dumps(r) for r in [
        {"id": "vb:4:1:0", "verdict": f"c{c4['options'].index('丙')}"},
        {"id": "vb:2:1:0", "verdict": "defect"}, {"id": "vb:3:1:0", "verdict": "idk"}, {"id": "zz", "verdict": "c0"}]))
    t = FL.harvest(edir, vj)
    assert t == {"chars": 1, "none": 0, "defect": 1, "idk": 1, "unknown": 1}
    extra = {x.cell: x for x in LB.read_jsonl(edir / FL.EXTRA)}
    assert extra["vb:4:1:0"].truth == "丙" and extra["vb:2:1:0"].defect
    rep = RP.build(edir, same=lambda a, b: bool(a) and a == b)
    assert rep["comparisons"]["B"]["flips"]["char_changed"]["a_ok_b_err"] == 1


def test_allocate():
    q = FL.allocate({"a": 100, "b": 3, "c": 0}, 20)
    assert q["b"] == 3 and "c" not in q and 15 <= q["a"] <= 18
