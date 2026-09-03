"""引擎：指纹、stale 判定、执行。

指纹 = sha256(step.version, params, 代码哈希, 上游产物 sha)。
上游一改 → 指纹变 → 本步该页 stale；引擎只**标**，不自动重跑（重跑是人下的命令）。
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from .book import BookSpec
from .pipeline import Pipeline
from .spec import page_key
from .step import STEPS, RunContext, Step, kind_of
from ..products.cache import ImageCache
from ..products.manifest import ManifestEntry
from ..products.store import ProductStore

FRESH, STALE, MISSING, FAILED, BLOCKED = "fresh", "stale", "missing", "failed", "blocked"

_code_hash_cache: dict[str, str] = {}


def _module_source_hash(mod_name: str) -> str:
    if mod_name in _code_hash_cache:
        return _code_hash_cache[mod_name]
    mod = importlib.import_module(mod_name)
    src = inspect.getsourcefile(mod)
    h = hashlib.sha256(Path(src).read_bytes()).hexdigest() if src else "nosrc"
    _code_hash_cache[mod_name] = h
    return h


def code_hash(step: Step) -> str:
    mods = [type(step).__module__, *step.spec.code_deps]
    h = hashlib.sha256()
    for m in mods:
        h.update(m.encode())
        h.update(_module_source_hash(m).encode())
    return h.hexdigest()[:16]


def params_hash(params: BaseModel) -> str:
    return hashlib.sha256(json.dumps(params.model_dump(mode="json"), sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()[:16]


def git_rev(repo: Path | None = None) -> str | None:
    try:
        root = repo or Path(__file__).resolve().parent.parent.parent
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root,
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or None
    except Exception:
        return None


@dataclass
class PageOutcome:
    step: str
    page: int
    status: str            # ok | skipped | failed
    elapsed: float = 0.0
    error: str | None = None


@dataclass
class RunReport:
    book: str
    pipeline: str
    steps: list[str]
    pages: list[int]
    outcomes: list[PageOutcome] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def counts(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        for o in self.outcomes:
            d = out.setdefault(o.step, {"ok": 0, "skipped": 0, "failed": 0})
            d[o.status] = d.get(o.status, 0) + 1
        return out

    def to_dict(self) -> dict:
        return {
            "book": self.book, "pipeline": self.pipeline, "steps": self.steps,
            "pages": self.pages, "counts": self.counts(),
            "started_at": self.started_at, "finished_at": self.finished_at,
            "failed": [{"step": o.step, "page": o.page, "error": o.error}
                       for o in self.outcomes if o.status == "failed"],
        }


class Engine:
    def __init__(self, book: BookSpec, pipeline: Pipeline,
                 store: ProductStore | None = None, cache: ImageCache | None = None,
                 params: dict[str, dict] | None = None,
                 log: Callable[[str], None] | None = None):
        self.book = book
        self.pipeline = pipeline
        self.store = store or ProductStore()
        self.cache = cache or ImageCache()
        self.log = log or (lambda s: print(s, flush=True))
        resolved: dict[str, BaseModel] = {}
        for sid, override in (params or {}).items():
            resolved[sid] = STEPS[sid].spec.params(**override)
        self.ctx = RunContext(book, self.store, self.cache, resolved, self.log)
        self._rev = git_rev()

    # ── 指纹 ─────────────────────────────────────────────────────────
    def upstream_shas(self, step: Step, page: int) -> dict[str, str] | None:
        """{kind: sha}；任一上游缺失返回 None（blocked）。"""
        out: dict[str, str] = {}
        for kind in step.spec.consumes:
            if kind == "raw_page":
                p = self.book.raw_path(page)
                if not p.exists():
                    return None
                out[kind] = self.store.raw_sha(self.book.id, p)
                continue
            from .step import producer_of
            prod = producer_of(kind)
            entry = self.store.manifest(self.book.id, prod.spec.id).get(page_key(page))
            if entry and entry.status == "ok" and entry.sha256 and \
                    self.store.exists(self.book.id, prod.spec.id, page_key(page)):
                out[kind] = entry.sha256
                continue
            sha = self.store.sha(self.book.id, prod.spec.id, page_key(page))
            if sha is None:
                return None
            out[kind] = sha
        return out

    def fingerprint(self, step: Step, page: int) -> tuple[str | None, dict[str, str] | None, str]:
        ups = self.upstream_shas(step, page)
        p = self.ctx.params_for(step)
        ph = params_hash(p)
        if ups is None:
            return None, None, ph
        payload = {"step": step.spec.id, "version": step.spec.version, "params": ph,
                   "code": code_hash(step), "upstream": ups}
        fp = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]
        return fp, ups, ph

    # ── 状态 ─────────────────────────────────────────────────────────
    def page_status(self, step: Step, page: int) -> tuple[str, ManifestEntry | None]:
        entry = self.store.manifest(self.book.id, step.spec.id).get(page_key(page))
        fp, _, _ = self.fingerprint(step, page)
        if fp is None:
            return BLOCKED, entry
        if entry is None or not self.store.exists(self.book.id, step.spec.id, page_key(page)):
            return (FAILED if entry and entry.status == "failed" else MISSING), entry
        if entry.status == "failed":
            return FAILED, entry
        return (FRESH if entry.fingerprint == fp else STALE), entry

    def status(self, pages: list[int] | None = None, steps: list[str] | None = None) -> dict:
        """每步每页的状态。**过期沿 DAG 向下传**：某页的任一直接上游不是 fresh，本步该页
        即使指纹还对得上也标 stale（`upstream_stale=True`）——上游一改，下游整链过期。"""
        pages = pages if pages is not None else self.book.resolve_pages("dev_set")
        steps = steps or self.pipeline.steps
        out: dict[str, dict] = {}
        seen: dict[str, dict[int, str]] = {}
        for sid in self.pipeline.steps:          # 按拓扑序算，保证上游先有结果
            step = STEPS[sid]
            ups = [u for u in self.pipeline.upstream(sid) if u in seen]
            per_page: dict[int, dict] = {}
            counts = {FRESH: 0, STALE: 0, MISSING: 0, FAILED: 0, BLOCKED: 0}
            seen[sid] = {}
            for pg in pages:
                st, entry = self.page_status(step, pg)
                upstream_stale = st == FRESH and any(seen[u].get(pg) != FRESH for u in ups)
                if upstream_stale:
                    st = STALE
                seen[sid][pg] = st
                counts[st] += 1
                per_page[pg] = {"status": st, "upstream_stale": upstream_stale,
                                "ts": entry.ts if entry else None,
                                "elapsed": entry.elapsed if entry else None,
                                "error": entry.error if entry else None}
            if sid in steps:
                out[sid] = {"counts": counts, "pages": per_page}
        return {"book": self.book.id, "pipeline": self.pipeline.id, "pages": pages, "steps": out}

    # ── 执行 ─────────────────────────────────────────────────────────
    def run(self, steps: list[str] | None = None, pages: list[int] | None = None,
            force: bool = False, stop_on_error: bool = False) -> RunReport:
        steps = steps or self.pipeline.steps
        pages = pages if pages is not None else self.book.resolve_pages("dev_set")
        report = RunReport(self.book.id, self.pipeline.id, list(steps), list(pages))
        total = len(steps) * len(pages)
        done = 0
        for sid in steps:
            step = STEPS[sid]
            manifest = self.store.manifest(self.book.id, sid)
            self.log(f"== {sid} {step.spec.title}：{len(pages)} 页")
            for pg in pages:
                done += 1
                key = page_key(pg)
                fp, ups, ph = self.fingerprint(step, pg)
                pct = int(done * 100 / max(total, 1))
                if fp is None:
                    msg = f"上游缺失: {[k for k in step.spec.consumes]}"
                    self.log(f"[{done}/{total}] {pct}% {sid} p{pg}: 阻塞（{msg}）")
                    report.outcomes.append(PageOutcome(sid, pg, "failed", error=msg))
                    manifest.put(ManifestEntry(key=key, fingerprint="", params_hash=ph,
                                               upstream={}, code_rev=self._rev,
                                               status="failed", error=msg))
                    if stop_on_error:
                        report.finished_at = time.time()
                        return report
                    continue
                entry = manifest.get(key)
                if (not force and entry and entry.status == "ok" and entry.fingerprint == fp
                        and self.store.exists(self.book.id, sid, key)):
                    self.log(f"[{done}/{total}] {pct}% {sid} p{pg}: 新鲜，跳过")
                    report.outcomes.append(PageOutcome(sid, pg, "skipped"))
                    continue
                t0 = time.time()
                try:
                    products = step.run_page(self.ctx, pg)
                    for k in products:
                        if k not in step.spec.produces:
                            raise ValueError(f"{sid} 产出了未声明的种类 {k!r}")
                        if kind_of(k).storage != "numeric":
                            raise ValueError(f"{sid} 把图像类 {k!r} 当 numeric 返回了")
                    _, sha = self.store.write(self.book.id, sid, key, products)
                    elapsed = time.time() - t0
                    manifest.put(ManifestEntry(key=key, fingerprint=fp, sha256=sha,
                                               params_hash=ph, upstream=ups or {},
                                               code_rev=self._rev, elapsed=round(elapsed, 3)))
                    self.log(f"[{done}/{total}] {pct}% {sid} p{pg}: 完成 {elapsed:.2f}s")
                    report.outcomes.append(PageOutcome(sid, pg, "ok", elapsed))
                except Exception as e:  # noqa: BLE001 —— 一页失败不拖垮整轮
                    elapsed = time.time() - t0
                    err = f"{type(e).__name__}: {e}"
                    manifest.put(ManifestEntry(key=key, fingerprint=fp, params_hash=ph,
                                               upstream=ups or {}, code_rev=self._rev,
                                               elapsed=round(elapsed, 3), status="failed", error=err))
                    self.log(f"[{done}/{total}] {pct}% {sid} p{pg}: 失败 {err}")
                    report.outcomes.append(PageOutcome(sid, pg, "failed", elapsed, err))
                    if stop_on_error:
                        report.finished_at = time.time()
                        return report
        report.finished_at = time.time()
        c = report.counts()
        self.log("完成：" + "；".join(f"{s} ok {v['ok']} / 跳过 {v['skipped']} / 失败 {v['failed']}"
                                    for s, v in c.items()))
        return report
