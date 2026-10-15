# -*- coding: utf-8 -*-
"""GUJI-208kl：用 Elena 的 make_mini_roots.py（14 种情形）对比旧／新两版比对脚本，输出对照表。纯自造数据，只读脚本。
用法：python run_v2_cases.py <输出目录> <旧w5> <旧compare> <新w5_v2> <新compare_v2> <make_mini_roots.py所在目录>"""
import shutil, subprocess, sys
from pathlib import Path

out, ow5, ocm, nw5, ncm, mdir = sys.argv[1], *sys.argv[2:5], sys.argv[5], sys.argv[6]
sys.path.insert(0, mdir)
import make_mini_roots as M

out = Path(out)
if out.exists():
    shutil.rmtree(out)


def run(cmd):
    p = subprocess.run([sys.executable, *cmd], capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


print("| 情形 | 脚本 | 旧 rc | 新 rc | 变化 |\n|---|---|---|---|---|")
detail = []
for name, (a, b) in M.case_defs().items():
    root = out / name
    M.write(root / "base", a)
    if name.startswith("c11"):
        M.write(root / "new", b, indent=2, sort=True)
    else:
        M.write(root / "new", b)
    books = ["vol04", "vol05"] if not name.startswith("c12") else ["vol99"]
    B, N = str(root / "base"), str(root / "new")
    runs = [("w5", [ow5, B, N, *books], [nw5, B, N, *books]),
            ("w5 --sha256", None, [nw5, B, N, *books, "--sha256"]),
            ("compare 无strip(单册=原写法)", [ocm, B, N, books[0]], [ncm, B, N, books[0]]),
            ("compare --strip", [ocm, B, N, books[0], "--strip-demoted-from"], [ncm, B, N, books[0], "--strip-demoted-from"]),
            ("compare 多册 vol04 vol05", None, [ncm, B, N, *books]),
            ("compare --sha256", None, [ncm, B, N, books[0], "--sha256"])]
    for label, oc, nc in runs:
        o = run(oc) if oc else None
        n = run(nc)
        chg = "" if o is None else ("—" if o[0] == n[0] else f"**{o[0]}→{n[0]}**")
        print(f"| {name} | {label} | {o[0] if o else '（新增）'} | {n[0]} | {chg} |")
        detail.append(f"=== {name} · {label}\n  新 rc={n[0]}  {n[1][:400]!r}")
print("\n## 新脚本输出明细\n" + "\n".join(detail))
