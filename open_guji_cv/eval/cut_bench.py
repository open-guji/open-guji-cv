"""cut-bench：第二步「切字」整步的固定样本集（CV2，2026-11-23 起；2026-11-28 从 ai-team 搬进 cv，四大步验收 L4／L5）。

一页一个样本，冻结第二步的全部输入：原图＋第一步产物（border_detect、border_detect_gate、seal_detect）
＋册配置（册 yaml、book_defaults、corpus、书仓 code/）。金标一律存原图坐标（规范空间 raw_page_px@top-right，
与产物 quad_page／bbox_page 同一空间），拉直、缩放怎么改都不失效。金标住 open-guji-dataset
`char-segmentation/cut-bench/<书>/`（bench.json＋每页一个 jsonl）。

    # 冻结（要工作区与产物包；--gold-from 给了就拷现成金标，不再从包起草稿）
    python -m open_guji_cv.eval.cut_bench freeze --ws <工作区> --data <数据目录> --pack <产物包根> --book shiji --vol 42 \
        --pages 2,3,7 --out <bench 根> [--gold-from <dataset>/char-segmentation/cut-bench/shiji]
    # 只跑切字大步（--from cut --to cut，不带人裁）
    python -m open_guji_cv.eval.cut_bench run   --bench <bench 根> --book shiji --out <结果目录> [--params JSON]
    # 2d 字间切分：字数全对、列全对、格 F1、劈字、粗／细档切线；--against 出翻转列
    python -m open_guji_cv.eval.cut_bench score --bench <bench 根> --book shiji --pred <结果目录> [--against <另一结果目录>] [--json out.json]
    # 出口闸 cut_gate：以 score 的「列全对」为真值，量检出率、误报率（L5）
    python -m open_guji_cv.eval.cut_bench gate  --bench <bench 根> --book shiji --pred <结果目录> [--json out.json]

冻结的书目录是一个「旧布局」工作区（没有 .central.json）：books/、config/、corpus/、code/、data_full/、
products/ 都在目录里，**不带 feedback/**——人裁（manual-cells 等）不生效，量的是算法本身。
打分只计人核过的列（label_origin human／checked；silver 是没抽查的草稿、needs_fix 是金标待修，都不计）。
主指标：列全对（L2，格数、类型、每格 IoU≥0.75 全对上）、字数全对（L1）；护栏：好列改坏（`--against` 的「对→错」翻转，必须为 0 或逐列点名）。
测试集按 bench.json `splits` 分报：random＝随机整页（真实准确率）、hard＝难例（偏低，针对性测）。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

LAYOUT_STEPS = ("border_detect", "border_detect_gate", "seal_detect", "page_survey", "invert_detect")
CUT_STEPS = ("column_warp", "column_gate", "row_segment", "row_segment_gate", "cell_shrink")


def _pages(s: str) -> list[int]:
    out = []
    for part in s.split(","):
        if "-" in part:
            a, b = part.split("-")
            out += list(range(int(a), int(b) + 1))
        elif part:
            out.append(int(part))
    return out


def _pj(page: int) -> str:
    return f"p{page:04d}.json"


# ---------------------------------------------------------------- 金标草稿
def gold_from_pack(pack_vol: Path, page: int, pins: dict) -> list[dict]:
    """一页每列一行。来源（label_origin）：
    - `human`：这一列有 manual-cells 钉子，产物包里这一列就是钉子格（旗 manual_cells），取它的 quad_page；
    - `silver`：没有钉子，取产物包（已过人审出 v0.1 的版本）的格——待人抽查确认后改 human。
    L1（字数字序）＝ cells 里 kind 不是 blank 的格的序列；L2 ＝ 每格原图四边形。"""
    cells = json.loads((pack_vol / "row_segment" / _pj(page)).read_text())["cells"]
    chars = json.loads((pack_vol / "cell_shrink" / _pj(page)).read_text())["char_index"]
    tight = {c["col"]: {(ch.get("slot"), ch.get("sub")): ch for ch in c.get("chars", [])} for c in chars["columns"]}
    rows = []
    for col in cells["columns"]:
        c = col["col"]
        pinned = (page, c) in pins
        items = []
        for cell in col.get("cells", []):
            if cell.get("kind") in ("blank", None):
                continue
            t = tight.get(c, {}).get((cell.get("slot"), cell.get("sub")))
            items.append({
                "slot": cell.get("slot"), "sub": cell.get("sub"), "kind": cell.get("kind"),
                "quad": cell.get("quad_page"),
                "tight": t.get("bbox_page") if t else None,
            })
        rows.append({
            "id": f"{page}:{c}", "page": page, "col": c,
            "label_origin": "human" if pinned else "silver",
            "status": "active" if pinned else "draft",
            "tags": [],
            "n": len(items),
            "kinds": [i["kind"] for i in items],
            "cells": items,
        })
    return rows


def freeze(a) -> None:
    ws, data, pack = Path(a.ws), Path(a.data), Path(a.pack)
    out = Path(a.out) / a.book
    vol = a.vol
    pages = _pages(a.pages)
    out.mkdir(parents=True, exist_ok=True)
    # 配置：册 yaml、基础配置、语料、书仓 code（实拷，不留软链）
    for sub in ("books", "config", "corpus"):
        if (data / sub).exists():
            shutil.copytree(data / sub, out / sub, dirs_exist_ok=True)
    code = (ws / "code").resolve()
    if code.exists():
        shutil.copytree(code, out / "code", dirs_exist_ok=True, ignore=shutil.ignore_patterns("tests", "__pycache__"))
    wy = (ws / "workspace.yaml").read_text()
    (out / "workspace.yaml").write_text(f"id: cutbench-{a.book}\n# 原工作区：\n" + "".join("# " + l + "\n" for l in wy.splitlines()))
    # 册钉了字形库（殿本 glyph_pin）时 row_segment 读 g<N> 库（roster_glyph_refine），一并冻结
    for db in (ws / "output").glob("glyph-g*.db"):
        (out / "output").mkdir(exist_ok=True)
        shutil.copy2(db, out / "output" / db.name)
    # 原图与第一步产物
    # 原图目录按册 yaml 的 raw_dir（殿本是 data_full/qiefen/<册>），缺省 data_full/<册>
    raw_rel = f"data_full/{vol}"
    vy = data / "books" / f"{vol}.yaml"
    if vy.exists():
        import yaml
        raw_rel = (yaml.safe_load(vy.read_text()) or {}).get("raw_dir") or raw_rel
    raw_dir = out / raw_rel
    raw_dir.mkdir(parents=True, exist_ok=True)
    pv = pack / vol
    pins = set()
    pin_file = data / "feedback/verdicts/char-segmentation/manual-cells/items.jsonl"
    if pin_file.exists():
        for line in pin_file.read_text().splitlines():
            d = json.loads(line)
            an = d.get("anchor", {})
            if d.get("status", "active") == "active" and str(an.get("book")) == vol:
                pins.add((int(an["page"]), int(an["col"])))
    gold_dir = out / "gold"
    gold_dir.mkdir(exist_ok=True)
    gold_from = Path(a.gold_from) if getattr(a, "gold_from", None) else None
    old = [p for p in pages if (gold_dir / f"{vol}-{p:04d}.jsonl").exists()]
    if old and not gold_from and not getattr(a, "overwrite", False):
        raise SystemExit(f"这些页已有金标，冻结会覆盖人标结果：{old}（确要重冻加 --overwrite）")
    for p in pages:
        src = ws / raw_rel / f"{p}.png"
        shutil.copy2(src, raw_dir / src.name)
        for st in LAYOUT_STEPS:
            f = pv / st / _pj(p)
            if f.exists():
                (out / "products" / vol / st).mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, out / "products" / vol / st / f.name)
        # 原始包里的第二步产物留作「冻结时的参照」（不参与跑分，只给出草稿、做回归核对）
        for st in CUT_STEPS:
            f = pv / st / _pj(p)
            if f.exists():
                (out / "ref_products" / vol / st).mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, out / "ref_products" / vol / st / f.name)
        if gold_from:                  # 现成金标（dataset char-segmentation/cut-bench/<书>/）：原样拷，不起草稿
            shutil.copy2(gold_from / f"{vol}-{p:04d}.jsonl", gold_dir / f"{vol}-{p:04d}.jsonl")
            continue
        rows = gold_from_pack(pv, p, pins)
        with open(gold_dir / f"{vol}-{p:04d}.jsonl", "w") as fh:
            for r in rows:
                r["vol"] = vol
                fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    src_meta = json.loads((pv / "_source.json").read_text()) if (pv / "_source.json").exists() else {}
    meta_f = out / "bench.json"
    meta = json.loads(meta_f.read_text()) if meta_f.exists() else {"book": a.book, "vols": {}}
    meta["vols"].setdefault(vol, {"pages": [], "pack": str(pack), "source": src_meta})
    meta["vols"][vol]["pages"] = sorted(set(meta["vols"][vol]["pages"]) | set(pages))
    if gold_from and (gold_from / "bench.json").exists():   # 测试集划分（random／hard）跟金标走
        gm = json.loads((gold_from / "bench.json").read_text())
        for k in ("splits", "splits_note"):
            if k in gm:
                meta[k] = gm[k]
    meta_f.write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(f"冻结 {a.book} {vol} {pages} → {out}")


# ---------------------------------------------------------------- 跑第二步
def run(a) -> None:
    bench = Path(a.bench) / a.book
    meta = json.loads((bench / "bench.json").read_text())
    work = Path(a.out)
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(bench, work / "ws", ignore=shutil.ignore_patterns("gold", "ref_products"))
    env = {**os.environ, "GUJI_WORKSPACE": str(work / "ws"), "GUJI_PRODUCTS_DIR": str(work / "ws" / "products"),
           "GUJI_CODE_DRIFT": "warn", "GUJI_DATA_HOME": str(work / "datahome")}
    for vol, v in meta["vols"].items():
        cmd = [sys.executable, "-m", "open_guji_cv", "pipeline", a.pipeline, vol, "-w", str(work / "ws"),
               "--from", "cut", "--to", "cut", "--pages", ",".join(map(str, v["pages"])), "--force",
               "--no-pack", "--no-prep", "--allow-cv-mismatch", "--why", "cut-bench", "--allow-missing-deps"]
        if a.params:
            cmd += ["--params", a.params]
        r = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
        if r.returncode:
            print(r.stdout[-3000:], r.stderr[-3000:])
            raise SystemExit(f"{vol} 跑失败")
    print(f"跑完 → {work}/ws/products")


# ---------------------------------------------------------------- 打分
def _poly_box(q):
    xs = [p[0] for p in q]
    ys = [p[1] for p in q]
    return min(xs), min(ys), max(xs), max(ys)


def _iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def _pred_cols(pred_vol: Path, page: int) -> dict:
    d = json.loads((pred_vol / "row_segment" / _pj(page)).read_text())["cells"]
    out = {}
    for col in d["columns"]:
        out[col["col"]] = [c for c in col.get("cells", []) if c.get("kind") not in ("blank", None)]
    return out


def _match(gold_cells, pred_cells, thr=0.75):
    gb = [_poly_box(g["quad"]) for g in gold_cells]
    pb = [_poly_box(p["quad_page"]) for p in pred_cells]
    pairs = sorted(((_iou(g, p), i, j) for i, g in enumerate(gb) for j, p in enumerate(pb)), reverse=True)
    ug, up, tp = set(), set(), 0
    for v, i, j in pairs:
        if v < thr:
            break
        if i in ug or j in up:
            continue
        ug.add(i); up.add(j); tp += 1
    return tp


def _split_through(gold_cells, pred_cells, frac=0.15) -> int:
    """劈字：预测格的上下边界落在某个金标字（同一道）中间，离字的上下沿都超过字高 frac。"""
    n = 0
    for g in gold_cells:
        x0, y0, x1, y1 = _poly_box(g["quad"])
        h = y1 - y0
        for p in pred_cells:
            px0, py0, px1, py1 = _poly_box(p["quad_page"])
            if min(x1, px1) - max(x0, px0) < 0.5 * min(x1 - x0, px1 - px0):
                continue
            for y in (py0, py1):
                if y0 + frac * h < y < y1 - frac * h:
                    n += 1
                    break
    return n


#: 粗档（Sheldon 11-25「实际切线在金标上下不远就算对」）：格的上下沿离金标 ≤ COARSE_TOL × 本列金标中位字高
COARSE_TOL = 0.25
#: 细档穿墨：切线所在 ±1 行、本格左右 15% 内收的范围里墨占比 > INK_CUT 算穿墨
INK_CUT = 0.08


def _raw_dir(bench: Path, vol: str) -> Path:
    vy = bench / "books" / f"{vol}.yaml"
    raw = f"data_full/{vol}"
    if vy.exists():
        import yaml
        raw = (yaml.safe_load(vy.read_text()) or {}).get("raw_dir") or raw
    return bench / raw


def _ink_page(bench: Path, vol: str, page: int):
    """原图二值墨（True＝墨），读不到返回 None（细档穿墨就不算）。"""
    try:
        import cv2

        from ..utils.image_io import imread as cv_imread
    except ImportError:
        return None
    f = _raw_dir(bench, vol) / f"{page}.png"
    im = cv_imread(str(f), cv2.IMREAD_GRAYSCALE) if f.exists() else None
    return None if im is None else im < 128


def _line_ink(ink, W: int, box, y: float) -> float:
    x0, _, x1, _ = box
    w = x1 - x0
    X0, X1 = int(W - x1 + 0.15 * w), int(W - x0 - 0.15 * w)
    yi = round(y)
    if X1 <= X0 or yi < 1 or yi >= ink.shape[0] - 1:
        return 0.0
    return float(ink[yi - 1:yi + 2, X0:X1].max(axis=0).mean())


def _edges(gold_cells, pred_cells, ink, W):
    """字数、类型都对上的列：逐格上下沿对比。返回 [(|dy| 像素, |dy|/字高, 预测线穿墨, 金标线穿墨)]。"""
    import statistics
    hs = [_poly_box(g["quad"])[3] - _poly_box(g["quad"])[1] for g in gold_cells]
    m = statistics.median(hs) if hs else 1.0
    out = []
    seen = set()
    for g, p in zip(gold_cells, pred_cells):
        gb, pb = _poly_box(g["quad"]), _poly_box(p["quad_page"])
        for gy, py in ((gb[1], pb[1]), (gb[3], pb[3])):
            key = round(gy)
            if key in seen:          # 相邻两格共用的切线只算一次
                continue
            seen.add(key)
            pi = _line_ink(ink, W, gb, py) if ink is not None else None
            gi = _line_ink(ink, W, gb, gy) if ink is not None else None
            out.append((abs(py - gy), abs(py - gy) / m, pi, gi))
    return out


def _split_of(meta: dict) -> dict:
    """(册, 页) → 测试集名（bench.json `splits`：random／hard）；没划分的页不在表里。"""
    out = {}
    for name, vols in (meta.get("splits") or {}).items():
        for vol, pages in vols.items():
            for p in pages:
                out[(str(vol), int(p))] = name
    return out


def iter_gold(bench: Path, only=("human", "checked")):
    """逐列金标（跳过 retired、needs_fix 与不在 `only` 里的来源）：yield (册, 页, 金标行)。"""
    meta = json.loads((bench / "bench.json").read_text())
    for vol, v in meta["vols"].items():
        for page in v["pages"]:
            f = bench / "gold" / f"{vol}-{page:04d}.jsonl"
            if not f.exists():
                continue
            for line in f.read_text().splitlines():
                if not line.strip():
                    continue
                g = json.loads(line)
                if g["label_origin"] not in only or g.get("status") in ("retired", "needs_fix"):
                    continue
                yield vol, page, g


def score_dir(bench: Path, pred_root: Path, only=("human", "checked")) -> dict:
    meta = json.loads((bench / "bench.json").read_text())
    split_of = _split_of(meta)
    res = {"columns": 0, "L1_count_ok": 0, "L1_kinds_ok": 0, "L2_col_exact": 0, "gold_cells": 0, "pred_cells": 0,
           "tp": 0, "split": 0, "by_origin": {}, "by_set": {}, "cols": {},
           "coarse_cols": 0, "coarse_edges_ok": 0, "edges": 0, "edge_dy": [], "ink_cut_pred": 0, "ink_cut_gold": 0}
    for vol, v in meta["vols"].items():
        for page in v["pages"]:
            pred = _pred_cols(pred_root / vol, page)
            ink = _ink_page(bench, vol, page)
            W = ink.shape[1] if ink is not None else 0
            for line in (bench / "gold" / f"{vol}-{page:04d}.jsonl").read_text().splitlines():
                g = json.loads(line)
                if g["label_origin"] not in only or g.get("status") in ("retired", "needs_fix"):
                    continue
                pc = pred.get(g["col"], [])
                k_ok = len(pc) == g["n"]
                kinds_ok = [c["kind"] for c in pc] == g["kinds"]
                tp = _match(g["cells"], pc)
                exact = tp == g["n"] == len(pc)
                sp = _split_through(g["cells"], pc)
                res["columns"] += 1
                res["L1_count_ok"] += k_ok
                res["L1_kinds_ok"] += kinds_ok
                res["L2_col_exact"] += exact
                res["gold_cells"] += g["n"]
                res["pred_cells"] += len(pc)
                res["tp"] += tp
                res["split"] += sp
                coarse = False
                if kinds_ok and k_ok:
                    ed = _edges(g["cells"], pc, ink, W)
                    ok_e = sum(e[1] <= COARSE_TOL for e in ed)
                    coarse = ok_e == len(ed)
                    res["edges"] += len(ed); res["coarse_edges_ok"] += ok_e
                    res["edge_dy"] += [e[0] for e in ed]
                    res["ink_cut_pred"] += sum(1 for e in ed if e[2] is not None and e[2] > INK_CUT)
                    res["ink_cut_gold"] += sum(1 for e in ed if e[3] is not None and e[3] > INK_CUT)
                res["coarse_cols"] += coarse
                o = res["by_origin"].setdefault(g["label_origin"], {"columns": 0, "L1_count_ok": 0, "L2_col_exact": 0, "coarse": 0})
                o["columns"] += 1; o["L1_count_ok"] += k_ok; o["L2_col_exact"] += exact; o["coarse"] += coarse
                ts = split_of.get((str(vol), int(page)), "-")
                t = res["by_set"].setdefault(ts, {"columns": 0, "L1_count_ok": 0, "L2_col_exact": 0})
                t["columns"] += 1; t["L1_count_ok"] += k_ok; t["L2_col_exact"] += exact
                res["cols"][f"{vol}:{page}:{g['col']}"] = {"origin": g["label_origin"], "set": ts, "n_gold": g["n"], "n_pred": len(pc),
                                                         "count_ok": k_ok, "exact": exact, "split": sp, "coarse": coarse}
    P = res["tp"] / res["pred_cells"] if res["pred_cells"] else 0
    R = res["tp"] / res["gold_cells"] if res["gold_cells"] else 0
    res["cell_P"], res["cell_R"] = round(P, 4), round(R, 4)
    res["cell_F1"] = round(2 * P * R / (P + R), 4) if P + R else 0
    dy = sorted(res.pop("edge_dy"))
    q = lambda f: round(dy[min(len(dy) - 1, int(f * len(dy)))], 1) if dy else None
    res["edge_dy_px"] = {"median": q(0.5), "p90": q(0.9), "p99": q(0.99), "mean": round(sum(dy) / len(dy), 1) if dy else None}
    return res


def score(a) -> None:
    bench = Path(a.bench) / a.book
    r = score_dir(bench, Path(a.pred) / "ws" / "products")
    n = r["columns"]
    print(f"{a.book}：{n} 列")
    print(f"  L1 字数全对 {r['L1_count_ok']}/{n}  类型序列全对 {r['L1_kinds_ok']}/{n}")
    print(f"  L2 列全对 {r['L2_col_exact']}/{n}  格 P {r['cell_P']} R {r['cell_R']} F1 {r['cell_F1']}  劈字 {r['split']}")
    print(f"  粗档（格沿离金标 ≤{COARSE_TOL} 字高）列对 {r['coarse_cols']}/{n}  切线对 {r['coarse_edges_ok']}/{r['edges']}")
    print(f"  细档 切线偏移 px 中位 {r['edge_dy_px']['median']} 均值 {r['edge_dy_px']['mean']} p90 {r['edge_dy_px']['p90']} p99 {r['edge_dy_px']['p99']}"
          f"  穿墨线 预测 {r['ink_cut_pred']} / 金标 {r['ink_cut_gold']}（共 {r['edges']} 条）")
    for o, v in r["by_origin"].items():
        print(f"  [{o}] {v['columns']} 列：字数全对 {v['L1_count_ok']}  列全对 {v['L2_col_exact']}  粗档列对 {v['coarse']}")
    for o, v in sorted(r["by_set"].items()):
        print(f"  测试集 {o}：{v['columns']} 列  字数全对 {v['L1_count_ok']}  列全对 {v['L2_col_exact']}")
    if a.against:
        b = score_dir(bench, Path(a.against) / "ws" / "products")
        flips = [(k, b["cols"][k]["exact"], v["exact"]) for k, v in r["cols"].items() if k in b["cols"] and b["cols"][k]["exact"] != v["exact"]]
        print(f"  对照 {a.against}：列全对 {b['L2_col_exact']} → {r['L2_col_exact']}；粗档列对 {b['coarse_cols']} → {r['coarse_cols']}；翻转 {len(flips)} 列")
        for k, x, y in flips:
            print(f"    {k}: {'对' if x else '错'} → {'对' if y else '错'}")
    if a.json:
        Path(a.json).write_text(json.dumps(r, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- 出口闸 cut_gate 的检出率、误报率（L5）
def _gate_cols(pred_vol: Path, page: int) -> dict | None:
    """一页的出口闸裁决 → {列号: {"block": [...], "flag": [...]}}。读 `cut_gate/pNNNN.json`（两种产物同一文件）；
    没有闸产物返回 None（那页不计）。block＝admitted 为假的原因（页级不收也算到每列），flag＝flags／碎格。"""
    f = pred_vol / "cut_gate" / _pj(page)
    if not f.exists():
        return None
    d = json.loads(f.read_text())
    out: dict = {}

    def add(col, kind, why):
        out.setdefault(col, {"block": [], "flag": []})[kind].append(why)

    for key, tag in (("gate_manifest", "2列"), ("row_segment_gate_manifest", "2格")):
        m = d.get(key)
        if not m:
            continue
        cols = [c["col"] for c in m.get("columns", [])]
        if not m.get("admitted", True):
            for c in cols:
                add(c, "block", f"{tag}页:" + "；".join(m.get("reject", []))[:60])
        for c in m.get("columns", []):
            out.setdefault(c["col"], {"block": [], "flag": []})
            if not c.get("admitted", True):
                add(c["col"], "block", f"{tag}:" + "；".join(c.get("reject", []))[:60])
            for x in c.get("flags", []):
                add(c["col"], "flag", f"{tag}:" + x[:60])
            if c.get("sliver_slots"):
                add(c["col"], "flag", f"{tag}:L4 碎格 {c['sliver_slots']}")
    return out


def _reason(why: str) -> str:
    """闸原因句 → 判据名（「2格:cut_touching：3 条…」→「2格:cut_touching」）。"""
    head = why.split("：")[0]
    return head.split(" ")[0] if not head.startswith(("2列:", "2格:")) else head.split(" ")[0][:40]


def gate_metrics(bench: Path, pred_root: Path, truth: str = "exact", only=("human", "checked")) -> dict:
    """出口闸量法（四大步验收 L5，CV2 2026-11-28）：以 cut-bench 金标对现役切分的打分当真值
    （`truth`＝exact：列全对；count：字数全对），闸的裁决分两档——
    block（admitted 为假，下游不收）、any（block 或 flag）。每档报
    检出率＝闸命中的坏列／坏列，误报率＝闸命中的好列／好列，精确率＝坏列／闸命中列。
    只算有闸产物的页；闸产物与切分产物须是同一次 run（同一份产物根）。"""
    sc = score_dir(bench, pred_root, only)
    res = {"truth": truth, "pages_no_gate": [], "columns": 0, "bad": 0, "good": 0,
           "tiers": {t: {"hit_bad": 0, "hit_good": 0} for t in ("block", "any")}, "by_set": {}, "by_reason": {},
           "missed": [], "false_alarm": []}
    cache: dict = {}
    for key, c in sc["cols"].items():
        vol, page, col = key.rsplit(":", 2)
        pk = (vol, int(page))
        if pk not in cache:
            cache[pk] = _gate_cols(pred_root / vol, int(page))
            if cache[pk] is None:
                res["pages_no_gate"].append(f"{vol}:{page}")
        g = cache[pk]
        if g is None:
            continue
        v = g.get(int(col), {"block": [], "flag": []})
        bad = not c["exact" if truth == "exact" else "count_ok"]
        res["columns"] += 1
        res["bad" if bad else "good"] += 1
        s = res["by_set"].setdefault(c.get("set", "-"), {"columns": 0, "bad": 0, "block_hit_bad": 0, "block_hit_good": 0,
                                                       "any_hit_bad": 0, "any_hit_good": 0})
        s["columns"] += 1; s["bad"] += bad
        for t, hit in (("block", bool(v["block"])), ("any", bool(v["block"] or v["flag"]))):
            if hit:
                res["tiers"][t]["hit_bad" if bad else "hit_good"] += 1
                s[f"{t}_hit_{'bad' if bad else 'good'}"] += 1
        for why in {_reason(w) for w in v["block"] + v["flag"]}:     # 按判据分报：哪条判据在抓坏列、哪条在误报
            br = res["by_reason"].setdefault(why, {"hit_bad": 0, "hit_good": 0})
            br["hit_bad" if bad else "hit_good"] += 1
        if bad and not (v["block"] or v["flag"]):
            res["missed"].append({"col": key, "n_gold": c["n_gold"], "n_pred": c["n_pred"]})
        if not bad and (v["block"] or v["flag"]):
            res["false_alarm"].append({"col": key, "why": (v["block"] + v["flag"])[:3]})
    for x in res["by_reason"].values():
        x["recall"] = round(x["hit_bad"] / res["bad"], 4) if res["bad"] else None
        x["false_alarm_rate"] = round(x["hit_good"] / res["good"], 4) if res["good"] else None
    for t, x in res["tiers"].items():
        hit = x["hit_bad"] + x["hit_good"]
        x["recall"] = round(x["hit_bad"] / res["bad"], 4) if res["bad"] else None
        x["false_alarm_rate"] = round(x["hit_good"] / res["good"], 4) if res["good"] else None
        x["precision"] = round(x["hit_bad"] / hit, 4) if hit else None
    return res


def gate(a) -> None:
    bench = Path(a.bench) / a.book
    r = gate_metrics(bench, Path(a.pred) / "ws" / "products", truth=a.truth)
    print(f"{a.book} 出口闸 cut_gate（真值＝{'列全对' if a.truth == 'exact' else '字数全对'}）：{r['columns']} 列，坏 {r['bad']}、好 {r['good']}")
    for t, x in r["tiers"].items():
        name = "拦（admitted 假）" if t == "block" else "拦或旗（block＋flag）"
        print(f"  {name}：检出率 {x['hit_bad']}/{r['bad']}＝{x['recall']}  误报率 {x['hit_good']}/{r['good']}＝{x['false_alarm_rate']}  精确率 {x['precision']}")
    for k, v in sorted(r["by_set"].items()):
        print(f"  测试集 {k}：{v['columns']} 列 坏 {v['bad']}  拦或旗命中 坏 {v['any_hit_bad']}／好 {v['any_hit_good']}")
    for k, v in sorted(r["by_reason"].items(), key=lambda kv: -kv[1]["hit_bad"] - kv[1]["hit_good"]):
        print(f"  判据 {k}：命中坏 {v['hit_bad']}（检出 {v['recall']}）  命中好 {v['hit_good']}（误报 {v['false_alarm_rate']}）")
    if r["pages_no_gate"]:
        print(f"  没有闸产物、不计的页：{r['pages_no_gate']}")
    print(f"  漏检 {len(r['missed'])} 列：" + "、".join(m["col"] for m in r["missed"][:30]))
    print(f"  误报 {len(r['false_alarm'])} 列：" + "、".join(m["col"] for m in r["false_alarm"][:30]))
    if a.json:
        Path(a.json).write_text(json.dumps(r, ensure_ascii=False, indent=1))


# ---------------------------------------------------------------- 抽查页 items
def review_items(a) -> None:
    """金标草稿（默认只出 silver 列）→ guji-manager `review-pages build col_check` 的 items：
    每列从原图按格四边形外包裁出（左右各留 pad、上下留 pad），缩到高 ≤ max_h，格框换成图像素。"""
    import cv2

    from ..utils.image_io import imread as cv_imread
    from ..utils.image_io import imwrite as cv_imwrite
    bench = Path(a.bench) / a.book
    out = Path(a.out)
    (out / "img").mkdir(parents=True, exist_ok=True)
    origins = set(a.origins.split(","))
    rows_out = []
    for f in sorted((bench / "gold").glob("*.jsonl")):
        rows = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
        if not rows:
            continue
        vol, page = rows[0]["vol"], rows[0]["page"]
        raw_rel = f"data_full/{vol}"
        vy = bench / "books" / f"{vol}.yaml"
        if vy.exists():
            import yaml
            raw_rel = (yaml.safe_load(vy.read_text()) or {}).get("raw_dir") or raw_rel
        im = cv_imread(str(bench / raw_rel / f"{page}.png"), cv2.IMREAD_GRAYSCALE)
        H, W = im.shape
        # 页坐标 raw_page_px@top-right：x 从右往左量，画到图上要 x_img = W - x
        def ibox(q, W=W):
            b = _poly_box(q)
            return W - b[2], b[1], W - b[0], b[3]
        allb = [ibox(c["quad"]) for r in rows for c in r["cells"]]
        if not allb:
            continue
        # 一页所有列用同一上下范围、同一比例：上下各多留 4% 页高，抬头、列端都看得全
        y0 = max(0, int(min(b[1] for b in allb) - 0.04 * H)); y1 = min(H, int(max(b[3] for b in allb) + 0.04 * H))
        k = min(1.0, a.max_h / (y1 - y0))
        for r in rows:
            if r["label_origin"] not in origins or not r["cells"] or (a.pages and page not in a.pages):
                continue
            bs = [ibox(c["quad"]) for c in r["cells"]]
            # --box tight：画字的紧框（cell_shrink／人钉的 tight，页坐标 x0,y0,x1,y1），没有紧框的格退回格四边形
            show = [(W - c["tight"][2], c["tight"][1], W - c["tight"][0], c["tight"][3]) if a.box == "tight" and c.get("tight") else b
                    for c, b in zip(r["cells"], bs)]
            x0 = max(0, int(min(b[0] for b in bs)) - a.pad); x1 = min(W, int(max(b[2] for b in bs)) + a.pad)
            crop = im[y0:y1, x0:x1]
            if k < 1.0:
                crop = cv2.resize(crop, (max(1, round(crop.shape[1] * k)), round(crop.shape[0] * k)), interpolation=cv2.INTER_AREA)
            cid = f"{a.book}:{vol}:{page}:{r['col']}"
            fn = out / "img" / (cid.replace(":", "_") + ".png")
            cv_imwrite(str(fn), crop)
            cells = [{"key": f"{cid}:{c['slot']}" + (f":{c['sub']}" if c.get("sub") is not None else ""), "kind": c["kind"],
                      "box": [round((b[0] - x0) * k, 1), round((b[1] - y0) * k, 1), round((b[2] - x0) * k, 1), round((b[3] - y0) * k, 1)]}
                     for c, b in zip(r["cells"], show)]
            rows_out.append({"id": cid, "vol": f"{a.book}·{vol}", "page": page, "col": r["col"], "img": str(fn),
                             "cells": cells, "note": {"silver": None, "human": "人工钉过"}.get(r["label_origin"], r["label_origin"])})
    with open(out / "items.jsonl", "w") as fh:
        for r in rows_out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows_out)} 列 → {out / 'items.jsonl'}")


# ---------------------------------------------------------------- 收抽查结果
def apply_review(a) -> None:
    """`guji review-pages colcheck-apply` 的结果 → 改金标：全对的 silver 列改 checked（人抽查过的算法格，当金标用），
    有错的列 status=needs_fix、tags 记错格（打分先跳过，等人裁修好再改 human）。列号形如 书:册:页:列。
    `--level`：这轮人看到什么程度。count＝只确认字数与大致位置（Sheldon 11-22：连接处切点、与边框分离都没核，
    checked 列只能当 L1 金标）；cut＝切点也核过。"""
    bench = Path(a.bench)
    res = {}
    for line in Path(a.results).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            res[r["id"]] = r
    n = {"checked": 0, "needs_fix": 0}
    for book_dir in [d for d in bench.iterdir() if (d / "gold").is_dir()]:
        for f in sorted((book_dir / "gold").glob("*.jsonl")):
            rows = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
            ch = False
            for g in rows:
                r = res.get(f"{book_dir.name}:{g['vol']}:{g['page']}:{g['col']}")
                if not r or g["label_origin"] not in ("silver", "human") or any(x.get("round") == a.round for x in g.get("review", [])):
                    continue
                if r["label"] == "ok":
                    if g["label_origin"] == "silver":
                        g.update(label_origin="checked", checked_level=a.level)
                    g.update(status="active"); n["checked"] += 1
                elif r["label"] == "bad":
                    g.update(status="needs_fix", tags=sorted(set(g.get("tags", [])) | {"bad:" + b for b in r["bad"]})); n["needs_fix"] += 1
                g.setdefault("review", []).append({"round": a.round, "label": r["label"], "bad": r.get("bad", []), "level": a.level})
                ch = True
            if ch:
                f.write_text("".join(json.dumps(g, ensure_ascii=False) + "\n" for g in rows))
    print(n)


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("freeze")
    for k in ("ws", "data", "pack", "book", "vol", "pages", "out"):
        f.add_argument("--" + k, required=True)
    f.add_argument("--overwrite", action="store_true")
    f.add_argument("--gold-from", dest="gold_from", help="现成金标目录（dataset char-segmentation/cut-bench/<书>），给了就拷它、不从包起草稿")
    r = sub.add_parser("run")
    r.add_argument("--bench", required=True); r.add_argument("--book", required=True); r.add_argument("--out", required=True)
    r.add_argument("--pipeline", default="keben_body_v2"); r.add_argument("--params")
    s = sub.add_parser("score")
    s.add_argument("--bench", required=True); s.add_argument("--book", required=True); s.add_argument("--pred", required=True)
    s.add_argument("--against"); s.add_argument("--json")
    gt = sub.add_parser("gate")
    gt.add_argument("--bench", required=True); gt.add_argument("--book", required=True); gt.add_argument("--pred", required=True)
    gt.add_argument("--truth", default="exact", choices=["exact", "count"], help="坏列的口径：列全对／字数全对")
    gt.add_argument("--json")
    v = sub.add_parser("review-items")
    v.add_argument("--bench", required=True); v.add_argument("--book", required=True); v.add_argument("--out", required=True)
    v.add_argument("--origins", default="silver"); v.add_argument("--pad", type=int, default=20)
    v.add_argument("--max-h", dest="max_h", type=int, default=1100)
    v.add_argument("--box", default="quad", choices=["quad", "tight"], help="画格四边形（切点）还是字紧框（切点＋框线分离）")
    v.add_argument("--pages", type=lambda x: set(_pages(x)), default=None, help="只出这些页")
    w = sub.add_parser("apply-review")
    w.add_argument("--bench", required=True); w.add_argument("--results", required=True); w.add_argument("--round", required=True)
    w.add_argument("--level", default="cut", choices=["count", "cut"])
    a = ap.parse_args(argv)
    {"apply-review": apply_review, "freeze": freeze, "run": run, "score": score, "gate": gate,
     "review-items": review_items}[a.cmd](a)


if __name__ == "__main__":
    main()
