# -*- coding: utf-8 -*-
"""给 2026-09-20 之前写出的 manifest 条目补 `self_hash`，让第一轮重跑就能格级复用。

    python scripts/backfill_self_hash.py <book> -w <workspace> [--steps glyph_match,ocr_candidates,rare_candidates] [--apply]

## 为什么需要它

格级复用（core/reuse.py）第一道闸是「manifest 上一条 `self_hash` == 现在算的」。老条目没有
这个字段，第一轮重跑一格都复用不了——而这一轮正是最贵的那轮（bxgb 全量 45 min）。

## 补的是什么、凭什么

`self_hash` = sha(版本 + 参数 + 代码 + 册配置)。老产物是**老代码**算的，按现在的代码补
`self_hash`，等于宣称「插桩前后代码对产物等价」。这个宣称只对 2026-09-20 加复用插桩那一次
成立（三步各插了 6 行「查表→搬记录→continue」，判决逻辑一行没动，有单测），**别拿这个
脚本去掩盖真正的算法改动**——那种情况产物就该重算。

三条护栏，任一不过就跳过那一页（打印出来，不补）：
- 条目 `status == ok`、没被 `invalidated`；
- 条目 `params_hash` == 现在的参数哈希（参数变了不是等价）；
- 条目 `sha256` == 盘上产物文件的 sha（文件被手改过不认）。

补法与 `migrate_manifest_eol.py` 同：**追加带 `self_hash` 的副本，不改旧行**。
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import open_guji_cv.steps  # noqa: E402,F401
from open_guji_cv.core.book import load_book  # noqa: E402
from open_guji_cv.core.engine import params_hash, self_hash  # noqa: E402
from open_guji_cv.core.step import STEPS  # noqa: E402
from open_guji_cv.products.manifest import ManifestEntry  # noqa: E402
from open_guji_cv.products.store import ProductStore  # noqa: E402

DEFAULT_STEPS = "glyph_match,ocr_candidates,rare_candidates"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("book")
    ap.add_argument("-w", "--workspace", required=True)
    ap.add_argument("--steps", default=DEFAULT_STEPS)
    ap.add_argument("--apply", action="store_true", help="不给只试算")
    a = ap.parse_args()
    import os
    os.environ["GUJI_WORKSPACE"] = str(Path(a.workspace).resolve())
    bk = load_book(a.book)
    store = ProductStore()
    for sid in a.steps.split(","):
        step = STEPS[sid]
        params = step.spec.params()
        ph, sh = params_hash(params), self_hash(step, bk, params)
        man = store.manifest(bk.id, sid)
        n_ok = n_skip = n_has = 0
        for key, e in sorted(man.all().items()):
            if e.self_hash:
                n_has += 1
                continue
            why = None
            if e.status != "ok" or e.invalidated:
                why = f"status={e.status} invalidated={e.invalidated!r}"
            elif e.params_hash != ph:
                why = "参数哈希不同"
            elif e.sha256 and store.sha(bk.id, sid, key) != e.sha256:
                why = "盘上文件与条目 sha 不符"
            if why:
                n_skip += 1
                print(f"  跳过 {sid} {key}: {why}")
                continue
            n_ok += 1
            if a.apply:
                man.put(ManifestEntry(**{**asdict(e), "self_hash": sh}))
        print(f"{sid}: 可补 {n_ok} · 跳过 {n_skip} · 已有 {n_has}" + ("（已写）" if a.apply else "（试算）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
