"""把「只因软参数改制而过期」的产物记录迁到新指纹（一次性，2026-09-25）。

`StepSpec.soft_params` 上线后（`glyph_match.db_fingerprint`），`params_hash` 不再含
软参数，凡是之前跑的产物指纹都对不上了——产物本身一字未变。逐页：用**旧算法**
（软参数取产物里记的那个值、一起进 `params_hash`）重算指纹，与 manifest 最新条目
相等（= 除了软参数改制什么都没变）才追加一条改成新指纹的副本，并把当时的软参数值
记进 `soft`（`status` 据此报漂移）；对不上的（代码/参数/上游真变了）一律不动。

    python scripts/migrate_soft_params.py bxgb -w <workspace> [--old-rev 2f0b349812] [--apply]

`--old-rev`：改制这一刀本身改了 `steps/glyph_match.py`（加 `soft_params`、改文档），
代码哈希跟着变。给了它，旧指纹按**那个 rev 的源码**算代码哈希（行尾归一，同
`engine._module_source_hash`）——等于宣称「那个 rev 到现在，这一步的判决逻辑没动」，
所以只在 `git diff <rev> -- <该步及 code_deps>` 确认只有软参数改制时用。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("book")
    ap.add_argument("-w", "--workspace", required=True)
    ap.add_argument("--pipeline", default=None, help="缺省按册的 edition 选默认管线")
    ap.add_argument("--apply", action="store_true", help="不给只试算")
    ap.add_argument("--old-rev", default=None, help="旧指纹按这个 git rev 的源码算代码哈希")
    a = ap.parse_args()
    os.environ["GUJI_WORKSPACE"] = str(Path(a.workspace).resolve())

    from open_guji_cv.core import engine as E
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.pipeline import default_pipeline_id, load_pipeline
    from open_guji_cv.core.step import STEPS
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.manifest import ManifestEntry
    from open_guji_cv.products.store import ProductStore
    import open_guji_cv.steps, open_guji_cv.gates  # noqa: F401,E401  注册 STEPS

    bk = load_book(a.book)
    pl = load_pipeline(a.pipeline or default_pipeline_id(bk))
    store = ProductStore()
    eng = E.Engine(bk, pl, store, ImageCache())

    def fp_of(step, ph: str, upstream: dict) -> str:
        payload = {**E._self_payload(step, bk, ph), "upstream": upstream}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]

    import importlib
    import inspect
    import subprocess
    repo = Path(__file__).resolve().parent.parent

    def old_fp_of(step, ph: str, upstream: dict) -> str:
        """旧指纹：代码哈希按 `--old-rev` 的源码算（没给就是现在的源码）。"""
        if not a.old_rev:
            return fp_of(step, ph, upstream)
        saved = dict(E._code_hash_cache)
        try:
            for m in [type(step).__module__, *step.spec.code_deps]:
                rel = Path(inspect.getsourcefile(importlib.import_module(m))).resolve().relative_to(repo)
                raw = subprocess.run(["git", "show", f"{a.old_rev}:{rel.as_posix()}"], cwd=repo,
                                     capture_output=True, check=True).stdout
                E._code_hash_cache[m] = hashlib.sha256(E._normalize_eol(raw)).hexdigest()
            return fp_of(step, ph, upstream)
        finally:
            E._code_hash_cache.clear()
            E._code_hash_cache.update(saved)

    total_ok = total_skip = 0
    for sid in pl.steps:
        step = STEPS[sid]
        soft = step.spec.soft_params
        if not soft:
            continue
        params = eng.ctx.params_for(step)
        new_ph = E.params_hash(params, soft)
        new_self = E.self_hash(step, bk, params)
        man = store.manifest(bk.id, sid)
        n_ok = n_new = n_skip = 0
        reasons: dict[str, int] = {}
        for key, ent in sorted(man.all().items()):
            if ent.status != "ok" or not key.startswith("p"):
                continue
            if ent.params_hash == new_ph and ent.soft is not None:
                n_new += 1                      # 已是新制
                continue
            prod = store.read(bk.id, sid, key, step.spec.produces[0])
            if prod is None:
                reasons["无产物"] = reasons.get("无产物", 0) + 1
                n_skip += 1
                continue
            old_vals = {k: getattr(prod, k, None) for k in soft}
            if any(v in (None, "") for v in old_vals.values()):
                reasons["产物没记软参数值"] = reasons.get("产物没记软参数值", 0) + 1
                n_skip += 1
                continue
            old_ph = E.params_hash(params.model_copy(update=old_vals))
            if old_ph != ent.params_hash:
                reasons["其余参数变了"] = reasons.get("其余参数变了", 0) + 1
                n_skip += 1
                continue
            if old_fp_of(step, old_ph, ent.upstream) != ent.fingerprint:
                reasons["代码/版本/册配置变了"] = reasons.get("代码/版本/册配置变了", 0) + 1
                n_skip += 1
                continue
            n_ok += 1
            if a.apply:
                man.put(ManifestEntry(**{
                    **asdict(ent), "params_hash": new_ph, "self_hash": new_self,
                    "fingerprint": fp_of(step, new_ph, ent.upstream),
                    "soft": {k: str(v) for k, v in old_vals.items()}, "ts": time.time()}))
        total_ok += n_ok
        total_skip += n_skip
        print(f"{sid}: 迁 {n_ok}  已是新制 {n_new}  不动 {n_skip}  "
              + "  ".join(f"{k} {v}" for k, v in reasons.items()))
    print(("已写入" if a.apply else "试算（加 --apply 写入）") + f"：迁 {total_ok}，不动 {total_skip}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
