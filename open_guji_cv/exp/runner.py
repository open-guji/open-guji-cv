# -*- coding: utf-8 -*-
"""跑实验：共享上游一份、各变体各跑各的产物根。

```
<exp根>/<exp名>/
  exp.yaml                    合并后的配置 + 代码版本 + 快照戳 + 各变体跑批计数（可复现）
  _upstream/<book>/<step>/    `--from` 之前各步：从快照**硬链接**过来（跨盘退回复制），只读
  <变体>/<book>/<step>/       该变体的产物根；上游再从 `_upstream` 硬链接，`--from…--to` 现跑
```

- **只从第一个受影响的步起算**：上游各步不跑（显式点名 `steps=[from…to]`），指纹照常判；
- `_manifest.jsonl` 是追加写的，**复制而不是硬链接**——万一引擎往上游清单追加，不会写穿快照；
  产物文件本身由 `ProductStore.write` 原子替换（`os.replace`），替换的是链接不是原文件；
- **绝不写书的正式 `products/`**：`guard_root` 在任何写盘之前拒掉落在工作区 `products/`
  （或快照）之内的 exp 根。
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

import yaml

from ..errors import BadRequest
from .config import EXP_REL, ExpConfig, effective_params, validate_params

UPSTREAM = "_upstream"
#: 不随上游一起搬的东西：上一代产物（格级复用用，实验里不需要）与临时文件。
_SKIP_NAMES = {"_prev"}


# ── 根与护栏 ─────────────────────────────────────────────────────────────
def default_root() -> Path:
    from ..core.workspace import workspace_root
    ws = workspace_root()
    if ws is None:
        raise BadRequest("没有工作区（-w / GUJI_WORKSPACE），请用 --root 指定实验根")
    return ws / EXP_REL


def exp_root(cfg: ExpConfig, root: str | Path | None = None) -> Path:
    return Path(root or cfg.root or default_root()).expanduser().resolve()


def exp_dir(cfg: ExpConfig, root: str | Path | None = None) -> Path:
    return exp_root(cfg, root) / cfg.name


def protected_roots(snapshot: Path | None = None) -> list[Path]:
    """不许写的根：工作区正式 `products/`、仓内默认 `products/`、快照本身。"""
    from ..core.workspace import PRODUCTS_REL, REPO_ROOT, workspace_root
    out = [REPO_ROOT / PRODUCTS_REL]
    ws = workspace_root()
    if ws is not None:
        out.append(ws / PRODUCTS_REL)
    if snapshot is not None:
        out.append(Path(snapshot))
    return [p.expanduser().resolve() for p in out]


def _inside(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


def guard_root(path: Path, snapshot: Path | None = None) -> None:
    """exp 目录落在受保护的根之内（或反过来把它们包进来）就拒跑。"""
    p = Path(path).expanduser().resolve()
    for r in protected_roots(snapshot):
        if _inside(p, r) or _inside(r, p):
            raise BadRequest(f"实验目录 {p} 与受保护的产物根 {r} 重叠——实验绝不写书的正式 products/"
                             f"（也不写进快照）。换个 --root。")


# ── 上游准备 ─────────────────────────────────────────────────────────────
def _link_or_copy(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    if src.name == "_manifest.jsonl" or src.suffix != ".json":
        shutil.copy2(src, dst)
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _mirror(src: Path, dst: Path) -> int:
    n = 0
    for f in sorted(src.rglob("*")):
        rel = f.relative_to(src)
        if any(part in _SKIP_NAMES or part.endswith(".tmp") for part in rel.parts):
            continue
        if f.is_file():
            _link_or_copy(f, dst / rel)
            n += 1
    return n


def run_steps(cfg: ExpConfig, pipeline) -> list[str]:
    """管线里 `from…to` 这一段（含两端）。"""
    steps = list(pipeline.steps)
    for s in (cfg.from_step, cfg.to_step):
        if s not in steps:
            raise BadRequest(f"管线 {pipeline.id} 里没有 {s}")
    i, j = steps.index(cfg.from_step), steps.index(cfg.to_step)
    if i > j:
        raise BadRequest(f"from={cfg.from_step} 在 to={cfg.to_step} 之后")
    return steps[i:j + 1]


def _owned_dirs(steps: list[str]) -> set[str]:
    """变体自己产出的目录：要跑的步，加上它们挂的闸（引擎会自动接着跑）。"""
    from ..core.step import STEPS
    out = set(steps)
    for s in steps:
        g = STEPS[s].spec.gate if s in STEPS else None
        if g:
            out.add(g.id)
    return out


def snapshot_stamp(book_dir: Path) -> dict[str, str]:
    """各步 `_manifest.jsonl` 的内容戳（快照换了，实验结果就不可比——记下来）。"""
    out = {}
    for d in sorted(p for p in book_dir.iterdir() if p.is_dir()):
        m = d / "_manifest.jsonl"
        if m.exists():
            out[d.name] = hashlib.sha256(m.read_bytes()).hexdigest()[:16]
    return out


def prepare_upstream(cfg: ExpConfig, edir: Path, snapshot: Path, steps: list[str]) -> dict:
    """快照 → `_upstream/<book>/`，跳过本实验要跑的步。返回 {book: {step: 戳}}。"""
    owned = _owned_dirs(steps)
    stamps = {}
    for book in cfg.books:
        src = snapshot / book
        if not src.is_dir():
            raise BadRequest(f"快照里没有 {book}：{src}")
        dst = edir / UPSTREAM / book
        for item in sorted(src.iterdir()):
            if item.name in owned or item.name in _SKIP_NAMES:
                continue
            if item.is_dir():
                _mirror(item, dst / item.name)
            elif item.is_file():
                _link_or_copy(item, dst / item.name)
        stamps[book] = snapshot_stamp(src)
    return stamps


def seed_variant(edir: Path, variant: str, book: str) -> Path:
    """变体根 ← `_upstream`（硬链接）。返回变体的产物根（`<exp>/<变体>`）。"""
    vroot = edir / variant
    _mirror(edir / UPSTREAM / book, vroot / book)
    return vroot


# ── 页 ───────────────────────────────────────────────────────────────────
def page_types(products_root: Path, book: str) -> dict[int, str]:
    """页 → 页型（`border_detect_gate` 产物的 `page_type`；缺了不猜）。"""
    out: dict[int, str] = {}
    d = Path(products_root) / book / "border_detect_gate"
    for f in sorted(d.glob("p*.json")) if d.is_dir() else []:
        try:
            g = json.loads(f.read_text(encoding="utf-8")).get("border_detect_gate") or {}
        except (OSError, ValueError):
            continue
        out[int(f.stem[1:])] = str(g.get("page_type") or "unknown")
    return out


def _pages_with(products_root: Path, book: str, step: str) -> list[int]:
    d = Path(products_root) / book / step
    return sorted(int(f.stem[1:]) for f in d.glob("p*.json")) if d.is_dir() else []


def select_pages(cfg: ExpConfig, upstream_root: Path, book: str, pipeline, steps: list[str],
                 book_spec=None) -> list[int]:
    """跑哪些页。`all` = `from` 之前最近一个在快照里有产物的步覆盖的页。"""
    order = list(pipeline.steps)
    before = order[:order.index(steps[0])]
    have: list[int] = []
    for s in reversed(before):
        have = _pages_with(upstream_root, book, s)
        if have:
            break
    sel = cfg.pages
    if sel in (None, "all"):
        return have
    if sel == "body":
        pt = page_types(upstream_root, book)
        return [p for p in have if pt.get(p) == "body"]
    if book_spec is None:
        raise BadRequest(f"pages={sel!r} 要读册配置")
    want = set(book_spec.resolve_pages(sel))
    return [p for p in have if p in want] if have else sorted(want)


# ── 跑 ───────────────────────────────────────────────────────────────────
@contextmanager
def _products_env(root: Path):
    """有些生产代码不走 ctx 而是自己 `ProductStore()`——把默认根也指到变体根。"""
    old = os.environ.get("GUJI_PRODUCTS_DIR")
    os.environ["GUJI_PRODUCTS_DIR"] = str(root)
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("GUJI_PRODUCTS_DIR", None)
        else:
            os.environ["GUJI_PRODUCTS_DIR"] = old


def run(cfg: ExpConfig, *, snapshot: str | Path | None = None, root: str | Path | None = None,
        variants: list[str] | None = None, jobs: int = 1, force: bool = False,
        book_loader: Callable | None = None, pipeline=None, cache=None,
        log: Callable[[str], None] | None = None) -> dict:
    """准备上游 → 逐变体逐册跑 → 写 `exp.yaml`。返回运行记录（也写进 `exp.yaml` 的 `runs:`）。

    `book_loader` / `pipeline` / `cache` 供测试注入；缺省读工作区册配置与 `cfg.pipeline`。"""
    from ..core.engine import Engine, git_rev
    from ..core.pipeline import load_pipeline
    from ..products.store import ProductStore

    log = log or (lambda s: print(s, flush=True))
    snap = Path(snapshot or cfg.snapshot or "").expanduser()
    if not str(snapshot or cfg.snapshot or ""):
        raise BadRequest("要给快照产物根（yaml 的 snapshot: 或 --snapshot）")
    snap = snap.resolve()
    edir = exp_dir(cfg, root)
    guard_root(edir, snap)
    validate_params(cfg)
    pl = pipeline or load_pipeline(cfg.pipeline)
    steps = run_steps(cfg, pl)
    if book_loader is None:
        from ..core.book import load_book as book_loader  # noqa: N813

    edir.mkdir(parents=True, exist_ok=True)
    stamps = prepare_upstream(cfg, edir, snap, steps)
    want = variants or [v.name for v in cfg.variants]
    runs: dict[str, dict] = {}
    effective: dict[str, dict] = {}
    for v in cfg.variants:
        if v.name not in want:
            continue
        for book in cfg.books:
            bk = book_loader(book)
            eff = effective_params(cfg, v, getattr(bk, "params", None))
            effective.setdefault(v.name, {})[book] = eff
            bk = dataclasses.replace(bk, params={})      # 书级参数已合进 eff，见 effective_params
            pages = select_pages(cfg, edir / UPSTREAM, book, pl, steps, bk)
            vroot = seed_variant(edir, v.name, book)
            if force:
                for s in _owned_dirs(steps):
                    shutil.rmtree(vroot / book / s, ignore_errors=True)
            log(f"[exp {cfg.name}] 变体 {v.name} · {book} · {len(pages)} 页 · 跑 {steps[0]}→{steps[-1]}")
            t0 = time.time()
            with _products_env(vroot):
                eng = Engine(bk, pl, store=ProductStore(vroot), cache=cache,
                             params=eff, log=log)
                rep = eng.run(steps=list(steps), pages=pages, jobs=jobs)
            runs[f"{v.name}/{book}"] = {"pages": len(pages), "counts": rep.counts(),
                                        "elapsed": round(time.time() - t0, 1)}
    state = {"config": cfg.to_dict(), "code_rev": git_rev(), "snapshot": str(snap),
             "snapshot_stamp": stamps, "steps": steps, "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "runs": runs, "effective_params": effective}
    old = read_state(edir)
    if old and old.get("runs"):
        state["runs"] = {**old["runs"], **runs}
        state["effective_params"] = {**(old.get("effective_params") or {}), **effective}
    (edir / "exp.yaml").write_text(yaml.safe_dump(state, allow_unicode=True, sort_keys=False),
                                   encoding="utf-8")
    return state


def read_state(edir: Path) -> dict | None:
    p = Path(edir) / "exp.yaml"
    if not p.exists():
        return None
    return yaml.safe_load(p.read_text(encoding="utf-8")) or None


def list_experiments(root: Path) -> list[dict]:
    out = []
    for d in sorted(Path(root).iterdir()) if Path(root).is_dir() else []:
        st = read_state(d) if d.is_dir() else None
        if st:
            cfg = st.get("config") or {}
            out.append({"name": d.name, "books": cfg.get("books"), "variants":
                        [cfg.get("base", {}).get("name", "A"), *(cfg.get("variants") or {})],
                        "ran_at": st.get("ran_at"), "code_rev": st.get("code_rev"),
                        "report": (d / "report.md").exists()})
    return out
