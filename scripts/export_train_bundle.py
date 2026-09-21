# -*- coding: utf-8 -*-
"""把本机才有的训练/评测数据打成一个包，给没有工作区的机器（云端会话）用。

    PYTHONIOENCODING=utf-8 .venv/Scripts/python scripts/export_train_bundle.py \
        [--out cache/train_bundle.zip]

设计稿 §11 #4：云端唯一缺的就是**真刻例与靶子**。包里只放已经存在的两个目录
（都是 64² 归一化图 + items.jsonl，不含原图、不含库文件）：

- `cache/glyph_bench/`  seen_train / seen_test / unseen 三档真刻例（`build_glyph_bench.py` 建）
- `cache/oov_bench/`    类外真刻例 314 条（`build_oov_bench.py` 建）

外加一个 `manifest.json`（各档条数、字种数、checkpoint 指纹、建包时间）。
几十 MB 量级。**不进 git**（大文件纪律），随实验分支传或直接拷。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DIRS = ("cache/glyph_bench", "cache/oov_bench")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="cache/train_bundle.zip")
    a = ap.parse_args()

    manifest: dict = {"built_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "dirs": {}}
    try:
        from open_guji_cv.clustering.cnn_candidates import DEFAULT_CKPT, fingerprint
        manifest["ckpt"] = {"path": str(DEFAULT_CKPT), "fingerprint": fingerprint()}
    except Exception:
        pass
    n_files = 0
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for d in DIRS:
            p = Path(d)
            if not p.exists():
                print(f"跳过 {d}：不存在（先跑 build_glyph_bench.py / build_oov_bench.py）")
                continue
            items = p / "items.jsonl"
            rows = [json.loads(l) for l in items.read_text(encoding="utf-8").splitlines() if l.strip()] \
                if items.exists() else []
            manifest["dirs"][d] = {
                "items": len(rows), "chars": len({r.get("char") for r in rows}),
                "splits": dict(Counter(r.get("split") or r.get("src") or "?" for r in rows)),
            }
            for f in p.rglob("*"):
                if f.is_file():
                    z.write(f, f.as_posix()); n_files += 1
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    print(json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"→ {out}  {n_files} 个文件  {out.stat().st_size/1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
