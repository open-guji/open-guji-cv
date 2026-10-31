"""切分样页对比（切分模块化第 4 步，2026-10-30）：改了哪套书的切分，就在那套书的样页上跑改前、改后两版，逐页比产物。

每套书一份样页单 `open_guji_cv/books/<套书>/samples.yaml`（哪几册、哪几页、每页为什么在单上）。
改 `books/<套书>/` 只比那一套；改共用原语 `seg/`、Step 壳这些各套书都用的代码，就比全部套书。

    # 这次改动（相对 origin/dev）牵动哪几套书：按各套书切分步的指纹模块及其 import 闭包算
    python scripts/seg_samples.py affected --base origin/dev

    # 看样页单
    python scripts/seg_samples.py list [--set siku_zongmu]

    # 往任务库交单（云端执行方跑）：每册两条——改前那版 rerun 存包，改后那版 ab 跟它比（报告在 guji job show）
    export GUJI_JOBS_WHO=A22
    python scripts/seg_samples.py submit --set affected --base origin/dev --cv claude/my-branch --why "…" [--dry-run]

    # 本机跑（数据不在 guji-workspace 的书，如北行日錄现代本 bxrl）：两版各跑进私有产物目录再逐页比
    python scripts/seg_samples.py local --set beixing --base origin/dev --ws bxrl=D:/workspace/beixingrilu-workspace

`submit` 的两条单都从 main 包铺底、只重跑样页、`--force`；改前那条同配置跑过就复用（任务库按指纹去重）。
`local` 的做法同 `scripts/code_equiv.py check`：`git worktree` 检出 `--base`，产物目录各拷一份本册的，
缓存各用一个空目录，分别 `guji pipeline <管线> <册> --from … --to … --pages …`，再按 `parallel_equivalence.compare`
逐步逐页比 sha256。只说「哪些页变了」，变得对不对要人看图。
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PKG = "open_guji_cv"
BOOKS = ROOT / PKG / "books"


# ── 样页单 ──────────────────────────────────────────────

def sample_path(seg_set: str) -> Path:
    return BOOKS / seg_set / "samples.yaml"


def load_samples(seg_set: str) -> dict:
    """读一套书的样页单并校验。返回 {pipeline, steps: {from, to}, local_only, books: [{book, ws_glob, pages: {页: 理由}}]}。"""
    import yaml
    from open_guji_cv.core.pipeline import PIPELINES_DIR
    d = yaml.safe_load(sample_path(seg_set).read_text(encoding="utf-8")) or {}
    # 只读管线 yaml 的步骤表，不走 load_pipeline 的上下游校验：管线本身坏了也要能列出样页、算牵动
    pl = SimpleNamespace(id=d["pipeline"], steps=[str(x) for x in yaml.safe_load(
        (PIPELINES_DIR / f"{d['pipeline']}.yaml").read_text(encoding="utf-8"))["steps"]])
    st = d.get("steps") or {}
    lo, hi = st.get("from"), st.get("to")
    if lo not in pl.steps or hi not in pl.steps or pl.steps.index(lo) > pl.steps.index(hi):
        raise ValueError(f"{seg_set} 样页单的 steps {st} 不是管线 {pl.id} 里的一段")
    books = []
    for b in d.get("books") or []:
        pages = {int(k): str(v) for k, v in (b.get("pages") or {}).items()}
        if not b.get("book") or not pages:
            raise ValueError(f"{seg_set} 样页单里有一册缺 book 或 pages：{b}")
        books.append({"book": str(b["book"]), "ws_glob": b.get("ws_glob"), "ws_repo": b.get("ws_repo"),
                      "pages": pages, "note": b.get("note", "")})
    return {"pipeline": pl.id, "steps": {"from": lo, "to": hi}, "local_only": bool(d.get("local_only")),
            "books": books, "step_ids": pl.steps[pl.steps.index(lo):pl.steps.index(hi) + 1]}


def all_sets() -> tuple[str, ...]:
    from open_guji_cv.core.seg_set import SEG_SETS
    return SEG_SETS


def pages_arg(pages: dict[int, str]) -> str:
    return ",".join(str(p) for p in sorted(pages))


# ── 改动牵动哪几套书 ─────────────────────────────────────

def _module_file(mod: str) -> Path | None:
    p = ROOT / (mod.replace(".", "/") + ".py")
    if p.is_file():
        return p
    p = ROOT / mod.replace(".", "/") / "__init__.py"
    return p if p.is_file() else None


def _imports(mod: str) -> set[str]:
    """一个模块在包内 import 的模块（相对、绝对都算；`from pkg import 子模块` 也算）。"""
    f = _module_file(mod)
    if f is None:
        return set()
    pkg = mod if f.name == "__init__.py" else mod.rsplit(".", 1)[0]
    out = set()
    for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg.split(".")
                base = ".".join(base[:len(base) - (node.level - 1)] + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            if not base.startswith(PKG):
                continue
            out.add(base)
            out.update(f"{base}.{a.name}" for a in node.names if _module_file(f"{base}.{a.name}"))
        elif isinstance(node, ast.Import):
            out.update(a.name for a in node.names if a.name.startswith(PKG))
    return {m for m in out if _module_file(m)}


#: 只顺着 import 追进这两处：切分代码都在这里。全包闭包没有意义——Step 壳经 core／steps 包能间接 import 到几乎所有模块。
_FOLLOW = (f"{PKG}.seg", f"{PKG}.books")


def set_modules(seg_set: str) -> set[str]:
    """一套书的切分步（样页单 steps 那一段）跑到的代码：指纹模块（按套书换过），加上从它们出发、
    只在 seg／books 里追的 import 闭包（指纹没列、但实际调到的原语也算）。"""
    import open_guji_cv.steps  # noqa: F401
    from open_guji_cv.core.seg_set import replace_deps
    from open_guji_cv.core.step import STEPS
    book = SimpleNamespace(seg_set=seg_set)
    todo = []
    for sid in load_samples(seg_set)["step_ids"]:
        st = STEPS[sid]
        todo += replace_deps(book, [type(st).__module__, *st.spec.code_deps])
    seen: set[str] = set()
    while todo:
        m = todo.pop()
        if m in seen:
            continue
        seen.add(m)
        todo += [x for x in _imports(m) if x.startswith(_FOLLOW)]
    return seen


def changed_modules(base: str) -> set[str]:
    out = subprocess.run(["git", "-C", str(ROOT), "diff", "--name-only", base, "--", PKG],
                         capture_output=True, text=True, check=True).stdout
    mods = set()
    for ln in out.splitlines():
        if ln.endswith(".py"):
            parts = Path(ln).with_suffix("").parts
            mods.add(".".join(parts[:-1] if parts[-1] == "__init__" else parts))
        elif ln.endswith("/samples.yaml"):
            mods.add(".".join(Path(ln).parts[:-1]) + ".__samples__")
    return mods


def affected_sets(base: str) -> dict[str, list[str]]:
    """{套书: [牵动它的改动模块]}；改了某套书的样页单也算牵动那一套。"""
    ch = changed_modules(base)
    out = {}
    for s in all_sets():
        hit = sorted(ch & set_modules(s)) + sorted(m for m in ch if m == f"{PKG}.books.{s}.__samples__")
        if hit:
            out[s] = hit
    return out


def _resolve_sets(arg: str, base: str) -> list[str]:
    if arg == "all":
        return list(all_sets())
    if arg == "affected":
        return list(affected_sets(base))
    names = [s for s in arg.split(",") if s]
    bad = [s for s in names if s not in all_sets()]
    if bad:
        sys.exit(f"✗ 没有这套书：{bad}，可选 {list(all_sets())}、all、affected")
    return names


# ── 命令 ────────────────────────────────────────────────

def cmd_list(a) -> int:
    for s in _resolve_sets(a.set, a.base):
        d = load_samples(s)
        n = sum(len(b["pages"]) for b in d["books"])
        flag = "（只能本机跑）" if d["local_only"] else ""
        print(f"== {s}：{d['pipeline']} {d['steps']['from']}→{d['steps']['to']}，{len(d['books'])} 册 {n} 页{flag}")
        for b in d["books"]:
            print(f"  {b['book']}  --pages {pages_arg(b['pages'])}" + (f"  （{b['note']}）" if b["note"] else ""))
            for p, why in sorted(b["pages"].items()):
                print(f"      p{p}：{why}")
    return 0


def cmd_affected(a) -> int:
    hit = affected_sets(a.base)
    if not hit:
        print(f"相对 {a.base} 的改动不碰任何一套书的切分代码")
        return 0
    for s, mods in hit.items():
        print(f"{s}：{'、'.join(m.removeprefix(PKG + '.') for m in mods[:8])}" + ("…" if len(mods) > 8 else ""))
    print("交单：python scripts/seg_samples.py submit --set " + ",".join(hit) + f" --base {a.base} --cv <改后的分支> --why …")
    return 0


def job_specs(seg_set: str, base_cv: str, new_cv: str, why: str) -> list[tuple[dict, dict]]:
    """每册一对：(改前 rerun 存包, 改后 ab 跟改前那条比)。ab 的 compare_to 在交单时填改前那条的号。"""
    d = load_samples(seg_set)
    pairs = []
    for b in d["books"]:
        common = {"book": b["book"], "pipeline": d["pipeline"], "steps": dict(d["steps"]),
                  "pages": pages_arg(b["pages"]), "base": "main"}
        if b["ws_glob"]:
            common["ws_glob"] = b["ws_glob"]
        if b["ws_repo"]:
            common["ws_repo"] = b["ws_repo"]
        old = {**common, "kind": "rerun", "cv": base_cv, "why": f"切分样页对比 {seg_set} 改前（{why}）",
               "output": {"change": f"segsamples-{seg_set}-before", "pack": True}}
        new = {**common, "kind": "ab", "cv": new_cv, "why": f"切分样页对比 {seg_set} 改后（{why}）",
               "output": {"change": f"segsamples-{seg_set}-after", "pack": False}}
        pairs.append((old, new))
    return pairs


def cmd_submit(a) -> int:
    from open_guji_cv.jobs import spec as SP
    sets = _resolve_sets(a.set, a.base)
    if not sets:
        print("没有要比的套书")
        return 0
    db = S = None
    if not a.dry_run:
        from open_guji_cv.jobs import store as S
        db = S.DB()
    rows = []
    for s in sets:
        if load_samples(s)["local_only"]:
            print(f"跳过 {s}：书不在 guji-workspace，只能本机跑（seg_samples.py local --set {s} …）")
            continue
        for old, new in job_specs(s, a.base_cv or a.base, a.cv, a.why):
            o = SP.normalize(old)
            if a.dry_run:
                n = SP.normalize({**new, "compare_to": {"job": 0}})
                print(json.dumps({"before": o, "after": n}, ensure_ascii=False))
                continue
            r = db(S.submit, o, SP.spec_hash(o), by=S.who(), why=o.get("why"), priority=a.priority)
            oid = r["duplicate_of"] or r["id"]
            n = SP.normalize({**new, "compare_to": {"job": oid}})
            r2 = db(S.submit, n, SP.spec_hash(n), by=S.who(), why=n.get("why"), priority=a.priority,
                    depends_on=[oid])
            rows.append((s, old["book"], oid, r2["id"]))
            print(f"{s} {old['book']}：改前 #{oid}" + ("（复用）" if r["duplicate_of"] else "") + f"，改后 #{r2['id']}")
    if rows:
        print("看结果：guji job show <改后的号>（「对比」一栏是和改前逐页比的报告）")
    return 0


def _run_pipeline(code_root: Path, pipeline: str, book: str, steps: dict, pages: str, ws: str,
                  products: Path, cache: Path, jobs: int, log: Path) -> int:
    env = dict(os.environ, PYTHONPATH=str(code_root), GUJI_PRODUCTS_DIR=str(products),
               GUJI_CACHE_DIR=str(cache), GUJI_WORKSPACE=ws, PYTHONIOENCODING="utf-8")
    argv = ["guji", "pipeline", pipeline, book, "-w", ws, "--pages", pages, "--from", steps["from"],
            "--to", steps["to"], "--force", "--no-pack", "--jobs", str(jobs), "--allow-cv-mismatch",
            "--why", "seg_samples：私有产物目录里比两版切分代码"]
    code = f"import sys; sys.argv = {argv!r}; from open_guji_cv.cli_v2 import main; main()"
    with open(log, "w", encoding="utf-8") as fh:
        return subprocess.run([sys.executable, "-c", code], cwd=str(code_root), env=env,
                              stdout=fh, stderr=subprocess.STDOUT).returncode


def cmd_local(a) -> int:
    from scripts.parallel_equivalence import compare
    ws_of = dict(x.split("=", 1) for x in a.ws)
    work = Path(a.workdir or tempfile.mkdtemp(prefix="seg_samples_"))
    base_tree = work / "base_tree"
    if base_tree.exists():
        subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(base_tree)], check=False)
    subprocess.run(["git", "-C", str(ROOT), "worktree", "add", "--detach", str(base_tree), a.base],
                   check=True, capture_output=True)
    bad = ran = 0
    try:
        for s in _resolve_sets(a.set, a.base):
            d = load_samples(s)
            for b in d["books"]:
                book, ws = b["book"], ws_of.get(b["book"])
                if not ws:
                    print(f"跳过 {s} {book}：没给 --ws {book}=<工作区>")
                    continue
                src = Path(a.products or Path(ws) / "products") / book
                rcs = {}
                for side, code_root in (("old", base_tree), ("new", ROOT)):
                    prod, cache = work / s / book / side / "products", work / s / book / side / "cache"
                    shutil.rmtree(prod.parent, ignore_errors=True)
                    if src.is_dir():
                        shutil.copytree(src, prod / book)
                    else:
                        prod.mkdir(parents=True)
                    cache.mkdir(parents=True)
                    print(f"{s} {book} 跑{'改前' if side == 'old' else '改后'}…", flush=True)
                    rcs[side] = _run_pipeline(code_root, d["pipeline"], book, d["steps"], pages_arg(b["pages"]),
                                              ws, prod, cache, a.jobs, work / s / book / f"{side}.log")
                ran += 1
                if any(rcs.values()):
                    print(f"  ✗ 跑批失败 {rcs}，日志在 {work / s / book}")
                    bad += 1
                    continue
                rep = compare(work / s / book / "old" / "products", work / s / book / "new" / "products", book,
                              d["step_ids"])
                for sid in d["step_ids"]:
                    r = rep[sid]
                    changed = r["diff"] + r["only_a"] + r["only_b"]
                    print(f"  {sid}：{r['same']} 页相同" + (f"，变了 {', '.join(changed)}" if changed else ""))
                    bad += bool(changed)
        if not ran:
            print("✗ 一册也没跑（--ws 没给对？）")
            return 1
        print(f"✓ {ran} 册样页全部逐字节相同" if not bad else f"有 {bad} 处变化或失败，产物在 {work}，变了的页要看图判对错")
        return 1 if bad else 0
    finally:
        if not a.keep:
            subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(base_tree)], check=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list")
    p.add_argument("--set", default="all")
    p.add_argument("--base", default="origin/dev")
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("affected")
    p.add_argument("--base", default="origin/dev")
    p.set_defaults(fn=cmd_affected)
    p = sub.add_parser("submit")
    p.add_argument("--set", default="affected", help="套书名（逗号分隔）、all 或 affected（缺省）")
    p.add_argument("--base", default="origin/dev", help="改前的 commit／分支（affected 也按它算）")
    p.add_argument("--base-cv", default=None, help="改前那版交给任务库的 cv 引用（缺省 --base 指着的提交）")
    p.add_argument("--cv", required=True, help="改后的分支／提交（要已推到 GitHub）")
    p.add_argument("--why", required=True)
    p.add_argument("--priority", type=int, default=100)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_submit)
    p = sub.add_parser("local")
    p.add_argument("--set", default="affected")
    p.add_argument("--base", default="origin/dev")
    p.add_argument("--ws", action="append", default=[], help="<册>=<工作区目录>，可多次")
    p.add_argument("--products", default=None, help="产物根（缺省 <工作区>/products）")
    p.add_argument("--jobs", type=int, default=1)
    p.add_argument("--workdir", default=None)
    p.add_argument("--keep", action="store_true", help="留着改前那版的检出")
    p.set_defaults(fn=cmd_local)
    a = ap.parse_args(argv)
    if a.cmd == "submit" and a.base_cv is None:      # 改前那版钉成 --base 当前指着的提交（要已推到 GitHub）
        a.base_cv = subprocess.run(["git", "-C", str(ROOT), "rev-parse", a.base + "^{commit}"], capture_output=True, text=True,
                                   check=True).stdout.strip()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
