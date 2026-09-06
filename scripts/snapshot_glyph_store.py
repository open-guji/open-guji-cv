#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""字形库快照：output/glyph.db → output/glyph_store/（真源，进 Git）。

## 为什么不直接提交 glyph.db

SQLite 是二进制，改一个字节就重排页面，git 的 delta 压缩失效——历史里 63 个
版本合计 3.19 GiB，占了仓库九成。而 store 是「15913 个独立 PNG + 逐行 JSONL」，
新进库 200 个字就只多 200 个小文件和 200 行文本，git 只存增量。

## 用法

    python scripts/snapshot_glyph_store.py            # 看有多少变化，够阈值才导
    python scripts/snapshot_glyph_store.py --force    # 无论变化多少都导
    python scripts/snapshot_glyph_store.py --commit   # 导完顺手提交（不推）

阈值：新增实例 ≥ MIN_DELTA，或距上次快照 ≥ MAX_AGE_DAYS。两个都不满足就
不动——避免把「跑了一遍流水线但没新东西」也变成一次提交。

反向（拿到仓库后重建 sqlite）：
    python -m open_guji_cv glyph-db rebuild --store output/glyph_store
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "output" / "glyph.db"
STORE = ROOT / "output" / "glyph_store"
MIN_DELTA = 200          # 新增实例数达到这个量就值得快照
MAX_AGE_DAYS = 14        # 或者距上次快照过了这么久


def _count(db: Path) -> int:
    if not db.exists():
        return 0
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return c.execute("SELECT COUNT(*) FROM instances").fetchone()[0]
    finally:
        c.close()


def _stored() -> tuple[int, float]:
    """store 里已有多少实例、上次快照什么时候。"""
    meta = STORE / "_snapshot.json"
    if meta.exists():
        d = json.loads(meta.read_text(encoding="utf-8"))
        r = subprocess.run(["git", "log", "-1", "--format=%ct", "--",
                            str(meta)], cwd=ROOT, capture_output=True, text=True)
        ts = float(r.stdout.strip()) if r.stdout.strip() else 0.0
        return d.get("instances", 0), ts
    n = sum(1 for f in (STORE / "instances").glob("*.jsonl")
            for _ in f.read_text(encoding="utf-8").splitlines()) if (STORE / "instances").exists() else 0
    return n, 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="不看阈值，直接导")
    ap.add_argument("--commit", action="store_true", help="导完 git add + commit（不推送）")
    a = ap.parse_args()

    if not DB.exists():
        print(f"没有 {DB}——先跑流水线，或从 store 重建", file=sys.stderr)
        return 1

    now, (was, ts) = _count(DB), _stored()
    delta = now - was
    age_days = (time.time() - ts) / 86400 if ts else 1e9
    print(f"库内实例 {now}，上次快照 {was}（+{delta}），距上次 "
          f"{'从未' if not ts else f'{age_days:.1f} 天'}")

    if not a.force and delta < MIN_DELTA and age_days < MAX_AGE_DAYS:
        print(f"变化不够（新增 <{MIN_DELTA} 且未满 {MAX_AGE_DAYS} 天），不快照。"
              f"要强制导用 --force")
        return 0

    from open_guji_cv.clustering.glyph_db import GlyphDB, export_store
    s = export_store(GlyphDB(DB), STORE)
    # 只记实例数，不记时间戳——时间戳会让「内容没变的重导」也产生一次 diff，
    # 正好破坏 store 的幂等性（重导同一个库应当零改动）。上次快照时间改从
    # git log 取。
    (STORE / "_snapshot.json").write_text(
        json.dumps({"instances": s["instances"]}, ensure_ascii=False,
                   indent=1), encoding="utf-8")
    print("导出:", {k: v for k, v in s.items() if k != "bytes"},
          f"{s['bytes'] / 1024 / 1024:.1f} MB")

    if a.commit:
        subprocess.run(["git", "add", "output/glyph_store"], cwd=ROOT, check=True)
        r = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
        if r.returncode == 0:
            print("store 内容没变，不提交")
            return 0
        msg = (f"字形库快照：{s['instances']} 实例（+{delta}）\n\n"
               f"output/glyph.db 不进 Git（二进制，历史 63 版 3.19 GiB）；\n"
               f"真源是本 store，sqlite 用 glyph-db rebuild 重建。\n\n"
               f"Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>")
        subprocess.run(["git", "commit", "-q", "-m", msg], cwd=ROOT, check=True)
        print("已提交（未推送）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
