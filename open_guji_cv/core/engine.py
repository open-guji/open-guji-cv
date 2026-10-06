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
from .pipeline import Pipeline, _produces
from .spec import live_optional_consumes, page_key
from .step import STEPS, RunContext, Step, kind_of
from ..products.cache import ImageCache
from ..products.manifest import ManifestEntry
from ..products.store import ProductStore
from ..utils.preclean import effective_raw_path

FRESH, STALE, MISSING, FAILED, BLOCKED = "fresh", "stale", "missing", "failed", "blocked"

_code_hash_cache: dict[str, str] = {}


def _module_source_hash(mod_name: str) -> str:
    """模块源码的哈希，**只认代码**（2026-10-06，overview#413 用户定）：去掉注释和 docstring、
    行尾归一（CRLF→LF）、去空行和行尾空白之后再算。

    沿革：最早直接哈希文件字节；2026-09-20 改成行尾归一——实锤过编辑器把 CRLF 存回 LF，
    内容一字未改，Step2 闸以下 11 步 54 页全线过期。2026-10-06 再进一步：改注释、补 docstring
    也会让各书产物整体过期，逼得大家不敢整理代码，所以注释和 docstring 也不进指纹。
    改代码本身（哪怕只改一个常量）照样判过期。见 `code_only_text`。
    """
    if mod_name in _code_hash_cache:
        return _code_hash_cache[mod_name]
    mod = importlib.import_module(mod_name)
    src = inspect.getsourcefile(mod)
    h = hashlib.sha256(code_only_text(Path(src).read_text(encoding="utf-8")).encode("utf-8")).hexdigest() \
        if src else "nosrc"
    _code_hash_cache[mod_name] = h
    return h


_legacy_hash_cache: dict[str, str] = {}


def _module_source_hash_legacy(mod_name: str) -> str:
    """2026-09-20 至 10-06 的老公式（整份源码、只做行尾归一）。只给 `guji fp-migrate --code-formula`
    回放老指纹用：老公式算出来与 manifest 记的逐位相等，才证明代码自那以后没变、可以只改写指纹。"""
    if mod_name not in _legacy_hash_cache:
        src = inspect.getsourcefile(importlib.import_module(mod_name))
        _legacy_hash_cache[mod_name] = (hashlib.sha256(_normalize_eol(Path(src).read_bytes())).hexdigest()
                                        if src else "nosrc")
    return _legacy_hash_cache[mod_name]


def _normalize_eol(raw: bytes) -> bytes:
    return raw.replace(b"\r\n", b"\n")


def code_only_text(src: str) -> str:
    """源码去掉注释与 docstring、去掉空行与行尾空白后的文本（指纹用，不保证还是合法 Python）。

    做法是从原文里**挖掉区间**：docstring 区间由 ast 给，注释区间由 tokenize 给。
    不用 `ast.dump` / `ast.unparse`、也不把 token 拼起来——这几样的输出随 Python 小版本变
    （3.12 改了 f-string 的 token 化、3.13 改了 `ast.dump` 的缺省字段），会让不同机器算出不同指纹。
    """
    import ast
    import io
    import tokenize
    import warnings
    src = src.replace("\r\n", "\n")
    lines = src.split("\n")

    def char_col(ln: int, byte_off: int) -> int:          # ast 的列是 utf-8 字节偏移
        return len(lines[ln - 1].encode("utf-8")[:byte_off].decode("utf-8", "ignore"))

    spans: list[tuple[tuple[int, int], tuple[int, int]]] = []
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")                   # 老代码里的非法转义只是 SyntaxWarning
        tree = ast.parse(src)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and body:
            d = body[0]
            if isinstance(d, ast.Expr) and isinstance(d.value, ast.Constant) and isinstance(d.value.value, str):
                spans.append(((d.lineno, char_col(d.lineno, d.col_offset)),
                              (d.end_lineno, char_col(d.end_lineno, d.end_col_offset))))
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            spans.append((tok.start, tok.end))
    buf = lines[:]
    for (sl, sc), (el, ec) in sorted(spans, reverse=True):   # 从后往前挖，前面的偏移不受影响
        if sl == el:
            buf[sl - 1] = buf[sl - 1][:sc] + buf[sl - 1][ec:]
        else:
            buf[sl - 1] = buf[sl - 1][:sc] + buf[el - 1][ec:]
            del buf[sl:el]
    return "\n".join(ln.rstrip() for ln in buf if ln.strip())


