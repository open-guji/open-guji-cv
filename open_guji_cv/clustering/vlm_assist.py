"""VLM 辅助识别：把簇代表拼成带编号的识别清单图，供视觉语言模型
（如 Claude）逐批识字；识别结果导回 M4 契约的 candidates.json。

无 OCR 环境下的候选生成路径：簇级识别一次惠及全簇，492 簇的识别
即可覆盖整书 17% 的实例（book9 实测）。

流程：
1. make_sheets()  → sheets/batch_NN.png + mapping.json
2. 视觉模型逐批识别，结果写 recognitions.json：
   {"batch_01": {"1": "一", "27": "日|曰~", "6": null, ...}}
   语法："字"=高置信；"字1|字2"=多候选；后缀 "~"=低置信；null=非字残片
3. import_recognitions() → phase6_labels/candidates.json（source="vlm"）
"""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np

from ..utils.image_io import imread
from .extractor import load_index
from .variants import VariantMap

TILE = 68
COLS, ROWS = 4, 10          # 每批 40 簇
N_REPS = 3                  # 每簇展示成员数


def make_sheets(book_out_dir: str | Path, out_dir: str | Path,
                min_size: int = 4, min_ink: float = 0.08) -> dict:
    """生成识别清单图。返回 mapping（同时写入 out_dir/mapping.json）。"""
    book = Path(book_out_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    inst = {i.id: i for i in load_index(book / "phase4_chars")}
    with open(book / "phase5_clusters" / "clusters.json", encoding="utf-8") as f:
        clusters = json.load(f)["clusters"]

    good = []
    for c in clusters:
        if c["size"] < min_size:
            continue
        ms = [inst[m] for m in c["members"] if m in inst]
        if not ms or float(np.mean([m.ink_ratio for m in ms])) < min_ink:
            continue
        good.append(c)
    good.sort(key=lambda c: -c["size"])

    def load_patch(iid):
        img = imread(str(book / "phase4_chars" / inst[iid].patch_path))
        if img is None:
            return np.full((TILE, TILE), 255, np.uint8)
        if img.ndim == 3:
            img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return cv2.resize(img, (TILE, TILE), interpolation=cv2.INTER_AREA)

    cell_w = 30 + N_REPS * TILE + 12
    cell_h = TILE + 8
    per_batch = COLS * ROWS
    batches = [good[i:i + per_batch] for i in range(0, len(good), per_batch)]
    mapping: dict = {}
    for bi, batch in enumerate(batches, 1):
        canvas = np.full((ROWS * cell_h + 8, COLS * cell_w + 8, 3), 255,
                         np.uint8)
        bmap = {}
        for k, c in enumerate(batch):
            r, col = divmod(k, COLS)
            x0, y0 = 8 + col * cell_w, 8 + r * cell_h
            cv2.putText(canvas, str(k + 1), (x0, y0 + 44),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            reps = list(dict.fromkeys(c["reps"] + c["members"]))[:N_REPS]
            for j, iid in enumerate(reps):
                canvas[y0:y0 + TILE,
                       x0 + 30 + j * TILE:x0 + 30 + (j + 1) * TILE] = \
                    cv2.cvtColor(load_patch(iid), cv2.COLOR_GRAY2BGR)
            bmap[str(k + 1)] = {"cluster": c["cluster_id"], "size": c["size"]}
        cv2.imwrite(str(out / f"batch_{bi:02d}.png"), canvas)
        mapping[f"batch_{bi:02d}"] = bmap
    with open(out / "mapping.json", "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False)
    return mapping


def parse_spec(spec: str | None) -> list[tuple[str, float, bool]]:
    """识别语法 → [(char, p, surface_uncertain)]。None → []。"""
    if not spec:
        return []
    low = spec.endswith("~")
    spec = spec.rstrip("~")
    chars = [c for c in spec.split("|") if c]
    if not chars:
        return []
    if len(chars) == 1:
        ps = [0.55 if low else 0.9]
    else:
        ps = ([0.5, 0.3] if low else [0.6, 0.3])[:len(chars)]
        ps += [0.15] * (len(chars) - len(ps))
    return [(c, p, low) for c, p in zip(chars, ps)]


def import_recognitions(book_out_dir: str | Path, sheets_dir: str | Path,
                        variant_map: VariantMap | None = None) -> dict:
    """mapping.json + recognitions.json → phase6_labels/candidates.json。"""
    book = Path(book_out_dir)
    sheets = Path(sheets_dir)
    vm = variant_map or VariantMap.load()
    with open(sheets / "mapping.json", encoding="utf-8") as f:
        mapping = json.load(f)
    with open(sheets / "recognitions.json", encoding="utf-8") as f:
        recs = json.load(f)
    with open(book / "phase5_clusters" / "clusters.json", encoding="utf-8") as f:
        size_of = {c["cluster_id"]: c["size"]
                   for c in json.load(f)["clusters"]}

    out = []
    n_ok = n_junk = 0
    for bname, bmap in mapping.items():
        brec = recs.get(bname, {})
        for num, info in bmap.items():
            cands = [{"char": ch, "semantic": vm.semantic(ch), "p": p,
                      "sources": ["vlm"], "surface_uncertain": unc}
                     for ch, p, unc in parse_spec(brec.get(num))]
            if cands:
                n_ok += 1
            else:
                n_junk += 1
            out.append({"cluster_id": info["cluster"],
                        "size": size_of.get(info["cluster"], 0),
                        "candidates": cands})

    phase6 = book / "phase6_labels"
    phase6.mkdir(parents=True, exist_ok=True)
    with open(phase6 / "candidates.json", "w", encoding="utf-8") as f:
        json.dump({"sources": ["vlm"], "clusters": out}, f,
                  ensure_ascii=False, indent=1)
    covered = sum(c["size"] for c in out if c["candidates"])
    return {"recognized": n_ok, "junk": n_junk, "instances_covered": covered}
