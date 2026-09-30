# -*- coding: utf-8 -*-
"""jiazhu_tail 金标迁移到 v2（M1 道 C 组，2026-09-30）。

源：`char-segmentation/jiazhu-tail/expected.json`：57 条，键 (book,page,col,idx) + 三分类 expect
    （tail_a 奇数字末行单字 / row 漏拆末行 / reject 正文不收）。`label_origin=model_visual`——
    当年就是**模型看接触表目视核对**的，没有保存图块、没有图像指纹、没有 bbox。

为什么不能按「图块/指纹对得上」迁：这分片从来没存过图。能拿到的只有 v1 键 (page,col,idx)，
而 v1 键漂移是这分片的老病（README「已知局限」记过一次 vol02/145:5）。

做法（仍然是看图，不是看算法）：
  0. 先按**用户定的排除页**剔条：vol01/89、vol01/90、vol02/159（压缩职名页，2026-08-25 用户定「不判读、不入测试集」）
     ——这 10 条本来就不该在金标里；
  1. 锚位：v1 idx → v2 `pos = idx+1`（已在 recrop 上得到 31/31 旁证），取 v2 Step3 的 (col, slot)；
  2. 出联系表：v2 列图里该格及其上两格、下一格的原图切片（**不叠任何算法判断**，只在左缘用短线标 Step3 格界、
     用括号标被评格），逐条目视：被评格是「a 行单个小字」/「a+b 双行小字」/「一个正文大字」/ 说不清；
  3. 目视结论与原 expect 相符 → 迁移（`visual_check=consistent`）；不符 / 说不清 → 失效并写明。
  结论登记在 `visual_review.json`（可复核），`apply` 只认其中登记的。

用法：
  python migrate_jiazhu.py sheets            # 出联系表 sheets/
  python migrate_jiazhu.py apply             # 并入目视结论，写 jiazhu-tail/expected_v2.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "scripts"))
from _v2_step4 import V2Book, dataset_root  # noqa: E402

DS = dataset_root() / "char-segmentation" / "jiazhu-tail"
EXCLUDED = {("vol01", 89), ("vol01", 90), ("vol02", 159), ("vol02", 160), ("vol02", 3)}


def load_gold():
    return json.loads((DS / "expected.json").read_text(encoding="utf-8"))


def cmd_sheets():
    gold = [e for e in load_gold() if (e["book"], int(e["page"])) not in EXCLUDED]
    (HERE / "sheets").mkdir(exist_ok=True)
    books: dict = {}
    tiles, meta = [], []
    for n, e in enumerate(gold):
        b, pg = e["book"], int(e["page"])
        v = books.setdefault(b, V2Book(b))
        v.ensure([pg])
        cells = v.cells(pg)
        cc = cells.column(e["col"]) if cells else None
        tag = f"{b}:{pg}:{e['col']}:{e['idx']} [{e['expect']}]"
        if cc is None or not cc.ok:
            tiles.append(_blank(f"#{n} {tag}\nv2 无此列"))
            meta.append({"n": n, "id": tag})
            continue
        pos = e["idx"] + 1
        at = {c.pos: c for c in cc.cells}
        tgt = at.get(pos)
        if tgt is None:
            tiles.append(_blank(f"#{n} {tag}\nv2 无 pos={pos}"))
            meta.append({"n": n, "id": tag})
            continue
        img = v.col_img(pg, e["col"])
        y0 = int(max(0, (at.get(pos - 2) or at.get(pos - 1) or tgt).y0 - 8))
        y1 = int(min(img.shape[0], (at.get(pos + 1) or tgt).y1 + 8))
        crop = cv2.cvtColor(img[y0:y1], cv2.COLOR_GRAY2BGR)
        # 左缘：Step3 格界短线 + 被评格括号（仅作定位参考）
        for c in cc.cells:
            if c.sub == "b":
                continue
            for yy in (c.y0, c.y1):
                if y0 <= yy <= y1:
                    cv2.line(crop, (0, int(yy - y0)), (10, int(yy - y0)), (0, 140, 0), 2)
        cv2.rectangle(crop, (0, int(tgt.y0 - y0)), (4, int(tgt.y1 - y0)), (0, 0, 255), -1)
        s = 330 / crop.shape[0] if crop.shape[0] > 330 else 1.0
        crop = cv2.resize(crop, (int(crop.shape[1] * s), int(crop.shape[0] * s)), interpolation=cv2.INTER_AREA)
        t = np.full((380, 300, 3), 255, np.uint8)
        w = min(300, crop.shape[1])
        t[40:40 + crop.shape[0], :w] = crop[:, :w]
        cv2.putText(t, f"#{n} {e['expect']}", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        cv2.putText(t, f"{b[-2:]}:{pg}:{e['col']}:{e['idx']}->s{tgt.slot}", (4, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (90, 90, 90), 1)
        tiles.append(t)
        meta.append({"n": n, "id": f"{b}:{pg}:{e['col']}:{e['idx']}", "expect": e["expect"], "slot": tgt.slot, "col_v2": e["col"]})
    per = 5
    while len(tiles) % per:
        tiles.append(np.full((380, 300, 3), 255, np.uint8))
    for k in range(0, len(tiles), per):
        cv2.imwrite(str(HERE / "sheets" / f"sheet_{k // per:02d}.png"), np.hstack(tiles[k:k + per]))
    (HERE / "sheets" / "order.json").write_text(json.dumps(meta, ensure_ascii=False, indent=0), encoding="utf-8")
    print(len(gold), "条 →", len(tiles) // per, "页")


def _blank(text):
    t = np.full((380, 300, 3), 255, np.uint8)
    for i, ln in enumerate(text.split("\n")):
        cv2.putText(t, ln, (4, 20 + 18 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 200), 1)
    return t


def cmd_apply():
    gold = load_gold()
    rv = json.loads((HERE / "visual_review.json").read_text(encoding="utf-8"))
    order = json.loads((HERE / "sheets" / "order.json").read_text(encoding="utf-8"))
    by_id = {m["id"]: m for m in order}
    seen = rv["seen"]                      # {id: 目视结论 tail_a|row|reject|unsure|nocell}
    items, retired = [], []
    for e in gold:
        gid = f"{e['book']}:{e['page']}:{e['col']}:{e['idx']}"
        base = {"id_v1": gid, "book": e["book"], "page": int(e["page"]), "v1_col": e["col"], "v1_idx": e["idx"],
                "expect": e["expect"]}
        if (e["book"], int(e["page"])) in EXCLUDED:
            retired.append({**base, "reason": "用户 2026-08-25 定的排除页（压缩职名页，不判读、不入测试集）"})
            continue
        m = by_id.get(gid)
        seen_v = seen.get(gid)
        if m is None or "slot" not in m:
            retired.append({**base, "reason": "v2 没有对应列/格位（v1 键漂移或该页 v2 无产物）"})
        elif seen_v is None:
            retired.append({**base, "reason": "未目视核对"})
        elif seen_v != e["expect"]:
            retired.append({**base, "reason": f"目视结论 {seen_v} 与原标签 {e['expect']} 不符/说不清（按规矩踢出，不硬改标签）"})
        else:
            items.append({"book": e["book"], "page": e["page"], "col": m["col_v2"], "slot": m["slot"],
                          "expect": e["expect"], "label_origin": "model_visual",
                          "visual_check": "consistent", "id_v1": gid})
    doc = {"schema": 1, "note": "M1 C 组 2026-09-30 迁移；判据见 artifacts/m1_gold/jiazhu_tail/MIGRATION.md",
           "items": items, "retired": retired}
    for d in (DS, HERE):
        (d / "expected_v2.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("迁移", len(items), Counter(i["expect"] for i in items), "失效", len(retired))
    print(Counter(r["reason"].split("（")[0][:30] for r in retired))


if __name__ == "__main__":
    {"sheets": cmd_sheets, "apply": cmd_apply}[sys.argv[1]]()
