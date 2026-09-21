# -*- coding: utf-8 -*-
"""建**类外评测集**：金标字落在 CNN `classes` 之外的真刻例。

## 为什么必须单独建这个集（2026-09-17）

现有全部评测集（`cache/glyph_bench` 的 unseen/seen/mid、`rare-char` 21 条）
**100% 落在 CNN 的 4,654 类内**——实测逐条核过。原因也清楚：
`eval_zero_shot_fusion.py` 的 `--corpus` 默认值与 `train_glyph_cnn.py` 的
是同一份文件，而 bench 本身是从字形库长出来的，字形库又是跑四庫總目攒的。

于是「HOG 被 embedding 完全覆盖」「emb 泛化好」这类结论，
**都只在「CNN 认识那个字」的前提下被验证过**。而我们真正依赖的恰恰是类外：
分类头对类外字 top-1/top-10 都是 **0.0%**，扩字表的收益 100% 由 emb 兑现。

`06-给embedding加独立度量损失.md` 要改的就是 emb 的类外泛化——
没有这个集，做完了也说不清有没有变好。

## 样本来源（都是**真刻例**，不掺字体渲染）

1. **字形库 `instances`**，`sources.kind='woodblock'` 且 `label` 非空；
2. **用户裁决** `feedback/events/*.jsonl` 的 `actor=user, kind=confirm`
   （`payload.reading`/`shape`），图块取 `cache/<book>/char_patch/`。

两路都过 `config/crop_exclusions.jsonl`（坏图块一律排除，2026-08-25 用户定的口径）。

输出 `cache/oov_bench/items.jsonl`，每行 `{char, png, src, book, id}`，
`png` 是落盘的 64×64 归一化图（与 `normalize_patch` 同口径，评测时直接读）。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OUT = Path("cache/oov_bench")


def _classes() -> set[str]:
    import torch
    from open_guji_cv.clustering.cnn_candidates import DEFAULT_CKPT
    return set(torch.load(DEFAULT_CKPT, map_location="cpu",
                          weights_only=False)["classes"])


def _exclusions() -> set[str]:
    f = Path("config/crop_exclusions.jsonl")
    if not f.exists():
        return set()
    out = set()
    for ln in f.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not ln.strip():
            continue
        try:
            d = json.loads(ln)
        except Exception:
            continue
        for k in ("id", "key", "instance_id"):
            if d.get(k):
                out.add(str(d[k]))
    return out


def from_glyph_db(db: Path, S: set[str], excl: set[str]) -> list[dict]:
    """库里的真刻例。`patch_png` 是 BLOB，直接解码。"""
    import cv2
    if not db.exists():
        return []
    con = sqlite3.connect(str(db))
    cur = con.cursor()
    cur.execute("""select i.instance_id, i.label, i.patch_png, s.edition_tag
                   from instances i join sources s on i.source_id = s.source_id
                   where s.kind = 'woodblock'
                     and i.label is not null and i.label != ''""")
    rows = []
    for iid, label, blob, tag in cur.fetchall():
        if label in S or not blob or str(iid) in excl:
            continue
        img = cv2.imdecode(np.frombuffer(blob, np.uint8), cv2.IMREAD_GRAYSCALE)
        if img is None or img.size == 0:
            continue
        rows.append({"char": label, "img": img, "src": "glyphdb",
                     "book": tag or db.parent.parent.name, "id": str(iid)})
    con.close()
    return rows


def from_user_verdicts(ws: Path, book: str, S: set[str], excl: set[str]) -> list[dict]:
    """用户亲眼裁过的字位——最硬的金标。"""
    from open_guji_cv.clustering.rare_panel import rare_patch
    from open_guji_cv.products.cache import ImageCache
    ev = ws / "feedback" / "events"
    if not ev.exists():
        return []
    gold: dict[str, str] = {}
    for f in sorted(ev.glob("*.jsonl")):
        for ln in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not ln.strip():
                continue
            try:
                d = json.loads(ln)
            except Exception:
                continue
            if d.get("kind") != "confirm" or d.get("actor") != "user":
                continue
            k = (d.get("target") or {}).get("key")
            r = (d.get("payload") or {}).get("reading") or (d.get("payload") or {}).get("shape")
            if k and r and len(r) == 1:
                gold[k] = r
    cache = ImageCache(root=ws / "cache")
    rows = []
    for key, ch in gold.items():
        if ch in S or key in excl:
            continue
        parts = key.split(":")
        if len(parts) < 4:
            continue
        img = rare_patch(parts[0], int(parts[1]), int(parts[2]), int(parts[3]), "", cache)
        if img is None:
            continue
        rows.append({"char": ch, "img": img, "src": "user", "book": book, "id": key})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspaces", nargs="*", default=[
        r"D:\workspace\guji-workspace\988g7gsqhd-北行日錄清乾隆道光間長塘鮑氏刊知不足齋叢書之一",
        r"D:\workspace\siku-zongmu-workspace",
    ])
    a = ap.parse_args()
    from open_guji_cv.clustering.normalize import normalize_patch
    import cv2

    S, excl = _classes(), _exclusions()
    print(f"CNN classes {len(S)}，排除名单 {len(excl)}")
    rows: list[dict] = []
    for w in a.workspaces:
        ws = Path(w)
        book = ws.name.split("-")[0]
        g = from_glyph_db(ws / "output" / "glyph.db", S, excl)
        u = from_user_verdicts(ws, book, S, excl)
        print(f"  {ws.name}: 库真刻例 {len(g)}，用户裁决 {len(u)}")
        rows += g + u

    # 同 (char, book, id) 去重；按字种排序让输出稳定
    seen, out = set(), []
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "patches").mkdir(exist_ok=True)
    for r in sorted(rows, key=lambda r: (r["char"], r["src"], r["id"])):
        k = (r["char"], r["book"], r["id"])
        if k in seen:
            continue
        seen.add(k)
        norm = normalize_patch(r["img"])
        name = f"{len(out):05d}.png"
        cv2.imwrite(str(OUT / "patches" / name), (norm * 255).astype(np.uint8))
        out.append({"char": r["char"], "png": f"patches/{name}",
                    "src": r["src"], "book": r["book"], "id": r["id"]})
    (OUT / "items.jsonl").write_text(
        "\n".join(json.dumps(o, ensure_ascii=False) for o in out) + "\n",
        encoding="utf-8")
    kinds = {}
    for o in out:
        kinds[o["src"]] = kinds.get(o["src"], 0) + 1
    print(f"\n写出 {OUT/'items.jsonl'}：{len(out)} 条 / "
          f"{len({o['char'] for o in out})} 字种，来源 {kinds}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
