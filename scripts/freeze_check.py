# -*- coding: utf-8 -*-
"""J2 冻结包：生成（build）与校验（check，V1–V14）。GUJI-24 / GUJI-208i。

规矩（Mila 10-14 决定，见 overview `J2-11项决定-Mila.md`）：
- 只读：不写 products/、不动工作区；只往 `--out` 指的目录写（build）或不写任何东西（check）。
- 先放 scripts/，不进 `guji` 子命令、不改 steps/*、不动 code_deps（窗口后再议）。
- 缓存只冻范围＋汇总哈希；人裁事件记 sha256＋行数；产物靠快照引用，不拷产物。
- V14 的 iron 通道差异单列，不要求 100%。

用法（在 cv 仓根、用 .venv 的 python，设 GUJI_PRODUCTS_DIR 指向要冻的产物根）::

    python scripts/freeze_check.py build vol04 -w <工作区> --out /tmp/F1 [--note 演练]
    python scripts/freeze_check.py check /tmp/F1 -w <工作区> [--skip-status] [--replay A.jsonl.gz --frozen B.jsonl.gz]
    python scripts/freeze_check.py selftest vol04 -w <工作区>     # 4 个故意弄坏用例
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

FORMAT = "guji-freeze/1"
REPO = Path(__file__).resolve().parent.parent
PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"

#: 第 5 节的默认可复现性声明（build 写进 freeze.json，人可再改）。
REPRO_DEFAULT = {
    "rare_candidates": ("conditional", "候选由 yaml 外状态（CNN ckpt／字体集／emb 索引／字表语料／real_proto／GlyphWiki）决定；冻结产物当数据，不重算",
                        ["E"]),
    "seed_admit": ("conditional", "iron 通道同输入不稳（缓存范围依赖）；条件＝全缓存 vol01–07＋冻结 rare_candidates", ["E", "G"]),
    "glyph_match": ("yes", "前提＝冻结时刻 glyph.db 指纹＋events 哈希（V8／V9）", ["F"]),
}


# ───────────────────────── 通用小工具 ─────────────────────────
def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sums_hash(rows: list[tuple[str, str]]) -> str:
    return sha_bytes("\n".join(f"{k}\t{v}" for k, v in sorted(rows)).encode())


def nlines(p: Path) -> int:
    with open(p, "rb") as f:
        return sum(1 for _ in f)


def now_la() -> str:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:  # noqa: BLE001
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S local")


def git(*a, cwd=REPO) -> tuple[int, str]:
    cp = subprocess.run(["git", *a], cwd=cwd, capture_output=True, text=True)
    return cp.returncode, (cp.stdout or "").strip()


def products_root() -> Path:
    env = os.environ.get("GUJI_PRODUCTS_DIR")
    return Path(env) if env else None


def flat(d, prefix="") -> list[tuple[str, str]]:
    out = []
    if isinstance(d, dict):
        for k in sorted(d, key=str):
            out += flat(d[k], f"{prefix}{k}.")
    elif isinstance(d, list):
        out.append((prefix[:-1], json.dumps(d, ensure_ascii=False)))
    else:
        out.append((prefix[:-1], json.dumps(d, ensure_ascii=False)))
    return out


def yaml_flat(text: str) -> list[tuple[str, str]]:
    try:
        import yaml
        return flat(yaml.safe_load(text) or {})
    except Exception:  # noqa: BLE001
        return []


def _step_code_hashes(steps: list[str]) -> dict[str, str]:
    """各步 code_hash（行尾归一后，读 engine）。import 失败＝空（check 里记 SKIP）。"""
    try:
        sys.path.insert(0, str(REPO))
        from open_guji_cv import steps as _r  # noqa: F401
        from open_guji_cv.core.step import STEPS
        from open_guji_cv.core.engine import code_hash
        return {s: code_hash(STEPS[s]) for s in steps if s in STEPS}
    except Exception:  # noqa: BLE001
        return {}


def _compact(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                out[d["key"]] = d
    return out


def scan_products(book: str, root: Path) -> dict:
    """每步：文件清单哈希（只记哈希，不拷）、params_hash／code_rev 集合、状态计数。"""
    res = {"root_hint": str(root), "steps": {}, "files": {}}
    src = root / book
    for d in sorted(p for p in src.iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        ents = _compact(d / "_manifest.jsonl")
        st: dict[str, int] = {}
        for e in ents.values():
            st[e.get("status", "ok")] = st.get(e.get("status", "ok"), 0) + 1
        rows = []
        for f in sorted(d.iterdir()):
            if f.is_file() and not f.name.endswith(".tmp"):
                h = sha_file(f)
                res["files"][f"{d.name}/{f.name}"] = h
                rows.append((f.name, h))
        res["steps"][d.name] = {
            "files": len(rows), "files_sums_sha256": sums_hash(rows),
            "manifest_sha256": sha_file(d / "_manifest.jsonl") if (d / "_manifest.jsonl").is_file() else None,
            "params_hash": sorted({e.get("params_hash") for e in ents.values() if e.get("params_hash")}),
            "code_revs": sorted({e.get("code_rev") for e in ents.values() if e.get("code_rev")}),
            "entries": st}
    return res


def external_state(ws: Path) -> list[dict]:
    """yaml 之外的外部状态（E 层）；每项拿不到就 note 写明，不报错。"""
    items: list[dict] = []

    def add(name, path, note=""):
        p = Path(path)
        if p.is_file():
            items.append({"name": name, "path": str(p), "sha256": sha_file(p), "size": p.stat().st_size, "note": note})
        else:
            items.append({"name": name, "path": str(p), "sha256": None, "size": None, "note": note or "文件不存在"})

    sys.path.insert(0, str(REPO))
    try:
        from open_guji_cv.clustering.font_candidates import font_set_fingerprint
        fp = font_set_fingerprint(str(REPO / "fonts"))
        items.append({"name": "font_set_fingerprint", "path": "fonts/", "sha256": fp, "size": None, "note": "字体集指纹"})
    except Exception as e:  # noqa: BLE001
        items.append({"name": "font_set_fingerprint", "path": "fonts/", "sha256": None, "size": None, "note": f"取不到：{type(e).__name__}"})
    try:
        from open_guji_cv.clustering.cnn_candidates import DEFAULT_CKPT, fingerprint
        add("cnn_ckpt", DEFAULT_CKPT, "CNN checkpoint 文件")
        items.append({"name": "cnn_fingerprint", "path": str(DEFAULT_CKPT), "sha256": fingerprint(DEFAULT_CKPT), "size": None, "note": "cnn_candidates.fingerprint()"})
    except Exception as e:  # noqa: BLE001
        items.append({"name": "cnn_ckpt", "path": "models/", "sha256": None, "size": None, "note": f"取不到：{type(e).__name__}"})
    for p in sorted((REPO / "models").glob("**/emb_*.npz")) if (REPO / "models").is_dir() else []:
        add(f"emb:{p.name}", p, "emb 模板索引")
    for p in sorted(REPO.glob("open_guji_cv/**/charset_spec.py")):
        add("charset_spec.py", p, "字表规格")
    corpus = ws / "corpus"
    for p in sorted(corpus.glob("*.txt")) if corpus.is_dir() else []:
        add(f"corpus:{p.name}", p, "字表语料（内容哈希）")
    return items


def human_state(ws: Path) -> dict:
    ev = []
    d = ws / "feedback" / "events"
    for p in sorted(d.glob("*.jsonl")) if d.is_dir() else []:
        last = ""
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        last = line
            ts = json.loads(last).get("ts", "") if last else ""
        except Exception:  # noqa: BLE001
            ts = ""
        ev.append({"name": p.name, "sha256": sha_file(p), "lines": nlines(p), "latest_ts": ts})
    cx = ws / "config" / "crop_exclusions.jsonl"
    out = {"events": ev,
           "crop_exclusions": {"sha256": sha_file(cx), "lines": nlines(cx)} if cx.is_file() else None,
           "glyph_db_fingerprint": None, "human_verdicts_fingerprint": None}
    db = ws / "output" / "glyph.db"
    if db.is_file():
        try:
            sys.path.insert(0, str(REPO))
            from open_guji_cv.steps.glyph_match import db_fingerprint, human_verdicts_fingerprint
            out["glyph_db_fingerprint"] = db_fingerprint(db)
            out["human_verdicts_fingerprint"] = human_verdicts_fingerprint(db)
        except Exception:  # noqa: BLE001
            pass
    rc, head = git("rev-parse", "HEAD", cwd=ws)
    rc2, dirty = git("status", "--porcelain", cwd=ws)
    out["ws_repo_commit"] = head if rc == 0 else None
    out["ws_repo_dirty"] = bool(dirty) if rc2 == 0 else None
    return out


def cache_state(book: str, ws: Path, hash_content: bool) -> dict:
    root = ws / "cache" / book
    rows, pages = [], set()
    for p in sorted(root.rglob("*")) if root.is_dir() else []:
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            rows.append((rel, sha_file(p) if hash_content else str(p.stat().st_size)))
            m = re.search(r"p?(\d{3,4})", p.name)
            if m:
                pages.add(int(m.group(1)))
    return {"dir": str(root), "files": len(rows), "pages": [min(pages), max(pages)] if pages else None,
            "n_pages": len(pages), "mode": "content-sha256" if hash_content else "size-only",
            "sums_sha256": sums_hash(rows) if rows else None}


def write_tsv(p: Path, header: list[str], rows: list[list]):
    p.write_text("\t".join(header) + "\n" + "".join("\t".join("" if c is None else str(c) for c in r) + "\n" for r in rows),
                 encoding="utf-8")


# ───────────────────────── build ─────────────────────────
def cmd_build(a) -> int:
    ws, book = Path(a.workspace), a.book
    pr = Path(a.products_dir) if a.products_dir else products_root()
    if not pr or not (pr / book).is_dir():
        print(f"没有产物目录：{pr}/{book}（设 GUJI_PRODUCTS_DIR 或 --products-dir）", file=sys.stderr)
        return 2
    out = Path(a.out)
    if out.exists() and any(out.iterdir()):
        print(f"--out 必须是空目录：{out}", file=sys.stderr)
        return 2
    (out / "config").mkdir(parents=True, exist_ok=True)
    ytxt = (ws / "books" / f"{book}.yaml").read_bytes()
    (out / "config" / f"{book}.yaml").write_bytes(ytxt)
    write_tsv(out / "config" / f"{book}.flat.tsv", ["key", "value"], [list(r) for r in yaml_flat(ytxt.decode("utf-8"))])
    prod = scan_products(book, pr)
    chs = _step_code_hashes(list(prod["steps"]))
    for s, h in chs.items():
        prod["steps"][s]["code_hash"] = h
    write_tsv(out / "products.tsv", ["step/file", "sha256"], [[k, v] for k, v in sorted(prod["files"].items())])
    ext = external_state(ws)
    write_tsv(out / "external.tsv", ["name", "path", "sha256", "size", "note"],
              [[e["name"], e["path"], e["sha256"], e["size"], e["note"]] for e in ext])
    hum = human_state(ws)
    write_tsv(out / "human.tsv", ["file", "sha256", "lines", "latest_ts"],
              [[e["name"], e["sha256"], e["lines"], e["latest_ts"]] for e in hum["events"]])
    cache = cache_state(book, ws, a.cache_hash)
    write_tsv(out / "cache.manifest.tsv", ["dir", "files", "pages", "mode", "sums_sha256"],
              [[cache["dir"], cache["files"], cache["pages"], cache["mode"], cache["sums_sha256"]]])
    deliv = []
    for pat in a.deliverable or []:
        for p in sorted(Path().glob(pat) if not os.path.isabs(pat) else Path("/").glob(pat[1:])):
            if p.is_file():
                deliv.append({"path": str(p), "sha256": sha_file(p), "size": p.stat().st_size})
    write_tsv(out / "deliverables.tsv", ["path", "sha256", "size"], [[d["path"], d["sha256"], d["size"]] for d in deliv])
    (out / "status.txt").write_text("", encoding="utf-8")
    rc, head = git("rev-parse", "HEAD")
    rc2, dirty = git("status", "--porcelain", "--untracked-files=no")
    lock = REPO / "uv.lock"
    ver = {"python": sys.version.split()[0]}
    for m in ("torch", "numpy", "cv2", "scipy"):
        try:
            ver[m] = __import__(m).__version__
        except Exception:  # noqa: BLE001
            ver[m] = None
    fid = a.id or "F0"
    rep = {s: {"reproducible": r, "reason": why, "external_refs": refs}
           for s, (r, why, refs) in REPRO_DEFAULT.items() if s in prod["steps"]}
    fz = {
        "format": FORMAT, "id": fid, "book": book, "workspace": ws.name,
        "created_la": now_la(), "by": a.by, "approved_by": a.approved_by, "note": a.note,
        "rehearsal": bool(a.rehearsal),
        "premise": "用户已选方案 A：交付后冻结；演练非交付" if a.rehearsal else "用户已选方案 A：交付后冻结",
        "code": {"cv_commit": head if rc == 0 else None, "cv_dirty": bool(dirty), "uv_lock_sha256": sha_file(lock) if lock.is_file() else None,
                 "versions": ver, "threads_env": {k: os.environ.get(k) for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS")},
                 "step_code_hash": chs},
        "config": {"ref_snapshot_yaml_sha": a.ref_snapshot_yaml_sha, "yaml_sha256": sha_bytes(ytxt), "yaml_sha256_lf": sha_bytes(ytxt.replace(b"\r\n", b"\n")),
                   "yaml_sha256_crlf": sha_bytes(ytxt.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))},
        "products": {"root_hint": prod["root_hint"], "snap_branch": a.snap_branch, "snap_commit": a.snap_commit,
                     "snap_manifest_sha256": a.snap_manifest_sha, "steps": prod["steps"]},
        "external": ext, "human": hum, "cache": cache, "deliverables": deliv,
        "reproducibility": rep,
    }
    (out / "REPRO.md").write_text("# 不可复现步说明\n\n" + "".join(
        f"- **{s}**：{v['reproducible']}——{v['reason']}\n" for s, v in rep.items()), encoding="utf-8")
    files = {}
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.name != "freeze.json":
            files[p.relative_to(out).as_posix()] = {"sha256": sha_file(p), "size": p.stat().st_size}
    fz["files"] = files
    (out / "freeze.json").write_text(json.dumps(fz, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"冻结包已生成：{out}（{len(files)+1} 个文件；产物只记哈希不拷贝）")
    return 0


# ───────────────────────── check ─────────────────────────
class Report:
    def __init__(self):
        self.rows: list[tuple[str, str, str, str]] = []

    def add(self, v, title, st, msg=""):
        self.rows.append((v, title, st, msg))

    def worst(self):
        return any(r[2] == FAIL for r in self.rows)

    def show(self):
        w = max(len(r[1]) for r in self.rows)
        for v, t, st, m in self.rows:
            print(f"{v:<4} {st:<5} {t:<{w}}  {m}")
        c = {k: sum(1 for r in self.rows if r[2] == k) for k in (PASS, FAIL, WARN, SKIP)}
        print(f"\n合计：PASS {c[PASS]}｜FAIL {c[FAIL]}｜WARN {c[WARN]}｜SKIP {c[SKIP]}")


SECRET = re.compile(r"(?i)(password|passwd|secret|token|api[_-]?key|authorization:\s*bearer)\s*[:=]\s*['\"]?[A-Za-z0-9_\-./+=]{8,}")


def _load_fz(pkg: Path, R: Report):
    try:
        fz = json.loads((pkg / "freeze.json").read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        R.add("V1", "清单完整", FAIL, f"freeze.json 读不了：{e}")
        return None
    need = ["format", "id", "book", "workspace", "created_la", "code", "config", "products", "external", "human",
            "cache", "reproducibility", "files"]
    miss = [k for k in need if k not in fz]
    if fz.get("format") != FORMAT:
        R.add("V1", "清单完整", FAIL, f"format={fz.get('format')!r}，只认 {FORMAT}")
    elif miss:
        R.add("V1", "清单完整", FAIL, "缺字段：" + ",".join(miss))
    else:
        R.add("V1", "清单完整", PASS, f"id={fz['id']} book={fz['book']}" + ("（演练）" if fz.get("rehearsal") else ""))
    return fz


def cmd_check(a) -> int:
    pkg, ws = Path(a.pkg), Path(a.workspace)
    R = Report()
    fz = _load_fz(pkg, R)
    if fz is None:
        R.show()
        return 1
    book = fz["book"]
    pr = Path(a.products_dir) if a.products_dir else products_root()
    # V2 包文件哈希（+ 产物逐文件哈希，只读）
    bad, extra = [], []
    on_disk = {p.relative_to(pkg).as_posix() for p in pkg.rglob("*") if p.is_file() and p.name != "freeze.json"}
    for rel, m in fz["files"].items():
        p = pkg / rel
        if not p.is_file() or sha_file(p) != m["sha256"]:
            bad.append(rel)
    extra = sorted(on_disk - set(fz["files"]))
    pbad = []
    ptsv = pkg / "products.tsv"
    if ptsv.is_file() and pr and (pr / book).is_dir():
        for line in ptsv.read_text(encoding="utf-8").splitlines()[1:]:
            k, _, h = line.partition("\t")
            f = pr / book / k
            if not f.is_file() or sha_file(f) != h:
                pbad.append(k)
    if bad or extra or pbad:
        R.add("V2", "文件哈希", FAIL, f"包内不符 {len(bad)}：{bad[:3]}；多余 {len(extra)}：{extra[:3]}；产物文件不符 {len(pbad)}：{pbad[:3]}")
    else:
        R.add("V2", "文件哈希", PASS, f"包内 {len(fz['files'])} 个＋产物 {max(0, len(ptsv.read_text().splitlines()) - 1) if ptsv.is_file() else 0} 个逐一相等")
    # V3 yaml
    cfg = fz["config"]
    cp = pkg / "config" / f"{book}.yaml"
    cur = ws / "books" / f"{book}.yaml"
    if not cp.is_file():
        R.add("V3", "yaml", FAIL, "包内没有 yaml 拷贝")
    else:
        pb = cp.read_bytes()
        if sha_bytes(pb) != cfg["yaml_sha256"]:
            R.add("V3", "yaml", FAIL, "包内拷贝与记录的 sha256 不符")
        elif not cur.is_file():
            R.add("V3", "yaml", FAIL, f"工作区没有 {cur}")
        else:
            cb = cur.read_bytes()
            ref = cfg.get("ref_snapshot_yaml_sha")
            if cb == pb and ref and ref != cfg["yaml_sha256"]:
                R.add("V3", "yaml", WARN if fz.get("rehearsal") else FAIL,
                      f"包内＝工作区 {cfg['yaml_sha256'][:12]}；与参照快照 {ref[:12]} 不同（演练只提示，正式冻结须与交付快照一致）")
            elif cb == pb:
                R.add("V3", "yaml", PASS, f"字节一致 {cfg['yaml_sha256'][:12]}")
            elif cb.replace(b"\r\n", b"\n") == pb.replace(b"\r\n", b"\n"):
                R.add("V3", "yaml", WARN, "仅行尾差异（LF／CRLF）")
            else:
                fa, fb = dict(yaml_flat(pb.decode("utf-8"))), dict(yaml_flat(cb.decode("utf-8")))
                diff = sorted(k for k in set(fa) | set(fb) if fa.get(k) != fb.get(k))
                R.add("V3", "yaml", FAIL, f"yaml 已漂移，{len(diff)} 键不同：{diff[:6]}（不自动裁定，转 Mila）")
    # V4 代码
    code = fz["code"]
    rc, head = git("rev-parse", "HEAD")
    msgs, st4 = [], PASS
    if rc != 0:
        R.add("V4", "代码", SKIP, "取不到 cv HEAD")
    else:
        rec = code.get("cv_commit")
        if rec and rec != head:
            ok, _ = git("merge-base", "--is-ancestor", rec, head)
            msgs.append(f"HEAD {head[:9]}≠冻结 {rec[:9]}（{'是祖先' if ok == 0 else '非祖先／取不到'}）")
            st4 = WARN
        cur_h = _step_code_hashes(list(code.get("step_code_hash", {})))
        if not cur_h:
            msgs.append("取不到 engine.code_hash，未复算")
            st4 = WARN if st4 == PASS else st4
        else:
            chg = sorted(s for s, h in code["step_code_hash"].items() if cur_h.get(s) != h)
            if chg:
                st4 = FAIL
                msgs.append(f"code_hash 变了的步：{chg}（该步及下游算过期，转 Ethan）")
            else:
                msgs.append(f"{len(cur_h)} 步 code_hash 复算相等")
        if code.get("cv_dirty"):
            st4 = FAIL if st4 == PASS else st4
            msgs.append("冻结时 cv 树不干净")
        R.add("V4", "代码", st4, "；".join(msgs))
    # V5 产物指纹
    if pr and (pr / book).is_dir():
        cur = scan_products(book, pr)
        diffs = []
        for s, rec in fz["products"]["steps"].items():
            c = cur["steps"].get(s)
            if not c:
                diffs.append(f"{s}:缺")
            elif (c["params_hash"], c["code_revs"], c["manifest_sha256"]) != (rec["params_hash"], rec["code_revs"], rec["manifest_sha256"]):
                diffs.append(f"{s}:params/code_rev/manifest 变")
            elif c["files_sums_sha256"] != rec["files_sums_sha256"]:
                diffs.append(f"{s}:文件集变")
        sc = fz["products"].get("snap_commit")
        note = "" if sc else "（未挂快照分支：snap_manifest 一项 SKIP）"
        R.add("V5", "产物指纹", FAIL if diffs else PASS, (f"{len(diffs)} 步不符：{diffs[:5]}" if diffs else f"{len(cur['steps'])} 步 params_hash／manifest／文件集相等") + note)
    else:
        R.add("V5", "产物指纹", SKIP, "没有 GUJI_PRODUCTS_DIR／--products-dir")
    # V6 产物新鲜
    if a.skip_status:
        R.add("V6", "产物新鲜", SKIP, "--skip-status")
    else:
        env = dict(os.environ)
        if pr:
            env["GUJI_PRODUCTS_DIR"] = str(pr)
        exe = [str(REPO / ".venv/bin/guji")] if (REPO / ".venv/bin/guji").is_file() else ["guji"]
        try:
            cp = subprocess.run([*exe, "status", book, "-w", str(ws), "--pages", "all"], capture_output=True, text=True, env=env, timeout=a.timeout)
            tot = {"过期": 0, "失败": 0, "缺失": 0}
            for m in re.finditer(r"过期\s+(\d+)\s+缺失\s+(\d+)\s+失败\s+(\d+)", cp.stdout):
                tot["过期"] += int(m.group(1))
                tot["缺失"] += int(m.group(2))
                tot["失败"] += int(m.group(3))
            if a.save_status:
                Path(a.save_status).write_text(cp.stdout, encoding="utf-8")
            if cp.returncode != 0 and not re.search(r"过期", cp.stdout):
                R.add("V6", "产物新鲜", SKIP, f"guji status 退出 {cp.returncode}：{cp.stderr[-120:]}")
            else:
                bad6 = tot["过期"] or tot["失败"]
                R.add("V6", "产物新鲜", FAIL if bad6 else PASS, f"步×页合计 过期 {tot['过期']}／缺失 {tot['缺失']}／失败 {tot['失败']}（不自动重跑）")
        except Exception as e:  # noqa: BLE001
            R.add("V6", "产物新鲜", SKIP, f"跑不了 guji status：{type(e).__name__}")
    # V7 外部状态
    ext = {e["name"]: e for e in fz["external"]}
    cur_ext = {e["name"]: e for e in external_state(ws)}
    d7, sk7 = [], []
    for n, e in ext.items():
        c = cur_ext.get(n)
        if e["sha256"] is None:
            sk7.append(n)
        elif c is None or c["sha256"] != e["sha256"]:
            d7.append(n)
    if d7:
        R.add("V7", "外部状态", FAIL, f"变了：{d7[:8]}（checkpoint／字体变＝全册 5a 过期，转 Mila）")
    else:
        R.add("V7", "外部状态", (WARN if fz.get("rehearsal") else FAIL) if sk7 else PASS,
              f"{len(ext) - len(sk7)} 项相等" + (f"；冻结时记 missing {len(sk7)} 项：{sk7[:4]}（演练提示不判败，正式冻结必须齐）" if sk7 else ""))
    # V8 字形库
    h = fz["human"]
    now_h = human_state(ws)
    if h.get("glyph_db_fingerprint") is None and now_h.get("glyph_db_fingerprint") is None:
        R.add("V8", "字形库", SKIP, "这个工作区没有 output/glyph.db（沙箱）")
    else:
        d8 = [k for k in ("glyph_db_fingerprint", "human_verdicts_fingerprint") if h.get(k) != now_h.get(k)]
        if d8:
            R.add("V8", "字形库", FAIL, f"指纹变了：{d8}（库在冻结后又变，转 Mila）")
        elif now_h.get("ws_repo_dirty"):
            R.add("V8", "字形库", WARN, "指纹相等但工作区仓有未提交改动")
        else:
            R.add("V8", "字形库", PASS, "四表指纹与人裁指纹相等")
    # V9 人裁事件与排除名单
    d9, add9 = [], []
    cur_ev = {e["name"]: e for e in now_h["events"]}
    for e in h["events"]:
        c = cur_ev.get(e["name"])
        if c is None:
            d9.append(f"{e['name']}:缺")
        elif c["sha256"] != e["sha256"]:
            # 只增不改：前 lines 行的哈希相等才算追加
            # 冻结时只存了整文件 sha，无法逐行回验「只增不改」，退化为行数判断（行数不增＝被改或删）
            if c["lines"] > e["lines"]:
                add9.append(f"{e['name']}:+{c['lines'] - e['lines']}行")
            else:
                d9.append(f"{e['name']}:被改（行数 {e['lines']}→{c['lines']}）")
    cx, cxn = h.get("crop_exclusions"), now_h.get("crop_exclusions")
    if (cx or {}).get("sha256") != (cxn or {}).get("sha256"):
        if cx and cxn and cxn["lines"] > cx["lines"]:
            add9.append(f"crop_exclusions:+{cxn['lines'] - cx['lines']}行")
        else:
            d9.append("crop_exclusions 变了")
    if d9:
        R.add("V9", "人裁事件与排除名单", FAIL, "；".join(d9))
    elif add9:
        R.add("V9", "人裁事件与排除名单", WARN, "冻结后追加：" + "；".join(add9))
    else:
        R.add("V9", "人裁事件与排除名单", PASS, f"{len(h['events'])} 个事件文件＋排除名单哈希／行数相等")
    # V10 缓存
    cs = fz["cache"]
    now_c = cache_state(book, ws, cs.get("mode") == "content-sha256")
    if cs.get("files") == 0 and now_c["files"] == 0:
        R.add("V10", "缓存", SKIP, "该册无缓存")
    elif (now_c["files"], now_c["sums_sha256"]) != (cs["files"], cs["sums_sha256"]):
        R.add("V10", "缓存", FAIL, f"文件数 {cs['files']}→{now_c['files']} 或汇总哈希变（缓存被外部换过，先查再谈重放）")
    else:
        R.add("V10", "缓存", PASS, f"{cs['files']} 个文件、页 {cs['pages']}、汇总（{cs['mode']}）相等；`guji cache verify` 未在此跑")
    # V11 交付物
    dv = fz.get("deliverables") or []
    if not dv:
        R.add("V11", "交付物", SKIP, "待 Morgan 确认交付册（演练不要求交付物清单）；close-check 14 项也未复跑")
    else:
        bad11 = [d["path"] for d in dv if not Path(d["path"]).is_file() or sha_file(Path(d["path"])) != d["sha256"]]
        R.add("V11", "交付物", FAIL if bad11 else PASS, f"{bad11[:4]}" if bad11 else f"{len(dv)} 个交付物哈希相等；lines.md 字数／close-check 重跑另列")
    # V12 不可变
    br = fz["products"].get("snap_branch") or fz.get("branch")
    if not br:
        R.add("V12", "不可变", SKIP, "包未挂远端分支（演练：本地目录）")
    else:
        rc, out = git("ls-remote", "origin", br, cwd=ws)
        want = fz.get("commit") or fz["products"].get("snap_commit")
        if rc != 0 or not out:
            R.add("V12", "不可变", WARN, "远端取不到该分支")
        else:
            tip = out.split()[0]
            R.add("V12", "不可变", PASS if (not want or tip == want) else FAIL, f"tip {tip[:9]}" + ("" if (not want or tip == want) else f"≠记录 {want[:9]}"))
    # V13 无敏感信息
    hit = []
    for p in sorted(pkg.rglob("*")):
        if p.is_file() and p.suffix in (".json", ".tsv", ".md", ".yaml", ".txt", ".yml"):
            t = p.read_text(encoding="utf-8", errors="ignore")
            m = SECRET.search(t)
            if m:
                hit.append(f"{p.relative_to(pkg)}:{m.group(1)}")
    if hit:
        R.add("V13", "无敏感信息", FAIL, f"疑似口令／令牌：{hit[:4]}")
    else:
        R.add("V13", "无敏感信息", PASS, f"扫了 {sum(1 for p in pkg.rglob('*') if p.is_file())} 个文件，无口令／令牌形态")
    # V14 重放一致性（重型，可选）
    if not (a.replay and a.frozen):
        R.add("V14", "重放一致性", SKIP, "重型可选：给 --replay/--frozen（两份逐格表）才比；iron 差异单列")
    else:
        R.add(*v14(a.replay, a.frozen))
    R.show()
    return 1 if R.worst() else 0


def _cells(path: str) -> dict[str, dict]:
    op = gzip.open if str(path).endswith(".gz") else open
    out = {}
    with op(path, "rt", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                out[d.get("id") or d.get("cell_id")] = d
    return out


def v14(replay: str, frozen: str):
    """逐格最终字比一致率；iron 通道的差异格单列（不要求 100%），其余必须 100%。"""
    A, B = _cells(replay), _cells(frozen)
    ch = lambda d: d.get("final") or d.get("char") or d.get("admit") or d.get("ch")  # noqa: E731
    chan = lambda d: str(d.get("channel") or d.get("lane") or "")  # noqa: E731
    both = sorted(set(A) & set(B))
    diff = [k for k in both if ch(A[k]) != ch(B[k])]
    iron = [k for k in diff if "iron" in chan(A[k]) or "iron" in chan(B[k])]
    rare = [k for k in diff if "rare" in chan(A[k]) or "rare" in chan(B[k])]
    other = [k for k in diff if k not in set(iron) | set(rare)]
    msg = (f"共同格 {len(both)}；仅一边有 {len(set(A) ^ set(B))}；最终字不同 {len(diff)}（iron {len(iron)}／rare_ref {len(rare)}／其它 {len(other)}）"
           f"；其它差异示例 {other[:5]}；iron 示例 {iron[:5]}")
    return ("V14", "重放一致性", FAIL if other else (WARN if (iron or rare) else PASS), msg)


# ───────────────────────── selftest ─────────────────────────
def cmd_selftest(a) -> int:
    """故意弄坏 4 处，V3/V7/V9/V2 必须各自 FAIL；全在临时目录里弄，不碰真产物和真工作区。"""
    ws, book = Path(a.workspace), a.book
    pr = Path(a.products_dir) if a.products_dir else products_root()
    tmp = Path(tempfile.mkdtemp(prefix="freeze_selftest_"))
    try:
        base = tmp / "F"
        ns = argparse.Namespace(workspace=str(ws), book=book, products_dir=str(pr), out=str(base), id="F0", by="selftest",
                                approved_by=None, note="selftest", rehearsal=True, snap_branch=None, snap_commit=None,
                                snap_manifest_sha=None, ref_snapshot_yaml_sha=None, cache_hash=False, deliverable=None)
        cmd_build(ns)
        # 工作区副本：只拷 books/ feedback/events config/crop_exclusions.jsonl corpus（缓存、库用原件，只读）
        w2 = tmp / "ws"
        (w2 / "books").mkdir(parents=True)
        shutil.copy2(ws / "books" / f"{book}.yaml", w2 / "books")
        for sub in ("feedback/events", "corpus", "cache", "output", "config"):
            s = ws / sub
            if s.exists():
                (w2 / sub).parent.mkdir(parents=True, exist_ok=True)
                os.symlink(s, w2 / sub)
        ck = argparse.Namespace(pkg=str(base), workspace=str(w2), products_dir=str(pr), skip_status=True, timeout=600,
                                replay=None, frozen=None, save_status=None)
        ok = True

        def run(label, want, setup):
            nonlocal ok
            import io
            from contextlib import redirect_stdout
            undo = setup()
            buf = io.StringIO()
            with redirect_stdout(buf):
                cmd_check(ck)
            txt = buf.getvalue()
            got = re.search(rf"^{want}\s+(\w+)", txt, re.M).group(1)
            print(f"  [{'OK' if got == FAIL else '未抓到'}] {label} → {want} {got}")
            ok &= got == FAIL
            if undo:
                undo()

        print("基线（未弄坏）：")
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            cmd_check(ck)
        print("\n".join("  " + l for l in buf.getvalue().splitlines() if re.match(r"^V\d+", l)))
        print("故意弄坏：")
        # V3：改工作区 yaml 一个键
        y = w2 / "books" / f"{book}.yaml"
        orig = y.read_bytes()
        run("改 yaml 一个键", "V3", lambda: (y.write_bytes(orig + b"\nselftest_key: 1\n"), lambda: y.write_bytes(orig))[1])
        # V7：改一个外部状态文件（拷贝一份 corpus 文件，改一字节后换掉链接）
        cdir = w2 / "corpus"
        files = sorted(Path(ws / "corpus").glob("*.txt"))
        if files:
            def s7():
                os.unlink(cdir)
                shutil.copytree(ws / "corpus", cdir, symlinks=True)
                f = cdir / files[0].name
                f.write_bytes(f.read_bytes() + b"x")
                def u():
                    shutil.rmtree(cdir)
                    os.symlink(ws / "corpus", cdir)
                return u
            run("改一个字表语料文件（外部状态）", "V7", s7)
        else:
            print("  [跳过] V7：该工作区没有 corpus/*.txt")
        # V9：删 events 一行
        evd = ws / "feedback" / "events"
        evf = sorted(evd.glob("*.jsonl"))
        evf = [p for p in evf if p.stat().st_size > 0]
        if evf:
            def s9():
                os.unlink(w2 / "feedback" / "events")
                shutil.copytree(evd, w2 / "feedback" / "events")
                p = w2 / "feedback" / "events" / evf[0].name
                lines = p.read_bytes().splitlines(True)
                p.write_bytes(b"".join(lines[1:]))
                def u():
                    shutil.rmtree(w2 / "feedback" / "events")
                    os.symlink(evd, w2 / "feedback" / "events")
                return u
            run("删一行人裁事件", "V9", s9)
        else:
            print("  [跳过] V9：该工作区没有 feedback/events/*.jsonl")
        # V2：改一个产物字节（在临时产物树里，真产物不动）
        pt = tmp / "prod"
        shutil.copytree(pr / book, pt / book, symlinks=True, copy_function=lambda s, d: os.symlink(os.path.abspath(s), d))
        first = next(p for p in sorted((pt / book).glob("*/p*.json")) if p.is_symlink())
        real = Path(os.readlink(first))
        os.unlink(first)
        shutil.copy2(real, first)
        first.write_bytes(first.read_bytes() + b" ")
        ck.products_dir = str(pt)
        run(f"改一个产物字节（{first.parent.name}/{first.name}，临时树）", "V2", lambda: None)
        print("自测：" + ("全部抓到" if ok else "有漏抓，见上"))
        return 0 if ok else 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="从工作区＋产物根生成冻结包目录（只读，产物不拷）")
    b.add_argument("book")
    b.add_argument("-w", "--workspace", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--products-dir")
    b.add_argument("--id", default="F0")
    b.add_argument("--by", default="")
    b.add_argument("--approved-by", default=None)
    b.add_argument("--note", default="")
    b.add_argument("--rehearsal", action="store_true", help="演练，非交付")
    b.add_argument("--ref-snapshot-yaml-sha", help="参照快照的 book_yaml_sha256（只提示差异，不判败；正式交付冻结才要求一致）")
    b.add_argument("--snap-branch")
    b.add_argument("--snap-commit")
    b.add_argument("--snap-manifest-sha")
    b.add_argument("--cache-hash", action="store_true", help="缓存逐文件内容哈希（默认只记文件名＋大小）")
    b.add_argument("--deliverable", action="append", help="交付物路径或 glob，可多次")
    c = sub.add_parser("check", help="V1–V14 逐项校验（只读）")
    c.add_argument("pkg")
    c.add_argument("-w", "--workspace", required=True)
    c.add_argument("--products-dir")
    c.add_argument("--skip-status", action="store_true")
    c.add_argument("--timeout", type=int, default=900)
    c.add_argument("--save-status")
    c.add_argument("--replay")
    c.add_argument("--frozen")
    s = sub.add_parser("selftest", help="脚本自测：4 个故意弄坏用例")
    s.add_argument("book")
    s.add_argument("-w", "--workspace", required=True)
    s.add_argument("--products-dir")
    a = ap.parse_args(argv)
    return {"build": cmd_build, "check": cmd_check, "selftest": cmd_selftest}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
