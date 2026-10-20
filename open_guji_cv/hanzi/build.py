# -*- coding: utf-8 -*-
"""构建：原始资料（`src/`）＋本仓 `config/` → 两个包的规范 tsv ＋ 清单（总设计 §6.1、B7）。

    from open_guji_cv.hanzi.build import build, publish
    m = build(src_dir, cfg_dir, out_dir)     # out_dir/{core,parts}/*.tsv ＋ manifest.json
    publish(out_dir, repo_root)              # 核心包与清单写进 config/hanzi/，部件包放进本机 blob 缓存

- 不联网；缺的原始资料先 `fetch_sources(src_dir)`。缺了哪个就跳过哪个来源，`stats.missing` 里记下。
- 清单里没有时间戳：同一份输入 ⇒ tsv 与清单逐字节相同（验收 A3），进 git 也不会无谓地变。
- sqlite 不在这里出，各机由 `pack.ensure()` 从 tsv 灌（几秒）。
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

from . import importers as I
from . import schema as S
from .ids import leaves

BUILDER_VERSION = 2
#: 核心包与清单在仓里的位置。
HANZI_CFG = Path("config") / "hanzi"
#: 字统网派生族的原始资料文件（由 `zi_jsonl()` 从缓存目录汇总，不是上游下载的）。
ZI_FILE = "zi-families.jsonl"


def data_root() -> Path:
    home = Path(os.environ.get("GUJI_DATA_HOME") or Path.home() / ".guji-data")
    return home / "_shared" / "hanzi"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "open-guji-cv hanzi-db"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()


def fetch_sources(src_dir: Path, force: bool = False) -> list[str]:
    """按 `schema.SRC_FILES` 下载缺的原始资料；Unihan.zip 只解出 `UNIHAN_PARTS` 几个文本文件。"""
    src_dir.mkdir(parents=True, exist_ok=True)
    got: list[str] = []
    unihan: zipfile.ZipFile | None = None
    for name, url in S.SRC_FILES.items():
        dest = src_dir / name
        if dest.exists() and not force:
            continue
        if name.startswith("unihan-"):
            if unihan is None:
                unihan = zipfile.ZipFile(io.BytesIO(_get(url)))
            data = unihan.read(name[len("unihan-"):])
        else:
            data = _get(url)
        tmp = dest.with_suffix(dest.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(dest)
        got.append(name)
    return got


def zi_jsonl(zi_dir: Path, dest: Path) -> int:
    """字统网缓存目录（`U+XXXX.json`）→ 一个排好序的 jsonl：q、一跳族、逐节点判断与连线（不留取的时间）。

    放进原始资料，跟版本一起进 R2：查一次全队共享，不用每台机器重查。已有的 dest 会并进来。"""
    fams: dict[str, dict] = {}
    if dest.exists():
        for line in dest.read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            fams[d["q"]] = d
    for f in sorted(Path(zi_dir).glob("U+*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if d.get("q") and d.get("fam") is not None:
            d.pop("ts", None)
            d["fam"] = sorted(d["fam"])
            fams[d["q"]] = d
    dest.write_text("".join(json.dumps(fams[q], ensure_ascii=False, sort_keys=True) + "\n"
                            for q in sorted(fams)), encoding="utf-8")
    return len(fams)


def _cell(v) -> str:
    if isinstance(v, float):
        return repr(v)
    return str(v).replace("\t", " ").replace("\n", " ").replace("\r", " ")


def _norm_edge(r: tuple) -> tuple:
    """无向边按码位排成 a<b。"""
    a, b, rel, directed, *rest = r
    if not directed and (a > b):
        a, b = b, a
    return (a, b, rel, int(directed), *rest)


def _dedupe_edges(rows: list[tuple]) -> list[tuple]:
    """同 (a, b, rel, directed, src, sense) 只留一行，ref／note 合并去重。"""
    acc: dict[tuple, list[set[str]]] = {}
    for r in map(_norm_edge, rows):
        refs = acc.setdefault(r[:6], [set(), set()])
        if r[6]:
            refs[0].add(r[6])
        if r[7]:
            refs[1].add(r[7])
    return [(*k, ";".join(sorted(v[0])), " | ".join(sorted(v[1]))) for k, v in acc.items()]


def _dedupe_forms(rows: list[tuple]) -> list[tuple]:
    acc: dict[tuple, set[str]] = {}
    for key, regular, src, ref in rows:
        acc.setdefault((key, regular, src), set()).add(ref)
    return [(*k, ";".join(sorted(v))) for k, v in acc.items()]


def _comps(ids_rows: list[tuple], vt: dict[str, str]) -> list[tuple]:
    """直接部件：主套 IDS（yibai:lv1，全部写法）的叶子，depth=1。多层部件查询时现算（`db.components`）。
    部件在 vt 里有折叠形的另记一行（folded=1），按折叠形也能查到。"""
    direct: dict[str, set[str]] = {}
    for ch, src, seq, _ in ids_rows:
        if src != "yibai:lv1":
            continue
        for p in leaves(seq):
            if p != ch:
                direct.setdefault(ch, set()).add(p)
    out: list[tuple] = []
    for ch, parts in direct.items():
        out += [(ch, p, 1, 0) for p in parts]
        out += [(ch, f, 1, 1) for f in {vt[p] for p in parts if p in vt} - parts]
    return out


def collect(src: Path, cfg: Path) -> tuple[dict[str, list[tuple]], dict]:
    """读原始资料与本仓表 → `{表: 行}`（形近对不在内，见 `schema.NEAR_FILES`）、统计。"""
    tables: dict[str, list[tuple]] = {t: [] for t in S.TABLES if t != "near"}
    stats: dict = {}
    missing: list[str] = []
    used_src: set[str] = set()

    def text(name: str) -> str | None:
        p = src / name
        if p.exists():
            return p.read_text(encoding="utf-8-sig")
        missing.append(name)
        return None

    edges = tables["edges"]

    if (t := text("unihan-Unihan_Variants.txt")) is not None:
        rows, stats["unihan_variants"] = I.unihan_variants(t)
        edges += rows
        stats["unihan_version"] = next((h.split("Version")[-1].strip() for h in t.splitlines()[:5]
                                        if "Unicode Version" in h), "")
        used_src.update(k for k in S.SOURCES if k.startswith("unihan:"))
    texts = [t for n in S.UNIHAN_PARTS[1:] if (t := text(f"unihan-{n}")) is not None]
    if texts:
        rows, stats["unihan_chars"] = I.unihan_chars(texts)
        tables["chars"] += rows
        used_src.add("unihan")

    for fname, tag in (("cjkvi-twedu-variants.txt", "twedu"), ("cjkvi-hydzd-variants.txt", "hydzd"),
                       ("cjkvi-hydzd-borrowed.txt", "hydzd-borrowed"),
                       ("cjkvi-dypytz-variants.txt", "dypytz"),
                       ("cjkvi-cjkvi-simplified.txt", "cjkvi-simplified")):
        if (t := text(fname)) is not None:
            rows, forms, stats[tag] = I.cjkvi_variants(t, tag)
            edges += rows
            tables["forms"] += forms
            used_src.add(tag)

    if (t := text("yitizi-index.js")) is not None:
        rows, stats["yitizi"] = I.yitizi(t)
        edges += rows
        used_src.add("yitizi")

    dt, rt = text("charcomp-dt.jsonl"), text("charcomp-rt.jsonl")
    if dt is not None and rt is not None:
        rows, stats["charcomp:rt"] = I.charcomp_rt(dt.splitlines(), rt.splitlines())
        edges += rows
        used_src.add("charcomp:rt")
    vt: dict[str, str] = {}
    if (t := text("charcomp-vt.json")) is not None:
        vt = {k: v for k, v in json.loads(t).items() if v and v != k}
        stats["charcomp:vt"] = {"folds": len(vt)}
        used_src.add("charcomp:vt")

    if (src / ZI_FILE).exists():
        docs = [json.loads(x) for x in (src / ZI_FILE).read_text(encoding="utf-8").splitlines() if x]
        rows, forms, stats["zi"] = I.zi_cache(docs)
        edges += rows
        tables["forms"] += forms
        used_src.update({"zi"} | {r[4] for r in rows})

    if (p := cfg / "variants" / "local_edges.json").exists():
        rows, stats["local:keben"] = I.local_edges(json.loads(p.read_text(encoding="utf-8")))
        edges += rows
        used_src.update(r[4] for r in rows)
    if (p := cfg / "variants" / "never_group.json").exists():
        rows, stats["local:never"] = I.never_group(json.loads(p.read_text(encoding="utf-8")))
        edges += rows
        used_src.add("local:never")
    used_src.update(S.NEAR_FILES)

    if (t := text("yibai-ids_lv1.txt")) is not None:
        tables["ids"] = sorted(set(I.ids_yibai(t, "yibai:lv1")))
        used_src.add("yibai:lv1")

    tables["comps"] = _comps(tables["ids"], vt)
    tables["edges"] = _dedupe_edges(edges)
    tables["forms"] = _dedupe_forms(tables["forms"])
    tables["sources"] = [(k, v["name"], v["url"], v["license"], v["tier"], v.get("note", ""))
                         for k, v in S.SOURCES.items() if k in used_src]
    stats["missing"] = missing
    return tables, stats


def _sort_key(row: tuple) -> tuple:
    return tuple((0, v, "") if isinstance(v, (int, float)) else (1, 0, v) for v in row)


def write_tsv(rows: list[tuple], cols: tuple[str, ...], p: Path) -> dict:
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(rows, key=_sort_key)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            assert len(r) == len(cols), (p.name, r)
            f.write("\t".join(_cell(v) for v in r) + "\n")
    return {"rows": len(rows), "sha256": sha256_file(p), "bytes": p.stat().st_size}


def content_sha(files: dict[str, dict]) -> str:
    h = hashlib.sha256()
    for key in sorted(files):
        h.update(f"{key}\t{files[key]['sha256']}\n".encode())
    return h.hexdigest()[:12]


def build(src: Path, cfg: Path, out: Path) -> dict:
    """构建一个版本到 `out/`（先清空）；返回清单（也写在 `out/manifest.json`）。

    清单 `files` 的键：包内文件是 `core/edges.tsv` 这种相对路径；形近对表的键是来源名（`near:v1`），
    `path` 指向仓里的那张表。每个文件都有 sha256——本机灌库、对外发布都按它认。"""
    src, cfg, out = Path(src), Path(cfg), Path(out)
    tables, stats = collect(src, cfg)
    if out.exists():
        shutil.rmtree(out)
    files: dict[str, dict] = {}
    for pack, names in S.PACKS.items():
        for t in names:
            if t == "near":
                continue
            rel = f"{pack}/{t}.tsv"
            files[rel] = {"pack": pack, "table": t, **write_tsv(tables[t], S.TABLES[t], out / rel)}
    for tag, path in S.NEAR_FILES.items():
        p = cfg.parent / path            # NEAR_FILES 的路径相对仓根，cfg 是仓根下的 config/
        if p.exists():
            n = sum(1 for x in p.read_text(encoding="utf-8").splitlines()
                    if x and not x.startswith(("#", "a\t")))
            files[tag] = {"pack": "core", "table": "near", "path": path, "rows": n,
                          "sha256": sha256_file(p), "bytes": p.stat().st_size}
            stats[tag] = {"pairs": n}
    sha = content_sha(files)
    raw = {p.name: {"sha256": sha256_file(p), "bytes": p.stat().st_size}
           for p in sorted(src.iterdir()) if p.name in S.SRC_FILES or p.name == ZI_FILE} \
        if src.exists() else {}
    manifest = {
        "version": f"hanzi-{sha}",
        "content_sha": sha,
        "builder": BUILDER_VERSION,
        "unihan_version": stats.get("unihan_version", ""),
        "files": files,
        "raw": raw,
        "stats": stats,
        "edges_by_src_rel": dict(sorted(Counter(f"{r[4]}|{r[2]}" for r in tables["edges"]).items())),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1, sort_keys=True)
                                       + "\n", encoding="utf-8")
    return manifest


def publish(out: Path, repo: Path, blob_dir: Path | None = None) -> dict:
    """把 `build()` 的产出放到位：核心包 tsv → `config/hanzi/core/`，清单 → `config/hanzi/manifest.json`
    与 `config/hanzi/versions/<版本>.json`；部件包 tsv 按 sha 放进本机 blob 缓存（上传 R2 另做）。"""
    from .pack import blob_cache_path
    out, repo = Path(out), Path(repo)
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    dest = repo / HANZI_CFG
    core = dest / "core"
    if core.exists():
        shutil.rmtree(core)
    core.mkdir(parents=True)
    for rel, f in m["files"].items():
        if "path" in f:
            continue
        if f["pack"] == "core":
            shutil.copyfile(out / rel, dest / rel)
        bp = blob_cache_path(f["sha256"], blob_dir)
        if not bp.exists():
            bp.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(out / rel, bp)
    (dest / "versions").mkdir(exist_ok=True)
    shutil.copyfile(out / "manifest.json", dest / "manifest.json")
    shutil.copyfile(out / "manifest.json", dest / "versions" / f"{m['version']}.json")
    return m
