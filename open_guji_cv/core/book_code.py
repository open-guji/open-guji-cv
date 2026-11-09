"""书级代码：各书工作区仓 `code/` 下自管的代码（2026-11-09，Sheldon 定，cv v0.7.0）。

代码只分两级：global（本仓 open-guji-cv：共用原语 `seg/`、Step 壳、三条版式的缺省实现）与书级（各书仓
`code/`）。书级代码有自己的整数版本号 `k<N>`，不跟 cv 一起发版。设计见 `doc/design/书级代码.md`。

## 书仓 `code/` 的样子

```
<工作区仓根>/code/
  code.yaml            name、base、cv 兼容段、overrides（缺省模块 → 本书模块）
  defaults.yaml        这套代码配套的参数缺省（同 books/<套书>/defaults.yaml 的 params:）
  samples.yaml         样页单
  equiv.yaml           本书自己登记的代码等价（moved / forked / entries，可选）
  *.py                 本书模块
  releases/k<N>.json   每版文件清单（路径 → sha256），只增不改
```

`code.yaml`：

```yaml
name: shiji_wyg          # 本书代码的名字＝册的 seg_set；进指纹的模块名是 guji_book.<name>.<模块>
base: keben              # 覆盖哪条版式的缺省实现：keben / modern / free（定走哪条管线）
cv: ">=0.7.0"            # 兼容的 cv 版本段（可省）
overrides:               # 缺省模块（<base>.<模块>）→ 本书模块（相对 code/ 的模块名）
  keben.roster_segment: roster_segment
```

**`code/` 是空的、或只有 `code.yaml` 没写 overrides 时，跑出来与没有 `code/` 完全相同**（全走缺省实现、指纹不变）。

## 钉版本

书配置（`book_defaults.yaml`）或册 yaml 写 `code: N`（或 `k3`）：起跑前拿工作副本比 `code/releases/k<N>.json`，
不符就拒跑（`GUJI_CODE_DRIFT=warn` 只告警）。**版本号不进指纹**——指纹照旧按每个模块的代码内容算，升了号而某步
用到的文件没变，那一步不过期。
"""
from __future__ import annotations

import hashlib
import importlib.abc
import importlib.machinery
import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: 书级模块挂在这个顶层包下：`guji_book.<name>.<模块>`。名字与本机路径无关，换机器指纹不变。
PKG = "guji_book"
CODE_DIR = "code"
CODE_YAML = "code.yaml"
RELEASES = "releases"
#: 不影响运行的说明文档：起跑前比对工作副本与 k<N> 时不算（`drift`）。
DOC_SUFFIX = ".md"

#: 三条版式的缺省实现（`code.yaml` 的 `base:` 与 overrides 键的前缀）。书仓里只写短名，cv 里搬家改名不牵动书仓。
BASES: dict[str, str] = {
    "keben": "open_guji_cv.impl.keben",
    "modern": "open_guji_cv.impl.modern",
    "free": "open_guji_cv.impl.free",
}
#: 版式 → 缺省走的管线（同 `seg_set.SEG_SET_PIPELINE` 里缺省实现那三行）。
BASE_PIPELINE: dict[str, str] = {"keben": "keben_body_v2", "modern": "modern_body", "free": "keben_free"}

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_MOD_RE = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)*$")


class BookCodeError(ValueError):
    pass


@dataclass(frozen=True)
class BookCode:
    root: Path                                  # <工作区>/code
    name: str
    base: str
    cv: str | None = None
    overrides: dict[str, str] = field(default_factory=dict)   # 缺省模块全名 → 书级模块全名
    moved: dict[str, tuple[str, str]] = field(default_factory=dict)
    forked: dict[str, tuple[str, str]] = field(default_factory=dict)
    entries: tuple[tuple[str, str, str], ...] = ()             # (模块, 新哈希, 旧哈希)

    @property
    def pkg(self) -> str:
        return f"{PKG}.{self.name}"

    def module(self, rel: str) -> str:
        return f"{self.pkg}.{rel}"

    @property
    def pipeline(self) -> str:
        return BASE_PIPELINE[self.base]


