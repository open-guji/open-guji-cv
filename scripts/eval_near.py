"""3b 形近字组整体 benchmark（CV3，2026-11-28；方案稿 ai-team domain/CV/A24/形近字组整体方案 第八、十一节 D「3b 整体」）。

只读 `scripts/build_near_bench.py` 冻好的东西（每书一册 test、一册 fit：3a 记录、放行字／人裁标签、被触发格的字块图），
按 `bench.json` 里每本书的 3b 书配置跑 `groups.near_methods` 的各方法，报：

- **触发量**：每组按触发方式数格（`_guard` 的 `gap` 一路只数、不判，没冻图）；
- **覆盖率**：放行字（去掉 3b 方法自己那几条放行通道，见 `labels.circular_channels`）／人裁字落在组内的格，被这组触发的比例；
- **方法级**：判出字的格的准确率、弃权率、空分（sims 为空）率、错例前 20 个 id；
- **方法间一致率**：同一格两个方法都判出字时，判的是不是同一个字；各方法与 3a 首位、与标签的一致率；
- **校准误差**：方法带校准表（或 `--calib-dir` 给的临时表）时，test 册上的 ECE（10 等宽箱）、Brier；
- **耗时**：每个方法每格毫秒（只算方法打分，不含出图；字块图已冻好）、载入模型秒数；
- **指纹**：`method_fingerprint`、`model_sha`、模型文件 sha256 与 `bench.json` 钉的是否一致，同一批格再打一遍分是否逐位相同。

`--fit-calib DIR`：拿 fit 册的 (原始分, 标签) 对每个「方法×组」做保序回归，出**临时**校准表 `near-calib/1`
（带 `version`、`temporary: true`、`fit_on`、`holdout`），在 test 册上报 holdout ECE（按册留出）；样本不够的组不出表、列进报告。
临时表只给排序展示用（Sheldon 11-28 定，不用于自动放行），收尾 `glyph_analyzer` 见 `temporary` 只出 `p_tmp`、不出 `p`。

模型文件：`models/…` 在 cv 仓；`config/groups/…` 在本书中心库数据目录 `<--data>/<工作区 id>/`（缺省
`$GUJI_DATA_HOME/main`，没设时 `~/.guji-data/main`；`guji db pull -w <工作区>` 拉下来，只读）。缺模型的组跳过并报 `missing_model`。

用法：
    PYTHONPATH=. python scripts/eval_near.py <dataset>/glyph-near/bench3b [--out report.json] [--data DIR]
        [--calib-dir DIR] [--fit-calib DIR] [--books 书,书] [--repeat 50]
"""
from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

CALIB_VERSION = "tmp-2026-11-28.1"
MIN_FIT = 30          # 拟合至少这么多格
MIN_CLASS = 5         # 正反两类各至少这么多格
BINS = 10


# ───────────────────────── 读冻结集 ─────────────────────────

