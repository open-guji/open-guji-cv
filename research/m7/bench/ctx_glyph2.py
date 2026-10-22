"""文意组字形第二路 v2（M7，2026-10-22 夜）：模板＝人裁格＋已放行格（每册每形 ≤ `--per` 格，放行字当标签），
字块先去邻格碎墨（`ids_whole.clean_patch`；跑之前把两个字块目录都清理一遍），按册留一：判某册时模板不含该册。报两组数：
① 人裁格（真值）上的错数与覆盖；② 已放行格上「字形有把握又和放行字不同」的格数（异议）。门槛取「人裁 0 错」与
「已放行异议率 ≤ `--dis`」两者中较高的。配置（尺寸、区域）沿用判别台的选择。

用法：python ctx_glyph2.py <dataset char-groups 根> <人裁字块目录> <bench json> <released.json> <已放行字块目录> <输出目录> <组,…> [--per 60] [--dis 0.002]
"""
import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from bench import load  # noqa: E402
from ctx_glyph import pick_cfg  # noqa: E402

from open_guji_cv.groups import ids_whole  # noqa: E402
from open_guji_cv.groups.registry import FLOW_GROUPS  # noqa: E402

ASPECT = (0.45, 2.2)   # 字块宽高比超出这个范围（多半连进邻字）→ 弃权


def aspect_ok(g):
    h, w = g.shape[:2]
    return ASPECT[0] <= w / max(h, 1) <= ASPECT[1]


def main():
    ap = argparse.ArgumentParser()
    for k in ("root", "labcrops", "bench", "released", "relcrops", "out"):
        ap.add_argument(k, type=Path)
    ap.add_argument("groups")
    ap.add_argument("--per", type=int, default=60)
    ap.add_argument("--dis", type=float, default=0.002)
    a = ap.parse_args()
    bench = json.loads(a.bench.read_text())
    rel = json.loads(a.released.read_text())
    a.out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(1022)
    for g in a.groups.split(","):
        mem = set(FLOW_GROUPS[g].members)
        size, region = pick_cfg(bench[g])
        hum = [(f, gr, b, i) for f, gr, b, i in load(a.root, a.labcrops, mem, only=True)]
        hum_ids = {i for *_r, i in hum}
        rc = []
        for ch in mem:
            for c in rel.get(ch, []):
                p = a.relcrops / (c["id"].replace(":", "_") + ".png")
                if c["id"] in hum_ids or not p.exists():
                    continue
                gr = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
                if gr is not None:
                    rc.append((c["char"], gr, c["id"].split(":")[0], c["id"], c))
        def nx(gr):
            return ids_whole.norm(np.asarray(gr), size) if aspect_ok(gr) else None
        H = [(f, nx(gr), b, i) for f, gr, b, i in hum]
        R = [(f, nx(gr), b, i, c) for f, gr, b, i, c in rc]
        vols = sorted({t[2] for t in H} | {t[2] for t in R})
        hres, rres = [], []
        for v in vols:
            bank = defaultdict(list)
            for f, x, b, _i in H:
                if b != v and x is not None:
                    bank[f].append(x)
            pool = defaultdict(list)
            for f, x, b, i, _c in R:
                if b != v and x is not None:
                    pool[(b, f)].append(x)
            for (b, f), xs in pool.items():
                rng.shuffle(xs)
                bank[f] += xs[:a.per]
            bank = {f: xs for f, xs in bank.items() if len(xs) >= 8}
            if len(bank) < 2:
                continue
            ids_whole._CACHE.clear()
            for f, x, b, i in H:
                if b == v:
                    ch, m, _ = ids_whole.score_norm(x, bank, "hog", region, 1.0) if x is not None else (None, 0.0, {})
                    hres.append((f, ch, m, i))
            for f, x, b, i, c in R:
                if b == v:
                    ch, m, _ = ids_whole.score_norm(x, bank, "hog", region, 1.0) if x is not None else (None, 0.0, {})
                    rres.append((f, ch, m, i, c))
        hw = sorted((m for f, ch, m, _ in hres if ch is not None and ch != f), reverse=True)
        t_h = hw[0] + 1e-3 if hw else 0.0
        rd = sorted((m for f, ch, m, _i, _c in rres if ch is not None and ch != f), reverse=True)
        k = int(a.dis * len(rres)) if a.dis < 1 else len(rres)
        t_r = rd[k] + 1e-3 if len(rd) > k else 0.0
        thr = round(max(t_h, t_r), 3)
        hr = sum(1 for f, ch, m, _ in hres if ch == f and m >= thr)
        ra = sum(1 for f, ch, m, _i, _c in rres if ch == f and m >= thr)
        dis = [dict(c, glyph=ch, margin=round(m, 3)) for f, ch, m, _i, c in rres if ch is not None and ch != f and m >= thr]
        r = {"group": g, "size": size, "region": region, "thr": thr, "thr_human": round(t_h, 3), "thr_rel": round(t_r, 3),
             "human": {"n": len(hres), "right": hr, "wrong_above": 0}, "released": {"n": len(rres), "agree": ra, "disagree": len(dis)},
             "disagree": sorted(dis, key=lambda d: -d["margin"])}
        (a.out / f"{g}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1))
        print(g, size, region, "thr", thr, f"(人裁 {t_h:.3f} 放行 {t_r:.3f})", "人裁", f"{hr}/{len(hres)}", "放行", f"同 {ra}/{len(rres)} 异 {len(dis)}", flush=True)


if __name__ == "__main__":
    main()
