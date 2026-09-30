"""page-geometry 金标 v1 帧 → 原图（raw 扫描页）帧迁移（M1·D 道，2026-09-30）。

背景：旧金标的 x 量在 v1 预处理输出 `output/<册>/<页>.png` 上（透视校正+裁到版框），
它的尺寸（如 vol01/101 = 1717×2474）与工作区原图（2353×3053）不同，39/39 页都对不上，
且 v1 链在云端重放不出来（尺寸 2/39 吻合）——所以金标**不能原样用**，必须落到原图上。

做法（**全程用图像内容作判据，不用任何 v2 算法输出**）：
 1. 用旧金标的「界行梳」（12 条左右、列距 ≈184px 的等距模式，人工目视确认过）当模板，
    在原图中带（±4% 页高）的**墨列投影**上做 (缩放 a, 平移 c) 互相关，定位梳子；
 2. 沿梳子预测位置，在原图 16/50/84% 页高三处各做一次**局部脊线拟合**
    （带内斜率 -0.03..0.03 逐档剪切，取覆盖率最高的 x），覆盖率 < COV_MIN 判「图上没有这条线」丢弃；
 3. 保留的界行写成同格式金标（x_top/x_mid/x_bot，band_ys = 原图页高的 16/50/84%，
    `x` 为左上原点，与 PageGeometry 一致）。

输出：新分片目录（samples/*.json + items.jsonl + migration_log.json）。
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import time

import cv2
import numpy as np

TS = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

FRACS = (0.16, 0.50, 0.84)   # 占「版框内竖直跨度」的比例（与 v1 帧里占页高一致，v1 帧=裁到版框）
HALF = 0.04          # 脊线拟合带半高（占页高）
COV_MIN = 0.45       # 与原 build_geometry_dataset.COV_T 相同
# 平移先验：v1 帧 = 原图裁掉左右边距（30 页无歧义页实测 c∈[256,390]、a≈1），取宽窗口防歧义页误锁
C_LO, C_HI = 200, 460
# 版框内竖直跨度可信范围（30 页实测 2440~2520；册级典型 285..2775）
FRAME_H = (2300, 2650)
FRAME_FALLBACK = (285, 2775)
SHAPE_TOL = 12.0   # 新旧三点相对偏移允许差（px）
AMBIG_RATIO = 0.88
SEARCH = 30          # 预测位置附近的搜索半宽 px


def ink(gray):
    return (gray < 128).astype(np.uint8)


def frame_left(b: np.ndarray):
    """原图里最左的长竖线（版框左边）x：中段 35~65% 高、竖向腐蚀（0.6 带高）后最左有墨列。找不到返回 None。"""
    H = b.shape[0]
    band = b[int(H * .35):int(H * .65)]
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (1, int(band.shape[0] * .6)))
    xs = np.where(cv2.erode(band, k).sum(axis=0) > 0)[0]
    return int(xs[0]) if len(xs) else None


def locate_comb(b_mid: np.ndarray, old_x: np.ndarray, prior_c: float | None = None):
    """(a, c, score, info)：x_raw = a*x_old + c。在墨列投影上互相关。

    prior_c：版框左缘先验（frame_left − 旧金标最左界行 x，仅当旧最左线确是版框左缘时给）。
    歧义判据：选定解 ±25px 之外、还有得分 ≥ AMBIG_RATIO(0.88)×选定解的另一个解 → ambiguous（无先验佐证时）。
    """
    prof = b_mid.mean(axis=0).astype(np.float32)
    prof = cv2.GaussianBlur(prof.reshape(1, -1), (0, 0), 1.5).ravel()
    W = len(prof)
    cs = list(range(C_LO, C_HI, 2))
    az = list(np.arange(0.98, 1.0201, 0.004))
    sc = np.full((len(az), len(cs)), -1.0)
    for i, a in enumerate(az):
        xs = old_x * a
        for j, c in enumerate(cs):
            p = np.round(xs + c).astype(int)
            ok = (p >= 0) & (p < W)
            if ok.sum() < max(3, int(0.6 * len(p))):
                continue
            sc[i, j] = prof[p[ok]].sum() / len(p)
    i, j = np.unravel_index(np.argmax(sc), sc.shape)
    g = sc[i, j]
    used_prior = False
    if prior_c is not None:
        jj = [k for k, c in enumerate(cs) if abs(c - prior_c) <= 25]
        if jj:
            sub = sc[:, jj]
            pi, pj = np.unravel_index(np.argmax(sub), sub.shape)
            if sub[pi, pj] >= 0.85 * g:
                i, j, used_prior = pi, jj[pj], True
    chosen = sc[i, j]
    far = [k for k, c in enumerate(cs) if abs(c - cs[j]) > 25]
    comp = float(sc[:, far].max()) if far else 0.0
    ambiguous = (comp >= AMBIG_RATIO * chosen) and not used_prior
    return float(az[i]), float(cs[j]), float(chosen), {"used_prior": used_prior, "competitor_ratio": round(comp / max(chosen, 1e-9), 3), "ambiguous": bool(ambiguous)}


def frame_extent(b: np.ndarray, traces: list, tol: int = 7):
    """版框内竖直方向的墨跨度 (y_top, y_bot)。

    traces 为每条界行的 (x_ref, slope, y_ref)：沿这条线（±tol）逐行看有没有墨，
    ≥50% 的界行在该行有墨 → 该行属于版框内；取最长连续段（合并 ≤40px 缺口）。
    """
    H, W = b.shape
    cnt = np.zeros(H)
    for xr, sl, yr in traces:
        for y in range(H):
            x = xr + sl * (y - yr)
            x0, x1 = int(max(0, x - tol)), int(min(W, x + tol + 1))
            if x1 - x0 >= 3 and b[y, x0:x1].any():
                cnt[y] += 1
    good = (cnt >= 0.5 * max(len(traces), 1)).astype(np.uint8)
    good = cv2.morphologyEx(good.reshape(-1, 1), cv2.MORPH_CLOSE, np.ones((41, 1), np.uint8)).ravel()
    best, cur0 = (0, 0), None
    for y in range(H + 1):
        v = good[y] if y < H else 0
        if v and cur0 is None:
            cur0 = y
        if not v and cur0 is not None:
            if y - cur0 > best[1] - best[0]:
                best = (cur0, y)
            cur0 = None
    return best


def ridge(b: np.ndarray, yc: int, half: int, xp: float, search: int = SEARCH):
    """在 (yc±half, xp±search) 内找一条竖脊线，返回 (x, coverage) 或 None。"""
    H, W = b.shape
    y0, y1 = max(0, yc - half), min(H, yc + half)
    x0, x1 = int(max(0, xp - search - 40)), int(min(W, xp + search + 40))
    win = b[y0:y1, x0:x1]
    h = win.shape[0]
    if h < 20 or win.shape[1] < 10:
        return None
    best = None
    ys = np.arange(h) - h / 2
    for slope in np.arange(-0.03, 0.0301, 0.003):
        sh = np.round(ys * slope).astype(int)
        cov = np.zeros(win.shape[1])
        for row, s in zip(win, sh):
            cov += np.roll(row, -s)
        cov /= h
        # 线宽 ~5px：3px 盒平滑后取峰
        sm = np.convolve(cov, np.ones(3) / 3, mode="same")
        lo, hi = int(xp - x0 - search), int(xp - x0 + search) + 1
        lo, hi = max(lo, 0), min(hi, len(sm))
        if hi <= lo:
            continue
        j = lo + int(np.argmax(sm[lo:hi]))
        if best is None or sm[j] > best[1]:
            # 峰宽质心
            k0, k1 = max(0, j - 4), min(len(cov), j + 5)
            w = cov[k0:k1]
            cx = float((np.arange(k0, k1) * w).sum() / max(w.sum(), 1e-9))
            best = (cx + x0, float(sm[j]))
    if best is None:
        return None
    return best


def accept_reason(m: dict, old: dict) -> str | None:
    """页级准入：返回排除原因，None=通过。只用图像内容证据（梳子互相关得分/歧义度/版框左缘先验），不看任何 v2 产物。"""
    ci = m["comb"]
    if ci["ambiguous"]:
        return f"梳子定位歧义（另一平移解得分为选定解的 {ci['competitor_ratio']:.2f}≥{AMBIG_RATIO}，且无版框左缘先验佐证）"
    if ci["used_prior"]:
        if m["comb_score"] < 0.45 or ci["competitor_ratio"] >= 0.9:
            return f"有先验但梳子得分弱（{m['comb_score']:.2f}）或竞争解过近（{ci['competitor_ratio']:.2f}）"
    elif m["comb_score"] < 0.5:
        return f"梳子得分 {m['comb_score']:.2f}<0.5 且无先验佐证"
    xl = m["frame_left"]
    om = min(r["x_mid"] for r in old["rules"])
    if xl is not None and om < 40 and xl < 420 and abs(m["c"] - (xl - om)) > 30:
        return f"平移 c={m['c']:.0f} 与版框左缘先验 {xl - om:.0f} 相差 >30px"
    if len(m["rules"]) < 3:
        return "保留界行<3（与原建集规则一致地排除）"
    return None


def migrate_page(gray: np.ndarray, old: dict):
    H, W = gray.shape
    b = ink(gray)
    om = np.array([r["x_mid"] for r in old["rules"]], float)
    mid0 = int(H * 0.5)
    band = b[max(0, mid0 - int(H * HALF)):mid0 + int(H * HALF)]
    xl = frame_left(b)
    prior = None
    if xl is not None and om.min() < 40 and xl < 420:     # 旧最左线 x<40 → 它就是版框左缘
        prior = xl - om.min()
    a, c, score, info = locate_comb(band, om, prior)
    # 阶段 1：页中段（35/50/65% 页高，必在版框内）先拟每条线，沿线外推去找版框上下端
    y1s = [int(H * f) for f in (0.35, 0.50, 0.65)]
    traces = []
    for r in old["rules"]:
        pred = a * r["x_mid"] + c
        g1 = [ridge(b, y, int(H * 0.04), pred + a * (r[k] - r["x_mid"]))
              for y, k in zip(y1s, ("x_top", "x_mid", "x_bot"))]
        if all(g is not None and g[1] >= COV_MIN for g in g1):
            sl = (g1[2][0] - g1[0][0]) / (y1s[2] - y1s[0])
            traces.append((g1[1][0], sl, y1s[1]))
    yt, yb = frame_extent(b, traces) if len(traces) >= 3 else (0, H)
    frame_src = "measured"
    if not (FRAME_H[0] <= yb - yt <= FRAME_H[1]):   # 稀疏页（职名/目录）取不到可信跨度 → 册级典型版框
        yt, yb = FRAME_FALLBACK
        frame_src = "fallback"
    ys = [int(yt + f * (yb - yt)) for f in FRACS]
    half = int((yb - yt) * HALF)
    # 旧金标的 x_top/x_mid/x_bot 在 v1 帧的 16/50/84% 高，斜率用它们推到原图帧（高度比例不同，取相对位置）
    # 第一遍：逐条逐高度脊线拟合
    fits = []
    for r in old["rules"]:
        pred = a * r["x_mid"] + c
        got = []
        for yc, key in zip(ys, ("x_top", "x_mid", "x_bot")):
            # 预测：以 mid 为基准，按旧斜率线性外推
            px = pred + a * (r[key] - r["x_mid"])
            got.append(ridge(b, yc, half, px))
        fits.append((r, pred, got))
    # 形状护栏：新旧三点「相对偏移」之差 = 原图相对 v1 帧多出来的整页错切/透视，应随页基本一致（取页中位数）；
    # 偏离中位数 > SHAPE_TOL 的多半是某个高度锁到了字笔画上。
    d_top, d_bot = [], []
    for r, pred, got in fits:
        if all(g is not None and g[1] >= COV_MIN for g in got):
            d_top.append((got[0][0] - got[1][0]) - a * (r["x_top"] - r["x_mid"]))
            d_bot.append((got[2][0] - got[1][0]) - a * (r["x_bot"] - r["x_mid"]))
    m_top = float(np.median(d_top)) if d_top else 0.0
    m_bot = float(np.median(d_bot)) if d_bot else 0.0
    rules, dropped = [], []
    for r, pred, got in fits:
        cov_ok = all(g is not None and g[1] >= COV_MIN for g in got)
        shape_ok = True
        if cov_ok:
            dt = (got[0][0] - got[1][0]) - a * (r["x_top"] - r["x_mid"])
            db = (got[2][0] - got[1][0]) - a * (r["x_bot"] - r["x_mid"])
            shape_ok = abs(dt - m_top) <= SHAPE_TOL and abs(db - m_bot) <= SHAPE_TOL
        if cov_ok and shape_ok:
            rules.append({"x_top": round(got[0][0], 1), "x_mid": round(got[1][0], 1),
                          "x_bot": round(got[2][0], 1), "kind": r.get("kind", "rule"),
                          "cov": [round(g[1], 2) for g in got]})
        else:
            dropped.append({"old_x_mid": r["x_mid"], "pred": round(pred, 1), "shape_ok": shape_ok,
                            "cov": [None if g is None else round(g[1], 2) for g in got]})
    return {"a": round(a, 4), "c": c, "comb_score": round(score, 3),
            "comb": info, "frame_left": xl, "band_ys": [float(y) for y in ys], "frame_y": [yt, yb], "frame_src": frame_src, "rules": rules, "dropped": dropped}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", default="../open-guji-dataset/page-geometry")
    ap.add_argument("--raw-root", default=None, help="默认 $GUJI_WORKSPACE/data_full/zongmu")
    ap.add_argument("--out", required=True)
    ap.add_argument("--apply", action="store_true", help="写 samples/ 与 items.jsonl")
    args = ap.parse_args()
    raw_root = Path(args.raw_root or Path(os.environ["GUJI_WORKSPACE"]) / "data_full" / "zongmu")
    out = Path(args.out)
    (out / "samples").mkdir(parents=True, exist_ok=True)
    log = []
    items = []
    for f in sorted(Path(args.old, "samples").glob("*.json")):
        old = json.loads(f.read_text(encoding="utf-8"))
        b, p = old["book"], old["page"]
        gray = cv2.imread(str(raw_root / b / f"{p}.png"), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            log.append({"book": b, "page": p, "error": "原图缺失"})
            continue
        m = migrate_page(gray, old)
        H, W = gray.shape
        rec = {"book": b, "page": p, "old_size": old["image_size"], "raw_size": {"width": W, "height": H},
               "n_old": len(old["rules"]), "n_kept": len(m["rules"]), **{k: m[k] for k in ("a", "c", "comb_score", "comb", "frame_left", "dropped", "frame_y", "frame_src")}}
        log.append(rec)
        print(b, p, rec["n_old"], "->", rec["n_kept"], "a=%.3f c=%.0f score=%.2f" % (m["a"], m["c"], m["comb_score"]), m["comb"], "xL", m["frame_left"], flush=True)
        why = accept_reason(m, old)
        if why:
            rec["excluded"] = why
            print("   排除:", why, flush=True)
            # 旧 v1 帧金标原样留档为 stale（评测不读，将来重标时可对照）
            items.append({"id": f"{b}_{p}", "anchor": {"book": b, "page": int(p)},
                          "input": {"legacy_source": f"samples/{b}_{p}.json", "coordinate_frame": "v1_frame"},
                          "expected": {k: old[k] for k in ("band_ys", "image_size", "n_cols", "page_class", "rules")},
                          "label_origin": "human", "status": "stale", "source_events": [],
                          "history": [{"change": "stale", "ts": TS, "why": "v1 帧金标无法可靠迁到原图帧：" + why}]})
            continue
        if len(m["rules"]) < 3:
            rec["excluded"] = "保留界行<3，与原建集规则一致地排除"
            continue
        g = {"book": b, "page": p, "image_size": {"width": W, "height": H},
             "band_ys": m["band_ys"],
             "rules": [{k: r[k] for k in ("x_top", "x_mid", "x_bot", "kind")} for r in m["rules"]],
             "n_cols": old.get("n_cols"), "page_class": old.get("page_class"),
             "label_origin": "derived", "schema_version": 1,
             "coordinate_frame": "raw_page_px@top-left", "frame_y": [float(v) for v in m["frame_y"]]}
        (out / "samples" / f"{b}_{p}.json").write_text(json.dumps(g, ensure_ascii=False, indent=1), encoding="utf-8")
        items.append({"id": f"{b}_{p}", "anchor": {"book": b, "page": int(p)},
                      "input": {"migrated_from": f"samples/{b}_{p}.json (v1 帧)", "coordinate_frame": g["coordinate_frame"]},
                      "expected": {k: g[k] for k in ("band_ys", "image_size", "n_cols", "page_class", "rules", "frame_y")},
                      "label_origin": "derived", "status": "active", "source_events": [],
                      "history": [{"change": "migrated", "ts": TS,
                                   "why": f"v1 帧→原图帧：{rec['n_old']} 条旧界行中 {rec['n_kept']} 条在原图上验证保留（migrate_geometry_gold.py）"}]})
    (out / "items.jsonl").write_text(
        "".join(json.dumps(i, ensure_ascii=False, sort_keys=True) + "\n" for i in items), encoding="utf-8")
    (out / "migration_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print("写出", len(items), "页 →", out)


if __name__ == "__main__":
    main()
