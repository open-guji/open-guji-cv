# -*- coding: utf-8 -*-
"""instance_quality 金标迁移到 v2（M1 道 C 组，2026-09-30）。

源：`char-segmentation/instances/expected.json`（562 条，v1 键 book/page/col/idx，人工四分类）+ `patches/`
    （909 张图块，命名 <册>_<页>_<列>_<idx>.png）。`items.jsonl` 里另有 ~595 条 v2 原生人裁（slot 键）。
目标：`instances/instances_v2.json`。

⚠ 先记一个**推翻前提**的实测（2026-09-30）：任务书说「patches 是人当时看的图」，但逐张看幸存图块发现
   很大一部分**不是**——2026-08-24 重建轮刷新过 415 张图块（README「参照图块已按新产物刷新」），标签却是刷新前
   人给的：标 contaminated/truncated 的图块里，有相当一批现在画的是干净完整的字（旧缺陷已被上游修好）。
   所以「图块与 v2 字块图像对得上」**不足以**证明标签还成立——对得上的只是「新产物的图」，不是「人看的图」。
   因此本脚本加第二道门：标签与图块的一致性由**目视**确认（不是算法判），结果存 `visual_review.json`，
   脚本 --apply 时只认其中登记为 consistent 的条目。

三道门（全部是图像/目视，不含「算法现在判得对不对」）：
  1. 有人裁图块（expected 里有 patches/ 对应图）——没有图块的 legacy 条目没有任何图像凭证 → 失效；
  2. 图块与 v2 字块同一张图：同页、v2 `pos == v1 idx + 1` 且**列号相同**、尺寸各差 ≤8px、
     σ=1 模糊后归一化互相关 ≥0.93（NCC 经验：同图 0.96~1.00，不同图 <0.85）→ 锚到 v2 (col, slot)；
  3. 标签↔图块一致性：目视登记（见上）。

用法：
  python migrate_instances.py candidates        # 第 1、2 道，写 candidates.json（供目视）
  python migrate_instances.py sheets            # 出目视用的联系表到 sheets/
  python migrate_instances.py apply             # 第 3 道并入，写数据集 instances/instances_v2.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "scripts"))
from _v2_step4 import V2Book, dataset_root  # noqa: E402

NCC_MIN = 0.93
SIZE_TOL = 8
DS = dataset_root() / "char-segmentation" / "instances"


def legacy_entries():
    """expected.json 里 vol01/vol02 的条目；同键重复标注的处理见返回的第二项。"""
    ex = json.loads((DS / "expected.json").read_text(encoding="utf-8"))
    ex = [e for e in ex if e["book"] in ("vol01", "vol02")]
    by = defaultdict(list)
    for e in ex:
        by[(e["book"], str(e["page"]), e["col"], e["idx"])].append(e)
    keep, conflict = [], []
    for k, es in by.items():
        if len({x["quality"] for x in es}) > 1:
            conflict.extend(es)             # 同一个键人给了两种标签：哪个对应哪张图说不清 → 都不要
        else:
            keep.append(es[0])              # 同键同标签的重复，留一条
    return keep, conflict


def best_match(v: V2Book, pg: int, P: np.ndarray, e: dict, recs) -> dict | None:
    Pb = cv2.GaussianBlur(P, (0, 0), 1.0)
    best = None
    for col, r in recs:
        if col != e["col"] or r.pos != e["idx"] + 1:
            continue
        Q = v.patch(r.patch_key)
        if abs(Q.shape[1] - P.shape[1]) > SIZE_TOL or abs(Q.shape[0] - P.shape[0]) > SIZE_TOL:
            continue
        Qb = cv2.GaussianBlur(Q, (0, 0), 1.0)
        H, W = max(Q.shape[0], P.shape[0]) + 4, max(Q.shape[1], P.shape[1]) + 4
        A = np.full((H, W), 255, np.uint8)
        A[2:2 + Q.shape[0], 2:2 + Q.shape[1]] = Qb
        if Pb.shape[0] > A.shape[0] or Pb.shape[1] > A.shape[1]:
            continue
        ncc = float(cv2.matchTemplate(A, Pb, cv2.TM_CCOEFF_NORMED).max())
        if best is None or ncc > best["ncc"]:
            best = {"ncc": round(ncc, 4), "col": col, "slot": r.slot, "sub": r.sub, "patch_key": r.patch_key,
                    "size_v2": [Q.shape[1], Q.shape[0]], "flags_v2": list(r.flags)}
    return best


def build_candidates():
    legacy, conflict = legacy_entries()
    by = defaultdict(list)
    for e in legacy:
        by[(e["book"], int(e["page"]))].append(e)
    books: dict[str, V2Book] = {}
    out, retired = [], []
    for e in conflict:
        retired.append({"id_v1": f"{e['book']}:{e['page']}:{e['col']}:{e['idx']}", "book": e["book"],
                        "page": int(e["page"]), "v1_col": e["col"], "v1_idx": e["idx"], "quality": e["quality"],
                        "defect": e.get("defect"), "seed": e.get("seed"),
                        "reason": "同一 v1 键在 expected.json 里有互相矛盾的多个标签（哪个标签对应哪张图说不清）"})
    for (b, pg), es in sorted(by.items()):
        v = books.setdefault(b, V2Book(b))
        pc = v.chars(pg) if v.has_step4(pg) else None
        recs = ([(c.col, r) for c in pc.columns if c.ok for r in c.chars
                 if r.cell_type == "char" and r.patch_key] if pc is not None else [])
        for e in es:
            base = {"id_v1": f"{b}:{pg}:{e['col']}:{e['idx']}", "book": b, "page": pg, "v1_col": e["col"],
                    "v1_idx": e["idx"], "quality": e["quality"], "defect": e.get("defect"),
                    "seed": e.get("seed"), "layout": e.get("layout")}
            pp = DS / "patches" / f"{b}_{pg}_{e['col']}_{e['idx']}.png"
            if not pp.exists():
                retired.append({**base, "reason": "无人裁图块（patches/ 里没有这条的图），没有任何图像凭证"})
                continue
            if pc is None:
                retired.append({**base, "reason": "v2 没有这一页的 Step4 产物（整页 DP 无解或未跑）"})
                continue
            P = cv2.imread(str(pp), 0)
            m = best_match(v, pg, P, e, recs)
            if m is None or m["ncc"] < NCC_MIN:
                retired.append({**base, "reason": "图块与 v2 同位字块不是同一张图"
                                + (f"（最佳 NCC {m['ncc']}）" if m else "（同位 pos 不存在或尺寸差 >8px）"),
                                "patch": pp.name})
                continue
            out.append({**base, "patch": pp.name, "v2": m})
    return out, retired


def cmd_candidates():
    cand, retired = build_candidates()
    (HERE / "candidates.json").write_text(json.dumps({"candidates": cand, "retired": retired},
                                                     ensure_ascii=False, indent=1), encoding="utf-8")
    print("候选（过 1、2 道）", len(cand), Counter(c["quality"] for c in cand))
    print("失效", len(retired), Counter(r["reason"].split("（")[0] for r in retired))


def cmd_sheets():
    cand = json.loads((HERE / "candidates.json").read_text(encoding="utf-8"))["candidates"]
    (HERE / "sheets").mkdir(exist_ok=True)
    order = {"contaminated": 0, "truncated": 1, "not_text": 2, "clean": 3}
    cand.sort(key=lambda c: (order[c["quality"]], c["book"], c["page"], c["v1_col"], c["v1_idx"]))
    per = 12
    TW, TH = 230, 250
    for si in range(0, len(cand), per):
        chunk = cand[si:si + per]
        tiles = []
        for n, c in enumerate(chunk):
            P = cv2.imread(str(DS / "patches" / c["patch"]), 0)
            t = np.full((TH, TW), 255, np.uint8)
            h, w = P.shape
            s = min(1.6, (TH - 40) / h, (TW - 10) / w)
            Pr = cv2.resize(P, (max(1, int(w * s)), max(1, int(h * s))), interpolation=cv2.INTER_AREA)
            t[22:22 + Pr.shape[0], 5:5 + Pr.shape[1]] = Pr
            cv2.putText(t, f"#{si + n} {c['quality'][:5]}", (3, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, 0, 1)
            cv2.putText(t, c["id_v1"].replace("vol0", "v"), (3, TH - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.4, 90, 1)
            cv2.rectangle(t, (0, 0), (TW - 1, TH - 1), 160, 1)
            tiles.append(t)
        while len(tiles) % 6:
            tiles.append(np.full((TH, TW), 255, np.uint8))
        rows = [np.hstack(tiles[i:i + 6]) for i in range(0, len(tiles), 6)]
        cv2.imwrite(str(HERE / "sheets" / f"sheet_{si // per:02d}.png"), np.vstack(rows))
    (HERE / "sheets" / "order.json").write_text(json.dumps([c["id_v1"] for c in cand], ensure_ascii=False))
    print(len(cand), "张 →", (len(cand) + per - 1) // per, "页联系表")


def cmd_apply():
    cand = json.loads((HERE / "candidates.json").read_text(encoding="utf-8"))
    rv = json.loads((HERE / "visual_review.json").read_text(encoding="utf-8"))
    bad = set(rv["inconsistent"])            # 标签与图块明显不符（含「图块现画的是干净字，标签却是缺陷」）
    unsure = set(rv.get("unsure", []))
    reviewed = set(rv["reviewed"])
    items, retired = [], list(cand["retired"])
    for c in cand["candidates"]:
        i = c["id_v1"]
        if i not in reviewed:
            retired.append({**c, "reason": "标签↔图块一致性未目视确认"})
        elif i in bad:
            retired.append({**c, "reason": "目视：图块与标签不符（图块已被后续产物刷新，标签描述的是旧图）"})
        elif i in unsure:
            retired.append({**c, "reason": "目视：放大仍拿不准，按规矩踢出（判不准不入金标）"})
        else:
            items.append({"id": f"{c['book']}:{c['page']}:{c['v2']['col']}:{c['v2']['slot']}"
                          + (c["v2"]["sub"] or ""),
                          "book": c["book"], "page": c["page"], "col": c["v2"]["col"], "slot": c["v2"]["slot"],
                          "quality": c["quality"], "defect": c["defect"], "seed": c["seed"],
                          "label_origin": "human",
                          "evidence": {"patch": c["patch"], "id_v1": i, "ncc": c["v2"]["ncc"],
                                       "size_v2": c["v2"]["size_v2"], "visual_check": "consistent"}})
    doc = {"schema": 1, "note": "M1 C 组 2026-09-30 迁移；判据见 artifacts/m1_gold/instance_quality/MIGRATION.md",
           "items": items, "retired": retired}
    (DS / "instances_v2.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (HERE / "instances_v2.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("迁移", len(items), Counter(i["quality"] for i in items), " 失效", len(retired))
    print(Counter(r["reason"].split("（")[0] for r in retired))


if __name__ == "__main__":
    {"candidates": cmd_candidates, "sheets": cmd_sheets, "apply": cmd_apply}[sys.argv[1]]()
