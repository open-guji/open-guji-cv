# -*- coding: utf-8 -*-
"""实验的标签：每格一条「这格该是什么字」，带来源与**选样方式**。

| `source` | 读哪里 | 缺省 `selection` |
|---|---|---|
| `human_events` | `<feedback>/events/<book>-*.jsonl`，`step=seed_admit ∧ unit=cell ∧ kind∈{confirm,verdict} ∧ actor=user`，每格取最新 | 批名带抽检标记（`audit` 等，同 `eval_step7_replay.py`）→ `random`；其余是审查队列 → `picked` |
| `vision` | `看图结论.jsonl`（`feedback/vision.py` 的格式：cell / v / char / shown / ts）| `picked` |
| `gold` | 金标分片 `items.jsonl`（`GoldItem`：anchor 定格，`expected.char`）| 带 `stratum` → `picked`，否则 `random` |

**选样方式决定能不能当错率**（`step7_replay_eval.md` §2 的陷阱）：`picked` 是被挑过的样本
（审查队列、请审单、vol04 那 163 个 wrong），只能报计数，不得当错率；错误率与置信区间只用
`random` 标签。yaml 里每个来源都可以写 `selection:` 显式覆盖。

同一格多个来源：human > gold > vision；真值不一致的记 `conflicts`。
"""
from __future__ import annotations

import glob
import json
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import BadRequest

RANDOM, PICKED = "random", "picked"
SELECTIONS = (RANDOM, PICKED)
PRIORITY = {"human": 0, "gold": 1, "vision": 2}
#: 批名命中这些子串的是「对已放行格抽审」（与 `scripts/eval_step7_replay.py` 同口径）
SAMPLED_MARKS = ("shadow-review", "confirm-2026", "glyphlib", "siku-claude", "audit", "snap-batch")
DEFECT_V = {"seg_defect", "not_a_char"}


@dataclass
class Label:
    cell: str
    source: str                         # human / vision / gold
    selection: str                      # random / picked
    truth: str | None = None            # 该是的字
    wrong: set[str] = field(default_factory=set)   # 已知不是这些字（看图判错但没认出该是什么）
    defect: bool = False                # 切坏 / 非字
    ref: str = ""                       # 出处（批名 / 文件名）

    def to_dict(self) -> dict:
        return {"cell": self.cell, "source": self.source, "selection": self.selection,
                "truth": self.truth, "wrong": sorted(self.wrong), "defect": self.defect, "ref": self.ref}

    @classmethod
    def from_dict(cls, d: dict) -> "Label":
        return cls(cell=d["cell"], source=d["source"], selection=d["selection"], truth=d.get("truth"),
                   wrong=set(d.get("wrong") or ()), defect=bool(d.get("defect")), ref=d.get("ref") or "")


def _book_of(cell: str) -> str:
    return cell.split(":", 1)[0]


def _resolve(path: str | Path) -> Path:
    p = Path(path).expanduser()
    if p.is_absolute():
        return p
    from ..core.workspace import workspace_root
    ws = workspace_root()
    return (ws / p) if ws is not None and (ws / p).exists() else p.resolve()


def _sel(spec: dict, default: str) -> str:
    s = spec.get("selection") or default
    if s not in SELECTIONS:
        raise BadRequest(f"标签 selection 只能是 {SELECTIONS}：{s!r}")
    return s


# ── 三种来源 ─────────────────────────────────────────────────────────────
def load_human_events(spec: dict, books: list[str]) -> list[Label]:
    from ..core.workspace import feedback_root
    d = _resolve(spec["path"]) if spec.get("path") else feedback_root() / "events"
    out: list[Label] = []
    for book in books:
        best: dict[str, tuple] = {}
        for f in sorted(glob.glob(str(d / f"{book}-*.jsonl"))):
            batch = Path(f).stem
            for ln in Path(f).read_text(encoding="utf-8").splitlines():
                if not ln.strip():
                    continue
                r = json.loads(ln)
                t = r.get("target") or {}
                if t.get("step") != "seed_admit" or t.get("unit") != "cell" or t.get("book") != book:
                    continue
                if r.get("kind") not in ("confirm", "verdict") or r.get("actor") != "user":
                    continue
                if (r.get("payload") or {}).get("source") == "vision":
                    continue
                key = t.get("key")
                if not key:
                    continue
                rank = (r.get("ts") or "", batch, int(r.get("seq") or 0))
                if key not in best or rank >= best[key][0]:
                    best[key] = (rank, r, batch)
        for key, (_, r, batch) in sorted(best.items()):
            p = r.get("payload") or {}
            v = p.get("v") or p.get("verdict")
            sampled = any(m in batch for m in SAMPLED_MARKS)
            lab = Label(cell=key, source="human", selection=_sel(spec, RANDOM if sampled else PICKED),
                        ref=batch)
            if v in DEFECT_V:
                lab.defect = True
            elif v == "confirm" and (p.get("reading") or p.get("shape")):
                lab.truth = p.get("reading") or p.get("shape")
            else:
                continue
            out.append(lab)
    return out


