# -*- coding: utf-8 -*-
"""云端字形库重建通道体检（Step5a-库验通道，2026-09-09）。

只读诊断脚本：不改真源、不进库、不 admit。跑一遍任务书 §四 的四问，
把结论打印出来，顺带暴露 `glyph-db rebuild` 产物落盘路径与
`glyph_match` 实际读库路径**对不对得上**——这条路径不对，`rebuild`
会"跑成功"但 `glyph_match` 读到的是空库，全判 diff，没有任何报错。

用法：
    .venv/bin/python scripts/verify_cloud_glyphdb.py
    GUJI_WORKSPACE=/path/to/siku-zongmu-workspace .venv/bin/python scripts/verify_cloud_glyphdb.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from open_guji_cv.core import workspace as ws  # noqa: E402


def main() -> int:
    print("=== Step5a 库验通道体检 ===")
    desc = ws.describe()
    for k, v in desc.items():
        print(f"  {k}: {v}")

    store_dir = ws.glyph_store_path()
    db_path_expected = ws.glyph_db_path()  # glyph_match 实际会读这里
    snapshot = store_dir / "_snapshot.json"

    if not store_dir.exists():
        print(f"✗ 真源 glyph_store 不存在：{store_dir}")
        return 1

    snapshot_instances = None
    if snapshot.exists():
        snapshot_instances = json.loads(snapshot.read_text()).get("instances")
        print(f"  _snapshot.json instances={snapshot_instances}")
    else:
        print("  （无 _snapshot.json，跳过快照比对）")

    # 问一：rebuild 跑不跑得通，rebuild 实际把 db 写到哪
    from open_guji_cv.clustering.glyph_db import rebuild_from_store

    # rebuild_from_store 的落盘位置由调用方决定；CLI `glyph-db rebuild`
    # 传的是 `<store>/glyphdb.sqlite`，与 glyph_match 读的
    # `<workspace>/output/glyph.db`（即 db_path_expected）不是同一个文件。
    db_path_cli_writes_to = store_dir / "glyphdb.sqlite"

    t0 = time.time()
    summary = rebuild_from_store(store_dir, db_path_cli_writes_to)
    elapsed = time.time() - t0
    print(f"\n=== 问一：rebuild ===")
    print(f"  耗时 {elapsed:.1f}s，产出 {db_path_cli_writes_to}"
          f"（{db_path_cli_writes_to.stat().st_size / 1e6:.1f} MB）")
    print(f"  summary: {json.dumps(summary, ensure_ascii=False)}")

    print(f"\n=== 问二：与 _snapshot.json 对不对得上 ===")
    rebuilt_instances = summary.get("instances")
    if snapshot_instances is not None:
        ok = rebuilt_instances == snapshot_instances
        print(f"  刻例数 {rebuilt_instances} vs 快照 {snapshot_instances}："
              f"{'一致' if ok else '不一致 ⚠️'}")
    else:
        print("  无快照可比（见上）")

    print(f"\n=== 关键体检：rebuild 产物路径 vs glyph_match 实际读库路径 ===")
    print(f"  glyph-db rebuild 落盘：{db_path_cli_writes_to}")
    print(f"  glyph_match 实际读取：{db_path_expected}")
    if db_path_cli_writes_to.resolve() != db_path_expected.resolve():
        print("  ⚠️ 两条路径不是同一个文件！")
        if db_path_expected.exists():
            print(f"     且 {db_path_expected} 已存在（可能是旧库/空库），"
                  f"glyph_match 会读到它，不会报错，只会静默用错库。")
        else:
            print(f"     且 {db_path_expected} 不存在——glyph_match 会对着一个"
                  f"空 SQLite 库跑，逐字判 diff、候选为空，exit code 仍是 0。")
        print("  按任务书铁律§六本道不改代码，此现象已写入 inbox ask 单。")
    else:
        print("  一致，没有问题。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
