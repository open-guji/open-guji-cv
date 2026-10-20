"""构建 hanzi 库、发布、上传 R2、跑验收（总设计 §7、B7）。

    python scripts/build_hanzi_db.py --fetch [--zi-dir DIR]   # 下载缺的原始资料，构建并发布到 config/hanzi/
    python scripts/build_hanzi_db.py --check --report out.json  # 对当前清单跑 A1 重放、A2 覆盖、A4 速度
    GUJI_DATA_TOKEN=$GUJI_DATA_TOKEN_PROD python scripts/build_hanzi_db.py --no-build --upload

- 原始资料 `$GUJI_DATA_HOME/_shared/hanzi/src/`（`--src` 可改），不进 git，`--upload` 时按 sha 进 R2；
- 构建产出先落 `$GUJI_DATA_HOME/_shared/hanzi/build/`，再发布：核心包 tsv 与清单写进本仓
  `config/hanzi/`（进 git），部件包 tsv 放本机 blob 缓存；`--upload` 把清单里的全部文件和原始资料
  经 guji-data Worker 传进 R2 正式桶（按 sha、txt 后缀，已有跳过；要正式令牌）；
- `--zi-dir` 给字统网缓存目录（`U+XXXX.json`）：先把其中的族汇总进原始资料 `zi-families.jsonl`。
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
from open_guji_cv.hanzi import schema as S
from open_guji_cv.hanzi.build import (
    ZI_FILE,
    build,
    data_root,
    fetch_sources,
    publish,
    zi_jsonl,
)
from open_guji_cv.hanzi.pack import read_manifest


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


def upload(src: Path) -> dict:
    """清单里的全部文件（核心包、部件包、形近对表）与原始资料 → R2 正式桶（txt 后缀，按 sha，已有跳过）。"""
    from open_guji_cv.datastore.r2 import upload_files
    from open_guji_cv.hanzi.build import sha256_file
    from open_guji_cv.hanzi.pack import Pack
    pk = Pack()
    files = {f["sha256"]: pk._file(k, f) for k, f in pk.manifest["files"].items()}
    for name, f in pk.manifest["raw"].items():
        p = src / name
        if p.exists() and sha256_file(p) == f["sha256"]:
            files[f["sha256"]] = p
        else:
            print(f"  原始资料 {name} 本机没有或 sha 对不上，跳过")
    return upload_files({k: str(v) for k, v in files.items()}, bucket="main", ext="txt")


def upload_emb() -> dict:
    """`config/hanzi/emb/` 里各版向量包的文件（本机 blob 缓存里有的）→ R2 正式桶（按 sha，已有跳过）。

    向量文件是二进制（`.npy`），Worker 目前只签 png／txt 两种后缀，按用户 10-19 定先一律走 txt 后缀；
    内容按 sha 核，后缀只决定 content-type，下载方（`hanzi.pack.get_blob`）按字节读、核 sha。"""
    from open_guji_cv.clustering.emb_pack import manifests
    from open_guji_cv.datastore.r2 import upload_files
    from open_guji_cv.hanzi.pack import blob_cache_path
    files = {}
    for m in manifests():
        for name, f in m["files"].items():
            p = blob_cache_path(f["sha256"])
            if p.exists():
                files[f["sha256"]] = str(p)
            else:
                print(f"  {m['version']}/{name} 本机没有，跳过")
    return upload_files(files, bucket="main", ext="txt")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=None, help="原始资料目录（缺省 <库根>/src）")
    ap.add_argument("--fetch", action="store_true", help="先下载缺的原始资料")
    ap.add_argument("--zi-dir", type=Path, default=None, help="字统网缓存目录，汇总进原始资料（可选）")
    ap.add_argument("--no-build", action="store_true", help="不构建，用 config/hanzi 里的当前清单")
    ap.add_argument("--upload", action="store_true", help="把当前版的文件与原始资料传进 R2 正式桶")
    ap.add_argument("--upload-emb", action="store_true", help="把 config/hanzi/emb/ 各版向量包的文件传进 R2")
    ap.add_argument("--check", action="store_true", help="跑 A1 重放、A2 覆盖、A4 速度")
    ap.add_argument("--report", type=Path, default=None, help="检查结果写到这个 json")
    args = ap.parse_args()

    root = data_root()
    src = args.src or root / "src"
    if args.fetch:
        got = fetch_sources(src)
        print(f"下载 {len(got)} 个：{got}")
    if args.zi_dir:
        print(f"字统网派生族 {zi_jsonl(args.zi_dir, src / ZI_FILE)} 字 → {src / ZI_FILE}")
    if not args.no_build:
        t0 = time.time()
        m = build(src, REPO / "config", root / "build")
        publish(root / "build", REPO, root / "blobs")
        print(f"{m['version']}  构建 {time.time() - t0:.1f} 秒，发布到 config/hanzi/")
        for k, f in m["files"].items():
            print(f"  {f['pack']:5s} {k:22s} {f['rows']:>9,d} 行 {f['bytes'] / 1e6:6.1f} MB")
        if m["stats"]["missing"]:
            print(f"  缺原始资料：{m['stats']['missing']}")
    if args.upload:
        print("上传 R2：", upload(src))
    if args.upload_emb:
        print("上传向量包：", upload_emb())
    if not args.check:
        return
    m = read_manifest()
    t0 = time.perf_counter()
    db = HanziDB.open(parts=True)
    open_s = round(time.perf_counter() - t0, 2)
    rep = {"version": db.version, "open_s（含首次灌库）": open_s,
           "A1_variants": check_variants(db, REPO / "config" / "variants" / "variants.json"),
           "A2_pivot": check_pivot(db, REPO / "research" / "pivot_family" / "rows.jsonl.gz"),
           "sizes_mb": {p: round(db._pack.db_path(p).stat().st_size / 1e6, 1) for p in S.PACKS},
           "rows": {k: f["rows"] for k, f in m["files"].items()}}
    sample = [r[0] for r in db.con.execute("SELECT ch FROM parts.chars ORDER BY cp")][::50][:2000]
    rep["A4_bench"] = bench(db, sample)
    text = json.dumps(rep, ensure_ascii=False, indent=1)
    if args.report:
        args.report.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