def load_vision(spec: dict, books: list[str]) -> list[Label]:
    if not spec.get("path"):
        raise BadRequest("vision 标签要给 path（看图结论.jsonl）")
    p = _resolve(spec["path"])
    if not p.exists():
        raise BadRequest(f"找不到看图结论：{p}")
    latest: dict[str, tuple[str, int, dict]] = {}
    for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines()):
        if not ln.strip():
            continue
        r = json.loads(ln)
        cell = r.get("cell")
        if not cell or _book_of(cell) not in books:
            continue
        rank = (r.get("ts") or "", i)
        if cell not in latest or rank >= latest[cell][:2]:
            latest[cell] = (*rank, r)
    out = []
    sel = _sel(spec, PICKED)
    for cell, (_, _, r) in sorted(latest.items()):
        v = r.get("v")
        lab = Label(cell=cell, source="vision", selection=sel, ref=p.name)
        if v == "ok" and r.get("shown"):
            lab.truth = r["shown"]
        elif v == "wrong" and r.get("char"):
            lab.truth = r["char"]
        elif v == "wrong" and r.get("shown"):
            lab.wrong = {r["shown"]}
        else:
            continue                  # unsure / 缺字段：不当标签
        out.append(lab)
    return out


_GOLD_CHAR_KEYS = ("char", "reading", "label", "text")


def load_gold(spec: dict, books: list[str]) -> list[Label]:
    if not spec.get("path"):
        raise BadRequest("gold 标签要给 path（分片 items.jsonl）")
    p = _resolve(spec["path"])
    if p.is_dir():
        p = p / "items.jsonl"
    if not p.exists():
        raise BadRequest(f"找不到金标分片：{p}")
    out = []
    for ln in p.read_text(encoding="utf-8").splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        if (r.get("status") or "active") != "active":
            continue
        a = r.get("anchor") or {}
        if str(a.get("book")) not in books or None in (a.get("page"), a.get("col"), a.get("slot")):
            continue
        exp = r.get("expected") or {}
        truth = next((exp[k] for k in _GOLD_CHAR_KEYS if exp.get(k)), None)
        defect = bool(exp.get("defect") or exp.get("v") in DEFECT_V)
        if not truth and not defect:
            continue
        cell = f"{a['book']}:{a['page']}:{a['col']}:{a['slot']}{exp.get('sub') or ''}"
        out.append(Label(cell=cell, source="gold", selection=_sel(spec, PICKED if r.get("stratum") else RANDOM),
                         truth=truth, defect=defect, ref=p.parent.name))
    return out


LOADERS = {"human_events": load_human_events, "vision": load_vision, "gold": load_gold}


# ── 合并 ─────────────────────────────────────────────────────────────────
def merge(labels: list[Label]) -> tuple[dict[str, Label], list[dict]]:
    """每格留优先级最高的一条；同格两来源真值不一致的记冲突（仍取高优先级的）。"""
    by_cell: dict[str, list[Label]] = {}
    for lab in labels:
        by_cell.setdefault(lab.cell, []).append(lab)
    out, conflicts = {}, []
    for cell, labs in by_cell.items():
        labs.sort(key=lambda x: PRIORITY.get(x.source, 9))
        top = labs[0]
        for other in labs[1:]:
            if other.source == top.source:
                continue
            t1 = "∅" if top.defect else top.truth
            t2 = "∅" if other.defect else other.truth
            if t1 and t2 and t1 != t2:
                conflicts.append({"cell": cell, top.source: t1, other.source: t2})
        out[cell] = top
    return out, conflicts


def load_all(specs: list[dict], books: list[str]) -> tuple[list[Label], list[dict]]:
    """按 yaml 的 `labels:` 读全部来源 → (标签列表, 每个来源的计数)。"""
    labels: list[Label] = []
    counts = []
    for spec in specs:
        src = spec.get("source")
        if src not in LOADERS:
            raise BadRequest(f"不认识的标签来源 {src!r}（可选 {sorted(LOADERS)}）")
        got = LOADERS[src](spec, books)
        labels.extend(got)
        counts.append({"source": src, "path": spec.get("path"), "n": len(got),
                       "random": sum(1 for x in got if x.selection == RANDOM),
                       "picked": sum(1 for x in got if x.selection == PICKED)})
    return labels, counts


def write_jsonl(labels: list[Label], path: Path) -> None:
    path.write_text("".join(json.dumps(x.to_dict(), ensure_ascii=False) + "\n" for x in labels),
                    encoding="utf-8")


def read_jsonl(path: Path) -> list[Label]:
    if not path.exists():
        return []
    return [Label.from_dict(json.loads(ln)) for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip()]
