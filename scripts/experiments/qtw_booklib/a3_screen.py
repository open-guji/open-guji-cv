"""a3：簇级确认格进库前的抽查闸（用户 09-27 22:20Z：书级库只收全唐文刻例，每字可多例，
簇级确认的先抽查再进）。

  GUJI_WORKSPACE=$QTW_WS python a3_screen.py <imp_dir>   → <imp_dir>/screen.json + 抽查拼图

两道机器闸，任一命中就**不进库**（照常记人裁事件，`no_glyph_lib=true`），逐条列出：
1. **留一近邻**：拿全部人裁确认格建一个只含全唐文的匹配器，每格排除自己去查，首选字既不是
   人裁字、也不是它的异体 → 疑错（簇里混进了别的字）；
2. **离群**：与同字其它格的平均相似度（归一 64² 模糊后余弦）低于该字中位数 − 3×MAD 且
   绝对值 < 0.35 → 疑错（残字、切坏、污损）。
逐格确认（batch1 `ok`）不过闸，直接进。另出每字一行的拼图（`montage/*.png`，疑错格红框）供目检。
"""
from __future__ import annotations

import collections
import json
import pickle
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "qtw_libfail"))
from a1_score_dist import rel  # noqa: E402
from a3_reps import vec  # noqa: E402


def main():
    d = Path(sys.argv[1])
    from open_guji_cv.clustering.match import GlyphMatcher
    from open_guji_cv.clustering.normalize import normalize_patch as N
    final = [json.loads(l) for l in open(d / "final.jsonl", encoding="utf-8")]
    P = pickle.load(open(d / "patches.pkl", "rb"))
    recs = [r for r in final if r["import"] and r["act"] == "confirm" and r["key"] in P]
    m = GlyphMatcher(k=10)
    norms = {}
    for r in recs:
        norms[r["key"]] = N(P[r["key"]])
        m.add(r["key"], r["char"], norms[r["key"]])
    loo = {}
    for r in recs:
        c = m.match(norms[r["key"]], exclude_id=r["key"]).candidates
        loo[r["key"]] = c[0][0] if c else None
    V = {r["key"]: vec(P[r["key"]]) for r in recs}
    by = collections.defaultdict(list)
    for r in recs:
        by[r["char"]].append(r)
    flags = {}
    for ch, rs in by.items():
        ks = [r["key"] for r in rs]
        if len(ks) >= 4:
            M = np.stack([V[k] for k in ks])
            s = (M @ M.T - np.eye(len(ks))).sum(1) / (len(ks) - 1)
            med = float(np.median(s)); mad = float(np.median(np.abs(s - med))) + 1e-6
            for k, v in zip(ks, s):
                if v < med - 3 * mad and v < 0.35:
                    flags.setdefault(k, []).append(f"离群（同字平均相似 {v:.2f}，中位 {med:.2f}）")
        for r in rs:
            t = loo[r["key"]]
            if len(ks) >= 2 and t is not None and not rel(t, ch):
                flags.setdefault(r["key"], []).append(f"留一近邻首选「{t}」≠人裁「{ch}」")
    for r in recs:
        if r.get("per_cell"):
            flags.pop(r["key"], None)
    out = {"n": len(recs), "n_flagged": len(flags),
           "flagged": [{"key": k, "char": next(r["char"] for r in recs if r["key"] == k),
                        "batch": next(r["batch"] for r in recs if r["key"] == k),
                        "cluster": next(r.get("cluster") for r in recs if r["key"] == k),
                        "why": v} for k, v in sorted(flags.items())],
           "by_char": {ch: {"n": len(rs), "flagged": sum(r["key"] in flags for r in rs)}
                       for ch, rs in sorted(by.items(), key=lambda x: -len(x[1]))}}
    json.dump(out, open(d / "screen.json", "w"), ensure_ascii=False, indent=1)
    # 拼图：每字一行，最多 14 格（疑错的全放前面，红框）
    md = d / "montage"
    md.mkdir(exist_ok=True)
    rows_img, T = [], 72
    for ch, rs in sorted(by.items(), key=lambda x: -len(x[1])):
        ks = [r["key"] for r in rs]
        fl = [k for k in ks if k in flags]
        rest = [k for k in ks if k not in flags]
        pick = fl + rest[: max(0, 14 - len(fl))]
        row = np.full((T, T * 15), 255, np.uint8)
        row = cv2.cvtColor(row, cv2.COLOR_GRAY2BGR)
        cv2.putText(row, str(len(rows_img)), (4, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
        for i, k in enumerate(pick[:14]):
            im = P[k]
            h, w = im.shape[:2]
            s = (T - 6) / max(h, w)
            im = cv2.resize(im, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
            tile = np.full((T, T), 255, np.uint8)
            y0, x0 = (T - im.shape[0]) // 2, (T - im.shape[1]) // 2
            tile[y0:y0 + im.shape[0], x0:x0 + im.shape[1]] = im
            tile = cv2.cvtColor(tile, cv2.COLOR_GRAY2BGR)
            if k in flags:
                cv2.rectangle(tile, (0, 0), (T - 1, T - 1), (0, 0, 255), 3)
            row[:, T * (i + 1): T * (i + 2)] = tile
        rows_img.append((ch, row, pick[:14]))
    legend = []
    for g in range(0, len(rows_img), 15):
        chunk = rows_img[g: g + 15]
        cv2.imwrite(str(md / f"m{g // 15:02d}.png"), np.vstack([r for _, r, _ in chunk]))
        legend += [{"sheet": g // 15, "row": i, "char": ch, "keys": ks} for i, (ch, _, ks) in enumerate(chunk)]
    json.dump(legend, open(md / "legend.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "by_char"}, ensure_ascii=False, indent=1)[:3000])


if __name__ == "__main__":
    main()