def cv_version() -> str:
    """cv 的版本（装了包就取包版本，再接仓里 HEAD 短哈希）。"""
    import subprocess
    from importlib.metadata import PackageNotFoundError, version
    try:
        v = version("open-guji-cv")
    except PackageNotFoundError:
        v = "?"
    try:
        h = subprocess.run(["git", "-C", str(Path(__file__).resolve().parents[1]), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=10, check=False).stdout.strip()
    except Exception:  # noqa: BLE001
        h = ""
    return f"{v}+{h}" if h else v


def read_cells(d: Path) -> list[dict]:
    with gzip.open(d / "cells.jsonl.gz", "rt", encoding="utf-8") as f:
        return [json.loads(x) for x in f]


def sha_of(p: Path) -> str:
    if p.is_dir():
        h = hashlib.sha256()
        for f in sorted(p.iterdir()):
            if f.is_file():
                h.update(f.name.encode())
                h.update(hashlib.sha256(f.read_bytes()).digest())
        return "dir:" + h.hexdigest()
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else "missing"


def model_path(rel: str, ws: str, data: Path) -> Path:
    return REPO / rel if rel.startswith("models/") else data / ws / rel


def abs_spec(sp, ws: str, data: Path):
    if isinstance(sp, str):
        return str(model_path(sp, ws, data))
    return {**sp, "path": str(model_path(sp["path"], ws, data))}


def rel_of(sp) -> str:
    return sp if isinstance(sp, str) else sp["path"]


def calib_path(rel: str, root: Path) -> Path:
    """临时校准表落点：模型目录 → `<目录>/calib.json`；模型文件 → 同名 `<去 .json>.calib.json`（同 near_methods 的读法）。"""
    p = root / rel
    if not rel.endswith(".json"):
        return p / "calib.json"
    return p.with_name(p.name[:-5] + ".calib.json")


# ───────────────────────── 标签 ─────────────────────────

def truth(cell: dict, circular: set, gold_only: bool = False) -> str | None:
    """这一格的真字：人裁优先（`gold_char`）；否则放行字（去掉 3b 方法自己的放行通道，免得循环）。"""
    lab = cell.get("label") or {}
    if lab.get("gold_char"):
        return lab["gold_char"]
    if gold_only:
        return None
    if lab.get("char") and lab.get("channel") not in circular:
        return lab["char"]
    return None


def canon(c, fold: dict):
    return fold.get(c, c) if c else c


def mfold(m) -> dict:
    """方法层面算「同一个字」的折叠：只有方法自己声明异体不分的（cnn_small 的 `merge`，宮→宫）。
    **不用登记表组的 fold**——hou 组 fold 把 𠋫 折成 候，hou_shape 要分的正是这两个字，折了就看不出错。"""
    return dict(getattr(m, "merge", None) or {})


# ───────────────────────── 方法输出 → 判字 ─────────────────────────

def pick_of(out: dict) -> tuple[str | None, bool]:
    """方法一格的输出 → (判的字, 是否弃权)。证据里有 `char` 的方法（rr／wu／hou／part／pair／book_knn）按它；
    stroke_veto 按 `cls`（类名，单字类就是字）；没有结论的（near_knn 只出量）取 sims 最高的字、不算弃权。"""
    ev, sims = out.get("evidence") or {}, out.get("sims") or {}
    if ev.get("error"):
        return None, True
    why = str(ev.get("why") or "")
    if ev.get("method") == "stroke_veto":
        c = ev.get("cls")
        return (c if c and len(c) == 1 else None), c is None
    if "char" in ev or ev.get("method") in ("rr_shape", "wu_shape", "hou_shape", "part_shape", "pair_shape", "book_knn"):
        c = ev.get("char")
        return c, c is None or why.startswith("abstain")
    if not sims:
        return None, True
    return max(sims, key=lambda k: (sims[k], k)), False


def method_chars(m, members: set) -> set:
    """方法真能分的字：二选一的刻形判法只认它那两三个字（hou_shape 只认 候𠋫，登记表 hou 组还有 侯俟𠉀）；
    近邻库方法（book_knn、near_knn）与没声明的按组成员。准确率只在真字落在这里面的格上算。"""
    name = type(m).__name__
    if name == "RrShape":
        return {"入", "人", "八"}
    if name == "StrokeVeto":
        return {c for v in m.members.values() for c in v}
    if name == "CnnSmall":
        return set(m.classes) | set(m.merge)
    ch = getattr(m, "chars", None)
    if ch and name not in ("BookKnn", "NearKnn"):
        return set(ch)
    return set(members)


def p_of(m, sims: dict) -> dict | None:
    try:
        return m.calibrate(sims) if sims else None
    except Exception:  # noqa: BLE001
        return None


def ece(conf: list[float], ok: list[bool], bins: int = BINS) -> float | None:
    if not conf:
        return None
    c, o = np.asarray(conf, float), np.asarray(ok, float)
    lo = 0.5 if c.min() >= 0.5 else 0.0
    edges = np.linspace(lo, 1.0, bins + 1)
    idx = np.clip(np.digitize(c, edges[1:-1]), 0, bins - 1)
    e = 0.0
    for b in range(bins):
        s = idx == b
        if s.any():
            e += s.sum() / len(c) * abs(o[s].mean() - c[s].mean())
    return round(float(e), 4)


# ───────────────────────── 保序回归（PAV） ─────────────────────────

def isotonic(x: list[float], y: list[int]) -> tuple[list[float], list[float]]:
    """(分, 0/1) → 单调不减的分段常数，出 knots（每段的最小、最大分各一个点，值＝段内 (正例+0.5)/(n+1)，
    不给 0／1 这种过满的值）。np.interp 在两端外取端点值。"""
    o = np.argsort(np.asarray(x, float), kind="stable")
    xs, ys = np.asarray(x, float)[o], np.asarray(y, float)[o]
    blocks: list[list] = []                      # [sum_y, n, x_lo, x_hi]
    for xv, yv in zip(xs, ys):
        blocks.append([yv, 1, xv, xv])
        while len(blocks) > 1 and blocks[-2][0] / blocks[-2][1] >= blocks[-1][0] / blocks[-1][1]:
            s, n, lo, hi = blocks.pop()
            blocks[-1][0] += s
            blocks[-1][1] += n
            blocks[-1][3] = hi
    kx, ky = [], []
    for s, n, lo, hi in blocks:
        v = round((s + 0.5) / (n + 1), 4)
        for xv in ((lo,) if lo == hi else (lo, hi)):
            if kx and xv <= kx[-1]:
                xv = kx[-1] + 1e-6
            kx.append(round(float(xv), 6))
            ky.append(v)
    return kx, ky


def two_class(m) -> tuple[str, str] | None:
    """能出 p 的二分类方法 → (正类字＝校准表 knots 的键, 反类字)；不读校准表的方法（book_knn、near_knn）→ None。"""
    name = type(m).__name__
    if name == "RrShape":
        return "入", "人"
    if name in ("WuShape", "PartShape", "PairShape"):
        return m.chars[1], m.chars[0]
    if name == "HouShape":
        return m.chars[0], m.chars[1]
    if name == "StrokeVeto":
        if any(len(v) != 1 for v in m.members.values()):
            return None
        (a,), (b,) = m.members[m.classes[0]], m.members[m.classes[1]]
        return a, b
    if name == "CnnSmall" and len(m.classes) == 2:
        pos = next((c for c in m.classes if c in ((m.calib or {}).get("knots") or {})), m.classes[1])
        return pos, next(c for c in m.classes if c != pos)
    return None


def fit_xy(m, rows: list[dict], pos: str, neg: str, fold: dict) -> tuple[list, list, dict]:
    """一个方法在一批格上的 (正类原始分, 是否正类)；rr_shape 的几何判 八 那一路另数（给 rule）。"""
    x, y, extra = [], [], {"ba": [0, 0]}
    for r in rows:
        t = canon(r["truth"], fold)
        sims = r["out"].get("sims") or {}
        if type(m).__name__ == "RrShape" and sims.get("八") == 1.0:
            if t in ("入", "人", "八"):
                extra["ba"][0] += 1
                extra["ba"][1] += int(t == "八")
            continue
        if t not in (canon(pos, fold), canon(neg, fold)) or pos not in sims:
            continue
        x.append(float(sims[pos]))
        y.append(int(t == canon(pos, fold)))
    return x, y, extra


# ───────────────────────── 主流程 ─────────────────────────

def run_book(shard: Path, bk: str, spec: dict, data: Path, circular: set, calib_dir: Path | None,
             repeat: int) -> tuple[dict, dict]:
    from open_guji_cv.groups.near_methods import load_method, method_fingerprint, score
    from open_guji_cv.groups.near_registry import resolve
    from open_guji_cv.steps.glyph_near import GUARD_GROUP, trigger_groups

    ws = spec["ws"]
    vols = spec["vols"]
    test_vol = next(v for v, s in vols.items() if s["role"] == "test")
    groups, skipped = resolve(dict(spec["groups"]), test_vol)
    rep: dict = {"title": spec.get("title"), "ws": ws, "vols": {v: s["role"] for v, s in vols.items()},
                 "skipped_methods": [f"{n}:{m}（登记表 {g}）" for n, g, m in skipped], "groups": {}, "models": {}}
    # 载入方法
    methods: dict[str, list] = {}
    for gid, g in sorted(groups.items()):
        ms = []
        for name, sp in sorted((g.get("methods") or {}).items()):
            rel = rel_of(sp)
            p = model_path(rel, ws, data)
            pin = (spec.get("models") or {}).get(rel, {}).get("sha256")
            info = {"file": rel, "sha256": sha_of(p), "pinned": pin}
            info["pin_ok"] = pin is None or info["sha256"] == pin
            if not p.exists():
                rep["models"][f"{name}:{gid}"] = {**info, "error": "missing_model"}
                continue
            t0 = time.time()
            m = load_method(name, abs_spec(sp, ws, data))
            info["load_s"] = round(time.time() - t0, 2)
            info["fingerprint"] = method_fingerprint(name, abs_spec(sp, ws, data))
            info["model_sha"] = str(getattr(m, "model_sha", "") or "")
            info["note"] = (spec.get("models") or {}).get(rel, {}).get("note", "")
            if calib_dir is not None:
                cp = calib_path(rel, calib_dir / ws)
                if cp.is_file():
                    m.calib = json.loads(cp.read_text(encoding="utf-8"))
                    info["calib"] = {"src": str(cp), "version": m.calib.get("version"),
                                     "temporary": bool(m.calib.get("temporary"))}
            if "calib" not in info and getattr(m, "calib", None):
                info["calib"] = {"src": "随模型", "version": m.calib.get("version"),
                                 "temporary": bool(m.calib.get("temporary"))}
            rep["models"][f"{name}:{gid}"] = info
            ms.append((name, m))
        methods[gid] = ms

    per_vol: dict = {}
    fit_rows: dict = collections.defaultdict(list)       # (组, 方法) → fit 册的 [{truth, out}]
    test_rows: dict = collections.defaultdict(list)
    for vol, vs in vols.items():
        d = shard / bk / vol
        cells = read_cells(d)
        trig = collections.defaultdict(collections.Counter)    # 组 → 触发方式 → 格数
        hits = collections.defaultdict(list)                   # 组 → [格]
        cov = collections.defaultdict(lambda: {"silver": [0, 0], "gold": [0, 0]})
        n_lab = collections.Counter()
        for c in cells:
            a = c["a"]
            from types import SimpleNamespace
            got = trigger_groups([tuple(x) for x in a["cands"]], a["char"], groups,
                                 SimpleNamespace(guard=a["guard"], verdict=a["verdict"]))
            tg = {g for g, _ in got}
            for g, how in got:
                trig[g][how] += 1
                hits[g].append((c, how))
            t_s, t_g = truth(c, circular), truth(c, circular, gold_only=True)
            n_lab["silver"] += t_s is not None
            n_lab["gold"] += t_g is not None
            for gid, g in groups.items():
                if gid == GUARD_GROUP:
                    continue
                fold = dict(g.get("fold") or {})
                mem = {canon(x, fold) for x in (g.get("chars") or [])}
                for kind, t in (("silver", t_s), ("gold", t_g)):
                    if t is not None and canon(t, fold) in mem:
                        cov[gid][kind][0] += 1
                        cov[gid][kind][1] += gid in tg
        vrep = {"role": vs["role"], "pack": vs["pack"], "cells": len(cells), "labeled": dict(n_lab), "groups": {}}
        for gid in sorted(groups):
            g = groups[gid]
            fold = dict(g.get("fold") or {})
            gr = {"triggered": sum(trig[gid].values()), "by_trigger": dict(trig[gid])}
            if gid != GUARD_GROUP:
                gr["coverage"] = {k: {"n": v[0], "covered": v[1], "rate": round(v[1] / v[0], 4) if v[0] else None}
                                  for k, v in cov[gid].items()}
            gr["methods"] = {}
            for name, m in methods.get(gid, []):
                kind = getattr(m, "patch", "raw")
                use, no_img, errs = [], 0, 0
                for c, how in hits[gid]:
                    img = c.get("img") or {}
                    f = img.get("p" if kind == "char_patch" else "r")
                    if not f:
                        no_img += 1
                        errs += bool(img.get("p_error"))
                        continue
                    use.append(c)
                pats = [cv2.imread(str(d / c["img"]["p" if kind == "char_patch" else "r"]), cv2.IMREAD_GRAYSCALE)
                        for c in use]
                cl = [{"id": c["id"], "page": c["page"], "col": c["col"], "slot": c["slot"], "sub": c["sub"],
                       "patch_key": c["patch_key"], "char": c["a"]["char"],
                       "candidates": [tuple(x) for x in c["a"]["cands"]]} for c in use]
                t0 = time.time()
                outs = score(m, pats, vol, cells=cl) if pats else []
                dt = time.time() - t0
                rep_eq = None
                if repeat and pats:
                    again = score(m, pats[:repeat], vol, cells=cl[:repeat])
                    rep_eq = all(json.dumps(x, sort_keys=True, ensure_ascii=False) == json.dumps(y, sort_keys=True, ensure_ascii=False)
                                 for x, y in zip(outs[:repeat], again))
                st = collections.Counter()
                errs_l, conf, okl, briers = [], [], [], []
                mf = mfold(m)
                mem = {canon(x, mf) for x in method_chars(m, set(g.get("chars") or []))}
                for c, o in zip(use, outs):
                    pk, ab = pick_of(o)
                    t = truth(c, circular)
                    a1 = c["a"]["char"] or (c["a"]["cands"][0][0] if c["a"]["cands"] else None)
                    row = {"id": c["id"], "truth": t, "gold": bool((c.get("label") or {}).get("gold_char")),
                           "out": o, "pick": pk, "abstain": ab, "a1": a1, "universe": mem, "mf": mf,
                           "in_scope": t is not None and (gid == GUARD_GROUP or canon(t, mf) in mem)}
                    (fit_rows if vs["role"] == "fit" else test_rows)[(gid, name)].append(row)
                    st["scored"] += 1
                    st["empty"] += not (o.get("sims"))
                    st["abstain"] += ab
                    if not row["in_scope"]:
                        continue
                    st["labeled"] += 1
                    if not ab and pk is not None:
                        st["decided"] += 1
                        if canon(pk, mf) == canon(t, mf):
                            st["right"] += 1
                        else:
                            st["wrong"] += 1
                            if len(errs_l) < 20:
                                errs_l.append({"id": c["id"], "truth": t, "pick": pk, "a1": a1,
                                               "gold": row["gold"]})
                    else:
                        st["labeled_abstain"] += 1
                    ps = p_of(m, o.get("sims") or {})
                    if ps:
                        best = max(ps, key=lambda k: (ps[k], k))
                        conf.append(float(ps[best]))
                        okl.append(canon(best, mf) == canon(t, mf))
                        briers.append(sum((float(v) - (canon(k, mf) == canon(t, mf))) ** 2 for k, v in ps.items()))
                mr = {"patch": kind, "scored": st["scored"], "no_img": no_img, "patch_error": errs,
                      "empty_sims": st["empty"], "abstain": st["abstain"],
                      "abstain_rate": round(st["abstain"] / st["scored"], 4) if st["scored"] else None,
                      "labeled": st["labeled"], "decided": st["decided"], "right": st["right"], "wrong": st["wrong"],
                      "acc": round(st["right"] / st["decided"], 4) if st["decided"] else None,
                      "labeled_abstain_rate": round(st["labeled_abstain"] / st["labeled"], 4) if st["labeled"] else None,
                      "errors": errs_l, "ms_per_cell": round(1000 * dt / len(pats), 2) if pats else None,
                      "seconds": round(dt, 2), "repeat_equal": rep_eq}
                if conf:
                    mr["calib"] = {"n": len(conf), "ece": ece(conf, okl), "brier": round(float(np.mean(briers)), 4),
                                   "version": ((getattr(m, "calib", None) or {}).get("version")),
                                   "temporary": bool((getattr(m, "calib", None) or {}).get("temporary"))}
                gr["methods"][name] = mr
            vrep["groups"][gid] = gr
        vrep["agreement"] = agreement(test_rows if vs["role"] == "test" else fit_rows)
        per_vol[vol] = vrep
    rep["per_vol"] = per_vol
    return rep, {"fit": fit_rows, "test": test_rows, "methods": methods, "groups": groups}


def agreement(rows_by: dict) -> dict:
    """同一格各方法的判字两两比；各方法与 3a 首位、与标签比。
    两两比只算「两个方法都判出字、且各自判的字都在对方能分的字里」的格（hou_shape 只认 候𠋫，near_knn 判 侯 的格不比）；
    与标签比只算真字落在方法能分的字里的格；与 3a 首位比只算 3a 首位落在方法能分的字里的格。"""
    by_cell = collections.defaultdict(dict)
    univ: dict = {}
    out: dict = {"vs_3a": {}, "vs_label": {}, "pairs": {}}
    for (gid, name), rows in rows_by.items():
        key = f"{name}:{gid}"
        a3 = [0, 0]
        lab = [0, 0]
        for r in rows:
            if r["abstain"] or r["pick"] is None:
                continue
            univ[key] = r["universe"] if gid != "_guard" else None
            by_cell[r["id"]][key] = r["pick"]
            if r["a1"] and (univ[key] is None or r["a1"] in univ[key]):
                a3[0] += 1
                a3[1] += r["pick"] == r["a1"]
            if r["in_scope"]:
                lab[0] += 1
                lab[1] += canon(r["pick"], r["mf"]) == canon(r["truth"], r["mf"])
        out["vs_3a"][key] = {"n": a3[0], "agree": a3[1], "rate": round(a3[1] / a3[0], 4) if a3[0] else None}
        out["vs_label"][key] = {"n": lab[0], "agree": lab[1], "rate": round(lab[1] / lab[0], 4) if lab[0] else None}
    pc = collections.defaultdict(lambda: [0, 0])
    for picks in by_cell.values():
        ks = sorted(picks)
        for i in range(len(ks)):
            for j in range(i + 1, len(ks)):
                ua, ub = univ.get(ks[i]), univ.get(ks[j])
                if (ub is not None and picks[ks[i]] not in ub) or (ua is not None and picks[ks[j]] not in ua):
                    continue
                pc[f"{ks[i]}|{ks[j]}"][0] += 1
                pc[f"{ks[i]}|{ks[j]}"][1] += picks[ks[i]] == picks[ks[j]]
    out["pairs"] = {k: {"n": v[0], "agree": v[1], "rate": round(v[1] / v[0], 4)} for k, v in sorted(pc.items())}
    return out


def fit_calibs(bk: str, spec: dict, st: dict, out_dir: Path) -> dict:
    """fit 册拟合、test 册报 holdout。返回 {方法:组: 结果}。"""
    res = {}
    ws = spec["ws"]
    fit_vol = next((v for v, s in spec["vols"].items() if s["role"] == "fit"), None)
    if fit_vol is None:
        return {}
    test_vol = next(v for v, s in spec["vols"].items() if s["role"] == "test")
    for gid, ms in sorted(st["methods"].items()):
        for name, m in ms:
            key = f"{name}:{gid}"
            tc = two_class(m)
            if tc is None:
                res[key] = {"status": "no_calib_reader", "why": "方法不读校准表（book_knn／near_knn 票份额只当证据；多类方法）"}
                continue
            if type(m).__name__ == "CnnSmall":
                res[key] = {"status": "has_calib", "why": "已有正式校准表（殿本 5 折留出），不出临时表"}
                continue
            pos, neg = tc
            x, y, extra = fit_xy(m, st["fit"].get((gid, name), []), pos, neg, mfold(m))
            npos = sum(y)
            if len(x) < MIN_FIT or npos < MIN_CLASS or len(x) - npos < MIN_CLASS:
                res[key] = {"status": "too_few", "n": len(x), "n_pos": npos, "pos": pos, "neg": neg,
                            "why": f"fit 册 {fit_vol} 可用格 {len(x)}（{pos} {npos}／{neg} {len(x) - npos}），"
                                   f"要 ≥{MIN_FIT} 且两类各 ≥{MIN_CLASS}"}
                continue
            kx, ky = isotonic(x, y)
            tab = {"format": "near-calib/1", "version": CALIB_VERSION, "temporary": True,
                   "use": "只给排序展示，不用于自动放行（Sheldon 11-28）",
                   "method": name, "group": gid, "book": bk,
                   "fit_on": {"vol": fit_vol, "n": len(x), "n_pos": npos,
                              "labels": "seed_admit 放行字（去掉 3b 方法自己的放行通道）＋人裁",
                              "algo": "保序回归 PAV，段值 (正例+0.5)/(n+1)"},
                   "knots": {pos: [kx, ky]}}
            if type(m).__name__ == "RrShape" and extra["ba"][0] >= MIN_CLASS:
                n_ba, n_ok = extra["ba"]
                tab["rule"] = {"八": round((n_ok + 0.5) / (n_ba + 1), 4)}
                tab["fit_on"]["rule_n"] = n_ba
            # holdout：test 册
            hx, hy, _ = fit_xy(m, st["test"].get((gid, name), []), pos, neg, mfold(m))
            conf, okl, br = [], [], []
            for xv, yv in zip(hx, hy):
                p = float(np.interp(xv, kx, ky))
                conf.append(max(p, 1 - p))
                okl.append((p >= 0.5) == bool(yv))
                br.append((p - yv) ** 2 * 2)
            tab["holdout"] = {"vol": test_vol, "n": len(hx), "n_pos": int(sum(hy)), "ece": ece(conf, okl),
                              "brier": round(float(np.mean(br)), 4) if br else None}
            ic, io = [], []
            for xv, yv in zip(x, y):
                p = float(np.interp(xv, kx, ky))
                ic.append(max(p, 1 - p))
                io.append((p >= 0.5) == bool(yv))
            tab["fit_on"]["ece_in_sample"] = ece(ic, io)
            rel = rel_of(st["groups"][gid]["methods"][name])
            dest = calib_path(rel, out_dir / ws)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.is_file():                       # 一份模型文件挂几组（stroke_veto）：并 knots
                old = json.loads(dest.read_text(encoding="utf-8"))
                old["knots"].update(tab["knots"])
                tab = {**old, "knots": old["knots"]}
            dest.write_text(json.dumps(tab, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
            res[key] = {"status": "ok", "file": str(dest.relative_to(out_dir)), "n_fit": len(x), "n_pos": npos,
                        "holdout": tab["holdout"], "ece_in_sample": tab["fit_on"]["ece_in_sample"],
                        "knots": len(kx), "rule": tab.get("rule")}
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shard")
    ap.add_argument("--out")
    ap.add_argument("--data", help="中心库数据目录的分支层（含 <工作区 id>/）；缺省 $GUJI_DATA_HOME/main")
    ap.add_argument("--calib-dir", help="临时校准表根（<工作区 id>/<模型相对路径>.calib.json），叠在模型上算 ECE")
    ap.add_argument("--fit-calib", help="拟合临时校准表写到这里（按 <工作区 id>/<模型相对路径> 放）")
    ap.add_argument("--books")
    ap.add_argument("--repeat", type=int, default=50, help="每个方法再打一遍分比逐位相同的格数（0 不比）")
    a = ap.parse_args()

    shard = Path(a.shard)
    bench = json.loads((shard / "bench.json").read_text(encoding="utf-8"))
    data = Path(a.data) if a.data else Path(os.environ.get("GUJI_DATA_HOME") or Path.home() / ".guji-data") / "main"
    circular = set((bench.get("labels") or {}).get("circular_channels") or ())
    want = set(a.books.split(",")) if a.books else None
    report = {"bench": "near-bench/1", "bench_version": bench.get("version"), "cv": cv_version(),
              "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "books": {}}
    calibs = {}
    for bk, spec in bench["books"].items():
        if want and bk not in want:
            continue
        missing = [v for v in spec["vols"] if not (shard / bk / v / "cells.jsonl.gz").is_file()]
        if any(spec["vols"][v]["role"] == "test" for v in missing):
            report["books"][bk] = {"error": f"冻结册缺：{missing}（先 build_near_bench.py）"}
            continue
        if missing:                                   # 只缺 fit 册：照报 test，不拟合临时校准
            print(f"{bk}: fit 册 {missing} 没冻，跳过", flush=True)
            spec = {**spec, "vols": {v: s for v, s in spec["vols"].items() if v not in missing}}
        t0 = time.time()
        rep, st = run_book(shard, bk, spec, data, circular, Path(a.calib_dir) if a.calib_dir else None, a.repeat)
        rep["seconds"] = round(time.time() - t0, 1)
        report["books"][bk] = rep
        if a.fit_calib:
            calibs[bk] = fit_calibs(bk, spec, st, Path(a.fit_calib))
        print(f"{bk}: {rep['seconds']}s", flush=True)
    report["methods_sha"] = {bk: ";".join(f"{k}={v.get('fingerprint', v.get('error'))}" for k, v in sorted(r.get("models", {}).items()))
                             for bk, r in report["books"].items()}
    report["headline"] = headline(report)
    if calibs:
        report["temp_calib"] = {"version": CALIB_VERSION, "dir": a.fit_calib, "books": calibs}
    s = json.dumps(report, ensure_ascii=False, indent=1)
    if a.out:
        Path(a.out).write_text(s + "\n", encoding="utf-8")
    summary(report)


def headline(rep: dict) -> list[dict]:
    """每书 test 册每个「方法:组」一行（manager `guji eval` 取数用）。"""
    out = []
    for bk, r in rep["books"].items():
        for vol, v in (r.get("per_vol") or {}).items():
            if v["role"] != "test":
                continue
            for gid, g in v["groups"].items():
                for name, mr in g["methods"].items():
                    cal = mr.get("calib") or {}
                    out.append({"book": bk, "vol": vol, "group": gid, "method": name, "cells": v["cells"],
                                "triggered": g["triggered"], "scored": mr["scored"], "decided": mr["decided"],
                                "right": mr["right"], "wrong": mr["wrong"], "acc": mr["acc"],
                                "abstain_rate": mr["abstain_rate"], "ms_per_cell": mr["ms_per_cell"],
                                "coverage": (g.get("coverage") or {}).get("silver"),
                                "ece": cal.get("ece"), "ece_n": cal.get("n"), "calib_version": cal.get("version")})
    return out


def summary(rep: dict) -> None:
    for bk, r in rep["books"].items():
        if "error" in r:
            print(bk, r["error"])
            continue
        print(f"== {bk} {r.get('title')}  跳过 {r['skipped_methods']}")
        for vol, v in r["per_vol"].items():
            print(f"  [{vol} {v['role']}] 格 {v['cells']}  标签 {v['labeled']}")
            for gid, g in v["groups"].items():
                cv_ = g.get("coverage", {})
                cs = " ".join(f"{k}:{x['covered']}/{x['n']}" for k, x in cv_.items())
                print(f"    {gid}: 触发 {g['triggered']} {g['by_trigger']}  覆盖 {cs}")
                for name, mr in g["methods"].items():
                    cal = mr.get("calib")
                    print(f"      {name}: 判 {mr['scored']} 弃 {mr['abstain_rate']} 有标 {mr['labeled']} 准 {mr['acc']}"
                          f"（错 {mr['wrong']}） {mr['ms_per_cell']}ms/格 重打一致 {mr['repeat_equal']}"
                          + (f" ECE {cal['ece']}（n {cal['n']}，{cal['version']}）" if cal else ""))
    for bk, c in (rep.get("temp_calib") or {}).get("books", {}).items():
        for k, v in c.items():
            print(f"  calib {bk} {k}: {v.get('status')} n={v.get('n_fit', v.get('n'))} holdout={v.get('holdout')}")


if __name__ == "__main__":
    main()
