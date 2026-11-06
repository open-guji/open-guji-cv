# -*- coding: utf-8 -*-
"""5a 字形比对基准（match_bench）：新图 × 字形库，按难例分档，另加受控扰动。

被测对象是生产的 Step5-a 比对栈：同一份 glyph.db、`GlyphMatchParams` 缺省（含 font_tier）、
按物理格留一（`exclude_id`）。查询集 = 三书人裁冻结分片
（open-guji-dataset `char-clustering/samples/00{4,5,6}-*-human`，每书约 3000 格），不另存图；
分档标注见 `glyph-match/bench/tiers-<分片>.jsonl`（本脚本 `--dump-tiers` 生成，只含实例号与特征）。

查询分两类（留一后）：
- **answerable**：留一后库里（刻本条目，含借库，不含字体域）还有别的同字刻例。答对 = same 档且字对，或候选首位对。
- **novel**：留一后库里没有这个字。正确行为是
  不判 same（弃权 / 另给候选）；判了 same 就是**误放**——比 answerable 判错更危险，单列。

难例分档（多标签，来自 64×64 归一图本身，规则见 `crop_flags`；分片自带的 `tier` 全是 clean，分不出）：
`offset` 笔画整体偏离格心、`edge` 墨贴边（疑截断）、`stain` 主体外有孤立墨点（污点／飞白）、
`heavy` / `thin` 本书墨比例最高 / 最低 10%、`clean` 都不是。另外按分片 `hard_pairs` 的字
（千干、十士…，己已巳与日曰已折叠）单列 `hard_pair`，体检标过的 `selfcheck_flag` 单列。

扰动（`--perturb`）：对一个分层子样本（只取 answerable，seed 固定）逐一施加受控扰动，量同一批
查询在扰动下的退化——`shift3/shift6` 平移、`rot4` 旋转、`scale` 缩放、`blot` 贴污块、
`speckle` 撒点、`dilate/erode` 笔画变粗变细、`blur` 模糊再二值、`cut` 一侧截掉。扰动加在
归一后的 64×64 上，近似切分偏移与污染进入匹配的样子（真实切分偏移要看 Step1-4，不在本基准里）。

指标（每书 × 每档 × 每扰动；己已巳、日曰折叠）：
- `cov`：answerable 里判 same 的占比；`prec`：same 里字对的占比；`recall`：same 且字对的占比；
- `rank1/rank5`：answerable 里候选（含 same 的字）首位／前五有金标字的占比；
- `novelFS`：novel 里判 same 的占比（越低越好）；
- 阈值无关：以首位候选分为置信度，`R@P.999`、`R@P.99`（精度达标时最大召回）与 `auroc`
  （首位字对 / 错的可分性）；
- 资源：每查询毫秒（中位 / p95）、平均精验对数 `n_verified`。

用法（云端沙箱，不碰正式 products）::

    python scripts/eval_match_bench.py \
        --book 004-siku-v2-human:<殿本 glyph.db> --book 005-shiji-human:<史記 glyph.db> \
        --book 006-qtw-human:<全唐文 glyph.db> --perturb --out bench.json

`--limit N` 每书只取前 N 个（试跑）；`--no-fold` 回旧口径。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from eval_fold import FOLD  # noqa: E402  己已巳、日曰图上分不开，按组折叠
from eval_fold import fold as fold_char  # noqa: E402
from open_guji_cv.clustering.confusable import NEVER_MATCH_FAMILIES  # noqa: E402
from open_guji_cv.steps.glyph_match import (GlyphMatchParams, GlyphMatchStep,  # noqa: E402
                                            _FontTier, _keben_subset)

HARD_CHARS = frozenset(c for fam in NEVER_MATCH_FAMILIES for c in fam if c not in FOLD)
FLAGS = ("clean", "offset", "edge", "stain", "heavy", "thin")

# ---- 分档规则（常量集中放这，改了要重出 tiers 文件） ----
OFFSET_PX = 4.0        # 墨 bbox 中心离格心 ≥ 4px（64 格）
EDGE_PX = 3            # 墨离边 ≤ 3px（归一后常态留边 4–7px，≤3 是贴边）
SPECK_AREA = 15        # 孤立墨点面积上限
SPECK_FAR = 4.0        # 离主体（面积 ≥ 30 的连通块）至少 4px 才算孤立
SPECK_N = 1            # 至少 1 个才记 stain
INK_Q = 0.10           # heavy / thin = 本书墨比例最高 / 最低的 10%（各书笔画粗细不同，用本书分位）


def crop_flags(norm: np.ndarray) -> dict:
    """64×64 二值（1 = 墨）→ 分档特征与标签。"""
    ink = norm.astype(np.uint8)
    h, w = ink.shape
    ys, xs = np.nonzero(ink)
    if len(xs) == 0:
        return {"flags": [], "dx": 0.0, "dy": 0.0, "margin": 0, "n_speck": 0, "ink": 0.0}
    dx = (xs.min() + xs.max()) / 2 - (w - 1) / 2
    dy = (ys.min() + ys.max()) / 2 - (h - 1) / 2
    margin = int(min(xs.min(), w - 1 - xs.max(), ys.min(), h - 1 - ys.max()))
    ratio = float(ink.mean())
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    core = np.isin(lab, [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= 30])
    n_speck = 0
    if core.any():
        dist = cv2.distanceTransform((~core).astype(np.uint8), cv2.DIST_L2, 3)
        for i in range(1, n):
            if st[i, cv2.CC_STAT_AREA] <= SPECK_AREA and dist[lab == i].min() >= SPECK_FAR:
                n_speck += 1
    flags = []
    if max(abs(dx), abs(dy)) >= OFFSET_PX:
        flags.append("offset")
    if margin <= EDGE_PX:
        flags.append("edge")
    if n_speck >= SPECK_N:
        flags.append("stain")
    return {"flags": flags, "dx": round(float(dx), 1), "dy": round(float(dy), 1),
            "margin": margin, "n_speck": n_speck, "ink": round(ratio, 3)}


# ---- 受控扰动（输入输出都是 64×64 uint8，1 = 墨；rng 固定种子，逐查询可复现） ----
def _affine(a: np.ndarray, M: np.ndarray) -> np.ndarray:
    out = cv2.warpAffine(a * 255, M, a.shape[::-1], flags=cv2.INTER_LINEAR, borderValue=0)
    return (out >= 127).astype(np.uint8)


def _shift(px: int):
    def f(a, rng):
        ang = rng.uniform(0, 2 * np.pi)
        M = np.float32([[1, 0, round(px * np.cos(ang))], [0, 1, round(px * np.sin(ang))]])
        return _affine(a, M)
    return f


def _rot(a, rng):
    return _affine(a, cv2.getRotationMatrix2D((31.5, 31.5), float(rng.choice([-4, 4])), 1.0))


def _scale(a, rng):
    return _affine(a, cv2.getRotationMatrix2D((31.5, 31.5), 0, float(rng.choice([0.88, 1.12]))))


def _blot(a, rng):
    out = a.copy()
    for _ in range(int(rng.integers(1, 3))):
        cv2.circle(out, (int(rng.integers(8, 56)), int(rng.integers(8, 56))), int(rng.integers(3, 6)), 1, -1)
    return out


def _speckle(a, rng):
    out = a.copy()
    for _ in range(int(rng.integers(6, 12))):
        cv2.circle(out, (int(rng.integers(2, 62)), int(rng.integers(2, 62))), 1, 1, -1)
    return out


def _dilate(a, rng):
    return cv2.dilate(a, np.ones((3, 3), np.uint8))


def _erode(a, rng):
    return cv2.erode(a, np.ones((3, 3), np.uint8))


def _blur(a, rng):
    return (cv2.GaussianBlur(a.astype(np.float32), (0, 0), 1.6) > 0.35).astype(np.uint8)


def _cut(a, rng):
    out = a.copy()
    k = int(rng.integers(5, 9))   # 约 10%–15%
    side = int(rng.integers(0, 4))
    if side == 0:
        out[:, :k] = 0
    elif side == 1:
        out[:, -k:] = 0
    elif side == 2:
        out[:k] = 0
    else:
        out[-k:] = 0
    return out


PERTURB = {"shift3": _shift(3), "shift6": _shift(6), "rot4": _rot, "scale": _scale, "blot": _blot,
           "speckle": _speckle, "dilate": _dilate, "erode": _erode, "blur": _blur, "cut": _cut}


def _auroc(pos: list[float], neg: list[float]) -> float | None:
    if not pos or not neg:
        return None
    s = np.array(pos + neg)
    r = s.argsort().argsort() + 1.0
    for v in np.unique(s):          # 并列取平均秩
        m = s == v
        if m.sum() > 1:
            r[m] = r[m].mean()
    n1, n0 = len(pos), len(neg)
    return float((r[:n1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def _recall_at_p(conf: list[tuple[float, bool]], total: int, p_min: float) -> dict | None:
    """按置信度从高到低累计：精度 ≥ p_min 时最大的召回（对数 / total）。"""
    best = None
    ok = 0
    for i, (c, good) in enumerate(sorted(conf, key=lambda t: -t[0]), 1):
        ok += good
        if ok / i >= p_min:
            best = {"recall": round(ok / total, 4), "n": i, "gate": round(c, 4), "prec": round(ok / i, 4)}
    return best


# 同形异码（库里同一个形标成两个码位，图上看是同一个字）。来源：A23 11-05 L2 证人标定看图确认的殿本例
# （ai-team 字形领域/L2图一致证人标定 第四节）。徃/往、閒/間、捜/搜 只在基准高置信错例里见过，没看图确认，
# 先不收，等 A24 确认再加。
SAME_SHAPE = {"删": "刪", "槪": "概", "歩": "步", "黙": "默", "徳": "德", "黄": "黃", "苖": "苗"}
_FOLD_VARIANTS = False   # --fold-variants：评测时同形异码与语义异体表（VariantMap）也折叠


def _fold_all(c: str) -> str:
    c = fold_char(c)
    if _FOLD_VARIANTS:
        from open_guji_cv.clustering.variants import VariantMap
        c = SAME_SHAPE.get(c, c)
        c = _variant_map().semantic(c)
    return c


_VM = None


def _variant_map():
    global _VM
    if _VM is None:
        from open_guji_cv.clustering.variants import VariantMap
        _VM = VariantMap.load()
    return _VM


def fold_row(r: dict) -> dict:
    best: dict[str, float] = {}
    for c, v in r["cand"]:
        k = _fold_all(c)
        best[k] = max(best.get(k, 0.0), v)
    return {**r, "gold": _fold_all(r["gold"]),
            "char": _fold_all(r["char"]) if r["char"] else None,
            "cand": sorted(best.items(), key=lambda kv: -kv[1])}


def metrics(rows: list[dict]) -> dict:
    ans = [r for r in rows if r["answerable"]]
    nov = [r for r in rows if not r["answerable"]]
    out: dict = {"n": len(rows), "n_ans": len(ans), "n_novel": len(nov)}
    if ans:
        same = [r for r in ans if r["verdict"] == "same"]
        ok = [r for r in same if r["char"] == r["gold"]]
        out.update(same_cov=round(len(same) / len(ans), 4),
                   same_prec=round(len(ok) / len(same), 4) if same else None,
                   same_err=len(same) - len(ok), recall=round(len(ok) / len(ans), 4),
                   rank1=round(sum(bool(r["cand"]) and r["cand"][0][0] == r["gold"] for r in ans) / len(ans), 4),
                   rank5=round(sum(r["gold"] in [c for c, _ in r["cand"][:5]] for r in ans) / len(ans), 4))
        conf = [(r["cand"][0][1], r["cand"][0][0] == r["gold"]) for r in ans if r["cand"]]
        out["auroc"] = _auroc([c for c, g in conf if g], [c for c, g in conf if not g])
        out["recall@P0.999"] = _recall_at_p(conf, len(ans), 0.999)
        out["recall@P0.99"] = _recall_at_p(conf, len(ans), 0.99)
    if nov:
        out["novel_false_same"] = round(sum(r["verdict"] == "same" for r in nov) / len(nov), 4)
        out["novel_false_same_n"] = sum(r["verdict"] == "same" for r in nov)
    ms = sorted(r["ms"] for r in rows)
    if ms:
        out["ms_p50"] = round(ms[len(ms) // 2], 1)
        out["ms_p95"] = round(ms[int(len(ms) * 0.95)], 1)
        out["n_verified_mean"] = round(float(np.mean([r["n_verified"] for r in rows])), 2)
    return out


def load_queries(shard: Path, limit: int | None) -> list[dict]:
    exp = json.loads((shard / "expected.json").read_text(encoding="utf-8"))
    inst = exp["instances"][:limit] if limit else exp["instances"]
    out = []
    for x in inst:
        img = cv2.imread(str(shard / x["crop"]), cv2.IMREAD_GRAYSCALE)
        norm = (img > 127).astype(np.uint8)
        f = crop_flags(norm)
        out.append({"id": x["instance_id"], "gold": x["char"], "norm": norm, "flags": f["flags"],
                    "feat": {k: f[k] for k in ("dx", "dy", "margin", "n_speck", "ink")},
                    "answerable": x.get("book_count", 2) > 1,   # 占位，跑前由 mark_answerable 按库改写
                    "hard": x["char"] in HARD_CHARS, "sc_flag": x.get("selfcheck_flag") or ""})
    ink = np.array([q["feat"]["ink"] for q in out])
    lo, hi = (np.quantile(ink, INK_Q), np.quantile(ink, 1 - INK_Q)) if len(out) else (0, 1)
    for q in out:
        r = q["feat"]["ink"]
        if r >= hi:
            q["flags"].append("heavy")
        if r <= lo:
            q["flags"].append("thin")
        if not q["flags"]:
            q["flags"] = ["clean"]
    return out


def run_matcher(matcher, q: dict, norm: np.ndarray, variant: str) -> dict:
    t0 = time.perf_counter()
    m = matcher.match(norm, exclude_id=q["id"])
    ms = (time.perf_counter() - t0) * 1000
    cand = [(c, round(float(v), 4)) for c, v in m.candidates[:5]]
    if m.verdict == "same" and m.char and not any(c == m.char for c, _ in cand):
        cand = [(m.char, round(float(m.cov), 4))] + cand
    return {"id": q["id"], "variant": variant, "gold": q["gold"], "flags": q["flags"],
            "answerable": q["answerable"], "hard": q["hard"], "sc_flag": q["sc_flag"],
            "verdict": m.verdict, "char": m.char, "guard": m.guard, "cov": round(float(m.cov), 4),
            "n_verified": m.n_verified, "ms": round(ms, 2), "cand": cand}


def mark_answerable(matcher, qs: list[dict]) -> None:
    """留一后库里（刻本条目，含借来的，不含 font: 字体域）还有没有金标字：有 = answerable。

    只看分片自带的 `book_count`（本书自有刻例数）不够：史記、全唐文借了别书的库，本书只有
    1 条的字，借库里可能有，判 same 就是对的，不能算 novel。"""
    full = getattr(matcher, "_full", matcher)
    cnt: dict[str, int] = {}
    for iid, ch in zip(full._ids, full._chars):
        if not str(iid).startswith("font:"):
            k = fold_char(ch)
            cnt[k] = cnt.get(k, 0) + 1
    for q in qs:
        k = fold_char(q["gold"])
        selfn = sum(fold_char(full._chars[j]) == k and not str(full._ids[j]).startswith("font:")
                    for j in full._same_cell_rows(q["id"]))
        q["lib_n"] = cnt.get(k, 0) - selfn
        q["answerable"] = q["lib_n"] > 0


def build_matcher(db: str):
    p = GlyphMatchParams(db_path=db)
    full = GlyphMatchStep()._matcher(p)
    tier = _FontTier.rule(p.font_tier)
    return (_FontTier(full, _keben_subset(full), tier) if tier is not None else full), len(full)


def report_for(rows: list[dict], fold: bool) -> dict:
    rows = [fold_row(r) for r in rows] if fold else rows
    base = [r for r in rows if r["variant"] == "orig"]
    clean_pop = [r for r in base if not r["hard"] and not r["sc_flag"]]
    rep: dict = {"headline": metrics(clean_pop), "all": metrics(base)}
    rep["by_flag"] = {f: metrics([r for r in clean_pop if f in r["flags"]]) for f in FLAGS}
    rep["hard_pair"] = metrics([r for r in base if r["hard"] and not r["sc_flag"]])
    rep["selfcheck_flagged"] = metrics([r for r in base if r["sc_flag"]])
    pert = {}
    for v in sorted({r["variant"] for r in rows} - {"orig"}):
        pr = [r for r in rows if r["variant"] == v]
        ids = {r["id"] for r in pr}
        pert[v] = {"perturbed": metrics(pr),
                   "orig_same_queries": metrics([r for r in clean_pop if r["id"] in ids])}
    if pert:
        rep["perturb"] = pert
    rep["same_errors"] = [{"id": r["id"], "gold": r["gold"], "claim": r["char"], "cov": r["cov"],
                           "flags": r["flags"]}
                          for r in clean_pop if r["verdict"] == "same" and r["char"] != r["gold"]][:60]
    return rep


def _fmt(x, pct=True):
    if x is None:
        return "     - "
    return f"{x * 100:7.2f}" if pct else f"{x:7.3f}"


def print_report(shard: str, rep: dict) -> None:
    h = rep["headline"]
    print(f"\n=== {shard}  头条 n={h['n']}（answerable {h['n_ans']} / novel {h['n_novel']}；不含 hard_pair、体检标记）")
    print(f'{"档":<14}{"n":>5}{"cov":>7}{"prec":>7}{"recall":>7}{"rank1":>7}{"rank5":>7}{"auroc":>7}'
          f'{"R@P.999":>8}{"R@P.99":>8}{"novelFS":>8}{"ms50":>6}')

    def line(name, m):
        r999 = (m.get("recall@P0.999") or {}).get("recall")
        r99 = (m.get("recall@P0.99") or {}).get("recall")
        print(f'{name:<14}{m["n"]:>5}{_fmt(m.get("same_cov"))}{_fmt(m.get("same_prec"))}{_fmt(m.get("recall"))}'
              f'{_fmt(m.get("rank1"))}{_fmt(m.get("rank5"))}{_fmt(m.get("auroc"), False)}'
              f'{_fmt(r999):>8}{_fmt(r99):>8}{_fmt(m.get("novel_false_same")):>8}{m.get("ms_p50", 0):>6}')
    line("头条", h)
    for f in FLAGS:
        if rep["by_flag"][f]["n"]:
            line(f, rep["by_flag"][f])
    line("hard_pair", rep["hard_pair"])
    if rep["selfcheck_flagged"]["n"]:
        line("体检标记", rep["selfcheck_flagged"])
    for v, d in rep.get("perturb", {}).items():
        line(f"扰动·{v}", d["perturbed"])
        line("  (同批原图)", d["orig_same_queries"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--book", action="append", required=True, help="<分片>[:<glyph.db>]，可重复；不给 db 按 GUJI_GLYPH_DB / GUJI_WORKSPACE 解析")
    ap.add_argument("--dataset", default="../open-guji-dataset/char-clustering")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--perturb", action="store_true", help="加受控扰动子集")
    ap.add_argument("--perturb-n", type=int, default=300, help="每书扰动子样本数（answerable，抽样）")
    ap.add_argument("--perturb-only", default=None, help="逗号分隔，只跑这几种扰动")
    ap.add_argument("--no-fold", action="store_true")
    ap.add_argument("--fold-variants", action="store_true",
                    help="评测再折叠同形异码（SAME_SHAPE）与语义异体表；头条另给「严格口径」不变")
    ap.add_argument("--dump-tiers", default=None, help="分档标注写到这个目录：tiers-<分片>.jsonl")
    ap.add_argument("--rows", default=None, help="逐查询结果写到 <前缀>.<分片>.jsonl")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    global _FOLD_VARIANTS
    _FOLD_VARIANTS = a.fold_variants
    samples = Path(a.dataset) / "samples"
    kinds = a.perturb_only.split(",") if a.perturb_only else list(PERTURB)
    report: dict = {"protocol": {"fold": not a.no_fold, "perturb": kinds if a.perturb else [],
                                 "perturb_n": a.perturb_n}}
    for spec in a.book:
        shard, _, db = spec.partition(":")   # 缺 db = 留空，按 GUJI_GLYPH_DB / GUJI_WORKSPACE 解析（登记表用这个）
        qs = load_queries(samples / shard, a.limit)
        if a.dump_tiers:
            Path(a.dump_tiers).mkdir(parents=True, exist_ok=True)
            with open(Path(a.dump_tiers) / f"tiers-{shard}.jsonl", "w", encoding="utf-8") as f:
                for q in qs:
                    f.write(json.dumps({"id": q["id"], "flags": q["flags"], **q["feat"]}, ensure_ascii=False) + "\n")
        matcher, nlib = build_matcher(db)
        mark_answerable(matcher, qs)
        print(f"[{shard}] 库 {nlib} 条，查询 {len(qs)}（answerable {sum(q['answerable'] for q in qs)}）", flush=True)
        rows, t0 = [], time.time()
        for i, q in enumerate(qs):
            rows.append(run_matcher(matcher, q, q["norm"], "orig"))
            if (i + 1) % 500 == 0:
                print(f"  {i + 1}/{len(qs)}  {time.time() - t0:.0f}s", flush=True)
        if a.perturb:
            ans = [q for q in qs if q["answerable"] and not q["hard"] and not q["sc_flag"]]
            pick = sorted(np.random.default_rng(7).permutation(len(ans))[: a.perturb_n])
            sub = [ans[i] for i in pick]
            for k, name in enumerate(kinds):
                rng = np.random.default_rng(11 + k)
                for q in sub:
                    rows.append(run_matcher(matcher, q, PERTURB[name](q["norm"], rng), name))
                print(f"  扰动 {name}: {len(sub)} 条  {time.time() - t0:.0f}s", flush=True)
        if a.rows:
            with open(f"{a.rows}.{shard}.jsonl", "w", encoding="utf-8") as f:
                for r in rows:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")
        rep = report_for(rows, not a.no_fold)
        report[shard] = rep
        print_report(shard, rep)
    if a.out:
        Path(a.out).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n→ {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
