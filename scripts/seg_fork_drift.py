"""套书分叉副本漂移检查（2026-11-06，三套书切分可共用盘点）。

套书从殿本复制一个模块改成自己的（`core/seg_set.OVERRIDES`）以后，两份各走各的。殿本那份之后修了 bug，
副本不会自动得到；这里逐个顶层函数／类比一下，提醒两边的负责人看要不要跟。

对 OVERRIDES 里每一对（原模块 → 套书副本）：
- 分叉点 = git 里副本文件第一次出现的提交；取那一刻原模块的源码当「分叉时」。
- 逐个顶层名字比三份：分叉时的原模块、现在的原模块、现在的副本（比的是去掉注释与 docstring 后的代码，
  同 `engine.code_only_text`）。
- 报三类：**原模块改了、副本没跟**（最该看）；两边都改了且不同；只在一边有的名字（只列数）。

**2026-11-09 起 OVERRIDES 已空**：史記、全唐文的副本搬去各自书仓 `code/`（`core/book_code.py`）。书仓用 `--ws <书仓>`
（2026-11-12 A22，《切分三方向》第 6 步）：读书仓 `code/code.yaml` 的 overrides，分叉点取「书仓里这个文件第一次提交的时间」
那一刻 cv 本仓（当前分支）上缺省模块的源码（缺省模块那时还在旧位置的，按 `code_equiv.MOVED` 往回找旧路径），
再照上面三份比。书仓文件若是从 cv 里的套书副本搬过去的，分叉点会偏晚（漏报更早的漂移），报告里写明分叉时刻。

只提示、不拦（退出码恒 0；`--strict` 时有「原模块改了、副本没跟」就退 1）。

    python scripts/seg_fork_drift.py            # 全部套书
    python scripts/seg_fork_drift.py --set quantangwen
    python scripts/seg_fork_drift.py --json
    python scripts/seg_fork_drift.py --ws <书仓工作区>      # 书仓 code/ 的覆盖模块 vs cv 缺省实现

要 git 历史够深（浅克隆先 `git fetch --depth=1000 origin dev`）；找不到分叉点的那一对报出来、跳过。
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from open_guji_cv.core.engine import code_only_text  # noqa: E402
from open_guji_cv.core.seg_set import OVERRIDES  # noqa: E402


def _path(mod: str) -> str:
    return mod.replace(".", "/") + ".py"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8").stdout


def _defs(src: str) -> dict[str, str]:
    """顶层函数／类／常量赋值 → 去注释、去 docstring 后的代码文本。"""
    out: dict[str, str] = {}
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    lines = src.splitlines(keepends=True)
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = n.name
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            tgt = n.targets[0] if isinstance(n, ast.Assign) else n.target
            if not isinstance(tgt, ast.Name):
                continue
            name = tgt.id
        else:
            continue
        start = min([d.lineno for d in getattr(n, "decorator_list", [])] + [n.lineno])
        seg = "".join(lines[start - 1:n.end_lineno])
        try:
            out[name] = code_only_text(seg)
        except Exception:  # 片段单独 tokenize 不了（极少）：退回原文
            out[name] = seg
    return out


def fork_point(fork_mod: str) -> str | None:
    shas = _git("log", "--diff-filter=A", "--format=%H", "--", _path(fork_mod)).split()
    return shas[-1] if shas else None


def drift(origin: str, fork: str) -> dict:
    fp = fork_point(fork)
    rec: dict = {"origin": origin, "fork": fork, "fork_commit": fp}
    if fp is None:
        rec["error"] = "git 里找不到副本第一次出现的提交（浅克隆？先 git fetch --depth=1000 origin dev）"
        return rec
    base = _defs(_git("show", f"{fp}:{_path(origin)}"))
    if not base:
        rec["error"] = f"分叉提交 {fp[:8]} 上读不到原模块"
        return rec
    now_o = _defs((ROOT / _path(origin)).read_text(encoding="utf-8"))
    now_f = _defs((ROOT / _path(fork)).read_text(encoding="utf-8"))
    not_ported, both, = [], []
    for name, b in base.items():
        o, f = now_o.get(name), now_f.get(name)
        if o is None or f is None:
            continue
        if o != b and f == b:
            not_ported.append(name)
        elif o != b and f != b and o != f:
            both.append(name)
    rec.update(not_ported=sorted(not_ported), both_changed=sorted(both),
               origin_only=len(set(now_o) - set(now_f)), fork_only=len(set(now_f) - set(now_o)))
    return rec


def _old_paths(mod: str) -> list[str]:
    """缺省模块现在的路径，加上它搬家前的旧路径（`code_equiv.MOVED` 沿链往回）。"""
    from open_guji_cv.core.code_equiv import MOVED
    out, seen = [mod], {mod}
    while mod in MOVED and MOVED[mod][0] not in seen:
        mod = MOVED[mod][0]
        out.append(mod)
        seen.add(mod)
    return [_path(m) for m in out]


def drift_book(ws: Path) -> list[dict]:
    """书仓 `code/` 的覆盖模块 vs cv 缺省实现（分叉点＝书仓文件第一次提交时刻的 cv 本仓）。"""
    from open_guji_cv.core.book_code import _parse, code_root
    root = code_root(ws)
    if root is None:
        return [{"error": f"{ws} 没有 code/code.yaml"}]
    bc = _parse(root)
    recs = []
    for origin, fork in bc.overrides.items():
        rel = fork[len(bc.pkg) + 1:].replace(".", "/") + ".py"
        f = root / rel
        rec: dict = {"seg_set": bc.name, "origin": origin, "fork": f"code/{rel}"}
        date = subprocess.run(["git", "log", "--diff-filter=A", "--follow", "--format=%cI", "--", rel], cwd=root,
                              capture_output=True, text=True, encoding="utf-8").stdout.split()
        if not date:
            rec["error"] = "书仓 git 里找不到这个文件第一次提交（没提交？）"
            recs.append(rec)
            continue
        cv_at = _git("rev-list", "-1", f"--before={date[-1]}", "HEAD").strip()
        rec["fork_commit"] = cv_at
        rec["fork_time"] = date[-1]
        base = {}
        for p in _old_paths(origin):
            base = _defs(_git("show", f"{cv_at}:{p}")) if cv_at else {}
            if base:
                break
        if not base:
            rec["error"] = f"cv {cv_at[:8] or '?'} 上读不到缺省模块（浅克隆？先 git fetch --depth=1000 origin dev）"
            recs.append(rec)
            continue
        now_o = _defs((ROOT / _path(origin)).read_text(encoding="utf-8"))
        now_f = _defs(f.read_text(encoding="utf-8"))
        not_ported, both = [], []
        for name, b in base.items():
            o, fk = now_o.get(name), now_f.get(name)
            if o is None or fk is None:
                continue
            if o != b and fk == b:
                not_ported.append(name)
            elif o != b and fk != b and o != fk:
                both.append(name)
        same = sorted(n for n in now_f if now_o.get(n) == now_f[n])
        rec.update(not_ported=sorted(not_ported), both_changed=sorted(both), identical=len(same),
                   origin_only=len(set(now_o) - set(now_f)), fork_only=len(set(now_f) - set(now_o)),
                   whole_same=bool(now_o) and now_o == now_f)
        recs.append(rec)
    return recs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", help="只看这一套书")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="有「原模块改了、副本没跟」就退 1")
    ap.add_argument("--ws", help="书仓工作区：比它 code/ 的覆盖模块与 cv 缺省实现")
    a = ap.parse_args(argv)
    recs = drift_book(Path(a.ws)) if a.ws else []
    for ss, pairs in ({} if a.ws else OVERRIDES).items():
        if a.set and ss != a.set:
            continue
        for origin, fork in pairs.items():
            recs.append({"seg_set": ss, **drift(origin, fork)})
    if a.json:
        print(json.dumps(recs, ensure_ascii=False, indent=1))
    else:
        for r in recs:
            head = f"[{r['seg_set']}] {r['fork'].rsplit('.', 1)[-1]} ← {r['origin'].rsplit('.', 2)[-2]}"
            if "error" in r:
                print(f"{head}: {r['error']}")
                continue
            print(f"{head}（分叉于 {r['fork_commit'][:8]}{'，' + r['fork_time'] if r.get('fork_time') else ''}）")
            if r.get("whole_same"):
                print("    与缺省实现逐个顶层名字都相同：这个覆盖可以去掉")
            print(f"    原模块改了、副本没跟：{', '.join(r['not_ported']) or '无'}")
            if r["both_changed"]:
                print(f"    两边都改了且不同：{', '.join(r['both_changed'])}")
            print(f"    只在原模块／只在副本的顶层名字：{r['origin_only']}／{r['fork_only']}")
    return 1 if a.strict and any(r.get("not_ported") for r in recs) else 0


if __name__ == "__main__":
    sys.exit(main())
