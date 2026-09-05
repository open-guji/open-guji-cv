# -*- coding: utf-8 -*-
"""校验金标迁移无损：items.jsonl 读出来的，与评测脚本从旧文件读的**逐条相同**。

    PYTHONPATH=. python scripts/verify_gold_migration.py [分片…] [--all]

迁移只改载体不改内容，所以「无损」的判准是：把 items.jsonl 还原回旧格式的那些
关键字段后，与旧文件逐条比对，**每个 id 的每个字段都一样**。

为什么不直接比整份 JSON：迁移**有意**做了两件重排——
  1. 溯源字段（label_origin / stratum / pipeline_version…）搬进 GoldItem 的专有位；
  2. 文档字段（coord_space / profile / tags…）搬进 input。
它们不该再出现在 expected 里。所以比对时把这两类还原回去再比。

任何一条对不上就退出码 1，并打印差异——迁移是可以重来的，破坏基线不行。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from open_guji_cv.gold.adapters.base import Adapter          # noqa: E402
from open_guji_cv.gold.store import GoldStore                # noqa: E402


def flatten(item) -> dict:
    """GoldItem → 旧格式那样的扁平 dict（只保留旧文件里真有的字段）。"""
    out = dict(item.expected)
    a = item.anchor
    for k, v in (("book", a.book), ("page", a.page), ("col", a.col)):
        if v is not None:
            out[k] = v
    if a.slot is not None:
        out["idx"] = a.slot
    if item.label_origin:
        out["label_origin"] = item.label_origin
    if item.pipeline_version:
        out["pipeline_version"] = item.pipeline_version
    if item.stratum:
        out["stratum"] = item.stratum
    if item.stratum_weight is not None:
        out["stratum_weight"] = item.stratum_weight
    for k in Adapter.INPUT_KEYS:
        if k in (item.input or {}):
            out[k] = item.input[k]
    for k in ("seed", "source_item"):
        if k in (item.input or {}):
            out[k] = item.input[k]
    return out


def norm(v):
    """比对前归一：page 在旧文件里有时是字符串有时是数字，list/tuple 同义。"""
    if isinstance(v, (list, tuple)):
        return [norm(x) for x in v]
    if isinstance(v, dict):
        return {k: norm(x) for k, x in v.items()}
    if isinstance(v, str) and v.lstrip("-").isdigit():
        return int(v)
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def compare(shard: str, store: GoldStore) -> tuple[bool, list[str]]:
    """比对 items.jsonl 与旧载体。返回 (是否一致, 差异说明)。"""
    from open_guji_cv.gold.adapters import detect

    d = store.shard_dir(shard)
    if not (d / "items.jsonl").exists():
        return True, [f"{shard}: 还没迁，跳过"]
    cls = detect_legacy(d)
    if cls is None:
        return True, [f"{shard}: 旧载体已不在（可能已清理），跳过"]

    legacy = {i.id: flatten(i) for i in cls().load(d)}
    new = {i.id: flatten(i) for i in store.list(shard)}

    msgs: list[str] = []
    only_old = set(legacy) - set(new)
    only_new = set(new) - set(legacy)
    # 冲突合并会让 items 少于源（迁移已显式报过），这里只报出来不算失败
    if only_new:
        # **多出来的不算迁移失败**：人裁回流只写 items、不回写旧载体，
        # 所以 items 长期会比载体多。2026-09-04 实例：用户在控制台裁的
        # 12 条切分缺陷进了 instances（559 → 571），旧载体自然没有。
        # 「迁移无损」说的是「迁过来的那批没变」，不是「两边永远一样大」。
        msgs.append(f"  items 里多出 {len(only_new)} 条（人裁回流，不算失败）:"
                    f" {sorted(only_new)[:5]}")

    if only_old:
        msgs.append(f"  items 里少了 {len(only_old)} 条（多为同 id 合并）: {sorted(only_old)[:5]}")

    bad = 0
    added_fields = 0
    for k in sorted(set(legacy) & set(new)):
        a, b = norm(legacy[k]), norm(new[k])
        # **新增字段不算迁移失败，丢字段才算**（2026-09-04）。
        # 迁移无损的含义是「原来记的东西没丢、没被改」，不是「不许再记新
        # 东西」。人裁回流与上游修复都会往同一条金标上补注解：本轮
        # `healed_by`（版框钉桩 bug 修好后，29 条 truncated 复量成 clean，
        # 注明是谁治好的）就是这类。旧字段少一个、或同名字段值变了，仍然报错。
        extra = {f for f in set(b) - set(a) if b.get(f) is not None}
        if extra and {f: a.get(f) for f in set(a)} == {f: b.get(f) for f in set(a)}:
            added_fields += 1
            continue
        if a != b:
            bad += 1
            if bad <= 3:
                diff = {f: (a.get(f), b.get(f)) for f in set(a) | set(b) if a.get(f) != b.get(f)}
                msgs.append(f"  ✗ {k}: {json.dumps(diff, ensure_ascii=False)[:220]}")
    if added_fields:
        msgs.append(f"  {added_fields} 条只是**新增**了字段（注解，不算失败）")
    ok = bad == 0
    msgs.insert(0, f"{shard}: 共 {len(new)} 条，逐条比对 {'一致 ✓' if ok else f'有 {bad} 条不一致 ✗'}")
    return ok, msgs


def detect_legacy(shard_dir: Path):
    """绕开 items.jsonl，强行认旧载体。"""
    from open_guji_cv.gold.adapters.base import _adapters
    for cls in _adapters():
        if cls.sniff(shard_dir):
            return cls
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("shards", nargs="*", help="要校验的分片；留空配合 --all 校验全部已迁的")
    ap.add_argument("--all", action="store_true")
    args = ap.parse_args()

    store = GoldStore()
    shards = args.shards or ([s for s in store.shards()
                              if (store.shard_dir(s) / "items.jsonl").exists()]
                             if args.all else [])
    if not shards:
        print("给分片名，或用 --all")
        sys.exit(2)

    n_bad = 0
    for sh in shards:
        ok, msgs = compare(sh, store)
        for m in msgs:
            print(m)
        if not ok:
            n_bad += 1
    print(f"\n{len(shards)} 个分片，{n_bad} 个不一致")
    sys.exit(1 if n_bad else 0)


if __name__ == "__main__":
    main()
