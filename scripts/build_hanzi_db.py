"""构建 hanzi 库并跑验收（总设计 §7 的 A1–A4）。

    python scripts/build_hanzi_db.py --fetch                 # 下载缺的原始文件，再构建
    python scripts/build_hanzi_db.py                          # 只用本地 src/ 构建
    python scripts/build_hanzi_db.py --check --report out.json   # 构建后跑 A1 重放、A2 覆盖、A4 速度

- 原始文件缓存 `$GUJI_DATA_HOME/_shared/hanzi/src/`（`--src` 可改），不进 git；
- 库落在 `$GUJI_DATA_HOME/_shared/hanzi/hanzi-<内容指纹>/`，`current` 指向最新一版；
- `--zi-dir` 给字统网缓存目录（`U+XXXX.json`），就把其中的族作为 `zi` 来源收进来。
"""
from __future__ import annotations

import argparse
import gzip
import json
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from open_guji_cv.hanzi import HanziDB
from open_guji_cv.hanzi.build import build, data_root, fetch_sources


def _by_tag(s: set) -> dict[str, int]:
    return dict(sorted(Counter(t for *_, t in s).items()))


def check_variants(db: HanziDB, path: Path) -> dict:
    """A1：导出与现役 variants.json 逐对比较。"""
    cur = json.loads(path.read_text(encoding="utf-8"))
    new = db.export_variants_json()
    out: dict = {}
    for part in ("pairs", "directed"):
        old_set = {(a, b, t) for a, bs in cur[part].items() for b, ts in bs.items() for t in ts}
        new_set = {(a, b, t) for a, bs in new[part].items() for b, ts in bs.items() for t in ts}
        only_old = old_set - new_set
        only_new = new_set - old_set
        out[part] = {
            "old": len(old_set), "new": len(new_set), "same": len(old_set & new_set),
            "only_old": len(only_old), "only_new": len(only_new),
            "only_old_by_tag": _by_tag(only_old), "only_new_by_tag": _by_tag(only_new),
            "only_old_sample": ["".join(x[:2]) + ":" + x[2] for x in sorted(only_old)[:30]],
            "only_new_sample": ["".join(x[:2]) + ":" + x[2] for x in sorted(only_new)[:30]],
            "local_missing": sorted("".join(x[:2]) for x in only_old if x[2].startswith("local:")),
        }
    return out


def check_pivot(db: HanziDB, rows_path: Path) -> dict:
    """A2：pivot_family 的 414 条 (p,g) 与 N 档（g 在现役表里无边）——族里有没有 g。"""
    from open_guji_cv.variants import variants_of
    with gzip.open(rows_path, "rt", encoding="utf-8") as f:
        rows = [json.loads(line) for line in f]
    v_rows = [r for r in rows if r.get("pivot") and r["pivot"] != r["g"]]
    res: dict = {"V": {"n": len(v_rows)}, "N": {}}
    for name, srcs in (("all", None), ("legacy", ("v",)), ("rt", ("rt",))):
        hit = sum(1 for r in v_rows if r["g"] in db.pool([r["pivot"]], near_k=0,
                                                          srcs=srcs))
        res["V"][name] = hit
    # N 档：口径同 coverage_sources.py——行上 has_family 为假的 oov/unseen 条（按行计，76 条）；
    # 看新库给不给 g 一个族（不含形近）
    n_rows = [r for r in rows if not r["has_family"] and r["tier"] in ("oov", "unseen")]
    fam_sizes = []
    has = 0
    by_src: dict[str, int] = {}
    for r in n_rows:
        pool = db.pool([r["g"]], near_k=0)
        pool.pop(r["g"], None)
        if pool:
            has += 1
            fam_sizes.append(len(pool))
            for s in {t for e in pool.values() for t in e["src"].split(",")}:
                by_src[s] = by_src.get(s, 0) + 1
    res["N"] = {"rows": len(n_rows), "distinct_g": len({r["g"] for r in n_rows}),
                "g_has_family": has, "by_src": by_src,
                "legacy_variants_of_empty": sum(1 for r in n_rows if not variants_of(r["g"])),
                "family_median": statistics.median(fam_sizes) if fam_sizes else 0}
    return res


def bench(db: HanziDB, chars: list[str]) -> dict:
    """A4：family()／pool() 的单字耗时。"""
    out = {}
    for name, fn in (("family", lambda c: db.family(c)), ("pool", lambda c: db.pool([c])),
                     ("by_components", lambda c: db.by_components(db.components(c)[:2]))):
        ts = []
        for c in chars:
            t = time.perf_counter()
            fn(c)
            ts.append((time.perf_counter() - t) * 1000)
        ts.sort()
        out[name] = {"n": len(ts), "p50_ms": round(ts[len(ts) // 2], 3),
                     "p99_ms": round(ts[int(len(ts) * 0.99) - 1], 3), "max_ms": round(ts[-1], 3)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=None, help="原始文件目录（缺省 <库根>/src）")
    ap.add_argument("--out", type=Path, default=None, help="库根（缺省 $GUJI_DATA_HOME/_shared/hanzi）")
    ap.add_argument("--fetch", action="store_true", help="先下载缺的原始文件")
    ap.add_argument("--zi-dir", type=Path, default=None, help="字统网缓存目录（可选）")
    ap.add_argument("--no-build", action="store_true", help="不构建，只对 current 跑检查")
    ap.add_argument("--check", action="store_true", help="跑 A1 重放、A2 覆盖、A4 速度")
    ap.add_argument("--report", type=Path, default=None, help="检查结果写到这个 json")
    args = ap.parse_args()

    root = args.out or data_root()
    src = args.src or root / "src"
    if args.fetch:
        got = fetch_sources(src)
        print(f"下载 {len(got)} 个：{got}")
    if not args.no_build:
        m = build(src, REPO / "config", root, zi_dir=args.zi_dir)
        print(f"{m['version']}  构建 {m['build_seconds']} 秒")
        for t, info in m["tables"].items():
            print(f"  {t:8s} {info['rows']:>9,d}")
        if m["stats"]["missing"]:
            print(f"  缺原始文件：{m['stats']['missing']}")
    if not args.check:
        return
    t0 = time.perf_counter()
    db = HanziDB.open(root / (root / "current").read_text(encoding="utf-8").strip() / "hanzi.sqlite")
    open_ms = round((time.perf_counter() - t0) * 1000, 1)
    rep = {"version": db.version, "open_ms": open_ms,
           "A1_variants": check_variants(db, REPO / "config" / "variants" / "variants.json"),
           "A2_pivot": check_pivot(db, REPO / "research" / "pivot_family" / "rows.jsonl.gz")}
    sample = [r[0] for r in db.con.execute("SELECT ch FROM chars ORDER BY cp")][::50][:2000]
    rep["A4_bench"] = bench(db, sample)
    text = json.dumps(rep, ensure_ascii=False, indent=1)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
