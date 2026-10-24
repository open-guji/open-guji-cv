"""代码等价登记的校验与出登记行（见 `open_guji_cv/core/code_equiv.py`）。

    # 某模块在某个 commit／工作区的「只认代码」哈希
    python scripts/code_equiv.py hash open_guji_cv.clustering.match [--rev origin/main]

    # 旧版本（--base）与工作区现版本在同一批页上各跑一遍这一步，产物逐页 sha256 全同才打印登记行
    python scripts/code_equiv.py check --base origin/main --step glyph_match --book vol04 \\
        --pages 5,10,15 -w $WS --products <已有上游产物的产物根> --cache <缓存根> --jobs 4

`check` 的做法：
1. 列出这一步的模块（Step 模块 + `code_deps`）里，`--base` 与工作区「只认代码」哈希不同的；
2. `git worktree add` 一份 `--base` 的检出；
3. 把 `--products`／`--cache` 各拷两份（旧、新），删掉这一步自己的旧产物（免得格级复用搬旧记录），
   分别用旧代码（`PYTHONPATH=<检出>`）与现代码跑 `guji step <step>`；
4. 逐页比这一步产物的 sha256（`scripts/parallel_equivalence.py`）。全同才打印 `Equiv(...)` 登记行，
   贴进 `open_guji_cv/core/code_equiv.py::ENTRIES`。任何一页不同就报出来、退出码 1。

只证明「这一批页上逐字节相同」，页要挑得够杂，见 `core/code_equiv.py` 的纪律。
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _module_path(mod: str) -> str:
    return mod.replace(".", "/") + ".py"


def code_hash_at(mod: str, rev: str | None) -> str:
    """模块在 `rev`（None = 工作区）的「只认代码」哈希，未经等价登记换算。"""
    from open_guji_cv.core.engine import code_only_text
    rel = _module_path(mod)
    if rev is None:
        src = (ROOT / rel).read_text(encoding="utf-8")
    else:
        src = subprocess.run(["git", "-C", str(ROOT), "show", f"{rev}:{rel}"], check=True,
                             capture_output=True).stdout.decode("utf-8")
    return hashlib.sha256(code_only_text(src).encode("utf-8")).hexdigest()


def step_modules(step_id: str) -> list[str]:
    import open_guji_cv.steps  # noqa: F401
    from open_guji_cv.core.step import STEPS
    st = STEPS[step_id]
    return [type(st).__module__, *st.spec.code_deps]


def _run_step(code_root: Path, step: str, book: str, pages: str, ws: str, products: Path,
              cache: Path, jobs: int, log: Path) -> int:
    env = dict(os.environ, PYTHONPATH=str(code_root), GUJI_PRODUCTS_DIR=str(products),
               GUJI_CACHE_DIR=str(cache), GUJI_WORKSPACE=ws, PYTHONIOENCODING="utf-8")
    argv = ["guji", "step", step, book, "-w", ws, "--pages", pages, "--jobs", str(jobs),
            "--allow-cv-mismatch", "--why", "code_equiv：私有产物目录里比两版代码"]
    code = f"import sys; sys.argv = {argv!r}; from open_guji_cv.cli_v2 import main; main()"
    with open(log, "w", encoding="utf-8") as fh:
        return subprocess.run([sys.executable, "-c", code], cwd=str(code_root), env=env,
                              stdout=fh, stderr=subprocess.STDOUT).returncode


def cmd_hash(args) -> int:
    print(code_hash_at(args.module, args.rev))
    return 0


def cmd_check(args) -> int:
    from open_guji_cv.core.code_equiv import canonical
    mods = step_modules(args.step)
    changed = []
    for m in mods:
        old, new = code_hash_at(m, args.base), code_hash_at(m, None)
        if old != new:
            changed.append((m, new, canonical(m, old)))
    if not changed and not args.always:
        print(f"{args.step} 的模块（{len(mods)} 个）在 {args.base} 与工作区之间代码没变，不用登记"
              "（改的是指纹外的代码、也要比产物时加 --always）")
        return 0
    print("代码变了的模块：" + ("、".join(m for m, _, _ in changed) or "（无，--always 照样比产物）"))

    work = Path(args.workdir or tempfile.mkdtemp(prefix="code_equiv_"))
    work.mkdir(parents=True, exist_ok=True)
    base_tree = work / "base_tree"
    if base_tree.exists():
        subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(base_tree)],
                       check=False)
    subprocess.run(["git", "-C", str(ROOT), "worktree", "add", "--detach", str(base_tree), args.base],
                   check=True, capture_output=True)
    try:
        rcs = {}
        for name, code_root in (("old", base_tree), ("new", ROOT)):
            prod, cache = work / name / "products", work / name / "cache"
            for src, dst in ((args.products, prod), (args.cache, cache)):
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            shutil.rmtree(prod / args.book / args.step, ignore_errors=True)
            print(f"跑 {name}（{code_root}）…", flush=True)
            rcs[name] = _run_step(code_root, args.step, args.book, args.pages, args.workspace,
                                  prod, cache, args.jobs, work / f"{name}.log")
        if any(rcs.values()):
            print(f"✗ 跑批失败：{rcs}，日志在 {work}/old.log、new.log")
            return 1
        from scripts.parallel_equivalence import compare
        rep = compare(work / "old" / "products", work / "new" / "products", args.book, [args.step])[args.step]
        if rep["diff"] or rep["only_a"] or rep["only_b"] or rep["same"] == 0:
            print(f"✗ 不等价：相同 {rep['same']} 页，不同 {rep['diff']}，只在旧 {rep['only_a']}，只在新 {rep['only_b']}")
            return 1
        print(f"✓ {args.step} {args.book} {rep['same']} 页产物逐字节相同。" + ("登记行：\n" if changed else "（指纹没变，不用登记）"))
        ev = (f"{args.step} 在 {args.book} {rep['same']} 页（--pages {args.pages}）上与 "
              f"{args.base} 产物逐字节相同；{args.note}".rstrip("；"))
        for m, new, old in changed:
            print(f"    Equiv(module={m!r},\n          new={new!r},\n          old={old!r},\n"
                  f"          evidence={ev!r}),")
        return 0
    finally:
        if not args.keep:
            subprocess.run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(base_tree)],
                           check=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    h = sub.add_parser("hash")
    h.add_argument("module")
    h.add_argument("--rev", default=None)
    c = sub.add_parser("check")
    c.add_argument("--base", required=True, help="改动之前的 commit／分支")
    c.add_argument("--step", required=True)
    c.add_argument("--book", required=True)
    c.add_argument("--pages", required=True)
    c.add_argument("-w", "--workspace", required=True)
    c.add_argument("--products", type=Path, required=True, help="已有这一步上游产物的产物根")
    c.add_argument("--cache", type=Path, required=True, help="缓存根（会整份拷两次）")
    c.add_argument("--jobs", type=int, default=1)
    c.add_argument("--workdir", default=None)
    c.add_argument("--note", default="", help="附进 evidence 的说明（比如页的来历）")
    c.add_argument("--keep", action="store_true", help="留着基线检出")
    c.add_argument("--always", action="store_true",
                   help="这一步的指纹模块没变也照样跑两遍比产物（改的是 feedback/ 之类指纹外的代码时用）")
    args = ap.parse_args(argv)
    return {"hash": cmd_hash, "check": cmd_check}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
