# -*- coding: utf-8 -*-
"""fold_aspect 阈值标定（折叠组框架见 `doc/字组/折叠组.md`）：按本书已放行格统计一对形近字的字块宽/高分布，给出书级阈值建议。

    python scripts/fold_aspect_dist.py <册产物目录> [<册产物目录> …] [--pair 日曰] [--lo 0.85 --hi 1.0] [--max-err 0.005]

- 册产物目录：`guji products pack fetch` 拉下来的 `<根>/<册>`，或本机产物目录；里面要有 `char_index/`（或 `cell_shrink/`）、
  `align_ref/`，有 `seed_admit/` 更好。可以一次给多册（同一本书），合起来标定。
- 真值：有 `seed_admit` 时只取「已放行、机器字＝整理本字」的格（比只看整理本字干净）；没有就退回整理本字（坐标对位，缺则 align_char）。
- 正文、夹注半格（格号以 a/b 结尾）分开统计：夹注字块常比正文扁，书级参数也分 `fold_aspect` 与 `fold_aspect_jiazhu`。
- 输出：两字分位数；给定 (lo, hi) 时各判多少；按 `--max-err`（判出来的格里错的占比上限，按本书两字实际出现比例算）推荐 lo、hi，
  收不到三成就明说「不建议开」。错的里有一部分是切分框不准，所以建议同开 `fold_aspect_ctx_veto`。只读。
"""
import argparse
import glob
import json
import os
import statistics


def _layer(vol_dir: str, names: tuple[str, ...], key: str, page: str):
    for n in names:
        f = os.path.join(vol_dir, n, page)
        if os.path.exists(f):
            d = json.load(open(f, encoding="utf-8"))
            return d.get(key, d)
    return None


def collect(vol_dirs: list[str], pair: str) -> dict:
    got = {k: {c: [] for c in pair} for k in ("body", "jiazhu")}
    for vd in vol_dirs:
        ci_dir = next((os.path.join(vd, n) for n in ("char_index", "cell_shrink") if os.path.isdir(os.path.join(vd, n))), None)
        if not ci_dir:
            print(f"跳过 {vd}：没有 char_index/cell_shrink")
            continue
        for f in sorted(glob.glob(os.path.join(ci_dir, "p*.json"))):
            pg = os.path.basename(f)
            ci = json.load(open(f, encoding="utf-8"))
            ci = ci.get("char_index", ci)
            ar = _layer(vd, ("align_ref",), "align_ref", pg) or {}
            ref = {c["id"]: c.get("ref_char") for c in ar.get("coord", []) or []}
            ref.update({c["id"]: c.get("align_char") for c in ar.get("chars", []) or [] if c.get("align_char")})
            sa = _layer(vd, ("seed_admit",), "seed_admit", pg)
            adm = None
            if sa:
                adm = {ch["id"]: ch.get("char") for col in sa.get("columns", []) for ch in col.get("chars", [])
                       if ch.get("admit") and "excluded" not in (ch.get("doubts") or [])}
            for key in ("columns", "alt_columns"):
                for col in ci.get(key, []) or []:
                    for c in col.get("chars", []):
                        cid = c["id"]
                        ch = ref.get(cid)
                        if not ch or ch not in pair or not c.get("width") or not c.get("height"):
                            continue
                        if adm is not None and adm.get(cid) != ch:
                            continue
                        kind = "jiazhu" if cid[-1:] in ("a", "b") else "body"
                        got[kind][ch].append(c["width"] / c["height"])
    return got


def suggest(narrow: list[float], wide: list[float], max_err: float) -> tuple[float | None, float | None]:
    """按本书两字的实际出现比例算「判出来的格里错几成」（精度口径）：
    lo＝≤lo 判窄字、其中实为宽字的占比 ≤ max_err 的最大 lo；hi＝≥hi 判宽字、其中实为窄字的占比 ≤ max_err 的最小 hi。"""
    grid = [round(0.40 + 0.01 * i, 2) for i in range(121)]

    def err_lo(t):
        ok, bad = sum(x <= t for x in narrow), sum(x <= t for x in wide)
        return bad / (ok + bad) if ok + bad else 1.0

    def err_hi(t):
        ok, bad = sum(x >= t for x in wide), sum(x >= t for x in narrow)
        return bad / (ok + bad) if ok + bad else 1.0
    lo = max((t for t in grid if err_lo(t) <= max_err), default=None)
    hi = min((t for t in grid if err_hi(t) <= max_err), default=None)
    return lo, hi


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vol_dirs", nargs="+")
    ap.add_argument("--pair", default="日曰", help="两个字：先窄后宽，同 fold_aspect_pairs")
    ap.add_argument("--lo", type=float, default=0.85)
    ap.add_argument("--hi", type=float, default=1.0)
    ap.add_argument("--max-err", type=float, default=0.005)
    a = ap.parse_args()
    nar, wid = a.pair[0], a.pair[1]
    got = collect(a.vol_dirs, a.pair)
    for kind, g in got.items():
        print(f"== {'正文' if kind == 'body' else '夹注半格'}")
        for ch, v in g.items():
            if len(v) < 20:
                print(f"{ch} 样本 {len(v)}，太少")
                continue
            q = statistics.quantiles(v, n=20)
            print(f"{ch} n={len(v)} p5 {q[0]:.3f} p25 {q[4]:.3f} 中位 {q[9]:.3f} p75 {q[14]:.3f} p95 {q[18]:.3f}"
                  f"  判{nar}(≤{a.lo}) {sum(x <= a.lo for x in v)}  判{wid}(≥{a.hi}) {sum(x >= a.hi for x in v)}  居中 {sum(a.lo < x < a.hi for x in v)}")
        N, W = g[nar], g[wid]
        if len(N) < 20 or len(W) < 20:
            continue
        lo, hi = suggest(N, W, a.max_err)
        cl = sum(x <= lo for x in N) / len(N) if lo is not None else 0.0
        ch_ = sum(x >= hi for x in W) / len(W) if hi is not None else 0.0
        print(f"建议（判出来的格里错 ≤{a.max_err:.1%}）：")
        print(f"  判{nar}：" + (f"lo={lo}，收 {nar} {cl:.0%}" if lo is not None and cl >= 0.3 else "不建议（lo 写 0 关掉这一侧）"))
        print(f"  判{wid}：" + (f"hi={hi}，收 {wid} {ch_:.0%}" if hi is not None and ch_ >= 0.3 else "不建议（hi 写 9 关掉这一侧）"))


if __name__ == "__main__":
    main()
