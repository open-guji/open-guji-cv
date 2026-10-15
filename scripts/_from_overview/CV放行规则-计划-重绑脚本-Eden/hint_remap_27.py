# -*- coding: utf-8 -*-
"""hint 名单里改号页上各格：A（hint 开）格号 → B1（hint 关）旧格号 的几何对位（GUJI-208fu／208hf）。

    python hint_remap_27.py --a <A 产物根> --b <B 产物根> --cells cells.txt --out-dir <目录>
        [--b-table volNN_base.jsonl.gz ...] [--iou 0.5] [--low 0.6]

--a / --b 是产物根（含 `<book>/cell_shrink/pNNNN.json`）：B＝默认参数现跑，A＝`--params '{"column_gate":{"hint_ignore_dash":true}}'` 现跑。
**两边都必须装了 torch**（Step3 `cut_judge: unet` 缺 torch 会静默退回旧规则，cell_shrink 框会变，见 `154页框高对账-Eden.md`）。
口径同 `rebind_lookups.py`：IoU 0.5 配对、0.5≤IoU<0.6 低置信、重叠系数 0.5 判拆分／合并；方向＝对每个 A 格求它在 B 里的对应格。

输出（--out-dir）
  对位.tsv        A格号｜状态｜B旧格号｜iou｜B框｜A框｜候选｜B基线状态｜竞争者数｜主导候选
  remap.tsv       两列「旧⇥新」，喂 Emi 的 `sample_newadmit.py --remap`。只含「一对一且 iou≥--low」；
                  **自检**：每个新号 N 若在 B 里另有一个同号格（不在旧键里），Emi 的 apply_remap 会把两格并到同一新号
                  （「任一放行则放行」→新放行被吞），所以自动补一行 N→（它在 A 里的真实对应号，找不到就留空＝已删），
                  新补的号再递归自检直到闭合；补行数写进摘要。
  主导候选.tsv    「一对多」里：最佳 iou≥--low、次佳 iou≤0.4、A 侧竞争者数＝1（A 页上除本格外没有别的 A 格与该 B 格重叠系数≥0.5），
                  **且（208hz，Esme 208hs）该 B 格之外没有另一个 B 格「整个落在同一 A 格里」**（inter/该 B 格面积 ≥ --contain，缺省 0.9）——
                  否则 A 格＝B 两格合并（多对一），喂 --remap 会撞号。仍是候选，不进 remap.tsv，未经人确认不要喂 --remap。
                  （Mila 原文写「oc≥0.5 包含」；按字面 0.5 会连 45:5:19〔B 5:18 的 0.54〕和 188:2:8〔B 2:7 的 0.61〕也剔掉，
                   与 Esme 逐格判「这两条成立」矛盾，所以我取「整个落在内」≥0.9，0.5 与 0.9 之间无格，请 Mila 确认。）
**适用范围（208hs）**：只给 cells 里这几个格找对位，**不能当整页 remap**——vol05 这 14 页 2133 个 A 格里 364 格（17%）A／B 号不同，
整列顺移远不止自检补行链；整页对位另走 `rebind_lookups.py`／`remap_gold.py`。窗口各臂（`--from seed_admit`，不含 hint）不用此表。
  摘要.json       各状态计数、补行数、主导候选数。
不碰任何真实事件／裁决／字形库。
"""
import argparse, gzip, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import rebind_lookups as R

