# -*- coding: utf-8 -*-
"""把影子预测落成控制台审卡读的文件（overview#269）。

    python research/shadow_admit/export_for_cards.py <shadow_picks.jsonl> --book vol03 \
        [--out <path>]      # 缺省 <ws>/cache/shadow/<book>.json

输入是 `predict.py` 产出的 `shadow_picks.jsonl`（每格一行：id / pick 影子字 / conf 把握度 / cur 现字…）。
输出格式见 `open_guji_cv/review/shadow.py` 模块头：`{"version":1,"book":…,"cells":{id:{char,conf}}}`。
只依赖标准库，不需要 pandas／sklearn。原子写（先写临时文件再替换）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def convert(picks_path: Path, book: str) -> dict:
    cells: dict[str, dict] = {}
    for ln in picks_path.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if not r.get("id") or not r.get("pick"):
            continue
        cells[str(r["id"])] = {"char": str(r["pick"]), "conf": round(float(r["conf"]), 4)}
    return {"version": 1, "book": book, "cells": cells}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("picks", help="shadow_picks.jsonl")
    ap.add_argument("--book", required=True)
    ap.add_argument("--out", help="缺省 <ws>/cache/shadow/<book>.json")
    a = ap.parse_args()
    doc = convert(Path(a.picks), a.book)
    if a.out:
        out = Path(a.out)
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from open_guji_cv.review.shadow import shadow_path
        out = shadow_path(a.book)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, out)
    print(f"{len(doc['cells'])} 格 → {out}")


if __name__ == "__main__":
    main()
