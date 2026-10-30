"""切分模块化的「搬家」工具（2026-10-30）：把模块原样搬进 `open_guji_cv/books/<套书>/`，改全仓 import，
并算出指纹不变所需的登记行（`core/code_equiv.py` 的 `MOVED` 与 `ENTRIES`）。

    # 在干净的工作区（已 checkout 到从 origin/dev 起的新分支）上：
    python scripts/seg_move.py move siku_zongmu row_boundaries row_grid jiazhu_split ...
    # 搬完后核登记：对 --base（缺省 origin/dev）每个被改过的模块算哈希，出登记行
    python scripts/seg_move.py register --base origin/dev

`move` 只做机械改写：git mv、搬走的文件里的相对 import 重算层数、全仓（open_guji_cv/tests/scripts/research）里指向
被搬模块的 import 与点号路径（`open_guji_cv.utils.x`）一并改。算法不动。搬完用 `register` 出登记行，再用
`tests/test_seg_move.py` 与 24 个 Step 的 `code_hash` 前后对比（见 PR 模板）证明指纹逐位不变。
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = "open_guji_cv"
SCAN = ("open_guji_cv", "tests", "scripts", "research")


def _mod_of(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _pkg_of(path: Path) -> str:
    m = _mod_of(path)
    return m if path.name == "__init__.py" else m.rsplit(".", 1)[0]


def _resolve(pkg: str, level: int, module: str | None) -> str:
    if not level:
        return module or ""
    base = pkg.split(".")
    base = base[: len(base) - (level - 1)]
    return ".".join(base + ([module] if module else []))


def _relative(from_pkg: str, target: str) -> str:
    """target 绝对模块名 → 从 from_pkg 出发的相对写法（`..x.y`）。"""
    a, b = from_pkg.split("."), target.split(".")
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return "." * (len(a) - i + 1) + ".".join(b[i:])


def _py_files():
    for d in SCAN:
        for p in (ROOT / d).rglob("*.py"):
            if ".venv" not in p.parts and "__pycache__" not in p.parts:
                yield p


def _rewrite_file(path: Path, old_pkg: str, new_pkg: str, rename: dict[str, str]) -> bool:
    """改一个文件里的 import。old_pkg/new_pkg：该文件搬家前后所在的包（没搬就相同）。"""
    src = path.read_text(encoding="utf-8")
    lines = src.split("\n")
    changed = False
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return False
    edits = []   # (lineno, old_spec, new_spec)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        base = _resolve(old_pkg, node.level, node.module)
        # from pkg import name（name 本身是被搬的模块）
        moved_names = [a.name for a in node.names if f"{base}.{a.name}" in rename]
        if moved_names and len(moved_names) == len(node.names):
            tgt = {rename[f"{base}.{a.name}"].rsplit(".", 1)[0] for a in node.names}
            if len(tgt) == 1:
                edits.append((node.lineno, node, tgt.pop()))
                continue
        new_base = rename.get(base, base)
        if new_base != base or old_pkg != new_pkg:
            edits.append((node.lineno, node, new_base))
    for lineno, node, new_base in sorted(edits, key=lambda e: -e[0]):
        line = lines[lineno - 1]
        m = re.match(r"^(\s*from\s+)(\.*)([\w.]*)(\s+import\b.*)$", line)
        if not m:
            print(f"!! 看不懂的 import 行 {path}:{lineno}: {line}", file=sys.stderr)
            continue
        spec = _relative(new_pkg, new_base) if node.level else new_base
        # 相对写法的 import 在包内保持相对；绝对写法保持绝对
        lines[lineno - 1] = f"{m.group(1)}{spec}{m.group(4)}"
        changed = True
    out = "\n".join(lines)
    # 点号路径（code_deps 字符串、monkeypatch、docstring 里的 `utils/x`）
    for old, new in rename.items():
        out2 = re.sub(rf"\b{re.escape(old)}\b", new, out)
        if out2 != out:
            out, changed = out2, True
        o_rel, n_rel = old[len(PKG) + 1:].replace(".", "/"), new[len(PKG) + 1:].replace(".", "/")
        out2 = re.sub(rf"(?<![\w/]){re.escape(o_rel)}(?=\.py|\b)", n_rel, out)
        if out2 != out:
            out, changed = out2, True
    if changed:
        path.write_text(out, encoding="utf-8")
    return changed


def cmd_move(args) -> None:
    rename: dict[str, str] = {}
    for m in args.modules:
        old = f"{PKG}.utils.{m}" if "." not in m else m
        name = old.rsplit(".", 1)[1]
        rename[old] = f"{PKG}.books.{args.seg_set}.{name}"
    dest = ROOT / "open_guji_cv" / "books" / args.seg_set
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "__init__.py").touch()
    moved_files: dict[Path, tuple[str, str]] = {}
    for old, new in rename.items():
        src = ROOT / (old.replace(".", "/") + ".py")
        dst = ROOT / (new.replace(".", "/") + ".py")
        subprocess.run(["git", "mv", str(src), str(dst)], check=True, cwd=ROOT)
        moved_files[dst] = (_pkg_of(src), _pkg_of(dst))
    n = 0
    for p in _py_files():
        old_pkg, new_pkg = moved_files.get(p, (_pkg_of(p), _pkg_of(p)))
        if p == Path(__file__).resolve():
            continue
        n += _rewrite_file(p, old_pkg, new_pkg, rename)
    print(f"搬了 {len(rename)} 个模块，改了 {n} 个文件")
    for old, new in rename.items():
        print(f"  {old} -> {new}")


def _raw_hash_text(text: str) -> str:
    import hashlib
    sys.path.insert(0, str(ROOT))
    from open_guji_cv.core.engine import code_only_text
    return hashlib.sha256(code_only_text(text).encode("utf-8")).hexdigest()


def cmd_register(args) -> None:
    """对每个在 base 与现在都存在（含搬家）、哈希不同的模块出 ENTRIES 行；对搬家的模块出 MOVED 行。"""
    out = subprocess.run(["git", "diff", "--name-status", "-M", args.base, "--", "open_guji_cv"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    moved, changed = [], []
    for ln in out.splitlines():
        parts = ln.split("\t")
        if parts[0].startswith("R"):
            moved.append((parts[1], parts[2]))
        elif parts[0] == "M" and parts[1].endswith(".py"):
            changed.append((parts[1], parts[1]))
    sys.path.insert(0, str(ROOT))
    import open_guji_cv.steps  # noqa: F401  注册各步
    from open_guji_cv.core.step import STEPS
    live = {m for st in STEPS.values() for m in (type(st).__module__, *st.spec.code_deps)}
    entries = []
    for old_p, new_p in moved + changed:
        if not (new_p.endswith(".py") and old_p.endswith(".py")):
            continue
        old_text = subprocess.run(["git", "show", f"{args.base}:{old_p}"], cwd=ROOT, capture_output=True,
                                  text=True, check=True).stdout
        new_text = (ROOT / new_p).read_text(encoding="utf-8")
        oh, nh = _raw_hash_text(old_text), _raw_hash_text(new_text)
        om, nm = _mod_of(ROOT / old_p), _mod_of(ROOT / new_p)
        if nm not in live:
            continue
        if (old_p, new_p) in moved:
            print(f'    "{nm}": ("{om}", "{oh}"),   # MOVED')
        if oh != nh:
            entries.append((nm, nh, oh))
    for nm, nh, oh in entries:
        print(f'    Equiv(module="{nm}",\n          new="{nh}",\n          old="{oh}",\n          evidence=_MV_XXX),   # ENTRIES')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("move")
    m.add_argument("seg_set")
    m.add_argument("modules", nargs="+")
    m.set_defaults(fn=cmd_move)
    r = sub.add_parser("register")
    r.add_argument("--base", default="origin/dev")
    r.set_defaults(fn=cmd_register)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
