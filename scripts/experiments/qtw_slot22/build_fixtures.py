"""overview#202 测试集生成：从改前/改后两个沙箱工作区抽冻结样本到 tests/fixtures/qtw_slot22/。

    python scripts/experiments/qtw_slot22/build_fixtures.py SPEC.json

SPEC.json（人手写，逐例目检过才进）：
  {"split": [{"ws": ".../qtw-new", "book": "v006", "page": 69, "col": 7, "slot": 13, "char": "二",
              "d_id": "v006:69:7:13"}, ...],          # 改后整字那一格（slot 为改后编号）
   "gate_keep": [{"ws": ..., "book": ..., "page": ..., "col": ..., "trim": false, "why": "..."}],
                                                     # 真抬头列：在该书口径（trim 开/关）下 hint 必须留着
   "tail": [{"ws": ..., "book": ..., "id": "v006:2:1:22", "frame": true, "why": "..."}]}

产出：
  cols/<book>_p<page>_c<col>.png   列图（二值，文字带整幅），给交接闸跨度与 Step3 DP 用
  cases.json                       每例的几何量（period / content_x / border_* / bbox）与标签
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

OUT = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "qtw_slot22"


def _rs(ws, book, page, col):
    d = json.load(open(f"{ws}/products/{book}/row_segment/p{page:04d}.json"))["cells"]["columns"]
    return next(c for c in d if c["col"] == col)


def _gate(ws, book, page, col):
    d = json.load(open(f"{ws}/products/{book}/column_gate/p{page:04d}.json"))
    d = d[next(iter(d))]
    return d, next(c for c in d["columns"] if c["col"] == col)


def _chars(ws, book, page, col):
    d = json.load(open(f"{ws}/products/{book}/cell_shrink/p{page:04d}.json"))["char_index"]["columns"]
    return next(c for c in d if c["col"] == col)["chars"]


def _save_col(ws, book, page, col) -> str:
    name = f"{book}_p{page}_c{col}.png"
    im = cv2.imread(f"{ws}/cache/{book}/column_image/p{page:04d}c{col:02d}.png", cv2.IMREAD_GRAYSCALE)
    (OUT / "cols").mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT / "cols" / name), np.where(im < 128, 0, 255).astype(np.uint8),
                [cv2.IMWRITE_PNG_BILEVEL, 1])
    return f"cols/{name}"


def _col_meta(ws, book, page, col) -> dict:
    r = _rs(ws, book, page, col)
    g, gc = _gate(ws, book, page, col)
    return dict(period=r["period"], ref_w=r["ref_w"], n_body_slots=r["n_body_slots"],
                border_top=r["border_top"], border_bottom=r["border_bottom"], top_slack=r["top_slack"],
                content_x=r["content_x"])


def main(spec_path: str) -> None:
    spec = json.load(open(spec_path))
    cases = {"split": [], "gate_keep": [], "tail": []}
    for s in spec.get("split", []):
        ws, book, page, col = s["ws"], s["book"], s["page"], s["col"]
        c = next(x for x in _chars(ws, book, page, col) if x["slot"] == s["slot"] and not x.get("sub"))
        cases["split"].append(dict(id=f"{book}:{page}:{col}", png=_save_col(ws, book, page, col),
                                   char=s["char"], d_id=s.get("d_id"), bbox=c["bbox_col"],
                                   **_col_meta(ws, book, page, col)))
    for s in spec.get("gate_keep", []):
        ws, book, page, col = s["ws"], s["book"], s["page"], s["col"]
        _, gc = _gate(ws, book, page, col)
        cases["gate_keep"].append(dict(id=f"{book}:{page}:{col}", png=_save_col(ws, book, page, col),
                                       hint=gc["n_raised_hint"], trim=bool(s.get("trim", False)),
                                       why=s.get("why", ""),
                                       **_col_meta(ws, book, page, col)))
    for s in spec.get("tail", []):
        ws, book = s["ws"], s["book"]
        _, page, col, slot = s["id"].split(":")
        page, col, slot = int(page), int(col), int(slot)
        r = _rs(ws, book, page, col)
        c = next(x for x in _chars(ws, book, page, col) if x["slot"] == slot and not x.get("sub"))
        cases["tail"].append(dict(id=s["id"], frame=bool(s["frame"]), why=s.get("why", ""),
                                  bbox=c["bbox_col"], pos=c["pos"],
                                  last_pos=max(x["pos"] for x in r["cells"]),
                                  period=r["period"], content_x=r["content_x"],
                                  border_bottom=r["border_bottom"]))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print({k: len(v) for k, v in cases.items()})


if __name__ == "__main__":
    main(sys.argv[1])
