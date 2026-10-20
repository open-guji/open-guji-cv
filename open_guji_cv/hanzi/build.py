# -*- coding: utf-8 -*-
"""构建：本地原始文件（`src/`）＋本仓 `config/` → 规范 tsv → sqlite → manifest（总设计 §6.1）。

    from open_guji_cv.hanzi.build import build
    manifest = build(src_dir, cfg_dir, out_root)

- 不联网；缺的原始文件先 `fetch_sources(src_dir)`。
- 同一份输入 ⇒ tsv 逐字节相同 ⇒ `content_sha` 相同（验收 A3）。版本目录名 `hanzi-<content_sha>`。
- 原始文件缺了哪个就跳过哪个来源，manifest 的 `missing` 里记下，不报错（测试与轻量构建用）。
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

from . import importers as I
from . import schema as S
from .ids import leaves

BUILDER_VERSION = 1
#: 部件闭包的最大深度（字 → 部件 → 部件的部件…）。
MAX_COMP_DEPTH = 6


def data_root() -> Path:
    home = Path(os.environ.get("GUJI_DATA_HOME") or Path.home() / ".guji-data")
    return home / "_shared" / "hanzi"


def fetch_sources(src_dir: Path, names: list[str] | None = None, force: bool = False) -> list[str]:
    """按 `schema.SRC_FILES` 下载缺的原始文件；返回下载了哪些。"""
    src_dir.mkdir(parents=True, exist_ok=True)
    got = []
    for name, url in S.SRC_FILES.items():
        if names and name not in names:
            continue
        dest = src_dir / name
        if dest.exists() and not force:
            continue
        req = urllib.request.Request(url, headers={"User-Agent": "open-guji-cv hanzi-db"})
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read()
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(dest)
        got.append(name)
    return got


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _cell(v) -> str:
    if isinstance(v, float):
        return repr(v)
    return str(v).replace("\t", " ").replace("\n", " ").replace("\r", " ")


def _norm_edge(r: tuple) -> tuple:
    """无向边按码位排成 a<b（单字比码位，未编码形比字符串）。"""
    a, b, rel, directed, *rest = r
    if not directed and (a > b):
        a, b = b, a
    return (a, b, rel, int(directed), *rest)


def _dedupe_edges(rows: list[tuple]) -> list[tuple]:
    """同 (a, b, rel, directed, src, sense) 只留一行，ref／note 合并去重。"""
    acc: dict[tuple, list[set[str]]] = {}
    for r in map(_norm_edge, rows):
        key = r[:6]
        refs = acc.setdefault(key, [set(), set()])
        if r[6]:
            refs[0].add(r[6])
        if r[7]:
            refs[1].add(r[7])
    return [(*k, ";".join(sorted(v[0])), " | ".join(sorted(v[1]))) for k, v in acc.items()]


def collect(src: Path, cfg: Path, zi_dir: Path | None = None) -> tuple[dict[str, list[tuple]], dict]:
    """读全部来源 → `{表: 行}`, 统计。"""
    tables: dict[str, list[tuple]] = {t: [] for t in S.TABLES}
    stats: dict[str, dict] = {}
    missing: list[str] = []
    used_src: set[str] = set()

    def have(name: str) -> Path | None:
        p = src / name
        if p.exists():
            return p
        missing.append(name)
        return None

    def txt(p: Path) -> str:
        return p.read_text(encoding="utf-8")

    edges = tables["edges"]

    # Unihan
    if (z := have("Unihan.zip")):
        with zipfile.ZipFile(z) as zf:
            names = set(zf.namelist())

            def rd(n: str) -> str:
                return zf.read(n).decode("utf-8") if n in names else ""

            rows, st = I.unihan_variants(rd("Unihan_Variants.txt"))
            edges += rows
            stats["unihan_variants"] = st
            rows, st = I.unihan_chars([rd("Unihan_IRGSources.txt"), rd("Unihan_Readings.txt"),
                                       rd("Unihan_DictionaryLikeData.txt")])
            tables["chars"] += rows
            stats["unihan_chars"] = st
            head = rd("Unihan_Variants.txt").splitlines()[:3]
            stats["unihan_version"] = next((h.split("Version")[-1].strip() for h in head
                                            if "Unicode Version" in h), "")
        used_src.update(t for t in S.SOURCES if t.startswith("unihan"))

    # cjkvi-variants
    for fname, tag in (("cjkvi-twedu-variants.txt", "twedu"), ("cjkvi-hydzd-variants.txt", "hydzd"),
                       ("cjkvi-hydzd-borrowed.txt", "hydzd-borrowed"),
                       ("cjkvi-dypytz-variants.txt", "dypytz"),
                       ("cjkvi-cjkvi-simplified.txt", "cjkvi-simplified")):
        if (p := have(fname)):
            rows, forms, st = I.cjkvi_variants(txt(p), tag)
            edges += rows
            tables["forms"] += forms
            stats[tag] = st
            used_src.add(tag)

    if (p := have("yitizi-index.js")):
        rows, st = I.yitizi(txt(p))
        edges += rows
        stats["yitizi"] = st
        used_src.add("yitizi")

    # 部件檢索
    dt, rt = src / "charcomp-dt.jsonl", src / "charcomp-rt.jsonl"
    if have("charcomp-dt.jsonl") and have("charcomp-rt.jsonl"):
        rows, st = I.charcomp_rt(txt(dt).splitlines(), txt(rt).splitlines())
        edges += rows
        stats["charcomp:rt"] = st
        used_src.add("charcomp:rt")
    vt: dict[str, str] = {}
    if (p := have("charcomp-vt.json")):
        vt = {k: v for k, v in json.loads(txt(p)).items() if v and v != k}
        stats["charcomp:vt"] = {"folds": len(vt)}
        used_src.add("charcomp:vt")

    # 本项目
    if (p := cfg / "variants" / "local_edges.json").exists():
        rows, st = I.local_edges(json.loads(txt(p)))
        edges += rows
        stats["local:keben"] = st
        used_src.update(r[4] for r in rows)
    if (p := cfg / "variants" / "never_group.json").exists():
        rows, st = I.never_group(json.loads(txt(p)))
        edges += rows
        stats["local:never"] = st
        used_src.add("local:never")
    for fname, tag in (("confusable_pairs_v1.tsv", "near:v1"),
                       ("ids_confusable_pairs_v1.tsv", "near:ids-v1")):
        if (p := cfg / "ids" / fname).exists():
            rows, st = I.near_pairs(txt(p), tag)
            tables["near"] += rows
            stats[tag] = st
            used_src.add(tag)

    # 字统网缓存（可选；只收派生的族）
    if zi_dir and Path(zi_dir).exists():
        docs = []
        for f in sorted(Path(zi_dir).glob("U+*.json")):
            try:
                docs.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                continue
        rows, st = I.zi_cache(docs)
        edges += rows
        stats["zi"] = st
        used_src.add("zi")

    # IDS
    for fname, tag in (("yibai-ids_lv0.txt", "yibai:lv0"), ("yibai-ids_lv1.txt", "yibai:lv1"),
                       ("yibai-ids_lv2.txt", "yibai:lv2")):
        if (p := have(fname)):
            tables["ids"] += I.ids_yibai(txt(p), tag)
            used_src.add(tag)
    if (p := have("babelstone-IDS.TXT")):
        tables["ids"] += I.ids_babelstone(p.read_text(encoding="utf-8-sig"))
        used_src.add("babelstone")
    if (p := have("cjkvi-ids.txt")):
        tables["ids"] += I.ids_chise(txt(p))
        used_src.add("chise")
    tables["ids"] = sorted(set(tables["ids"]))
    stats["ids"] = dict(Counter(r[1] for r in tables["ids"]))

    tables["comps"] = _comps(tables["ids"], vt)
    tables["edges"] = _dedupe_edges(edges)
    tables["forms"] = _dedupe_forms(tables["forms"])
    tables["sources"] = [(k, v["name"], v["url"], v["license"], v["tier"], v.get("note", ""))
                         for k, v in S.SOURCES.items() if k in used_src]
    stats["missing"] = missing
    return tables, stats


def _dedupe_forms(rows: list[tuple]) -> list[tuple]:
    acc: dict[tuple, set[str]] = {}
    for key, regular, src, ref in rows:
        acc.setdefault((key, regular, src), set()).add(ref)
    return [(*k, ";".join(sorted(v))) for k, v in acc.items()]


def _comps(ids_rows: list[tuple], vt: dict[str, str]) -> list[tuple]:
    """部件闭包：以 yibai:lv1 的全部写法为准，字 → 叶子部件 → 叶子的叶子…，记最小深度。
    部件在 vt 里有折叠形的，另记一行折叠后的部件（folded=1）。"""
    direct: dict[str, set[str]] = {}
    for ch, src, seq, _ in ids_rows:
        if src != "yibai:lv1":
            continue
        for p in leaves(seq):
            if p != ch:
                direct.setdefault(ch, set()).add(p)
    out: list[tuple] = []
    for ch in direct:
        depth: dict[str, int] = {}
        frontier = sorted(direct[ch])
        d = 1
        while frontier and d <= MAX_COMP_DEPTH:
            nxt = []
            for p in frontier:
                if p in depth or p == ch:
                    continue
                depth[p] = d
                nxt.extend(sorted(direct.get(p, ())))
            frontier = nxt
            d += 1
        folded: dict[str, int] = {}
        for p, dp in depth.items():
            f = vt.get(p)
            if f and f not in depth:
                folded[f] = min(folded.get(f, 99), dp)
        out += [(ch, p, dp, 0) for p, dp in depth.items()]
        out += [(ch, p, dp, 1) for p, dp in folded.items()]
    return out


def _sort_key(row: tuple) -> tuple:
    return tuple((0, v, "") if isinstance(v, (int, float)) else (1, 0, v) for v in row)


def write_tsv(tables: dict[str, list[tuple]], out: Path) -> dict[str, dict]:
    out.mkdir(parents=True, exist_ok=True)
    info = {}
    for name, cols in S.TABLES.items():
        rows = sorted(tables.get(name, []), key=_sort_key)
        p = out / f"{name}.tsv"
        with open(p, "w", encoding="utf-8", newline="\n") as f:
            for r in rows:
                assert len(r) == len(cols), (name, r)
                f.write("\t".join(_cell(v) for v in r) + "\n")
        info[name] = {"rows": len(rows), "sha256": _sha(p)}
    return info


def content_sha(tsv_info: dict[str, dict]) -> str:
    h = hashlib.sha256()
    for name in sorted(tsv_info):
        h.update(f"{name}\t{tsv_info[name]['sha256']}\n".encode())
    return h.hexdigest()[:12]


def _parse(col: str, v: str):
    if col in S.INT_COLS:
        return int(v) if v else 0
    if col in S.REAL_COLS:
        return float(v) if v else 0.0
    return v


def load_sqlite(tsv_dir: Path, db_path: Path) -> None:
    tmp = db_path.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    con = sqlite3.connect(tmp)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    for name, cols in S.TABLES.items():
        decl = ", ".join(f"{c} {'INTEGER' if c in S.INT_COLS else 'REAL' if c in S.REAL_COLS else 'TEXT'}"
                         for c in cols)
        con.execute(f"CREATE TABLE {name} ({decl})")
        p = tsv_dir / f"{name}.tsv"
        with open(p, encoding="utf-8") as f:
            rows = (tuple(_parse(c, v) for c, v in zip(cols, line.rstrip("\n").split("\t")))
                    for line in f)
            con.executemany(f"INSERT INTO {name} VALUES ({','.join('?' * len(cols))})", rows)
    for sql in S.INDEXES:
        con.execute(sql)
    con.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
    con.commit()
    con.close()
    tmp.replace(db_path)


def build(src: Path, cfg: Path, out_root: Path | None = None, zi_dir: Path | None = None,
          set_current: bool = True) -> dict:
    """构建一个版本；返回 manifest（也写在 `<版本目录>/manifest.json`）。"""
    src, cfg = Path(src), Path(cfg)
    out_root = Path(out_root) if out_root else data_root()
    t0 = time.time()
    tables, stats = collect(src, cfg, zi_dir)
    stage = out_root / f".building-{os.getpid()}"
    if stage.exists():
        shutil.rmtree(stage)
    tsv_info = write_tsv(tables, stage / "tsv")
    sha = content_sha(tsv_info)
    load_sqlite(stage / "tsv", stage / "hanzi.sqlite")
    version = f"hanzi-{sha}"
    manifest = {
        "version": version,
        "content_sha": sha,
        "builder": BUILDER_VERSION,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "build_seconds": round(time.time() - t0, 1),
        "inputs": {p.name: {"sha256": _sha(p), "bytes": p.stat().st_size}
                   for p in sorted(src.iterdir()) if p.name in S.SRC_FILES} if src.exists() else {},
        "config": {str(p.relative_to(cfg)): _sha(p) for p in (
            cfg / "variants" / "local_edges.json", cfg / "variants" / "never_group.json",
            cfg / "ids" / "confusable_pairs_v1.tsv", cfg / "ids" / "ids_confusable_pairs_v1.tsv")
            if p.exists()},
        "tables": tsv_info,
        "stats": stats,
        "edges_by_src_rel": dict(sorted(Counter(f"{r[4]}|{r[2]}" for r in tables["edges"]).items())),
    }
    con = sqlite3.connect(stage / "hanzi.sqlite")
    con.executemany("INSERT INTO meta VALUES (?, ?)",
                    [("version", version), ("content_sha", sha), ("builder", str(BUILDER_VERSION))])
    con.commit()
    con.close()
    (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1,
                                                    sort_keys=True) + "\n", encoding="utf-8")
    final = out_root / version
    if final.exists():
        shutil.rmtree(final)
    stage.replace(final)
    if set_current:
        (out_root / "current").write_text(version + "\n", encoding="utf-8")
    return manifest
