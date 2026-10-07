# -*- coding: utf-8 -*-
"""影子开关的分层抽样：出人裁清单，估全册放行错误率与各阈值下影子「拦对／误拦」（overview#457）。

翻转格是被挑出来的，只能说明那几格上两边不同，外推不了全册。这里改用**按影子判断分层**的抽样：

| 层 | 是什么 | 怎么抽 | 能回答 |
|---|---|---|---|
| `disagree_hi` | 影子认的字 ≠ 放行字，把握度 ≥ 0.8 | **普查**（全出题）| 现行阈值附近，拦下的格里几格真错 |
| `disagree_mid` | 同上，0.5 ≤ 把握度 < 0.8 | 普查 | 阈值往下调能多拦对几格、多误拦几格 |
| `disagree_lo` | 同上，把握度 < 0.5 | 普查 | 同上 |
| `agree` | 影子同意放行字（或弃权）| **简单随机**，记 `selection=random`、权重 = 层格数 / 抽中格数 | 影子漏掉的错有多少（放行错误率的大头）|

影子不同意的格在一册里只有几十格，全出题比抽样省事，算出来是精确数，不是估计。同意层几万格，只能抽；
抽几十格只能给出很宽的区间（0 错时 95% 上界约 3/n），这一点报告里照实写。

- **基线**：对实验的基线变体（缺省 A）的放行格离线跑一遍影子闸（与线上 `seed_admit._shadow_veto_pass` 同一个
  模型、同一份证据），记下影子认的字和把握度 → `sample/shadow_scan.jsonl`。**不套线上的「异体弃权」**：
  用户 10-07 定「异体码位放行算错」，异体关系正是要量的东西。
- **出题**：候选字 = 放行字 + 影子认的字 + 库前两名（去重、打乱），卡上不写哪个是放行字。已有人裁的格不再出题。
- **判对**：用实验的 `match:`（缺省 exact，口径 A）。
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from ..errors import BadRequest
from .compare import correct, load_cells, make_same
from .labels import PICKED, RANDOM, read_jsonl
from .stats import wilson

SCAN = "sample/shadow_scan.jsonl"
CARDS = "sample/cards.jsonl"
ESTIMATE = "sample/estimate.md"
BANDS = (("disagree_hi", 0.8, 1.01), ("disagree_mid", 0.5, 0.8), ("disagree_lo", 0.0, 0.5))
THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9, 0.97)


def band(row: dict) -> str:
    # 按闸自己的判定分：己已巳在影子里合为一类（模型分不出），pick 字面不同也判 agree，不算「不同意」
    if row.get("reason") not in ("differs", "differs_below_thr"):
        return "agree"
    c = row.get("conf") or 0.0
    return next(name for name, lo, hi in BANDS if lo <= c < hi)


# ── 离线影子扫描 ───────────────────────────────────────────────────────────
def scan(edir: str | Path, variant: str = "A", *, db_path: str | None = None, model_path: str | None = None,
         log=print) -> list[dict]:
    """基线变体的每个放行格（非人裁）过一遍影子闸，记 {cell, page, char, channel, reason, pick, conf, lib}。"""
    import open_guji_cv.steps  # noqa: F401  —— 注册产物种类
    from ..core.workspace import glyph_db_path
    from ..products.store import ProductStore
    from ..shadow.gate import ShadowGate
    from ..shadow.model import load_model
    from ..shadow.offline import page_evidence
    from ..shadow.signals import load_context
    from ..steps.seed_admit import SeedAdmitParams, _shadow_model_path
    from .runner import read_state

    edir = Path(edir)
    st = read_state(edir) or {}
    books = (st.get("config") or {}).get("books") or []
    p = SeedAdmitParams()
    gate = ShadowGate(load_model(Path(model_path) if model_path else _shadow_model_path(p)),
                      load_context(db_path or str(glyph_db_path()), None), 0.8)
    store = ProductStore(edir / variant)
    rows = []
    for book in books:
        cells = load_cells(edir / variant, book)
        for page in sorted({c["page"] for c in cells.values()}):
            for cid, ev in page_evidence(store, book, page).items():
                c = cells.get(cid)
                if c is None or c["state"] != "admit":
                    continue
                v = gate.judge(ev)
                rows.append({"cell": cid, "book": book, "page": page, "char": c["char"], "channel": c["channel"],
                             "reason": v.reason, "pick": v.pick,
                             "conf": None if v.conf is None else round(v.conf, 4),
                             "lib": [x for x, _ in ev.lib[:3]]})
        log(f"[scan] {book}: {len(rows)} 个放行格")
    out = edir / SCAN
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return rows


def read_scan(edir: Path) -> list[dict]:
    p = Path(edir) / SCAN
    if not p.exists():
        raise BadRequest(f"{p} 不存在——先 guji exp sample <实验> scan")
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


# ── 出题 ─────────────────────────────────────────────────────────────────
def _options(row: dict, rng: random.Random) -> list[str]:
    opts = []
    for c in [row["char"], row.get("pick"), *(row.get("lib") or [])[:2]]:
        if c and c not in opts:
            opts.append(c)
    rng.shuffle(opts)
    return opts


def build_cards(edir: str | Path, *, n_random: int = 35, seed: int = 0, resample: bool = False) -> list[dict]:
    """影子不同意的层全出题（已有人裁的跳过），同意层简单随机抽 `n_random` 格。卡片 id 冻住。"""
    edir = Path(edir)
    cp = edir / CARDS
    if cp.exists() and not resample:
        return [json.loads(x) for x in cp.read_text(encoding="utf-8").splitlines() if x.strip()]
    rows = read_scan(edir)
    human = {x.cell for x in read_jsonl(edir / "labels.jsonl") if x.source == "human"}
    human |= {x.cell for x in read_jsonl(edir / "labels_extra.jsonl")}
    rng = random.Random(seed)
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(band(r), []).append(r)
    cards = []
    for name, _, _ in BANDS:
        for r in by.get(name, []):
            if r["cell"] not in human:
                cards.append({"id": r["cell"], "stratum": name, "stratum_weight": 1.0, "selection": PICKED,
                              "options": _options(r, rng)})
    agree = by.get("agree", [])
    pick = rng.sample(agree, min(n_random, len(agree)))
    w = len(agree) / max(1, len(pick))
    for r in pick:
        cards.append({"id": r["cell"], "stratum": "agree", "stratum_weight": round(w, 3), "selection": RANDOM,
                      "options": _options(r, rng)})
    rng.shuffle(cards)
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in cards), encoding="utf-8")
    return cards


# ── 估计 ─────────────────────────────────────────────────────────────────
def estimate(edir: str | Path, *, match: str = "exact", variant: str = "A") -> dict:
    """分层估计：基线放行格里有多少错，影子在各阈值下拦对／误拦几格。"""
    from .labels import merge
    edir = Path(edir)
    rows = read_scan(edir)
    labs, _ = merge(read_jsonl(edir / "labels.jsonl") + read_jsonl(edir / "labels_extra.jsonl"))
    same = make_same(match)
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(band(r), []).append(r)

    def judge(r: dict, lab) -> bool | None:
        return correct({"state": "admit", "char": r["char"]}, lab, same)

    strata = {}
    for name, _, _ in BANDS:
        ok = err = unk = 0
        for r in by.get(name, []):
            c = judge(r, labs.get(r["cell"]))
            ok += c is True
            err += c is False
            unk += c is None
        strata[name] = {"N": len(by.get(name, [])), "ok": ok, "err": err, "unlabeled": unk, "kind": "census"}
    agree = by.get("agree", [])
    k = n = 0
    for r in agree:
        lab = labs.get(r["cell"])
        if lab is None or lab.selection != RANDOM or lab.stratum != "agree":
            continue
        c = judge(r, lab)
        if c is None:
            continue
        n += 1
        k += c is False
    ci = wilson(k, n)
    strata["agree"] = {"N": len(agree), "n": n, "err": k, "kind": "random",
                       "rate": k / n if n else None, "rate_ci": ci,
                       "est_err": len(agree) * k / n if n else None,
                       "est_err_ci": None if ci is None else (len(agree) * ci[0], len(agree) * ci[1])}
    census_err = sum(strata[b]["err"] for b, _, _ in BANDS)
    total_n = len(rows)
    tot = None
    if strata["agree"]["est_err"] is not None:
        lo, hi = strata["agree"]["est_err_ci"]
        tot = {"est": census_err + strata["agree"]["est_err"], "ci": (census_err + lo, census_err + hi)}
    thr = []
    dis = [r for r in rows if band(r) != "agree"]
    for t in THRESHOLDS:
        sel = [r for r in dis if (r.get("conf") or 0) >= t]
        cs = [judge(r, labs.get(r["cell"])) for r in sel]
        caught, blocked, unk = sum(c is False for c in cs), sum(c is True for c in cs), sum(c is None for c in cs)
        thr.append({"conf": t, "vetoed": len(sel), "caught": caught, "wrongly_blocked": blocked, "unlabeled": unk,
                    "recall": None if not tot or not tot["est"] else caught / tot["est"]})
    return {"variant": variant, "match": match, "admitted": total_n, "strata": strata,
            "census_err": census_err, "total": tot, "thresholds": thr}


def render(est: dict, name: str) -> str:
    def pct(x):
        return "—" if x is None else f"{x * 100:.2f}%"
    s = est["strata"]
    L = [f"# 影子开关分层抽样估计 · {name}", "",
         f"- 基线变体 {est['variant']} 的放行格 {est['admitted']} 格（非人裁）；判对口径 "
         f"{'逐码位（exact，口径 A）' if est['match'] == 'exact' else '异体等价（semantic）'}",
         "- 影子不同意的三层是**普查**（数是精确的，未裁的格单列）；影子同意层是**简单随机抽样**（给估计与 95% 区间）。",
         "- 阈值表**不套线上的「异体弃权」**：按口径 A 那正是要拦的错码位。", "",
         "| 层 | 格数 | 已裁 | 放行字错 | 放行字对 | 未裁 |", "|---|---|---|---|---|---|"]
    for b, _, _ in BANDS:
        x = s[b]
        L.append(f"| {b}（普查）| {x['N']} | {x['ok'] + x['err']} | {x['err']} | {x['ok']} | {x['unlabeled']} |")
    a = s["agree"]
    ci = a["rate_ci"]
    L.append(f"| agree（随机 {a['n']} 格）| {a['N']} | {a['n']} | {a['err']} | {a['n'] - a['err']} | — |")
    ci_txt = "—" if not ci else f"[{pct(ci[0])}, {pct(ci[1])}]"
    if a["est_err"] is None:
        n_txt = "—"
    else:
        lo, hi = a["est_err_ci"]
        n_txt = f"{a['est_err']:.0f}（{lo:.0f}–{hi:.0f}）"
    L += ["", f"- 影子同意层的放行错误率：{pct(a['rate'])}，95% 区间 {ci_txt}；折成格数约 {n_txt}。"]
    if a["n"] and a["n"] < 300:
        L.append(f"- ⚠ 随机层只抽了 {a['n']} 格，区间很宽（上界 {pct(ci[1]) if ci else '—'}）。"
                 "要把全册错误率估准，需几百上千格随机标签（例如确认 `看图结论.jsonl` 那批是随机抽检后并进来）。")
    t = est["total"]
    known = est["census_err"]
    if t:
        L.append(f"- 全册放行错：已发现 {known} 格（影子不同意的层里，精确数）；加上影子同意层的估计，"
                 f"合计约 {t['est']:.0f} 格，95% 区间 {t['ci'][0]:.0f}–{t['ci'][1]:.0f}。")
    L += ["", "## 各阈值下影子会拦什么（影子不同意的格，按把握度 ≥ 阈值）", "",
          f"「占已发现的放行错」以 {known} 格为分母，是影子能抓到的比例的**上界**：影子同意层里还藏着多少错，"
          "随机层太小，说不准。", "",
          "| 阈值 | 会拦 | 拦对（放行字错）| 误拦（放行字对）| 未裁 | 拦准率 | 占已发现的放行错 |",
          "|---|---|---|---|---|---|---|"]
    for r in est["thresholds"]:
        judged = r["caught"] + r["wrongly_blocked"]
        prec = pct(r["caught"] / judged) if judged else "—"
        share = pct(r["caught"] / known) if known else "—"
        L.append(f"| {r['conf']} | {r['vetoed']} | {r['caught']} | {r['wrongly_blocked']} | {r['unlabeled']} | "
                 f"{prec} | {share} |")
    return "\n".join(L) + "\n"