def code_root(ws: Path | None = None) -> Path | None:
    """工作区的 `code/`（有 `code.yaml` 才算）；没有工作区或没有书级代码 → None。"""
    if ws is None:
        from .workspace import workspace_root
        ws = workspace_root()
    if ws is None:
        return None
    d = Path(ws) / CODE_DIR
    return d if (d / CODE_YAML).is_file() else None


_CACHE: dict[str, tuple[float, BookCode]] = {}


def load(ws: Path | None = None) -> BookCode | None:
    """读工作区的书级代码登记；没有 → None。按 code.yaml 的 mtime 缓存。"""
    root = code_root(ws)
    if root is None:
        return None
    y = root / CODE_YAML
    key = str(y.resolve())
    mt = y.stat().st_mtime
    hit = _CACHE.get(key)
    if hit and hit[0] == mt:
        return hit[1]
    bc = _parse(root)
    _register(bc)
    _CACHE[key] = (mt, bc)
    return bc


def _yaml(path: Path) -> dict:
    import yaml
    d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(d, dict):
        raise BookCodeError(f"{path} 顶层应是映射")
    return d


def _parse(root: Path) -> BookCode:
    d = _yaml(root / CODE_YAML)
    name = str(d.get("name") or "")
    if not _NAME_RE.match(name):
        raise BookCodeError(f"{root / CODE_YAML}：name 要写小写字母、数字、下划线（现在是 {name!r}）")
    base = str(d.get("base") or "keben")
    if base not in BASES:
        raise BookCodeError(f"{root / CODE_YAML}：base 只能是 {sorted(BASES)}（现在是 {base!r}）")
    ov: dict[str, str] = {}
    for k, v in (d.get("overrides") or {}).items():
        k, v = str(k), str(v)
        b, _, rel = k.partition(".")
        if b not in BASES or not rel or not _MOD_RE.match(rel):
            raise BookCodeError(f"{root / CODE_YAML}：overrides 键要写 <版式>.<模块>，如 keben.row_boundaries（现在是 {k!r}）")
        if not _MOD_RE.match(v):
            raise BookCodeError(f"{root / CODE_YAML}：overrides 值要写 code/ 下的模块名（现在是 {v!r}）")
        if not (root / (v.replace(".", "/") + ".py")).is_file():
            raise BookCodeError(f"{root / CODE_YAML}：overrides {k} → {v}，但 code/{v.replace('.', '/')}.py 不存在")
        ov[f"{BASES[b]}.{rel}"] = f"{PKG}.{name}.{v}"
    moved, forked, entries = _parse_equiv(root, name)
    cv = d.get("cv")
    return BookCode(root=root, name=name, base=base, cv=None if cv is None else str(cv), overrides=ov,
                    moved=moved, forked=forked, entries=entries)


def _full(name: str, mod: str) -> str:
    """equiv.yaml 里的模块名：`open_guji_cv.…` 照写；别的当作本书模块（相对 code/）。"""
    if mod.startswith("open_guji_cv.") or mod.startswith(PKG + "."):
        return mod
    return f"{PKG}.{name}.{mod}"


def _parse_equiv(root: Path, name: str):
    p = root / "equiv.yaml"
    if not p.is_file():
        return {}, {}, ()
    d = _yaml(p)
    moved = {_full(name, k): (_full(name, v["from"]), str(v["hash"])) for k, v in (d.get("moved") or {}).items()}
    forked = {_full(name, k): (_full(name, v["from"]), str(v["hash"])) for k, v in (d.get("forked") or {}).items()}
    entries = tuple((_full(name, e["module"]), str(e["new"]), str(e["old"])) for e in (d.get("entries") or []))
    return moved, forked, entries


