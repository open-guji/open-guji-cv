"""benchmark 统一接口（CV0 2026-11-28，用户定「每个 benchmark 统一接口、命令接进 guji-manager」）。

设计：Claude Doc《benchmark 统一接口设计》；分派单 ai-team `domain/CV/规范/bench统一接口-2026-11-28.md`。

分工：
- **本模块（cv）**：登记表 `BenchSpec`、交给 bench 的上下文 `BenchCtx`、统一结果 `BenchResult`、护栏判定、
  翻转清单、结果落盘。各 bench 的跑法与打分放 `eval/benches/<名>.py`，跟算法一起发版。
- **guji-manager**：命令 `guji bench list|fetch|run|ab|guard|show`，按书备齐资源（金标、册配置、原图、产物包、
  字形库、模型、语料）填进 `BenchCtx.res`，再调本模块。bench 自己不找路径、不读环境变量。

约束：按书（没有金标报 `no_gold`，`nogold=True` 的只跑体检）；可复现（不在线问大模型、不带人裁）；
不写任何正式数据（金标、中心库、产物都不动）。结果格式 `schema: 1` 见 `BenchResult.to_json`。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

SCHEMA = 1
STATUSES = ("ok", "regressed", "skipped", "no_gold")
#: 资源种类（manager 按这些取，填进 ctx.res 的同名键）
NEEDS = ("gold", "config", "code", "raw", "products", "glyph_lib", "models", "corpus", "torch", "gpu", "ocr")


@dataclass(frozen=True)
class Guard:
    metric: str
    dir: str            # max：不许超过 limit；min：不许低于 limit
    limit: float

    def check(self, value) -> str:
        if value is None:
            return "unverified"
        bad = value > self.limit if self.dir == "max" else value < self.limit
        return "regressed" if bad else "ok"


@dataclass(frozen=True)
class BenchSpec:
    id: str
    title: str
    steps: tuple[str, ...]
    owner: str
    #: 金标：dataset 里的分片。字符串＝按约定 `<分片>/<书id>/`；字典＝显式表
    #: `{书id: 路径}` 或册一级 `{书id: {册: 路径}}`（路径相对 dataset 根）。
    gold: str | dict
    needs: tuple[str, ...]
    primary: str
    run: Callable[["BenchCtx"], Path]
    score: Callable[["BenchCtx", Path], "BenchResult"]
    mode: str = "run"                       # read：只读现成产物；run：从冻结输入跑
    guards: tuple[Guard, ...] = ()
    cost: str = "light"                     # light：一本书 10 分钟内；heavy：要 GPU、大库或更久
    nogold: bool = False                    # 没金标的书能不能只跑体检
    #: 结果里逐样本的键与「对不对」字段（翻转清单用）
    item_key: str = "id"
    item_ok: str = "ok"
    #: bench 自己的参数（`guji bench run … --arg k=v`），值是说明
    args: dict = field(default_factory=dict)
    suites: tuple[str, ...] = ()
    deprecated: str = ""

    def __post_init__(self):
        bad = set(self.needs) - set(NEEDS)
        if bad:
            raise ValueError(f"bench {self.id}：未知资源 {sorted(bad)}，只认 {NEEDS}")
        if self.mode not in ("run", "read") or self.cost not in ("light", "heavy"):
            raise ValueError(f"bench {self.id}：mode／cost 写错")

    def gold_rel(self, book: str, vol: str | None = None) -> str | None:
        """这本书（或这册）的金标相对路径；没有返回 None。"""
        g = self.gold
        if isinstance(g, str):
            return f"{g.rstrip('/')}/{book}"
        v = g.get(book)
        if isinstance(v, dict):
            return v.get(vol) if vol is not None else next(iter(v.values()), None)
        return v

    def gold_books(self) -> list[str] | None:
        """有金标的书；约定式分片要看 dataset 目录才知道，返回 None。"""
        return None if isinstance(self.gold, str) else sorted(self.gold)


@dataclass
class BenchCtx:
    book: str                               # 书 id（工作区 id）
    vols: list[str]
    work: Path                              # 这次的工作目录（bench 随便写）
    res: dict[str, Any]                     # 资源本地路径：gold、data、ws、products、glyph_lib…
    pages: dict[str, list[int]] | None = None
    params: dict | None = None              # 运行覆盖（只给 run 模式）
    args: dict[str, str] = field(default_factory=dict)
    env: dict[str, Any] = field(default_factory=dict)   # 资源版本、cv／manager 版本，原样进结果


@dataclass
class BenchResult:
    bench: str
    book: str
    vols: list[str]
    metrics: dict[str, Any]
    primary: str
    items: list[dict] = field(default_factory=list)
    n: int = 0
    status: str = "ok"
    reason: str = ""
    guards: list[dict] = field(default_factory=list)
    against: dict | None = None
    env: dict = field(default_factory=dict)
    seconds: float = 0.0

    def to_json(self) -> dict:
        return {"bench": self.bench, "schema": SCHEMA, "book": self.book, "vols": self.vols, "n": self.n,
                "primary": {"name": self.primary, "value": self.metrics.get(self.primary)},
                "metrics": self.metrics, "guards": self.guards, "status": self.status, "reason": self.reason,
                "against": self.against, "env": self.env, "seconds": round(self.seconds, 1)}


def skipped(spec: BenchSpec, ctx: BenchCtx, reason: str, status: str = "skipped") -> BenchResult:
    return BenchResult(spec.id, ctx.book, ctx.vols, {}, spec.primary, status=status, reason=reason, env=ctx.env)


def apply_guards(spec: BenchSpec, r: BenchResult) -> BenchResult:
    """按登记的护栏逐条判；任一条越线 → regressed。护栏阈值以 dataset `guards/` 为准时由调用方传进 extra。"""
    for g in spec.guards:
        v = r.metrics.get(g.metric)
        st = g.check(v)
        r.guards.append({"metric": g.metric, "dir": g.dir, "limit": g.limit, "value": v, "status": st})
        if st == "regressed" and r.status == "ok":
            r.status = "regressed"
    return r


def compare(spec: BenchSpec, now: list[dict], before: list[dict]) -> dict:
    """逐样本比：对→错算变坏，错→对算好转，两边都在但别的字段变了算其他。"""
    k, ok = spec.item_key, spec.item_ok
    old = {x[k]: x for x in before}
    better, worse, other = [], [], []
    for x in now:
        y = old.get(x[k])
        if y is None:
            continue
        if bool(y.get(ok)) and not bool(x.get(ok)):
            worse.append(x[k])
        elif not bool(y.get(ok)) and bool(x.get(ok)):
            better.append(x[k])
        elif {a: b for a, b in x.items() if a != k} != {a: b for a, b in y.items() if a != k}:
            other.append(x[k])
    return {"better": len(better), "worse": len(worse), "other": len(other),
            "worse_items": worse, "better_items": better, "other_items": other}


def execute(spec: BenchSpec, ctx: BenchCtx, against: Path | None = None) -> BenchResult:
    """跑一次：run → score → 对照 → 护栏。缺资源由调用方先判（manager），这里只兜异常不兜假通过。"""
    t0 = time.time()
    pred = spec.run(ctx)
    r = spec.score(ctx, pred)
    r.env = {**ctx.env, **r.env}
    r.n = r.n or len(r.items)
    if against is not None:
        cmp = compare(spec, r.items, load_items(against))
        r.against = {"result": str(against), **{k: v for k, v in cmp.items() if not k.endswith("_items")}}
        r.metrics.setdefault("flip_worse", cmp["worse"])
        r.metrics.setdefault("flip_better", cmp["better"])
        r._flips = cmp                                   # report.md 用
    apply_guards(spec, r)                                # 对照算完再判，flip_worse 护栏才有值
    r.seconds = time.time() - t0
    return r


def load_items(result_dir: Path) -> list[dict]:
    p = Path(result_dir) / "items.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def write_result(out: Path, r: BenchResult) -> Path:
    """落 `result.json`、`items.jsonl`、`report.md`。"""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "result.json").write_text(json.dumps(r.to_json(), ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    with open(out / "items.jsonl", "w", encoding="utf-8") as fh:
        for x in r.items:
            fh.write(json.dumps(x, ensure_ascii=False, default=str) + "\n")
    L = [f"# {r.bench} · {r.book}（{'、'.join(r.vols)}）", "",
         f"- 状态：**{r.status}**{('（' + r.reason + '）') if r.reason else ''}",
         f"- 主指标 {r.primary}：{r.metrics.get(r.primary)}（{r.n} 个样本）", ""]
    if r.metrics:
        L += ["| 指标 | 值 |", "|---|---|"] + [f"| {k} | {v} |" for k, v in r.metrics.items()
                                             if not isinstance(v, (dict, list))] + [""]
    if r.guards:
        L += ["护栏：", ""] + [f"- {g['metric']} {g['dir']} {g['limit']}：{g['value']} → {g['status']}" for g in r.guards] + [""]
    flips = getattr(r, "_flips", None)
    if flips:
        L += [f"对照 {r.against['result']}：好转 {flips['better']}、变坏 {flips['worse']}、其他 {flips['other']}", ""]
        L += [f"- 变坏 {x}" for x in flips["worse_items"][:20]]
    (out / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    return out


# ---------------------------------------------------------------- 登记表
_REGISTRY: dict[str, BenchSpec] = {}


def register(spec: BenchSpec) -> BenchSpec:
    if spec.id in _REGISTRY:
        raise ValueError(f"bench id 重复：{spec.id}")
    _REGISTRY[spec.id] = spec
    return spec


def _load() -> None:
    from . import benches  # noqa: F401 —— 各 bench 模块在 import 时登记


def get(bench_id: str) -> BenchSpec:
    _load()
    if bench_id not in _REGISTRY:
        raise KeyError(f"没有 bench {bench_id!r}；有：{', '.join(sorted(_REGISTRY))}")
    return _REGISTRY[bench_id]


def all_specs() -> list[BenchSpec]:
    _load()
    return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def expand(names: list[str]) -> list[BenchSpec]:
    """bench id 或 `@套名`（`suites` 里写了的）展开成登记项。"""
    _load()
    out: list[BenchSpec] = []
    for n in names:
        if n.startswith("@"):
            hit = [s for s in all_specs() if n[1:] in s.suites]
            if not hit:
                raise KeyError(f"没有 bench 套 {n}")
            out += hit
        else:
            out.append(get(n))
    return out