ONE = ("未变", "一对一改号")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True); ap.add_argument("--b", required=True)
    ap.add_argument("--cells", required=True); ap.add_argument("--out-dir", required=True)
    ap.add_argument("--b-table", action="append", default=[])
    ap.add_argument("--iou", type=float, default=R.DEFAULT_IOU); ap.add_argument("--low", type=float, default=R.DEFAULT_LOW)
    ap.add_argument("--second-max", type=float, default=0.4)
    ap.add_argument("--contain", type=float, default=0.9, help="另一 B 格「整个落在同一 A 格内」的面积比阈值（inter/该 B 格面积）")
    a = ap.parse_args()
    cells = [l.strip() for l in open(a.cells, encoding="utf-8") if l.strip()]
    books = sorted({c.split(":")[0] for c in cells})
    A = {bk: R.load_table(a.a, bk) for bk in books}
    B = {bk: R.load_table(a.b, bk) for bk in books}
    bt = {}
    for t in a.b_table:
        with gzip.open(t, "rt", encoding="utf-8") as f:
            for l in f:
                r = json.loads(l)
                if not r.get("header"):
                    bt[r["id"]] = r
    out = Path(a.out_dir); out.mkdir(parents=True, exist_ok=True)

    def pg(c): return c.split(":")[0], int(c.split(":")[1])

    rows, remap, dominant = [], {}, []
    for c in cells:
        bk, p = pg(c)
        ap_, bp_ = A[bk].get(p, {}), B[bk].get(p, {})
        if c not in ap_:
            rows.append([c, "缺A框", "", 0, "", "", "", "", "", ""]); continue
        v = R.classify([c], ap_, bp_, a.iou, R.DEFAULT_OV, R.DEFAULT_GONE, a.low)[c]
        st, old = v["status"], v["new"]
        cand = sorted(v["cands"], key=lambda t: -t[1])
        comp, dom = "", ""
        if st == "一对多" and cand:
            best = cand[0]; second = cand[1][1] if len(cand) > 1 else 0.0
            comp_n = sum(1 for k, bx in ap_.items() if R.ov(bx, bp_[best[0]]) >= R.DEFAULT_OV)  # A 侧竞争者数（含本格）
            comp = comp_n
            swallowed = [k for k, bx in bp_.items() if k != best[0] and R.inter(ap_[c], bx) / max(R.area(bx), 1e-9) >= a.contain]
            if best[1] >= a.low and second <= a.second_max and comp_n == 1 and not swallowed:
                dom = best[0]; dominant.append((best[0], c, best[1], second))
        if st in ONE:
            remap[old] = c
        label = {"未变": "一对一（同号）", "一对一改号": "一对一（B 号不同）"}.get(st, st)
        rows.append([c, label, old or "", v["iou"], bp_.get(old, "") if old else "", ap_[c],
                     "; ".join(f"{n}(iou={i:.2f})" for n, i, _o in cand[:4]),
                     ("" if not old or old not in bt else f"{'放行' if bt[old].get('admit') else '待审'}｜{bt[old].get('char')}"),
                     comp, dom])
    # 自检：新号在 B 里另有同号格且不在旧键里 → 补行（递归）
    added = []
    queue = list(remap.values())
    while queue:
        n = queue.pop()
        if n in remap:                      # 它自己已是旧键
            continue
        bk, p = pg(n)
        if n not in B[bk].get(p, {}):
            continue
        w = R.classify([n], B[bk][p], A[bk].get(p, {}), a.iou, R.DEFAULT_OV, R.DEFAULT_GONE, a.low)[n]
        tgt = w["new"] if w["status"] in ONE else ""
        remap[n] = tgt; added.append((n, tgt, w["status"], w["iou"]))
        if tgt:
            queue.append(tgt)
    with open(out / "对位.tsv", "w", encoding="utf-8") as f:
        f.write("A格号\t状态\tB旧格号\tiou\tB框\tA框\t候选\tB基线状态\tA侧竞争者数\t主导候选\n")
        for r in rows:
            f.write("\t".join(map(str, r)) + "\n")
    with open(out / "remap.tsv", "w", encoding="utf-8") as f:
        f.write("# 旧格号(B1,hint 关)\t新格号(A,hint 开)；新格号留空＝已删。一对一且 iou≥%s；末尾若干行是自检补行（见 摘要.json）\n" % a.low)
        f.write("# 适用范围：只给 27 个 hint 名单格找对位，**不能当整页 remap**（vol05 14 页 364／2133 个 A 格 A/B 号不同）；窗口 --from seed_admit 臂不用此表\n")
        for o, n in remap.items():
            f.write(f"{o}\t{n}\n")
    with open(out / "主导候选.tsv", "w", encoding="utf-8") as f:
        f.write("# 旧格号(B1)\t新格号(A)；一对多里最佳 iou≥%s、次佳≤%s、A 侧竞争者数=1，且该 B 格之外无另一 B 格整个落在同一 A 格内(>=%s)。**未确认，勿喂 --remap**\n" % (a.low, a.second_max, a.contain))
        for o, n, i1, i2 in dominant:
            f.write(f"{o}\t{n}\n")
    cnt = {}
    for r in rows:
        cnt[r[1]] = cnt.get(r[1], 0) + 1
    summ = {"cells": len(rows), "by_status": cnt, "remap_rows_from_cells": sum(1 for r in rows if r[1].startswith("一对一")),
            "selfcheck_added_rows": len(added), "selfcheck_added": [list(x) for x in added], "dominant": len(dominant)}
    (out / "摘要.json").write_text(json.dumps(summ, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: summ[k] for k in ("cells", "by_status", "remap_rows_from_cells", "selfcheck_added_rows", "dominant")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