def rare_candidates_consumed(pipeline_steps: list[str], params_for: Callable, book) -> bool:
    """这条 pipeline 里有没有哪一步这次**真的**在读 `rare_candidates`（硬依赖，或开着的可选依赖）。"""
    for sid in pipeline_steps:
        if sid == "rare_candidates" or sid not in STEPS:
            continue
        spec = STEPS[sid].spec
        if "rare_candidates" in spec.consumes:
            return True
        if "rare_candidates" in live_optional_consumes(spec, params_for(sid), book):
            return True
    return False


def code_hash(step: Step, legacy: bool = False) -> str:
    """`legacy=True` 用 10-06 之前的老公式（见 `_module_source_hash_legacy`）。"""
    mods = [type(step).__module__, *step.spec.code_deps]
    fn = _module_source_hash_legacy if legacy else _module_source_hash
    h = hashlib.sha256()
    for m in mods:
        h.update(m.encode())
        h.update(fn(m).encode())
    return h.hexdigest()[:16]


def _jsonable(v):
    """`book_deps` 取到的值 → 可稳定 json 化（Path 等按字符串）。"""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in sorted(v.items(), key=lambda kv: str(kv[0]))}
    return str(v)


def book_dep_values(step: Step, book: BookSpec) -> dict | None:
    """本步 `book_deps` 各字段的现值（记进 manifest，`status` 报过期原因用）；无 → None。"""
    if not step.spec.book_deps:
        return None
    return {k: _jsonable(getattr(book, k, None)) for k in sorted(step.spec.book_deps)}


