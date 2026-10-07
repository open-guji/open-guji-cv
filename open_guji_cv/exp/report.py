# -*- coding: utf-8 -*-
"""出报告：读 `exp.yaml` + 各变体产物 + 标签 → `labels.jsonl`、`report.json`、`report.md`。

标签 = yaml 的 `labels:` 各来源 + `<exp>/labels_extra.jsonl`（翻转格审查页收回的裁决，
`flips.harvest` 写；格式同 `labels.jsonl`）。报告只读产物，可以反复重出。
"""
from __future__ import annotations

import json
from pathlib import Path

from ..errors import BadRequest
from . import compare as C
from . import labels as LB
from .config import from_dict
from .report_md import render
from .runner import UPSTREAM, page_types, read_state

EXTRA_LABELS = "labels_extra.jsonl"


def build(edir: str | Path, *, same=None, write: bool = True) -> dict:
    edir = Path(edir)
    st = read_state(edir)
    if not st:
        raise BadRequest(f"{edir} 不是跑过的实验（没有 exp.yaml）")
    cfg = from_dict(dict(st["config"]))
    step = st["steps"][-1]
    if step != "seed_admit":
        raise BadRequest(f"报告目前只比 seed_admit 产物（本实验 to={step}）")

    cells: dict[str, dict] = {}
    for v in cfg.variants:
        acc: dict = {}
        for book in cfg.books:
            acc.update(C.load_cells(edir / v.name, book, step))
        if not acc:
            raise BadRequest(f"变体 {v.name} 没有 {step} 产物——先 guji exp run")
        cells[v.name] = acc
    pts = {book: page_types(edir / UPSTREAM, book) for book in cfg.books}

    raw, sources = LB.load_all(cfg.labels, cfg.books)
    extra = LB.read_jsonl(edir / EXTRA_LABELS)
    if extra:
        sources.append({"source": "flips", "path": EXTRA_LABELS, "n": len(extra),
                        "random": sum(x.selection == LB.RANDOM for x in extra),
                        "picked": sum(x.selection == LB.PICKED for x in extra)})
    merged, conflicts = LB.merge(raw + extra)

    comps = C.compare(cells, cfg.base.name, merged, lambda b, p: pts.get(b, {}).get(p), same=same,
                      guardrails=cfg.guardrails, n_boot=cfg.bootstrap, seed=cfg.seed, books=cfg.books)
    rep = {"name": cfg.name, "base": cfg.base.name, "books": cfg.books, "steps": st["steps"],
           "code_rev": st.get("code_rev"), "snapshot": st.get("snapshot"),
           "snapshot_stamp": st.get("snapshot_stamp"),
           "params": {v.name: v.params for v in cfg.variants}, "eval_params": cfg.eval_params,
           "bootstrap": cfg.bootstrap, "seed": cfg.seed,
           "labels": C.label_summary(merged, cells, conflicts, sources), "comparisons": comps}
    if write:
        LB.write_jsonl(sorted(merged.values(), key=lambda x: x.cell), edir / "labels.jsonl")
        (edir / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        (edir / "report.md").write_text(render(rep), encoding="utf-8")
    return rep
