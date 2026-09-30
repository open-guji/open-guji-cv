# -*- coding: utf-8 -*-
"""touching-cuts 金标 → 现役 v2 列图坐标（只迁「图/几何还在」的）。2026-09-30 M1 B 道。

金标 y / polyline 记在 Step2 列图坐标里，列图是射影矫正产物，边线几何一变同一行号就指到别处（列高可以一点不变，
见 open_guji_cv/eval/colgeom.py 文档）。**「人当时看的那张图」没有保存**（条目里只有 col_h 与字符标签，控制台卡片裁片
不落盘），所以判据只能是「金标是否记了页面坐标（page_x/page_y）或列窗几何签名」——有页面坐标 = 金标锚在原图上，按
**当前**列窗几何换算即得现役列图坐标（人看的是原图这一处，图还在）；只有签名则签名必须与当前一致；什么都没记的老条目
（legacy）无法证明坐标系没漂，标「无法验证」，**不迁、不硬造**。**不使用「格线与现役 Step3 一致」作判据（循环论证）。**

输出（同目录）：
  classification.json     每条 active 条目的去向 {id, tier: page|sig_ok|legacy|drift|no_geom, status: migrated|invalid, why}
  items_v2.jsonl          迁过来的条目（expected.y / polyline 已换成现役列图坐标，保留 y_old_legacy、重写 col_h、geom_sig）
用法（cwd=引擎仓；需沙箱 env、相关页已有 column_warp 产物）：
    python artifacts/m1_gold/touching_cuts/migrate_touching_cuts_v2.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from open_guji_cv.eval.colgeom import current_geom, gold_rows_now, stamp  # noqa: E402
from open_guji_cv.products import kinds as _k  # noqa: E402,F401
from open_guji_cv.products.store import ProductStore  # noqa: E402

SRC = ROOT.parent / "open-guji-dataset" / "char-segmentation" / "touching-cuts" / "items.jsonl"
OUT = Path(__file__).parent


def main() -> int:
    st = ProductStore()
    geoms: dict = {}
    cls, out_items = [], []
    for line in SRC.read_text(encoding="utf-8").splitlines():
        it = json.loads(line)
        if it.get("status") != "active":
            cls.append(dict(id=it["id"], tier="-", status="invalid", why=f"原 status={it.get('status')}（本就不进指标）"))
            continue
        a, ex = it["anchor"], it["expected"]
        k = (a["book"], a["page"], a["col"])
        if k not in geoms:
            geoms[k] = current_geom(st, *k)
        geom = geoms[k]
        has_anchor = ex.get("page_y") is not None or ex.get("geom_sig")
        if not has_anchor:
            cls.append(dict(id=it["id"], tier="legacy", status="invalid",
                            why="老条目：只记列图坐标 + col_h，未记页面坐标/列窗签名，人当时看的裁片也没落盘——无法证明坐标系没漂"))
            continue
        if geom is None:
            cls.append(dict(id=it["id"], tier="no_geom", status="invalid",
                            why="现役 column_windows 产物缺失（沙箱没跑到该页），无法换算——不是金标作废，补产物后可重判"))
            continue
        mode, y_now, pl_now = gold_rows_now(ex, geom)
        if mode == "drift":
            cls.append(dict(id=it["id"], tier="drift", status="invalid", why="列窗几何签名与现役不同且无页面坐标"))
            continue
        new = dict(it)
        nex = dict(ex)
        nex["y_legacy_colimg"] = ex.get("y")
        if y_now is not None:
            nex["y"] = round(float(y_now), 2)
        if pl_now is not None:
            nex["polyline"] = pl_now
        nex["col_h"] = geom.height
        nex.update(stamp(nex, geom))
        new["expected"] = nex
        new["history"] = list(it.get("history", [])) + [dict(change="m1_migrate", ts="2026-09-30T00:00:00Z",
                              why="M1 B 道：按页面坐标换算到现役列图（page 口径）")]
        out_items.append(new)
        cls.append(dict(id=it["id"], tier=mode, status="migrated", why=""))
    (OUT / "classification.json").write_text(json.dumps(cls, ensure_ascii=False, indent=0), encoding="utf-8")
    (OUT / "items_v2.jsonl").write_text("\n".join(json.dumps(i, ensure_ascii=False) for i in out_items) + "\n", encoding="utf-8")
    c = Counter((r["status"], r["tier"], r["why"][:26]) for r in cls)
    print(f"active+其他 {len(cls)}：迁 {len(out_items)}")
    for k, n in c.most_common():
        print("  ", n, k)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