# —— 把 code/ 挂成包 guji_book.<name> ——

class _Finder(importlib.abc.MetaPathFinder):
    roots: dict[str, Path] = {}

    def find_spec(self, fullname, path=None, target=None):
        if fullname == PKG:
            spec = importlib.machinery.ModuleSpec(PKG, None, is_package=True)
            spec.submodule_search_locations = []
            return spec
        if not fullname.startswith(PKG + "."):
            return None
        parts = fullname.split(".")
        root = self.roots.get(parts[1])
        if root is None:
            return None
        if len(parts) == 2:
            init = root / "__init__.py"
            spec = importlib.util.spec_from_file_location(
                fullname, init if init.is_file() else None, submodule_search_locations=[str(root)])
            if spec is None:          # 没有 __init__.py：命名空间式的空包
                spec = importlib.machinery.ModuleSpec(fullname, None, is_package=True)
                spec.submodule_search_locations = [str(root)]
            return spec
        rel = Path(root, *parts[2:])
        if (rel / "__init__.py").is_file():
            return importlib.util.spec_from_file_location(fullname, rel / "__init__.py",
                                                          submodule_search_locations=[str(rel)])
        f = rel.with_suffix(".py")
        if f.is_file():
            return importlib.util.spec_from_file_location(fullname, f)
        return None


_FINDER = _Finder()


def _register(bc: BookCode) -> None:
    old = _FINDER.roots.get(bc.name)
    if old is not None and old.resolve() != bc.root.resolve():
        # 同一进程换了另一份同名代码（控制台换工作区）：清掉已 import 的旧模块
        for m in [m for m in sys.modules if m == bc.pkg or m.startswith(bc.pkg + ".")]:
            del sys.modules[m]
    _FINDER.roots[bc.name] = bc.root
    if _FINDER not in sys.meta_path:
        sys.meta_path.insert(0, _FINDER)


# —— 版本号与清单 ——

def parse_pin(v) -> int | None:
    """册配置的 `code:`：`3` 或 `k3`；不写 → None。"""
    if v is None:
        return None
    s = str(v).strip().lower()
    if s.startswith("k"):
        s = s[1:]
    if not s.isdigit() or int(s) < 1:
        raise ValueError(f"code: 要写正整数或 k<N>（现在是 {v!r}）")
    return int(s)


#: 进清单的文件：code/ 下除 releases/、缓存与隐藏文件外的全部文件。
def _tracked(root: Path) -> list[Path]:
    out = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if rel.parts[0] == RELEASES or any(s.startswith(".") or s == "__pycache__" for s in rel.parts):
            continue
        if p.suffix in (".pyc", ".pyo"):
            continue
        out.append(p)
    return out


def file_table(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in _tracked(root)}


def digest(table: dict[str, str]) -> str:
    h = hashlib.sha256()
    for k in sorted(table):
        h.update(f"{k}\0{table[k]}\n".encode())
    return h.hexdigest()


def releases(root: Path) -> list[int]:
    d = root / RELEASES
    if not d.is_dir():
        return []
    return sorted(int(m.group(1)) for p in d.glob("k*.json") if (m := re.fullmatch(r"k(\d+)\.json", p.name)))


def release_path(root: Path, n: int) -> Path:
    return root / RELEASES / f"k{n}.json"


def load_release(root: Path, n: int) -> dict:
    p = release_path(root, n)
    if not p.is_file():
        raise BookCodeError(f"书级代码没有 k{n}：{p} 不存在（已有 {['k%d' % i for i in releases(root)]}）")
    return json.loads(p.read_text(encoding="utf-8"))