def params_hash(params: BaseModel, soft: tuple[str, ...] = (),
                path: tuple[str, ...] = ()) -> str:
    """参数指纹。`soft`（`StepSpec.soft_params`）、`path`（`StepSpec.path_params`）里的
    字段剔掉不算；两者都空的步与 2026-09-25 之前逐位相同。"""
    d = params.model_dump(mode="json")
    for k in (*soft, *path):
        d.pop(k, None)
    return hashlib.sha256(json.dumps(d, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()[:16]


def soft_values(step: Step, params: BaseModel) -> dict[str, str] | None:
    """这次跑的软参数取值（记进 manifest，`status` 比漂移用）；无软参数 → None。"""
    if not step.spec.soft_params:
        return None
    return {k: str(getattr(params, k, "")) for k in step.spec.soft_params}


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


def _self_payload(step: Step, book: BookSpec, ph: str, legacy_code: bool = False) -> dict:
    """指纹里**不含上游**的那部分：步 id、版本、参数、代码、册配置。
    `fingerprint` = 它 + 上游 sha；`self_hash` = 只有它（格级复用的判据，见 core/reuse.py）。
    键集与 2026-09-20 之前的 `fingerprint` payload 逐位相同，现有产物指纹不变。"""
    payload = {"step": step.spec.id, "version": step.spec.version, "params": ph,
               "code": code_hash(step, legacy=legacy_code)}
    # 册配置里影响产物的字段（`StepSpec.book_deps`）也要进指纹，否则改了
    # yaml 已有产物会照报「新鲜」。空 tuple（绝大多数步）时不写这个键，
    # 保证现有产物的指纹逐位不变、不触发全量重跑。
    if step.spec.book_deps:
        payload["book"] = book_dep_values(step, book)
    # `binarized_input` 换掉的是 `ctx.raw_page` 本身，**凡是读原图的步都受影响**
    # （Step1 版框、Step2 矫正、Step3 切格、Step4 收框…），没法靠某一步的
    # `book_deps` 覆盖全，所以在这里统一进指纹。
    # 只在开启时写这个键：关着的册（四庫等）指纹逐位不变，不触发全量重跑。
    if getattr(book, "binarized_input", False):
        payload["bin_input"] = True
    return payload


def self_hash(step: Step, book: BookSpec, params: BaseModel) -> str:
    """本步自身的指纹（不含上游）。引擎写进 `ManifestEntry.self_hash`，
    `RunContext`（含并行 worker 里没有 Engine 的那份）也能独立算出同一个值。"""
    payload = _self_payload(step, book, params_hash(params, step.spec.soft_params,
                                                    step.spec.path_params))
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]


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
        # 参数三层：Step 默认值 < 管线 yaml 的 `params:`（这条链的默认） < 调用方覆盖
        # （CLI `--params` / 控制台表单）。同一 Step 两层都有时按字段合并，调用方优先。
        resolved: dict[str, BaseModel] = {}
        merged: dict[str, dict] = {sid: dict(v) for sid, v in (pipeline.params or {}).items()}
        for sid, override in (params or {}).items():
            merged.setdefault(sid, {}).update(override)
        for sid, kv in merged.items():
            resolved[sid] = STEPS[sid].spec.params(**kv)
        self.ctx = RunContext(book, self.store, self.cache, resolved, self.log, pipeline=pipeline)
        self._rev = git_rev()

    def _stamp_cache(self, step: Step, key: str, sha: str) -> None:
        """这一步刚写完一页产物：它顺手 `cache.put` 的图像类缓存，记上「对着这版产物切的」戳。"""
        for k in step.spec.produces:
            if kind_of(k).storage == "image_cache":
                self.ctx.cache.set_page_stamp(self.book.id, k, key, sha)

    # ── 按 book 配置关掉的可选步骤 ───────────────────────────────────────
    def _enabled(self, steps: list[str]) -> list[str]:
        """过滤掉本书没开启的可选步骤：

        - `ocr_candidates`（Step5-c OCR候选，`BookSpec.ocr_candidates` 控制，默认 False）；
        - `rare_candidates`（Step5-b 生僻字候选）**没有任何下游真正在读它时**（2026-10-01）：
          读它的只有 `seed_admit.rare_agree` 与 `context_decide.rare_topk`，缺省都关；两个都关的
          书（vol02/vol03）跑它是白花时间——vol03 104 页 ≈12 分钟，而且指纹里带着字形库内容
          （`real_proto`），每次导出字形库都会让它整册过期重算。审字卡上的「查候选」走
          `/api/rare` 现算，不读这一步的产物。

        只跳过执行，不改 pipeline 拓扑，下游本来就处理得了「这一路证据没有」。"""
        out = list(steps)
        if not self.book.ocr_candidates:
            out = [s for s in out if s != "ocr_candidates"]
        if "rare_candidates" in out and not rare_candidates_consumed(
                self.pipeline.steps, lambda sid: self.ctx.params_for(STEPS[sid]), self.book):
            out = [s for s in out if s != "rare_candidates"]
        return out

    def _default_steps(self, steps: list[str] | None) -> tuple[list[str], bool]:
        """`steps` 为 None（调用方走默认整条 pipeline）时应用可选步骤开关；
        调用方显式点名了子集（如控制台单独跑 `ocr_candidates` 调试）则原样
        尊重——开关只管「常规批量跑不跑」，不挡人手工点名。返回
        (steps, was_default)。"""
        if steps is None:
            return self._enabled(self.pipeline.steps), True
        return steps, False

    # ── 指纹 ─────────────────────────────────────────────────────────
    def upstream_shas(self, step: Step, page: int) -> dict[str, str] | None:
        """{kind: sha}；**硬依赖**（`consumes`）任一缺失返回 None（blocked）。

        `optional_consumes` 里的可选上游缺席不阻塞，只是不进指纹——在的时候照常
        进，所以它一改下游照样过期；不在的时候下游按"这一路证据没有"跑（见
        `StepSpec.optional_consumes`）。
        """
        out: dict[str, str] = {}
        for kind in step.spec.consumes:
            sha = self._upstream_sha(kind, page)
            if sha is None:
                return None
            out[kind] = sha
        # 带开关的可选上游（`StepSpec.optional_consumes_when`）开关关着时不进指纹
        for kind in live_optional_consumes(step.spec, self.ctx.params_for(step), self.book):
            sha = self._upstream_sha(kind, page)
            if sha is not None:
                out[kind] = sha
        return out

    def _live_upstream(self, step: Step) -> list[str]:
        """过期传播用的直接上游：`Pipeline.upstream` 减去「只因开关关着的可选上游
        才连上」的那些步（`StepSpec.optional_consumes_when`）。开关关着时 5-b 过期不该
        把 `align_ref` 等标成 `upstream_stale`——它们这次根本不读 5-b。"""
        ups = self.pipeline.upstream(step.spec.id)
        off = set(step.spec.optional_consumes) - set(
            live_optional_consumes(step.spec, self.ctx.params_for(step), self.book))
        if not off:
            return ups
        wants = set(step.spec.consumes) | (set(step.spec.optional_consumes) - off)
        needs = self.pipeline.needs.get(step.spec.id, [])
        return [u for u in ups if (_produces(STEPS[u]) & wants) or u in needs]

    def _upstream_sha(self, kind: str, page: int) -> str | None:
        """一个上游种类这一页的 sha，拿不到返回 None（调用方决定算不算阻塞）。"""
        if kind == "raw_page":
            p = effective_raw_path(self.book, page)
            if not p.exists():
                return None
            return self.store.raw_sha(self.book.id, p)
        prod = self.pipeline.producer_of(kind)
        entry = self.store.manifest(self.book.id, prod.spec.id).get(page_key(page))
        if entry and entry.status == "ok" and entry.sha256 and \
                self.store.exists(self.book.id, prod.spec.id, page_key(page)):
            return entry.sha256
        return self.store.sha(self.book.id, prod.spec.id, page_key(page))

    def missing_upstream(self, step: Step, page: int) -> list[str]:
        """真正缺的那些硬依赖——报错要点名它们，不是把 `consumes` 整串印出来。"""
        return [k for k in step.spec.consumes if self._upstream_sha(k, page) is None]

    def fingerprint(self, step: Step, page: int) -> tuple[str | None, dict[str, str] | None, str]:
        ups = self.upstream_shas(step, page)
        p = self.ctx.params_for(step)
        ph = params_hash(p, step.spec.soft_params, step.spec.path_params)
        if ups is None:
            return None, None, ph
        payload = {**_self_payload(step, self.book, ph), "upstream": ups}
        fp = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]
        return fp, ups, ph

    def self_hash(self, step: Step) -> str:
        return self_hash(step, self.book, self.ctx.params_for(step))

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
        if entry.invalidated:
            return STALE, entry        # 显式失效（人裁落定等），见 ManifestEntry.invalidated
        return (FRESH if entry.fingerprint == fp else STALE), entry

    def stale_reason(self, step: Step, page: int, entry: ManifestEntry | None) -> str | None:
        """指纹对不上时说清是哪一样变了（#174）。按能分辨的粒度报：显式失效 > 册配置
        （`book_deps` 值，只有记过 `entry.book` 的条目才分得出）> 参数 > 上游产物 > 代码/版本。
        册配置那条写成「册配置 period_prior 180→204」，调用方直接拿去印。"""
        if entry is None:
            return None
        if entry.invalidated:
            return f"显式失效：{entry.invalidated}"
        fp, ups, ph = self.fingerprint(step, page)
        if fp is None or entry.fingerprint == fp:
            return None
        now = book_dep_values(step, self.book)
        if now is not None and entry.book is not None and entry.book != now:
            diff = [f"{k} {entry.book.get(k)}→{now.get(k)}" for k in sorted(now)
                    if entry.book.get(k) != now.get(k)]
            return "册配置 " + "，".join(diff)
        if entry.params_hash != ph:
            return "参数变了"
        if (entry.upstream or {}) != (ups or {}):
            return "上游产物变了"
        if now is not None and entry.book is None:
            return "代码或册配置变了（" + "/".join(sorted(now)) + "；旧条目没记册配置原值）"
        return "代码或版本变了"

    def _page_status_row(self, step: Step, pages: list[int],
                          upstream_fresh: dict[int, bool]) -> tuple[dict, dict[int, str]]:
        """算一个 Step（普通 Step 或闸）逐页状态，返回 (给 status() 用的行, {页: 状态} 供下游查过期)。"""
        per_page: dict[int, dict] = {}
        counts = {FRESH: 0, STALE: 0, MISSING: 0, FAILED: 0, BLOCKED: 0}
        page_state: dict[int, str] = {}
        # 软参数漂移（`StepSpec.soft_params`）：只报数、不改状态。老条目没记 `soft`
        # （软化之前跑的）也算漂移——不知道当时对的是哪个库。
        soft_now = soft_values(step, self.ctx.params_for(step))
        n_drift = 0
        reasons: dict[str, int] = {}
        for pg in pages:
            st, entry = self.page_status(step, pg)
            upstream_stale = st == FRESH and not upstream_fresh.get(pg, True)
            if upstream_stale:
                st = STALE
            page_state[pg] = st
            counts[st] += 1
            drift = bool(soft_now and entry and entry.status == "ok"
                         and (entry.soft or {}) != soft_now)
            n_drift += drift
            reason = None
            if st == STALE:
                reason = "上游过期" if upstream_stale else self.stale_reason(step, pg, entry)
                if reason:
                    reasons[reason] = reasons.get(reason, 0) + 1
            per_page[pg] = {"status": st, "upstream_stale": upstream_stale, "drift": drift,
                            "reason": reason,
                            "ts": entry.ts if entry else None,
                            "elapsed": entry.elapsed if entry else None,
                            "error": entry.error if entry else None}
        return {"counts": counts, "pages": per_page, "drift": n_drift,
                "stale_reasons": reasons}, page_state

    def status(self, pages: list[int] | None = None, steps: list[str] | None = None) -> dict:
        """每步每页的状态。**过期沿 DAG 向下传**：某页的任一直接上游不是 fresh，本步该页
        即使指纹还对得上也标 stale（`upstream_stale=True`）——上游一改，下游整链过期。

        闸（`step.spec.gate`）不出现在 `pipeline.steps` 里，但仍按它挂的那个 Step
        刚算完的新鲜度接着算一行，用闸自己的 `id`（如 `column_gate`）作 key——
        跟闸迁移前、它还是 pipeline 里一个独立节点时的 status 输出**同名同形**。

        DAG 传播必须按 `self._enabled(...)` 过滤后的列表遍历，不能用原始
        `self.pipeline.steps`：书级开关关掉的 step（如 `ocr_candidates`）若
        manifest 里留着旧记录，指纹对不上当前代码/上游会判 stale；`run()`
        看开关是 false 根本不会去跑它，这条 stale 永远洗不掉。之前遍历未过滤
        列表时，这个 stale 会被记进 `seen`，沿 DAG 一路拖垮 `align_ref` 等
        以它为上游的下游 step——不管补跑多少次都好不了（2026-09-16 排查
        `test_route_snapshot` 不稳定时查出）。"""
        pages = pages if pages is not None else self.book.resolve_pages("dev_set")
        steps, _ = self._default_steps(steps)
        out: dict[str, dict] = {}
        seen: dict[str, dict[int, str]] = {}
        for sid in self._enabled(self.pipeline.steps):  # 按拓扑序算，保证上游先有结果；
            step = STEPS[sid]                            # 书级开关关掉的 step 不进 seen，见下
            ups = [u for u in self._live_upstream(step) if u in seen]
            upstream_fresh = {pg: all(seen[u].get(pg) == FRESH for u in ups) for pg in pages}
            row, page_state = self._page_status_row(step, pages, upstream_fresh)
            seen[sid] = page_state
            if sid in steps:
                out[sid] = row
            gate = step.spec.gate
            if gate:
                gate_step = STEPS[gate.id]
                gate_upstream_fresh = {pg: page_state.get(pg) == FRESH for pg in pages}
                grow, gpage_state = self._page_status_row(gate_step, pages, gate_upstream_fresh)
                seen[gate.id] = gpage_state
                out[gate.id] = grow
        return {"book": self.book.id, "pipeline": self.pipeline.id, "pages": pages, "steps": out}

    # ── 执行 ─────────────────────────────────────────────────────────
    def _run_one_step(self, step: Step, pages: list[int], report: RunReport,
                       force: bool, stop_on_error: bool, total: int, done: int,
                       jobs: int = 1) -> tuple[int, bool]:
        """跑一个 Step（普通 Step 或闸）逐页，返回 (新的 done 计数, 是否已 stop_on_error 中止)。

        `jobs > 1` 且 `step.spec.parallel_safe` 时走页级并行（见 `_run_one_step_parallel`）；
        否则串行——`parallel_safe=False` 是默认值，没标过的 Step 一律串行，标记本身
        就是「审查过、安全」的唯一凭证，`jobs` 参数不能替审查背书。"""
        if jobs > 1 and step.spec.parallel_safe:
            return self._run_one_step_parallel(step, pages, report, force, stop_on_error,
                                               total, done, jobs)
        sid = step.spec.id
        manifest = self.store.manifest(self.book.id, sid)
        self.log(f"== {sid} {step.spec.title}：{len(pages)} 页")
        for pg in pages:
            done += 1
            key = page_key(pg)
            fp, ups, ph = self.fingerprint(step, pg)
            pct = int(done * 100 / max(total, 1))
            if fp is None:
                msg = f"上游缺失: {self.missing_upstream(step, pg)}"
                self.log(f"[{done}/{total}] {pct}% {sid} p{pg}: 阻塞（{msg}）")
                report.outcomes.append(PageOutcome(sid, pg, "failed", error=msg))
                manifest.put(ManifestEntry(key=key, fingerprint="", params_hash=ph,
                                           upstream={}, code_rev=self._rev,
                                           status="failed", error=msg))
                if stop_on_error:
                    return done, True
                continue
            entry = manifest.get(key)
            if (not force and entry and entry.status == "ok" and entry.fingerprint == fp
                    and not entry.invalidated and self.store.exists(self.book.id, sid, key)):
                self.log(f"[{done}/{total}] {pct}% {sid} p{pg}: 新鲜，跳过")
                report.outcomes.append(PageOutcome(sid, pg, "skipped"))
                continue
            t0 = time.time()
            try:
                # 重跑前先把**这一页、这一步产出的图像类产物**的缓存删掉（2026-09-17）。
                # `ImageCache.materialize` 是「有就返回」，从不比对新旧：产物 JSON 重写了，
                # 缓存里的图块还是上一版代码切的。实锤 bxgb p4 c14 s1「巨」：cell_shrink
                # 产物 bbox 高 68.2（上横在框内），控制台 /api/cache 返回的图块却是
                # 59×61（少了上横那 9 行）——用户对着旧图裁了一整批「顶横被切」。
                # run_page 里的 cache.put 只覆盖它这次产出的键，被合并/删除的格位与
                # 惰性 render 的键都不会被覆盖，所以必须在跑之前按页前缀整体清掉。
                for k in step.spec.produces:
                    if kind_of(k).storage == "image_cache":
                        self.ctx.cache.invalidate(self.book.id, k, key_prefix=key)
                products = step.run_page(self.ctx, pg)
                for k in products:
                    if k not in step.spec.produces:
                        raise ValueError(f"{sid} 产出了未声明的种类 {k!r}")
                    if kind_of(k).storage != "numeric":
                        raise ValueError(f"{sid} 把图像类 {k!r} 当 numeric 返回了")
                _, sha = self.store.write(self.book.id, sid, key, products)
                self._stamp_cache(step, key, sha)
                elapsed = time.time() - t0
                manifest.put(ManifestEntry(key=key, fingerprint=fp, sha256=sha,
                                           params_hash=ph, upstream=ups or {},
                                           code_rev=self._rev, elapsed=round(elapsed, 3),
                                           self_hash=self.self_hash(step),
                                           soft=soft_values(step, self.ctx.params_for(step)),
                                           book=book_dep_values(step, self.book)))
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
                    return done, True
        return done, False

    def _run_one_step_parallel(self, step: Step, pages: list[int], report: RunReport,
                                force: bool, stop_on_error: bool, total: int, done: int,
                                jobs: int) -> tuple[int, bool]:
        """`_run_one_step` 的并行版：**计算在子进程、落盘在主进程**——子进程各自
        `load_book`/`load_pipeline` 建一份独立 `RunContext`（不 pickle `self.ctx`，
        它拖带 `store`/`cache` 这类跨进程共享不安全的对象），只跑纯函数
        `step.run_page`；指纹判断、`store.write`、`manifest.put`、图像缓存失效
        全部留在主进程串行做，与 `_run_one_step` 落盘代码逐行同形，保证产物
        sha256 与串行跑法逐位一致（`scripts/parallel_border_detect.py` 已验证过
        这个拆法：单进程/多进程/`guji step` 三方 sha 对得上）。

        `stop_on_error` 在并行分支里只能是「整批提交完、发现失败就不再继续下一批
        page」的近似语义，不能像串行那样跑到哪页失败就精确停在那页——`jobs`
        张页是同时提交的，无法半路收回已经在跑的任务。"""
        sid = step.spec.id
        manifest = self.store.manifest(self.book.id, sid)
        self.log(f"== {sid} {step.spec.title}：{len(pages)} 页（{jobs} 进程并行）")

        todo: list[int] = []
        fps: dict[int, tuple[str, dict, str]] = {}
        for pg in pages:
            done += 1
            key = page_key(pg)
            fp, ups, ph = self.fingerprint(step, pg)
            pct = int(done * 100 / max(total, 1))
            if fp is None:
                msg = f"上游缺失: {self.missing_upstream(step, pg)}"
                self.log(f"[{done}/{total}] {pct}% {sid} p{pg}: 阻塞（{msg}）")
                report.outcomes.append(PageOutcome(sid, pg, "failed", error=msg))
                manifest.put(ManifestEntry(key=key, fingerprint="", params_hash=ph,
                                           upstream={}, code_rev=self._rev,
                                           status="failed", error=msg))
                if stop_on_error:
                    return done, True
                continue
            entry = manifest.get(key)
            if (not force and entry and entry.status == "ok" and entry.fingerprint == fp
                    and not entry.invalidated and self.store.exists(self.book.id, sid, key)):
                self.log(f"[{done}/{total}] {pct}% {sid} p{pg}: 新鲜，跳过")
                report.outcomes.append(PageOutcome(sid, pg, "skipped"))
                continue
            for k in step.spec.produces:
                if kind_of(k).storage == "image_cache":
                    self.ctx.cache.invalidate(self.book.id, k, key_prefix=key)
            fps[pg] = (fp, ups, ph)
            todo.append(pg)

        if not todo:
            return done, False

        from concurrent.futures import ProcessPoolExecutor
        any_failed = False
        # `initializer`：重资源 Step（`glyph_match` 的字形库、`row_segment` 的
        # U-Net 权重等）在 worker **进程启动时**建一次 `RunContext`，之后这个
        # worker 处理的每一页都复用它——不是每页各自冷启动。`initializer` 只在
        # 进程刚起时跑一次，跟 worker 后续处理几页无关，工作量小的 Step（如
        # `border_detect`）多这一次 `load_book`/`load_pipeline` 也无害。
        with ProcessPoolExecutor(max_workers=jobs, initializer=_parallel_worker_init,
                                 initargs=(self.book.id, self.pipeline.id, sid)) as ex:
            for pg, products, err, elapsed in ex.map(_parallel_worker, todo, chunksize=1):
                fp, ups, ph = fps[pg]
                key = page_key(pg)
                if err is not None:
                    manifest.put(ManifestEntry(key=key, fingerprint=fp, params_hash=ph,
                                               upstream=ups or {}, code_rev=self._rev,
                                               elapsed=round(elapsed, 3), status="failed", error=err))
                    self.log(f"{sid} p{pg}: 失败 {err}")
                    report.outcomes.append(PageOutcome(sid, pg, "failed", elapsed, err))
                    any_failed = True
                    continue
                try:
                    for k in products:
                        if k not in step.spec.produces:
                            raise ValueError(f"{sid} 产出了未声明的种类 {k!r}")
                        if kind_of(k).storage != "numeric":
                            raise ValueError(f"{sid} 把图像类 {k!r} 当 numeric 返回了")
                    _, sha = self.store.write(self.book.id, sid, key, products)
                    self._stamp_cache(step, key, sha)
                    manifest.put(ManifestEntry(key=key, fingerprint=fp, sha256=sha,
                                               params_hash=ph, upstream=ups or {},
                                               code_rev=self._rev, elapsed=round(elapsed, 3),
                                               self_hash=self.self_hash(step),
                                               soft=soft_values(step, self.ctx.params_for(step)),
                                               book=book_dep_values(step, self.book)))
                    self.log(f"{sid} p{pg}: 完成 {elapsed:.2f}s")
                    report.outcomes.append(PageOutcome(sid, pg, "ok", elapsed))
                except Exception as e:  # noqa: BLE001 —— 落盘校验失败也不拖垮整批
                    err2 = f"{type(e).__name__}: {e}"
                    manifest.put(ManifestEntry(key=key, fingerprint=fp, params_hash=ph,
                                               upstream=ups or {}, code_rev=self._rev,
                                               elapsed=round(elapsed, 3), status="failed", error=err2))
                    self.log(f"{sid} p{pg}: 失败 {err2}")
                    report.outcomes.append(PageOutcome(sid, pg, "failed", elapsed, err2))
                    any_failed = True
        return done, any_failed and stop_on_error

    def run(self, steps: list[str] | None = None, pages: list[int] | None = None,
            force: bool = False, stop_on_error: bool = False, jobs: int = 1) -> RunReport:
        """按 `steps`（默认 pipeline 的 `steps:` 列表）逐个跑。

        **闸跟着它挂的 Step 自动跑**，不需要出现在 `steps` 里：`step.spec.gate`
        非空时，这个 Step 跑完当前这批页之后紧接着跑 `STEPS[gate.id]`——这就是
        「框架统一跑闸」，调用方（含 `steps=[...]` 显式点名到某个旧 Step id 的
        历史调用，如 `scripts/seg_harness.py` 的 `BOOTSTRAP_STEPS`）不用改。
        显式把闸的 id 也点在 `steps` 里仍然安全：闸第二次跑到时指纹已新鲜，
        直接跳过。

        `jobs > 1`：页级并行只对 `step.spec.parallel_safe=True` 的 Step 生效
        （见 `StepSpec.parallel_safe`），其余 Step 不受影响、照常串行——同一次
        `run()` 里几个 Step 的并行与否可以不一样，调用方不用分开调。闸目前都
        不是 `parallel_safe`（闸很快，见 `scripts/parallel_border_detect.py`
        的实测：<0.1s/页），跟 Step 本体一起传 `jobs` 也没有额外风险，只是
        闸内部判断到没标记会自动退回串行。
        """
        steps, _ = self._default_steps(steps)
        pages = pages if pages is not None else self.book.resolve_pages("dev_set")
        report = RunReport(self.book.id, self.pipeline.id, list(steps), list(pages))
        gated_extra = [STEPS[s].spec.gate.id for s in steps
                       if STEPS[s].spec.gate and STEPS[s].spec.gate.id not in steps]
        total = len(pages) * (len(steps) + len(gated_extra))
        done = 0
        for sid in steps:
            step = STEPS[sid]
            done, stopped = self._run_one_step(step, pages, report, force, stop_on_error,
                                               total, done, jobs)
            if stopped:
                report.finished_at = time.time()
                return report
            gate = step.spec.gate
            if gate and gate.id not in steps:
                gate_step = STEPS[gate.id]
                done, stopped = self._run_one_step(gate_step, pages, report, force,
                                                    stop_on_error, total, done, jobs)
                if stopped:
                    report.finished_at = time.time()
                    return report
        report.finished_at = time.time()
        c = report.counts()
        self.log("完成：" + "；".join(f"{s} ok {v['ok']} / 跳过 {v['skipped']} / 失败 {v['failed']}"
                                    for s, v in c.items()))
        return report


