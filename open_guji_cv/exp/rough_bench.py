# -*- coding: utf-8 -*-
"""粗校基准（M9 D6-5，GUJI-669）：固定的一批页＋冻结的标签，专家改动先在这上面量两个数再进 rc。

设计见 `doc/design/M9-平台粗校-调研与总设计.md` D6 第 5 条：

- **人审率变化**：正文页送审率，变体对基线（以页为簇的自助法区间，同 `guji exp`）；
- **错放数**：有标签的格里，变体放行了、字又不对的格数。**新增错放（基线对、变体错）必须为 0**；
  基线本来就错的格另报（那是现行版的已知错，不算这次改动的账）。

## 基准由什么组成（open-guji-dataset `rough-bench/`）

| 文件 | 内容 |
|---|---|
| `bench.yaml` | 册、每册冻结的页（`random` 随机页 + `hard` 标签最多的难页）、快照产物包标签、判准 |
| `items.jsonl` | 冻结的标签（金标信封，`exp.labels.load_gold` 直接读）：人裁（`label_origin=human`）＋看图结论（`vision`） |
| `report.json` | 建基准时现行代码在快照上的基线数（回归门比它） |

- **快照**：各册冻结时的 main 产物包（`guji products pack`），跑基准时从 R2 取回，seed_admit 之前的各步
  不重跑；改切分的专家从更早的步起跑（`--from`），快照照旧当上游。
- **人裁标签**按绑定表（`feedback/bindings.compute_page`）对到快照的现行切分：`valid`／`rebound` 才收，
  收的是快照里的格号。不看字块图（快照不带缓存），只按锚框几何判。
- **看图结论**没有锚框，只收「快照这一格的现行字＝看图时显示的字」的（同一块像素、同一个字，几乎不会对错格）；
  批注以 `[S8]` 开头的是出口抽样（对已放行格随机抽），记 `random`，可估错率；其余记 `picked`，只报计数。
- 冻结之后不再跟着中心库变：新的人裁要进基准，重建一版（`build`），旧版的数照旧可比。

只读快照与中心库，只写基准目录（建）或实验目录（跑）。不碰任何 Step，`code_hash` 不变。
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from ..errors import BadRequest

SHARD = "rough-bench"
BENCH_YAML = "bench.yaml"
ITEMS = "items.jsonl"
DEFAULT_BOOKS = tuple(f"vol{i:02d}" for i in range(4, 11))
S8_MARK = "[S8]"
DEFECT_V = {"seg_defect", "not_a_char"}
HUMAN_WEIGHT = 3


class _NoCache:
    """快照不带字块缓存：绑定只按几何判（`bindings.compute_page` 拿不到图就退回几何规则）。"""

    def get(self, *a, **k):
        return None


def _split_key(key: str) -> tuple[str, int, int, int, str]:
    from ..feedback.anchor import parse_cell_key
    pk = parse_cell_key(key)
    if pk is None:
        raise ValueError(key)
    return pk


# ── 标签 ─────────────────────────────────────────────────────────────────
def human_labels(snapshot: Path, books, log=None) -> list[dict]:
    """人裁（`counts_as_human` 的格级 confirm，每格取最新）→ 绑到快照现行切分的标签行。"""
    from ..feedback.bindings import compute_page
    from ..feedback.events import EventLog, counts_as_human, iter_events_readonly
    from ..products.store import ProductStore
    books = set(books)
    by_page: dict[tuple[str, int], list] = defaultdict(list)
    for e in sorted(iter_events_readonly(log or EventLog()), key=lambda e: (e.ts, e.batch, e.seq)):
        if e.kind != "confirm" or e.target.unit != "cell" or not counts_as_human(e):
            continue
        if (e.target.step or "seed_admit") != "seed_admit":
            continue
        try:
            book, page, *_ = _split_key(e.target.key)
        except ValueError:
            continue
        if book in books:
            by_page[(book, page)].append(e)
    st = ProductStore(snapshot)
    latest: dict[str, dict] = {}
    for (book, page), evs in sorted(by_page.items()):
        ev_by_id = {e.id: e for e in evs}
        for row in compute_page(book, page, evs, store=st, cache=_NoCache(), backfill={}):
            if row["status"] not in ("valid", "rebound") or not row.get("bound"):
                continue
            e = ev_by_id[row["event"]]
            p = e.payload or {}
            v = p.get("v") or p.get("verdict")
            lab = {"cell": row["bound"], "origin": "human", "selection": "picked", "event": e.id,
                   "batch": e.batch, "ts": e.ts, "bind": row["status"], "from_key": e.target.key,
                   "bbox": (e.target.anchor or {}).get("bbox")}
            if v in DEFECT_V:
                lab["defect"] = True
            elif p.get("reading") or p.get("shape"):
                lab["char"] = p.get("reading") or p.get("shape")
            else:
                continue
            latest[row["bound"]] = lab           # 按时间序，后到覆盖
    return [latest[k] for k in sorted(latest)]


def vision_labels(snapshot: Path, books, files) -> list[dict]:
    """看图结论事件（`feedback/vision/*.jsonl`）→ 只收快照现行字＝当时显示字的格。"""
    from .compare import load_cells
    books = set(books)
    latest: dict[str, tuple] = {}
    for f in files:
        for i, ln in enumerate(Path(f).read_text(encoding="utf-8").splitlines()):
            if not ln.strip():
                continue
            r = json.loads(ln)
            t = r.get("target") or {}
            if t.get("unit") != "cell" or t.get("book") not in books or not t.get("key"):
                continue
            rank = (r.get("ts") or "", Path(f).name, i)
            if t["key"] not in latest or rank >= latest[t["key"]][0]:
                latest[t["key"]] = (rank, r)
    cells: dict[str, dict] = {}
    for b in sorted(books):
        cells.update(load_cells(snapshot, b))
    out = []
    for key, (_, r) in sorted(latest.items()):
        p = r.get("payload") or {}
        shown, v = p.get("shown") or "", p.get("v")
        cur = cells.get(key)
        if cur is None or not shown or cur["char"] != shown:
            continue
        note = str(p.get("note") or "")
        lab = {"cell": key, "origin": "vision", "selection": "random" if note.startswith(S8_MARK) else "picked",
               "event": r.get("id"), "batch": r.get("batch"), "ts": r.get("ts"), "judge": p.get("judge"),
               "note": note[:120]}
        if v == "ok":
            lab["char"] = shown
        elif v == "wrong" and p.get("char"):
            lab["char"] = p["char"]
        elif v == "wrong":
            lab["wrong"] = [shown]
        else:
            continue                              # unsure：不当标签
        out.append(lab)
    return out


def merge_labels(human: list[dict], vision: list[dict]) -> tuple[list[dict], list[dict]]:
    """同格人裁优先；人裁与看图说的字不同记冲突（仍取人裁）。"""
    by = {x["cell"]: x for x in vision}
    conflicts = []
    for h in human:
        v = by.get(h["cell"])
        if v and v.get("char") and h.get("char") and v["char"] != h["char"]:
            conflicts.append({"cell": h["cell"], "human": h["char"], "vision": v["char"]})
        by[h["cell"]] = h
    return [by[k] for k in sorted(by, key=_cell_sort)], conflicts


def _cell_sort(k: str):
    b, p, c, s, sub = _split_key(k)
    return (b, p, c, s, sub)


# ── 选页 ─────────────────────────────────────────────────────────────────
def pick_pages(snapshot: Path, books, labels: list[dict], n_random: int = 12, n_hard: int = 16,
               seed: int = 0) -> dict[str, dict[str, list[int]]]:
    """每册正文页里：`hard` = 标签分最高的 n_hard 页（人裁一格记 3 分、看图一格 1 分——人裁多是难格，
    看图多是普查）；`random` = 其余正文页里按种子随机 n_random 页。"""
    from .compare import load_cells
    from .runner import page_types
    per_page: Counter = Counter()
    for x in labels:
        b, p, *_ = _split_key(x["cell"])
        per_page[(b, p)] += HUMAN_WEIGHT if x["origin"] == "human" else 1
    out = {}
    for b in books:
        pt = page_types(snapshot, b)
        have = sorted({c["page"] for c in load_cells(snapshot, b).values()})
        body = [p for p in have if pt.get(p) == "body"]
        hard = sorted(sorted(body, key=lambda p: (-per_page[(b, p)], p))[:n_hard])
        hard = [p for p in hard if per_page[(b, p)] > 0]
        rest = [p for p in body if p not in hard]
        rng = random.Random(f"{seed}:{b}")
        rnd = sorted(rng.sample(rest, min(n_random, len(rest))))
        out[b] = {"random": rnd, "hard": hard}
    return out


def gold_items(labels: list[dict], pages: dict[str, dict[str, list[int]]], snapshot_packs: dict[str, str],
               why: str) -> list[dict]:
    """选中页上的标签 → 金标信封行（`exp.labels.load_gold` 读：有 `stratum` 记 picked，没有记 random）。"""
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    keep = {(b, p) for b, d in pages.items() for p in d["random"] + d["hard"]}
    out = []
    for x in labels:
        b, p, c, s, sub = _split_key(x["cell"])
        if (b, p) not in keep:
            continue
        exp = {k: x[k] for k in ("char", "defect", "wrong") if x.get(k)}
        if sub:
            exp["sub"] = sub
        item = {"id": x["cell"], "anchor": {"book": b, "page": p, "col": c, "slot": s},
                "input": {k: x[k] for k in ("batch", "bind", "from_key", "note") if x.get(k)},   # 不抄 judge（模型名）
                "expected": exp, "label_origin": x["origin"], "pipeline_version": snapshot_packs.get(b),
                "status": "active", "source_events": [x["event"]] if x.get("event") else [],
                "history": [{"ts": now, "change": "created", "why": why}]}
        if x.get("bbox"):
            item["anchor"]["bbox"] = x["bbox"]
            item["anchor"]["space"] = "raw_page_px@top-right"
        if x["selection"] != "random":
            item["stratum"] = "human_queue" if x["origin"] == "human" else "vision_picked"
        out.append(item)
    return out


def build(snapshot: Path, out_dir: Path, snapshot_packs: dict[str, str], books=DEFAULT_BOOKS,
          vision_files=(), n_random: int = 12, n_hard: int = 16, seed: int = 0, why: str = "") -> dict:
    """冻结一版基准：写 `bench.yaml`、`items.jsonl`，返回概要（不跑管线）。"""
    import yaml
    books = list(books)
    human = human_labels(snapshot, books)
    vision = vision_labels(snapshot, books, vision_files)
    labels, conflicts = merge_labels(human, vision)
    pages = pick_pages(snapshot, books, labels, n_random=n_random, n_hard=n_hard, seed=seed)
    items = gold_items(labels, pages, snapshot_packs, why or "粗校基准冻结（M9 GUJI-669）")
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = {"name": SHARD, "books": books, "snapshot_packs": dict(snapshot_packs), "seed": seed,
           "pages": {b: pages[b] for b in books}, "labels": ITEMS, "match": "exact",
           "guardrails": [{"metric": "flips.right_to_wrong", "op": "==", "value": 0},
                          {"metric": "review_rate", "scope": "body", "op": "<=", "ref": "base", "delta": 0.002}]}
    (out_dir / BENCH_YAML).write_text(yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (out_dir / ITEMS).write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")
    cnt = Counter((i["label_origin"], "picked" if i.get("stratum") else "random") for i in items)
    return {"pages": sum(len(d["random"]) + len(d["hard"]) for d in pages.values()), "items": len(items),
            "by_origin": {f"{o}/{s}": n for (o, s), n in sorted(cnt.items())},
            "labels_all": len(labels), "human_all": len(human), "vision_all": len(vision),
            "conflicts": conflicts}


# ── 跑 ───────────────────────────────────────────────────────────────────
def load_bench(shard: Path) -> dict:
    import yaml
    p = Path(shard) / BENCH_YAML
    if not p.exists():
        raise BadRequest(f"不是粗校基准目录（没有 {BENCH_YAML}）：{shard}")
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def bench_pages(bench: dict) -> dict[str, list[int]]:
    return {b: sorted(set(d["random"]) | set(d["hard"])) for b, d in bench["pages"].items()}


def ensure_snapshot(bench: dict, snap: Path, ws: str | None, log=print) -> None:
    """快照缺哪册就从 R2 取哪册的冻结包（`guji products pack fetch --label`）。"""
    for b, label in bench["snapshot_packs"].items():
        if (snap / b / "seed_admit").is_dir():
            continue
        log(f"取快照 {b} ← {label}")
        cmd = [sys.executable, "-m", "open_guji_cv", "products", "pack", "fetch", b, "--label", label,
               "--to", str(snap)] + (["-w", ws] if ws else [])
        subprocess.run(cmd, check=True)


def exp_config(bench: dict, shard: Path, variants: dict[str, dict], base: dict | None = None,
               from_step: str = "seed_admit", name: str | None = None):
    """基准 → `guji exp` 的实验配置。没有变体时放一个空变体占位（`run` 只跑基线）。"""
    from .config import from_dict
    d = {"name": name or f"{SHARD}-{time.strftime('%m%d-%H%M')}", "books": list(bench["books"]),
         "from": from_step, "to": "seed_admit", "pages": bench_pages(bench), "match": bench.get("match", "exact"),
         "base": base or {}, "variants": variants or {"B": {}},
         "labels": [{"source": "gold", "path": str((Path(shard) / bench.get("labels", ITEMS)).resolve())}],
         "guardrails": list(bench.get("guardrails") or [])}
    return from_dict(d)


DRIFT_IOU = 0.8      # 变体重切后，同格号的框与快照里的框 IoU 低于这个就不拿标签考它（可能已不是同一个字）


def cell_boxes(root: Path, keys) -> dict[str, list[float]]:
    """产物根里这些格号的原图外接框（Step3 `quad_page`）；没有切分产物的册／页跳过。"""
    from ..core.spec import page_key
    from ..feedback.bindings import _cell_index
    from ..products.store import ProductStore
    from ..report.slots import CELLS_KIND, cells_step
    st = ProductStore(root)
    pages: dict[tuple[str, int], list[str]] = defaultdict(list)
    for k in keys:
        b, p, *_ = _split_key(k)
        pages[(b, p)].append(k)
    out: dict[str, list[float]] = {}
    for (b, p), ks in pages.items():
        try:
            cells = st.read(b, cells_step(b), page_key(p), CELLS_KIND)
        except Exception:  # noqa: BLE001 —— 没有这一页的切分产物：不比
            cells = None
        if cells is None:
            continue
        idx = _cell_index(cells)
        for k in ks:
            _, _, c, s, sub = _split_key(k)
            if (c, s, sub) in idx:
                out[k] = idx[(c, s, sub)][0]
    return out


def drifted(snapshot: Path | None, vroot: Path, keys) -> set[str]:
    """变体重切过（`--from` 在切分步或更早）时，格号还指着快照里那块像素吗？指不上的标签不用。"""
    if snapshot is None:
        return set()
    from ..feedback.bindings import _iou
    ref, now = cell_boxes(snapshot, keys), cell_boxes(vroot, keys)
    return {k for k in ref if k not in now or _iou(ref[k], now[k]) < DRIFT_IOU}


def summarize(edir: Path, cfg, variants: list[str], snapshot: Path | None = None) -> dict:
    """两个数：各变体的正文送审率；有标签的格里的错放（新增的必须为 0）。

    给了 `snapshot` 就先查格号漂没漂（`drifted`）：漂了的标签在那个变体上不算，计数记在 `label_drift`。"""
    from . import compare as C
    from . import labels as LB
    from .runner import UPSTREAM, page_types
    labs, _ = LB.load_all(cfg.labels, cfg.books)
    labels, _ = LB.merge(labs)
    same = C.make_same(cfg.match)
    pts = {b: page_types(edir / UPSTREAM, b) for b in cfg.books}
    cells = {v: {k: r for b in cfg.books for k, r in C.load_cells(edir / v, b).items()} for v in variants}
    out: dict = {"labels": len(labels), "variants": {}}
    base = variants[0]
    gone_by: dict[str, set] = {}
    for v in variants:
        body = [r for r in cells[v].values() if pts[r["book"]].get(r["page"]) == "body"]
        n_rev = sum(r["state"] == "review" for r in body)
        gone = drifted(snapshot, edir / v, labels)
        gone_by[v] = gone | {k for k in labels if k not in cells[v]}
        use = {k: lab for k, lab in labels.items() if k in cells[v] and k not in gone}
        wrong = sorted(k for k, lab in use.items() if C.admit_err(cells[v][k], lab, same) == 1)
        judged = sum(1 for k, lab in use.items() if C.admit_err(cells[v][k], lab, same) is not None)
        out["variants"][v] = {"cells_body": len(body), "review_body": n_rev,
                              "review_rate_body": round(n_rev / len(body), 6) if body else None,
                              "labelled_judged": judged, "wrong_admits": len(wrong), "wrong_cells": wrong,
                              "label_drift": len(gone), "label_missing": sum(1 for k in labels if k not in cells[v])}
    if len(variants) > 1:
        bw = set(out["variants"][base]["wrong_cells"])
        for v in variants[1:]:
            vw = set(out["variants"][v]["wrong_cells"])
            a, b = out["variants"][base], out["variants"][v]
            out["variants"][v].update(
                review_rate_diff=None if a["review_rate_body"] is None else round(b["review_rate_body"] - a["review_rate_body"], 6),
                new_wrong=sorted(vw - bw), fixed_wrong=sorted(bw - vw - gone_by[v]), passed=not (vw - bw))
    return out


def run(shard: Path, snapshot: Path, *, ws: str | None = None, variants: dict[str, dict] | None = None,
        base: dict | None = None, from_step: str = "seed_admit", root: Path | None = None, jobs: int = 1,
        name: str | None = None, log=print) -> dict:
    """在快照上跑基准（只跑基线，或基线＋变体），返回 `summarize` 的结果；有变体时另出 `guji exp` 报告。"""
    from . import runner as RN
    bench = load_bench(shard)
    ensure_snapshot(bench, Path(snapshot), ws, log=log)
    cfg = exp_config(bench, shard, variants or {}, base=base, from_step=from_step, name=name)
    only = None if variants else [cfg.variants[0].name]
    RN.run(cfg, snapshot=snapshot, root=root, variants=only, jobs=jobs, log=log)
    edir = RN.exp_dir(cfg, root)
    names = [v.name for v in cfg.variants] if variants else [cfg.variants[0].name]
    res = summarize(edir, cfg, names, snapshot=Path(snapshot))
    res.update(exp=str(edir), bench=dict(books=bench["books"], packs=bench["snapshot_packs"]))
    if variants:
        from .report import build as build_report
        build_report(edir)
        res["report"] = str(edir / "report.md")
    return res
