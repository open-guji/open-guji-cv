# -*- coding: utf-8 -*-
"""M1·A 道：column-warp 金标 → 现行 v2 链的迁移报告（2026-09-30）。

    python research/scripts_oneoff/migrate_m1_column_warp.py ../open-guji-dataset/char-segmentation/column-warp \\
        --out artifacts/m1_gold/column_warp

对每条原始标注（`samples/*.json` 全部，不只看「当前还留着的」）：取 v2 链产物
`cache/<册>/column_raw/pNNNNcNN.png`，过 `column_warp_v2.identity`（「人当时看的图还在不在」，
判据见那个模块的文档；**不拿算法一致性当判据**）。

输出（都在 `--out` 下）：
  samples_v2/<id>.json     迁得过去的样本原文 + `v2_identity`（走哪一档、指纹差、曲线差、宽度差；
                           remedy_clean 档另带重推的 canonical，并把 text_band.canonical_* 改成新值，
                           旧值留在 v2_identity.canonical_was）
  invalidated.json         迁不了的：id + 原因（图变了/产物缺），不硬造金标
  migration_report.json    逐条汇总（含已留用的）
幂等。不写数据集仓。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from column_warp_v2 import identity, load_v2  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = Path(a.out)
    (out / "samples_v2").mkdir(parents=True, exist_ok=True)
    files = sorted((Path(a.dataset) / "samples").glob("*.json"))
    kept, bad, rows = [], [], []
    chan = Counter()
    for f in files:
        s = json.loads(f.read_text(encoding="utf-8"))
        sid = f.stem
        got = load_v2(s["book"], int(s["page"]), int(s["col"]))
        if got is None:
            bad.append({"id": sid, "reason": "v2 产物缺（该页没跑 column_warp）"})
            rows.append({"id": sid, "status": "missing"})
            continue
        raw, rec = got
        ident = identity(s, raw)
        row = {"id": sid, "verdict": s.get("verdict"), "w_gold": len(s.get("profile") or []),
               "w_v2": int(raw.shape[1]), **{k: ident[k] for k in ("fp", "prof_mad", "dw")}}
        if ident["ok"]:
            chan[ident["channel"]] += 1
            s2 = json.loads(json.dumps(s))
            vi = {k: ident[k] for k in ("channel", "fp", "prof_mad", "dw")}
            if ident["channel"] == "remedy_clean":
                vi["canonical_was"] = [s["text_band"]["canonical_left"], s["text_band"]["canonical_right"]]
                s2["text_band"]["canonical_left"], s2["text_band"]["canonical_right"] = ident["canonical"]
                vi["ink_at_human"] = ident["ink_at_human"]
            s2["v2_identity"] = vi
            (out / "samples_v2" / f"{sid}.json").write_text(
                json.dumps(s2, ensure_ascii=False, indent=1), encoding="utf-8")
            kept.append(sid)
            row.update(status="kept", channel=ident["channel"])
        else:
            why = []
            if ident["dw"] is not None and abs(ident["dw"]) > 3:
                why.append(f"列图宽变了 {ident['dw']:+d}px（窗口/边线换过，x 坐标系不同）")
            if ident["prof_mad"] is not None and ident["prof_mad"] > 0.012:
                why.append(f"投影曲线变了（MAD {ident['prof_mad']}>0.012）")
            if s.get("verdict") != "clean":
                why.append(f"判为 {s.get('verdict')}，无零墨补救通道")
            elif not why:
                why.append("人标点在新图上墨占比>0.01")
            bad.append({"id": sid, "reason": "；".join(why), "verdict": s.get("verdict"),
                        "fp": ident["fp"], "prof_mad": ident["prof_mad"], "dw": ident["dw"]})
            row.update(status="invalidated")
        rows.append(row)
    (out / "invalidated.json").write_text(json.dumps(bad, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "migration_report.json").write_text(json.dumps(
        {"n_original": len(files), "kept": len(kept), "invalidated": len(bad),
         "channels": dict(chan), "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
    miss = sum(1 for r in rows if r["status"] == "missing")
    print(f"原始 {len(files)} 条：迁入 {len(kept)}（{dict(chan)}），失效 {len(bad) - miss}，产物缺 {miss}")


if __name__ == "__main__":
    main()
