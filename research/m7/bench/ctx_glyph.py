"""文意组的字形第二路（M7，2026-10-22）：配置取判别台（`bench.py`，嵌套按册留出）选得最多的岭回归配置，
用线上同一个打分器（`ids_whole.score_norm`）按册留一定 0 错门槛，再到 vol04–10 已放行格上数「字形有把握且与放行字不同」的格。

用法：python ctx_glyph.py <dataset char-groups 根> <人裁格字块目录> <bench json> <released.json> <已放行格字块目录> <输出目录> [组,…]
两个字块目录都应是线上同款字块（`char_patch`，`guji product patch` 同一取法；2026-10-22 实测：原图按框裁的字块与线上字块混用，
論→諭 这种明显的字会高把握判错）。人裁格只用给定目录里的图（`bench.load(only=True)`）。
released.json：{字: [{id, char, ch(通道), L, R}]}（已放行、未人裁的格）。输出 <组>.json：配置、门槛、留出成绩、线上分歧格。
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from bench import load  # noqa: E402

from open_guji_cv.groups import ids_whole  # noqa: E402
from open_guji_cv.groups.registry import FLOW_GROUPS  # noqa: E402


def pick_cfg(b):
    for s, _n in b["picks"]:
        clf, size, reg = s.split(" ", 2)
        if clf == "ridge":
            return int(size), tuple(float(x) for x in reg.strip("()").split(","))
    return 48, (0.0, 1.0, 0.0, 1.0)


def lobo(xs, size, region, lam=1.0):
    res = []
    for bk in sorted({b for *_r, b, _i in xs}):
        bank = defaultdict(list)
        for f, x, b, _i in xs:
            if b != bk:
                bank[f].append(x)
        if len(bank) < 2:
            continue
        ids_whole._CACHE.clear()
        for f, x, b, i in xs:
            if b == bk:
                ch, m, _ = ids_whole.score_norm(x, dict(bank), "hog", region, lam)
                res.append((f, ch, m, i))
    return res


def main():
    root, crops, bj, relp, relcrops, out = map(Path, sys.argv[1:7])
    bench = json.loads(bj.read_text())
    rel = json.loads(relp.read_text())
    gids = sys.argv[7].split(",") if len(sys.argv) > 7 else [g for g in bench if "picks" in bench[g]]
    out.mkdir(parents=True, exist_ok=True)
    for g in gids:
        mem = set(FLOW_GROUPS[g].members)
        size, region = pick_cfg(bench[g])
        cells = load(root, crops, mem, only=True)
        cnt = Counter(c[0] for c in cells)
        forms = {f for f, n in cnt.items() if n >= 8}
        xs = [(f, ids_whole.norm(np.asarray(gr), size), b, i) for f, gr, b, i in cells if f in forms]
        xs = [t for t in xs if t[1] is not None]
        res = lobo(xs, size, region)
        wrong = sorted((m for f, ch, m, _ in res if ch != f), reverse=True)
        thr = round(wrong[0] * 1.1 + 1e-3, 3) if wrong else 0.05
        right = sum(1 for f, ch, m, _ in res if ch == f and m >= thr)
        bank = defaultdict(list)
        for f, x, _b, _i in xs:
            bank[f].append(x)
        bank = dict(bank)
        ids_whole._CACHE.clear()
        # 线上：已放行格
        dis, n_ok, n_abs, by_ch = [], 0, 0, Counter()
        todo = [c for ch in mem for c in rel.get(ch, [])]
        for c in todo:
            f = relcrops / (c["id"].replace(":", "_") + ".png")
            pt = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE) if f.exists() else None
            x = ids_whole.norm(np.asarray(pt), size) if pt is not None and pt.size else None
            if x is None:
                continue
            ch, m, _ = ids_whole.score_norm(x, bank, "hog", region, 1.0)
            if m < thr:
                n_abs += 1
            elif ch == c["char"]:
                n_ok += 1
            else:
                by_ch[(c["char"], ch)] += 1
                dis.append({**c, "glyph": ch, "margin": round(m, 3)})
        r = {"group": g, "size": size, "region": region, "forms": dict(cnt), "thr": thr,
             "loo": {"right": right, "wrong_above": 0, "n": len(res), "max_wrong": round(wrong[0], 3) if wrong else None},
             "prod": {"n": n_ok + n_abs + len(dis), "agree": n_ok, "abstain": n_abs, "disagree": len(dis),
                      "pairs": {f"{a}→{b}": n for (a, b), n in by_ch.items()}},
             "disagree": sorted(dis, key=lambda d: -d["margin"])}
        (out / f"{g}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
        print(g, size, region, "thr", thr, "loo", f"{right}/{len(res)}", "prod", r["prod"], flush=True)


if __name__ == "__main__":
    main()
