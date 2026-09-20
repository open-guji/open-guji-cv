"""把「只因行尾翻转而过期」的产物记录迁到行尾归一后的指纹（一次性，2026-09-20）。

`engine._module_source_hash` 改成 CRLF→LF 归一之后，凡是当初在 CRLF 源码下算出来的
指纹都对不上了——产物本身一字未变。逐步逐页：用**旧算法**（原始字节）重算指纹，
与 manifest 最新条目相等（= 除了行尾什么都没变）才追加一条改成新指纹的副本；
对不上的（真过期的）一律不动，让它继续报过期。

    python scripts/migrate_manifest_eol.py bxgb -w D:/workspace/beixing-guben-workspace [--apply]
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import inspect
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
    ap.add_argument("--pipeline", default="keben_body_v2")
    ap.add_argument("--apply", action="store_true", help="不给只试算")
    a = ap.parse_args()
    os.environ["GUJI_WORKSPACE"] = str(Path(a.workspace).resolve())

    from open_guji_cv.core import engine as E
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.pipeline import load_pipeline
    from open_guji_cv.core.step import STEPS
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.manifest import ManifestEntry
    from open_guji_cv.products.store import ProductStore
    import open_guji_cv.steps, open_guji_cv.gates  # noqa: F401,E401  注册 STEPS

    bk, pl = load_book(a.book), load_pipeline(a.pipeline)
    store = ProductStore()
    eng = E.Engine(bk, pl, store, ImageCache())

    import itertools

    def mods_of(step):
        return [type(step).__module__, *step.spec.code_deps]

    def fill_cache(step, variant: dict[str, str] | None):
        """variant=None → 新算法（归一）；否则按每个模块指定的历史行尾形态算旧指纹。
        当初跑产物时源码是 LF 还是 CRLF 已不可考（同一文件被不同工具来回存），
        所以每个模块三种形态都试，任一组合能复现 manifest 里的指纹就算「仅行尾」。"""
        for m in mods_of(step):
            src = inspect.getsourcefile(importlib.import_module(m))
            b = Path(src).read_bytes()
            lf = E._normalize_eol(b)
            if variant is None:
                h = lf
            else:
                h = {"asis": b, "lf": lf, "crlf": lf.replace(b"\n", b"\r\n")}[variant[m]]
            E._code_hash_cache[m] = hashlib.sha256(h).hexdigest()

    def old_fps(step, pg) -> set[str]:
        out = set()
        for combo in itertools.product(("asis", "lf", "crlf"), repeat=len(mods_of(step))):
            E._code_hash_cache.clear(); fill_cache(step, dict(zip(mods_of(step), combo)))
            out.add(eng.fingerprint(step, pg)[0])
        return out

    sids = list(eng._enabled(pl.steps))
    for sid in list(sids):
        g = STEPS[sid].spec.gate
        if g:
            sids.insert(sids.index(sid) + 1, g.id)
    total_mig = total_stale = total_fresh = 0
    for sid in sids:
        step = STEPS[sid]
        mf = store.manifest(bk.id, sid)
        mig = stale = fresh = 0
        for key, ent in mf.all().items():
            if ent.status != "ok" or ent.invalidated or not key.startswith("p"):
                continue
            pg = int(key[1:])
            E._code_hash_cache.clear(); fill_cache(step, None)
            fp_new = eng.fingerprint(step, pg)[0]
            if fp_new is None:
                continue
            if ent.fingerprint == fp_new:
                fresh += 1
            elif ent.fingerprint in old_fps(step, pg):
                mig += 1
                if a.apply:
                    mf.put(ManifestEntry(**{**asdict(ent), "fingerprint": fp_new, "ts": time.time()}))
            else:
                stale += 1
        total_mig += mig; total_stale += stale; total_fresh += fresh
        print(f"{sid:18s} 已新鲜 {fresh:3d}  仅行尾 {mig:3d}{'（已迁）' if a.apply else '（试算）'}  真过期 {stale:3d}")
    print(f"合计：已新鲜 {total_fresh}，仅行尾 {total_mig}，真过期 {total_stale}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
