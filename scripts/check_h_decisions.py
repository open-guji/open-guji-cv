# -*- coding: utf-8 -*-
"""看图判读文件校验：检查 index_batchNN.json 与 decisions_batchNN.json 是否对得上。

用法：python scripts/check_h_decisions.py <目录>

目录里每个 index_batchNN.json 配一个同号的 decisions_batchNN.json。检查：
1. decisions 的 actor 必须是「整理看图」；
2. index 里每个 cell 恰好出现在 confirmed 或 unsure 其一（不漏、不在两处、不重复）；
   decisions 里不许有 index 没列的 cell；
3. decisions 里的 default 与 index 的 default_char 一致；
4. confirmed 里 kind 只能是 same / variant_identity / differs；
   kind == same 时 char == default，kind != same 时 char != default。

全部通过：退出 0，打印「N 格确定／M 格不确定」。有问题：逐条打印，退出 1。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ACTOR = "整理看图"
KINDS = {"same", "variant_identity", "differs"}


def check_batch(index: list[dict], decisions: dict) -> tuple[list[str], int, int]:
    """返回 (问题列表, 确定格数, 不确定格数)。"""
    errors: list[str] = []
    if decisions.get("actor") != ACTOR:
        errors.append(f"actor 应为「{ACTOR}」，实为 {decisions.get('actor')!r}")

    confirmed = decisions.get("confirmed", {})
    unsure = decisions.get("unsure", {})

    seen: dict[str, dict] = {}
    for item in index:
        cell = item["cell"]
        if cell in seen:
            errors.append(f"index 里 cell {cell} 重复出现")
        seen[cell] = item

    for cell, item in seen.items():
        hits = (cell in confirmed) + (cell in unsure)
        if hits == 0:
            errors.append(f"cell {cell} 在 confirmed 与 unsure 里都没有（漏格）")
        elif hits > 1:
            errors.append(f"cell {cell} 同时出现在 confirmed 与 unsure（重复判定）")

    for cell in list(confirmed) + list(unsure):
        if cell not in seen:
            errors.append(f"cell {cell} 不在 index 里（多出的格）")

    for cell, entry in confirmed.items():
        if cell not in seen:
            continue
        want = seen[cell]["default_char"]
        if entry.get("default") != want:
            errors.append(f"cell {cell} default={entry.get('default')!r} 与 index 的 {want!r} 不一致")
        kind = entry.get("kind")
        if kind not in KINDS:
            errors.append(f"cell {cell} kind={kind!r} 不在 {sorted(KINDS)} 里")
        elif kind == "same" and entry.get("char") != entry.get("default"):
            errors.append(f"cell {cell} kind=same 但 char≠default")
        elif kind != "same" and entry.get("char") == entry.get("default"):
            errors.append(f"cell {cell} kind={kind} 但 char==default")

    for cell, entry in unsure.items():
        if cell in seen and entry.get("default") != seen[cell]["default_char"]:
            errors.append(
                f"cell {cell} default={entry.get('default')!r} 与 index 的 "
                f"{seen[cell]['default_char']!r} 不一致"
            )

    n_sure = sum(1 for c in confirmed if c in seen)
    n_unsure = sum(1 for c in unsure if c in seen)
    return errors, n_sure, n_unsure


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    root = Path(argv[1])
    indexes = sorted(root.glob("index_batch*.json"))
    if not indexes:
        print(f"{root} 下没有 index_batch*.json")
        return 1

    all_errors: list[str] = []
    total_sure = total_unsure = 0
    for idx_path in indexes:
        m = re.fullmatch(r"index_batch(\d+)\.json", idx_path.name)
        if not m:
            continue
        dec_path = root / f"decisions_batch{m.group(1)}.json"
        if not dec_path.exists():
            all_errors.append(f"{idx_path.name} 缺少配对的 {dec_path.name}")
            continue
        index = json.loads(idx_path.read_text(encoding="utf-8"))
        decisions = json.loads(dec_path.read_text(encoding="utf-8"))
        errors, n_sure, n_unsure = check_batch(index, decisions)
        all_errors += [f"[batch{m.group(1)}] {e}" for e in errors]
        total_sure += n_sure
        total_unsure += n_unsure

    if all_errors:
        for e in all_errors:
            print("✗", e)
        return 1
    print(f"{total_sure} 格确定／{total_unsure} 格不确定")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
