# -*- coding: utf-8 -*-
"""看图结论重绑：格号变了以后，用页坐标框重叠把「旧格 id」映射到「新格 id」（离线、只读、纯标准库）。

    python rebind_lookups.py --old 旧格表 --new 新格表 --lookups 看图结论.csv --out-dir 输出目录 \\
        [--book vol05] [--iou 0.5] [--low 0.6] [--ov 0.5] [--gone 0.15] [--emit-vision-jsonl]

输入
  --old / --new   旧、新格表。两种形态，自动识别：
                  ① 文件（.jsonl 或 .jsonl.gz，`volNN_base.jsonl.gz` 同格式：一行一格，`id` 字段，首行 `header:true` 跳过），
                     每行须带页坐标框，认下面任一键：`bbox_page`=[x0,y0,x1,y1]、`bbox`=[x0,y0,x1,y1]、
                     `bbox_xywh_tl`=[x,y,w,h]（Ethan 导出）。**现有 `volNN_base.jsonl.gz` 基线表没有 bbox**，要用 ②；
                  ② 目录＝产物根（含 `<book>/cell_shrink/pNNNN.json`，同 `remap_gold.py` 的读法，取每格 `bbox_page`），要配 `--book`。
  --lookups       看图结论 CSV（UTF-8，可带 BOM）。必须有 `cell` 列（或「格id」「格」）；其余列原样带过。
                  想用 `--emit-vision-jsonl` 须有 `v`、`judge` 列（`char`、`shown`、`note`、`group`、`ref`、`ts` 可选）。

判法（逐页，只比同页）
  ov(a,b) = 交面积 / min(面积a, 面积b)（重叠系数，包含关系也=1）；iou 为常规 IoU。
  旧格 o 的候选集 N(o) = 新格里 ov ≥ --ov 的；新格 n 的反向候选集 O(n) = 旧格里 ov ≥ --ov 的。
    · 未变     ：|N(o)|=1，该新格同号，|O(n)|=1，iou ≥ --low
    · 一对一改号：|N(o)|=1，该新格不同号，|O(n)|=1，iou ≥ --low        ← 唯一自动重绑
    · 低置信配对：|N(o)|=1、|O(n)|=1，--iou ≤ iou < --low（缺省 0.5≤iou<0.6）  ← 不自动重绑，列清单交看图（Mila 10-14 定）
    · 一对多   ：|N(o)|≥2（旧格被切开）                              ← 要人看
    · 多对一   ：|N(o)|=1 但 |O(n)|≥2（几个旧格被并成一格）            ← 要人看
    · 部分重合 ：|N(o)|=1、|O(n)|=1 但 iou < --iou（缺省 <0.5）        ← 要人看
    · 无对应   ：|N(o)|=0（含最大 iou < --gone）                      ← 要人看
  **新旧同号但框不是同一块（id 串被复用）会按几何判，不会因号相同就算未变。**

输出（--out-dir）
  <stem>.新结论.csv   自动重绑的行（未变＋一对一改号）：原列＋ new_cell, rebind_status, iou, rebind_note
  <stem>.要人看.csv   其余行：原列＋ rebind_status, candidates（候选新格及 iou／ov）, rebind_note
  <stem>.摘要.json    各状态条数、阈值、输入文件 sha
  --emit-vision-jsonl 另出 <stem>.import-vision.jsonl（208hj 改，Elena C2）：**两遍输出**——先全部退役行（旧号 `v=unsure`），
                      后全部新号行（新号＝原结论）；旧号恰是别条新号目标时**不写退役行**；退役行 ts=T、新号行 ts=T+1s
                      （`--ts` 可指定 T），不沿用原判 ts；写完按看图日志同样的「后到覆盖」规则自检，不符 sys.exit。
                      格号没变的不出行。
                      导入仍由 H 道用 `guji events import-vision`，本脚本**不写任何事件、不碰真实事件文件**。
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import sys
from pathlib import Path

DEFAULT_IOU = 0.5    # 配对下限：与 research/y1_admit/remap_gold.py 缺省一致（Mila 10-14 定：全流程同一把尺）
DEFAULT_LOW = 0.6    # 自动重绑下限：0.5≤iou<0.6 单列「低置信配对」不自动搬（对应绑定表 IOU_OK=0.6）
DEFAULT_OV = 0.5     # 重叠系数：捕「包含／被切开／被并入」，0.5＝一半以上在对方里
DEFAULT_GONE = 0.15  # 与 bindings.IOU_GONE 同


def _open(p: Path):
    return gzip.open(p, "rt", encoding="utf-8") if p.suffix == ".gz" else open(p, encoding="utf-8")


def _page(cell: str) -> int | None:
    parts = cell.split(":")
    try:
        return int(parts[1]) if len(parts) >= 4 else None
    except ValueError:
        return None


def _bbox(r: dict):
    for k in ("bbox_page", "bbox"):
        b = r.get(k)
        if b and len(b) == 4:
            return [float(x) for x in b]
    b = r.get("bbox_xywh_tl")
    if b and len(b) == 4:
        x, y, w, h = (float(v) for v in b)
        return [x, y, x + w, y + h]
    return None


def load_table(path: str, book: str | None) -> dict[int, dict[str, list[float]]]:
    """→ {页: {格 id: [x0,y0,x1,y1]}}。"""
    p = Path(path)
    out: dict[int, dict[str, list[float]]] = {}
    if p.is_dir():
        if not book:
            sys.exit("--old/--new 给的是目录（产物根），需要 --book")
        for f in sorted(Path(p, book, "cell_shrink").glob("p*.json")):
            d = json.loads(f.read_text(encoding="utf-8"))
            d = next(iter(d.values()))
            pg = int(f.stem[1:])
            for col in d.get("columns", []):
                for r in col.get("chars") or []:
                    b = _bbox(r)
                    if b:
                        out.setdefault(pg, {})[r["id"]] = b
        return out
    n_no_box = 0
    with _open(p) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("header") or "id" not in r:
                continue
            b = _bbox(r)
            pg = _page(r["id"])
            if b is None or pg is None:
                n_no_box += 1
                continue
            out.setdefault(pg, {})[r["id"]] = b
    if not out:
        sys.exit(f"{path}: 没读到任何带页坐标框的格（{n_no_box} 行缺 bbox）。现有 volNN_base.jsonl.gz 基线表没有 bbox，"
                 f"请改用产物根目录（--book）或带 bbox 的导出。")
    return out


def area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def inter(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def iou(a, b):
    i = inter(a, b)
    u = area(a) + area(b) - i
    return i / u if u > 0 else 0.0


def ov(a, b):
    m = min(area(a), area(b))
    return inter(a, b) / m if m > 0 else 0.0


def classify(old_cells: list[str], old_page: dict[str, list[float]], new_page: dict[str, list[float]],
             thr_iou: float, thr_ov: float, gone: float, thr_low: float = DEFAULT_LOW) -> dict[str, dict]:
    """同一页内：旧格 id → {status, new, iou, cands:[(新id, iou, ov)]}。"""
    res: dict[str, dict] = {}
    # 反向候选集：对每个新格，用「页上所有旧格」（不仅是看图结论涉及的）算，才知道有没有被并
    rev: dict[str, list[str]] = {n: [] for n in new_page}
    for oid, ob in old_page.items():
        for nid, nb in new_page.items():
            if ov(ob, nb) >= thr_ov:
                rev[nid].append(oid)
    for oc in old_cells:
        ob = old_page.get(oc)
        if ob is None:
            res[oc] = {"status": "无对应", "new": None, "iou": 0.0, "cands": [], "note": "旧格表里没有这格的框"}
            continue
        cands = sorted(((nid, iou(ob, nb), ov(ob, nb)) for nid, nb in new_page.items()
                        if ov(ob, nb) >= thr_ov or iou(ob, nb) >= gone), key=lambda t: -t[1])
        N = [c for c in cands if c[2] >= thr_ov]
        best = cands[0][1] if cands else 0.0
        if not N or best < gone:
            res[oc] = {"status": "无对应", "new": None, "iou": round(best, 4), "cands": cands, "note": "新格表该页没有重叠足够的格"}
        elif len(N) >= 2:
            res[oc] = {"status": "一对多", "new": None, "iou": round(best, 4), "cands": cands, "note": "旧格被切成多格，需人看哪一格继承"}
        else:
            nid, i_, _o = N[0]
            if len(rev[nid]) >= 2:
                res[oc] = {"status": "多对一", "new": nid, "iou": round(i_, 4), "cands": cands,
                           "note": f"几个旧格并成一格 {nid}（旧：{','.join(sorted(rev[nid]))}），结论不能直接搬"}
            elif i_ < thr_iou:
                res[oc] = {"status": "部分重合", "new": nid, "iou": round(i_, 4), "cands": cands, "note": f"只部分重合（iou<{thr_iou}）"}
            elif i_ < thr_low:
                res[oc] = {"status": "低置信配对", "new": nid, "iou": round(i_, 4), "cands": cands,
                           "note": f"配对 {nid} 但 {thr_iou}≤iou<{thr_low}，不自动重绑，交看图"}
            elif nid == oc:
                res[oc] = {"status": "未变", "new": nid, "iou": round(i_, 4), "cands": cands, "note": ""}
            else:
                res[oc] = {"status": "一对一改号", "new": nid, "iou": round(i_, 4), "cands": cands, "note": ""}
    return res


def _sha(p: str) -> str | None:
    pp = Path(p)
    if pp.is_dir():
        return None
    return hashlib.sha256(pp.read_bytes()).hexdigest()[:16]


def main(argv=None) -> dict:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--lookups", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--book", default=None)
    ap.add_argument("--iou", type=float, default=DEFAULT_IOU)
    ap.add_argument("--low", type=float, default=DEFAULT_LOW)
    ap.add_argument("--ov", type=float, default=DEFAULT_OV)
    ap.add_argument("--gone", type=float, default=DEFAULT_GONE)
    ap.add_argument("--emit-vision-jsonl", action="store_true")
    ap.add_argument("--ts", default=None, help="导出行的基准时间 UTC（YYYY-MM-DDTHH:MM:SSZ，缺省取现在）；退役行用它，新号行 +1 秒")
    a = ap.parse_args(argv)

    old = load_table(a.old, a.book)
    new = load_table(a.new, a.book)
    lp = Path(a.lookups)
    with open(lp, encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        cols = list(rd.fieldnames or [])
        rows = list(rd)
    ck = next((c for c in ("cell", "格id", "格") if c in cols), None)
    if ck is None:
        sys.exit("看图结论 CSV 需要 cell（或「格id」「格」）列")
    by_page: dict[int | None, list[str]] = {}
    for r in rows:
        by_page.setdefault(_page(r[ck]), []).append(r[ck])
    verdict: dict[str, dict] = {}
    for pg, cells in by_page.items():
        if pg is None:
            for c in cells:
                verdict[c] = {"status": "无对应", "new": None, "iou": 0.0, "cands": [], "note": "格 id 形态不对"}
            continue
        if pg not in new:
            for c in cells:
                verdict[c] = {"status": "无对应", "new": None, "iou": 0.0, "cands": [], "note": "新格表没有这一页"}
            continue
        verdict.update(classify(sorted(set(cells)), old.get(pg, {}), new[pg], a.iou, a.ov, a.gone, a.low))

    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = lp.stem
    ok_rows, look_rows = [], []
    for r in rows:
        v = verdict[r[ck]]
        if v["status"] in ("未变", "一对一改号"):
            ok_rows.append({**r, "new_cell": v["new"], "rebind_status": v["status"], "iou": v["iou"], "rebind_note": v["note"]})
        else:
            cand = "; ".join(f"{n}(iou={i:.2f},ov={o:.2f})" for n, i, o in v["cands"][:6])
            look_rows.append({**r, "rebind_status": v["status"], "candidates": cand, "rebind_note": v["note"]})
    with open(out / f"{stem}.新结论.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols + ["new_cell", "rebind_status", "iou", "rebind_note"])
        w.writeheader()
        w.writerows(ok_rows)
    with open(out / f"{stem}.要人看.csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols + ["rebind_status", "candidates", "rebind_note"])
        w.writeheader()
        w.writerows(look_rows)

    counts: dict[str, int] = {}
    for r in rows:
        counts[verdict[r[ck]]["status"]] = counts.get(verdict[r[ck]]["status"], 0) + 1
    summ = {"rows": len(rows), "by_status": counts, "auto_rebound": len(ok_rows), "need_human": len(look_rows),
            "params": {"iou": a.iou, "low": a.low, "ov": a.ov, "gone": a.gone},
            "inputs": {"old": a.old, "new": a.new, "lookups": a.lookups,
                       "sha16": {"old": _sha(a.old), "new": _sha(a.new), "lookups": _sha(a.lookups)}}}
    n_vis = 0
    if a.emit_vision_jsonl:
        # 208hj ②（Elena C2）：看图日志「同格按 (ts, 批次, 行号) 后到覆盖」（vision.py:34-36、170-185）。
        # 所以：①两遍输出——先全部退役行、后全部新号行；②旧号恰是别条的新号目标时不写退役行（否则会把刚搬来的结论盖成 unsure）；
        # ③显式给 ts：退役行 ts=T，新号行 ts=T+1s（都晚于所有原判的 ts），**不沿用原判的 ts**（沿用会让更晚的退役行压过新号行）；
        # ④写完在脚本里按同样的覆盖规则模拟一遍，不符合就 sys.exit。
        import datetime as _dt
        t0 = _dt.datetime.strptime(a.ts, "%Y-%m-%dT%H:%M:%SZ") if a.ts else _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0, tzinfo=None)
        ts_retire = t0.strftime("%Y-%m-%dT%H:%M:%SZ")
        ts_new = (t0 + _dt.timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        keep = ("v", "char", "shown", "judge", "note", "group", "ref")
        moves = [r for r in ok_rows if r["rebind_status"] == "一对一改号"]
        targets = {r["new_cell"] for r in moves}
        retire_rows, new_rows, skipped = [], [], 0
        for r in moves:
            base = {k: r[k] for k in keep if r.get(k)}
            if "v" not in base or "judge" not in base:
                sys.exit(f"{r[ck]}: --emit-vision-jsonl 需要 v、judge 列")
            note = (base.get("note", "") + f"｜迁自 {r[ck]}" + (f"（原判 ts {r['ts']}）" if r.get("ts") else "")).lstrip("｜")
            new_rows.append({"cell": r["new_cell"], **{**base, "note": note}, "ts": ts_new})
            if r[ck] in targets:       # 旧号同时是别条的新号目标：不退役，由那条新号行覆盖
                skipped += 1
                continue
            retire_rows.append({"cell": r[ck], "v": "unsure", "judge": base["judge"],
                                "note": f"格号迁移退役：原结论已搬到 {r['new_cell']}", "ts": ts_retire})
        out_rows = retire_rows + new_rows            # 先全部退役、后全部新号
        with open(out / f"{stem}.import-vision.jsonl", "w", encoding="utf-8") as f:
            for row in out_rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        # 模拟 vision_checks：同格取 (ts, 行号) 最大的一条
        eff = {}
        for i, row in enumerate(out_rows):
            k = row["cell"]
            if k not in eff or (row["ts"], i) >= (eff[k][0], eff[k][1]):
                eff[k] = (row["ts"], i, row["v"])
        for r in moves:
            want = r["v"]
            if eff[r["new_cell"]][2] != want:
                sys.exit(f"导出顺序自检失败：{r['new_cell']} 应为 {want}，模拟结果 {eff[r['new_cell']][2]}")
            if r[ck] not in targets and eff[r[ck]][2] != "unsure":
                sys.exit(f"导出顺序自检失败：旧号 {r[ck]} 应退役为 unsure，模拟结果 {eff[r[ck]][2]}")
        n_vis = len(out_rows)
        summ["import_vision_rows"] = n_vis
        summ["retire_rows"] = len(retire_rows)
        summ["retire_skipped_as_target"] = skipped
        summ["emit_selfcheck"] = "ok"
    (out / f"{stem}.摘要.json").write_text(json.dumps(summ, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summ, ensure_ascii=False))
    return summ


if __name__ == "__main__":
    main()