# worker 进程级状态——每个子进程一份，`_parallel_worker_init` 在进程启动时填好，
# 之后这个进程处理的每一页都复用，不重新 `load_book`/建 `RunContext`。
_worker_ctx: "RunContext | None" = None
_worker_step: "Step | None" = None


def _parallel_worker_init(book_id: str, pipeline_id: str, step_id: str) -> None:
    """`ProcessPoolExecutor(initializer=...)`：每个 worker 进程启动时跑一次。
    像 `glyph_match`（字形库）、`row_segment`（U-Net 权重）这类 Step 把重资源
    缓存在 `Step` 实例的 `self.<attr>` 上（进程内单例，见各 Step 源码），这里
    建的 `step` 实例正是后续 `run_page` 调用会用到的那个，一次初始化、整个
    worker 生命周期内的所有页都复用，不是每页各自冷启动。"""
    global _worker_ctx, _worker_step
    from .book import load_book
    from .pipeline import load_pipeline
    from ..products.cache import ImageCache
    from ..products.store import ProductStore
    book = load_book(book_id)
    pipeline = load_pipeline(pipeline_id)
    _worker_step = STEPS[step_id]
    _worker_ctx = RunContext(book, ProductStore(), ImageCache(), log=lambda s: None, pipeline=pipeline)


def _parallel_worker(page: int) -> tuple[int, dict | None, str | None, float]:
    """`_run_one_step_parallel` 的子进程体：用 `_parallel_worker_init` 建好的
    进程级 ctx/step，只算不写盘。模块级函数（不是方法）——`ProcessPoolExecutor`
    要能 pickle 它；实际状态在 `_worker_ctx`/`_worker_step`，不在参数里。"""
    t0 = time.time()
    try:
        products = _worker_step.run_page(_worker_ctx, page)
        return page, products, None, time.time() - t0
    except Exception as e:  # noqa: BLE001 —— 一页失败不拖垮整批
        return page, None, f"{type(e).__name__}: {e}", time.time() - t0
