# -*- coding: utf-8 -*-
"""从真字形库抽一个小样本库，留在引擎仓供测试。

    python scripts/make_sample_store.py --src <真库 glyph_store> --chars 200

## 为什么要这个

《四庫全書總目》的全部数据（含 16,557 条刻例的字形库）已迁到
`siku-zongmu-workspace` 私有仓。引擎仓不该自带某本书的完整数据，
但完全没有库又跑不了测试——于是留一个结构完整、体积很小的样本。

**样本库只用来跑测试，不用来跑真书。** 真书走 `GUJI_WORKSPACE`。

## 库的结构（照实测，别照猜）

| 文件 | 主键 | 说明 |
|---|---|---|
| `glyphs.jsonl` | `(char, edition_tag)` | 字头 |
| `exemplars.jsonl` | `instance_id` | 哪些实例被选为该字头的刻例 |
| `admissions.jsonl` | `instance_id` | 进库裁决与证据 |
| `instances/<source>.jsonl` | `instance_id` | 实例本身（bbox、label、来源页） |
| `patches/<instance_id 冒号换下划线>.png` | — | 刻例图 |

抽样按**字头**抽，一个字头连它的全部刻例一起搬——否则几个 jsonl 互相对不上，
库的自洽性就坏了（`audit_glyph_consistency` 会满屏报错）。
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
from collections import defaultdict
from pathlib import Path


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(ln) for ln in io.open(p, encoding="utf-8") if ln.strip()]


def write_jsonl(p: Path, rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with io.open(p, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def patch_name(instance_id: str) -> str:
    return instance_id.replace(":", "_") + ".png"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="真库 glyph_store 目录")
    ap.add_argument("--dst", default="output/glyph_store", help="样本库输出目录")
    ap.add_argument("--chars", type=int, default=150, help="抽多少个字头")
    ap.add_argument("--max-per-char", type=int, default=6,
                    help="每个字头最多留几条刻例。头部字头刻例极多（「其」有 222 条），"
                         "全留会让样本库涨到几十 MB；测匹配有 3~6 条可比就够")
    a = ap.parse_args()

    src, dst = Path(a.src), Path(a.dst)
    if not (src / "glyphs.jsonl").exists():
        print(f"✗ {src} 不像字形库（没有 glyphs.jsonl）")
        return 1

    glyphs = load_jsonl(src / "glyphs.jsonl")
    exemplars = load_jsonl(src / "exemplars.jsonl")
    admissions = load_jsonl(src / "admissions.jsonl")

    # 按 (char, edition_tag) 聚刻例，优先抽刻例多的字头
    by_key: dict = defaultdict(list)
    for e in exemplars:
        by_key[(e.get("char"), e.get("edition_tag"))].append(e)
    ranked = sorted(glyphs, key=lambda g: -len(by_key.get((g.get("char"), g.get("edition_tag")), [])))
    keep = ranked[:a.chars]
    keep_keys = {(g.get("char"), g.get("edition_tag")) for g in keep}

    # 每字头截断：头部字头刻例极多，全留会让样本库涨到几十 MB
    keep_ex = []
    for k in keep_keys:
        keep_ex.extend(by_key.get(k, [])[:a.max_per_char])
    keep_iids = {e.get("instance_id") for e in keep_ex}
    keep_adm = [r for r in admissions if r.get("instance_id") in keep_iids]

    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    write_jsonl(dst / "glyphs.jsonl", keep)
    write_jsonl(dst / "exemplars.jsonl", keep_ex)
    write_jsonl(dst / "admissions.jsonl", keep_adm)
    for name in ("sources.jsonl", "pairs.jsonl", "_snapshot.json"):
        if (src / name).exists():
            shutil.copy2(src / name, dst / name)

    # instances：每个 source 一份，只留被选中的实例
    n_inst = 0
    for sp in sorted((src / "instances").glob("*.jsonl")) if (src / "instances").is_dir() else []:
        rows = [r for r in load_jsonl(sp) if r.get("instance_id") in keep_iids]
        if rows:
            write_jsonl(dst / "instances" / sp.name, rows)
            n_inst += len(rows)

    # patches：文件名是 instance_id 把冒号换成下划线
    n_img = 0
    for iid in keep_iids:
        f = src / "patches" / patch_name(iid)
        if f.exists():
            (dst / "patches").mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst / "patches" / f.name)
            n_img += 1

    io.open(dst / "README.md", "w", encoding="utf-8").write(
        "# 样本字形库（**不是真库**）\n\n"
        f"从《四庫全書總目》真库抽的 {len(keep)} 个字头 / {len(keep_ex)} 条刻例 / "
        f"{n_img} 张图，**只用来跑测试**。\n\n"
        "真库（2,664 字头 / 16,557 刻例）在 `siku-zongmu-workspace` 私有仓。\n"
        "跑真书要设：\n\n```bash\nexport GUJI_WORKSPACE=/path/to/siku-zongmu-workspace\n```\n\n"
        "重新生成：\n\n```bash\npython scripts/make_sample_store.py \\\n"
        "  --src /path/to/siku-zongmu-workspace/output/glyph_store --chars 200\n```\n"
    )

    size = sum(f.stat().st_size for f in dst.rglob("*") if f.is_file())
    print(f"✓ 样本库：{len(keep)} 字头 / {len(keep_ex)} 刻例 / {n_inst} 实例 / "
          f"{n_img} 图 / {size/1024/1024:.1f} MB → {dst}")
    if n_img < len(keep_ex) * 0.9:
        print(f"⚠️ 图只搬到 {n_img}/{len(keep_ex)}，检查 patches 命名约定是否变了")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