def drift(root: Path, n: int) -> list[str]:
    """工作副本与 k<N> 清单的差异（空 = 一致）。说明文档（`*.md`）不算：改 README 不该让钉了 code: N 的册拒跑
    （2026-11-09 实际踩到）。清单里照样记着它们。"""
    want = {k: v for k, v in load_release(root, n)["files"].items() if not k.endswith(DOC_SUFFIX)}
    have = {k: v for k, v in file_table(root).items() if not k.endswith(DOC_SUFFIX)}
    out = [f"改了 {k}" for k in sorted(want) if k in have and have[k] != want[k]]
    out += [f"少了 {k}" for k in sorted(want) if k not in have]
    out += [f"多了 {k}" for k in sorted(have) if k not in want]
    return out


def make_release(root: Path, *, cv_version: str, note: str = "", samples: str = "") -> tuple[int, Path]:
    """写下一版清单 `releases/k<N+1>.json`；内容与最新一版相同拒绝（不空升）。只写文件，不提交、不打 tag。"""
    table = file_table(root)
    have = releases(root)
    if have:
        last = load_release(root, have[-1])
        if last.get("digest") == digest(table):
            raise BookCodeError(f"code/ 与 k{have[-1]} 完全相同，不出新版")
    n = (have[-1] + 1) if have else 1
    p = release_path(root, n)
    p.parent.mkdir(parents=True, exist_ok=True)
    body = {"k": n, "digest": digest(table), "files": table, "tested_cv": cv_version, "note": note}
    if samples:
        body["samples"] = samples
    p.write_text(json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return n, p


def label(book, ws: Path | None = None) -> str | None:
    """版本串里的书级代码一段：钉了 `k<N>`；没钉但有 code/ → `k-<工作副本摘要前6位>`；没有 code/ → None。"""
    n = getattr(book, "code", None)
    if n:
        return f"k{n}"
    root = code_root(ws)
    if root is None:
        return None
    return "k-" + digest(file_table(root))[:6]


def check_cv(bc: BookCode, version: str) -> str | None:
    """`code.yaml` 的 cv 段不含当前 cv → 原因；含或没写 → None。"""
    if not bc.cv or not version or version.startswith("dev"):
        return None              # 没写段，或 cv 是开发检出（dev+g…）：不拦
    try:
        from packaging.specifiers import SpecifierSet
        from packaging.version import Version
    except ImportError:          # pragma: no cover
        return None
    v = version.split("+")[0]
    try:
        if Version(v).is_devrelease:
            return None          # 开发检出（setuptools_scm 的 0.6.31.dev3+g…）：不拦
        ok = Version(v) in SpecifierSet(bc.cv, prereleases=True)
    except Exception:            # noqa: BLE001 —— 写错的段当不合
        return f"code.yaml 的 cv: {bc.cv!r} 写法不对"
    return None if ok else f"本书代码要求 cv {bc.cv}，现在是 {version}"


def require_clean(book, ws: Path | None = None) -> None:
    """起跑前：钉了 `code: N` 的册，工作副本要与 k<N> 一致、cv 版本要在 code.yaml 的段内。"""
    n = getattr(book, "code", None)
    root = code_root(ws)
    if n and root is None:
        raise BookCodeError(f"册 {book.id} 钉了 code: {n}，但工作区没有 code/{CODE_YAML}")
    if root is None:
        return
    bc = load(ws)
    problems: list[str] = []
    from .cv_version import describe
    why = check_cv(bc, describe()[0] or "")
    if why:
        problems.append(why)
    if n:
        problems += [f"与 k{n} 不符：{d}" for d in drift(root, n)]
    if not problems:
        return
    msg = f"册 {book.id} 的书级代码（{root}）：" + "；".join(problems)
    if os.environ.get("GUJI_CODE_DRIFT", "").lower() == "warn":
        import logging
        logging.getLogger(__name__).warning(msg + "（GUJI_CODE_DRIFT=warn，照跑）")
        return
    raise BookCodeError(msg + "。开发中可设 GUJI_CODE_DRIFT=warn 照跑；正式跑先 git checkout k<N> 或改钉")
