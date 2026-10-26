"""`guji promote mine`：从一本书的人裁里挖可升格进共享层的候选（共享方案 4.2 节，S7；先做语料部分）。

只读、只出清单，不改任何表：候选要人审（方案第六节门槛待 sheldon 定），审过的语料改动走引擎仓 PR
（异体表、形近表、规则）→ 合入 → ``guji corpus build-base`` 出新底库；刻例走 ``guji glyphlib build``。

现在挖两类，证据都来自对勘裁决（``collate_verdict``：我们认的字和整理本不同，人判谁对）：
- **形近对**：人判整理本对（``who=theirs``）、不是异体（``cat`` 不是 ``variant``）——CV 把 B 认成了 A。
  同一对在本书出现 ≥ ``min_confusable`` 次（初稿 3）才列。已在 ``config/confusable_human.json`` 的标「已有」。
- **异体对**：人判是异体（``cat=variant``）的字对。已在 ``config/dicts/variants*.tsv`` 的标「已有」；
  没有的要补字书出处才能升格（初稿：有出处＋本书 ≥1 例），清单里标 ``needs_source``。
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ..core.corpus_pin import REPO_ROOT


def _known_confusable(repo: Path = REPO_ROOT) -> set[frozenset]:
    p = repo / "config" / "confusable_human.json"
    if not p.exists():
        return set()
    return {frozenset(k) for k in (json.loads(p.read_text(encoding="utf-8")).get("pairs") or {}) if len(k) == 2}


def _known_variants(repo: Path = REPO_ROOT) -> set[frozenset]:
    out: set[frozenset] = set()
    for p in sorted((repo / "config" / "dicts").glob("variants*.tsv")):
        for ln in p.read_text(encoding="utf-8").splitlines():
            if not ln or ln.startswith("#"):
                continue
            parts = ln.split("\t")
            if len(parts) >= 2 and parts[0] != parts[1]:
                out.add(frozenset(parts[:2]))
    return out


def _collate_verdicts(events_dir: Path):
    from ..core.event_files import iter_event_dicts
    for e in iter_event_dicts(Path(events_dir)):
        if e.get("kind") == "collate_verdict":
            yield e


def mine_corpus(ws_dir: Path, *, min_confusable: int = 3, repo: Path = REPO_ROOT) -> dict:
    """本书对勘裁决 → 形近对、异体对候选（只读）。"""
    from ..core.workspace import central_marker, data_root
    ws_dir = Path(ws_dir)
    root = data_root(ws_dir) or ws_dir
    conf: Counter = Counter()
    var: Counter = Counter()
    n = 0
    for e in _collate_verdicts(root / "feedback" / "events"):
        p = e.get("payload") or {}
        pair = p.get("pair") or []
        if len(pair) < 2 or not pair[0] or not pair[1] or pair[0] == pair[1]:
            continue
        n += 1
        ours, ref = str(pair[0]), str(pair[1])
        if p.get("cat") == "variant":
            var[tuple(sorted((ours, ref)))] += 1
        elif p.get("who") == "theirs":
            conf[(ours, ref)] += 1
    kc, kv = _known_confusable(repo), _known_variants(repo)
    # 异体表里已有的字对不算形近（多半是对勘时没标 cat 的异体）；形近表里已有的异体候选也标出来，人审时一眼看到
    confusable = [{"cv": a, "truth": b, "n": c, "known": frozenset((a, b)) in kc}
                  for (a, b), c in conf.most_common() if c >= min_confusable and frozenset((a, b)) not in kv]
    variants = [{"pair": [a, b], "n": c, "known": frozenset((a, b)) in kv,
                 "needs_source": frozenset((a, b)) not in kv, "also_confusable": frozenset((a, b)) in kc}
                for (a, b), c in var.most_common()]
    return {"ws": (central_marker(ws_dir) or {}).get("ws"), "collate_verdicts": n,
            "thresholds": {"min_confusable": min_confusable},
            "confusable": confusable, "variants": variants,
            "new": {"confusable": sum(1 for x in confusable if not x["known"]),
                    "variants": sum(1 for x in variants if not x["known"])}}
