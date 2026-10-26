"""字频解法（字组统一流程 `group_flow` 的 `freq`，2026-10-18 sheldon 定）：一组异体里，**这套书人裁确认过的刻形**
哪个多、哪个没有。主形 ≥ `major`（缺省 20）且其余成员都是 0 → 给主形；否则弃权。

只用于异体组（读音相同、各书只偏用一形，如 即卽、㫖旨、彚彙）；形近不同义组（己已巳、日曰）各字都常见，字频说明不了问题。

计数来源**只认人裁**（字形库 `instances` 里 `label_status=human` 的刻例，加 `feedback/events` 里 `confirm` 事件的
`shape`、字形库体检 `glyph_audit` 的改字／撤库，同一格以最晚的事件为准；`not_a_char`／`seg_defect`／`skip`／`damaged` 视为这一格没有刻形）。不用产物
（流水线自己放的，循环论证），不用整理本（已规范化，异体写法全是 0）。

**冻结成表**：离线算成一张 json（`build` → `write`），`seed_admit.group_flow_freq` 指向它，内容哈希进指纹。
新人裁进来不会让 Step7 自动过期；要吃新数据就重算表（一次显式动作）。

    python -m open_guji_cv.groups.freq <工作区> [--out <工作区>/config/groups/freq.json]

本模块不读产物、不读图，只读工作区的字形库与事件文件。
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
from pathlib import Path

from .protocol import GroupVerdict

VERSION = 1
MAJOR = 10          # 2026-10-20 sheldon 定 20→10，配 MIN_VOLS（主形须来自至少两册，防单册偏用）
MIN_VOLS = 2
#: 这些 confirm 结论说明这一格没有可数的刻形
_NO_SHAPE = frozenset({"not_a_char", "seg_defect", "skip", "damaged"})


def _cell_key(k: str) -> str:
    """同一格在字形库里可能带来源前缀（`v2:vol02:132:8:17`），统一成 `册:页:列:格` 再去重。"""
    return ":".join(k.split(":")[-4:])


def human_shapes(workspace: Path) -> dict[str, str]:
    """{格 key（`vol01:10:1:10`）: 人裁刻形}。字形库 human 标注打底，confirm 事件按时间覆盖。"""
    out: dict[str, str] = {}
    from ..core.workspace import data_root
    data = data_root(Path(workspace)) or Path(workspace)      # 迁到中心库后在数据目录（GUJI-608）
    for f in sorted(glob.glob(str(data / "output" / "glyph_store" / "instances" / "*.jsonl"))):
        for line in open(f, encoding="utf-8"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("label_status") == "human" and r.get("label") and r.get("instance_id"):
                out[_cell_key(r["instance_id"])] = r["label"]
    evs = []
    from ..core.event_files import iter_event_dicts
    for e in iter_event_dicts(data / "feedback" / "events"):     # 换图源的页表 rev 判据在这里一并生效
        kind = e.get("kind")
        if kind not in ("confirm", "glyph_audit"):
            continue
        p = e.get("payload") or {}
        key = (p.get("instance_id") if kind == "glyph_audit" else None) or (e.get("target") or {}).get("key")
        if key:
            evs.append((e.get("ts") or "", _cell_key(key), kind, p))
    for _, key, kind, p in sorted(evs, key=lambda x: x[0]):
        v = p.get("v")
        if kind == "glyph_audit":                 # 字形库体检：改字／撤库
            if v == "relabel" and p.get("char") and len(p["char"]) == 1:
                out[key] = p["char"]
            elif v == "evict" and _cell_key(p.get("target") or key) in out:
                out.pop(_cell_key(p.get("target") or key), None)
        elif v == "confirm" and p.get("shape") and len(p["shape"]) == 1:
            out[key] = p["shape"]
        elif v in _NO_SHAPE:
            out.pop(key, None)
    return out


def build(workspace: Path, groups: dict[str, frozenset]) -> dict:
    """→ 表：`{"version", "source", "groups": {组 id: {成员: 人裁刻形数}}}`。"""
    shapes = human_shapes(Path(workspace))
    counts: dict[str, dict[str, int]] = {}
    vols: dict[str, dict[str, int]] = {}
    for gid, members in sorted(groups.items()):
        c = {ch: 0 for ch in sorted(members)}
        v: dict[str, set] = {ch: set() for ch in c}
        for k, s in shapes.items():
            if s in c:
                c[s] += 1
                v[s].add(k.split(":")[0])
        counts[gid] = c
        vols[gid] = {ch: len(x) for ch, x in v.items()}
    return {"version": VERSION, "source": {"workspace": Path(workspace).name, "cells": len(shapes)},
            "groups": counts, "vols": vols}


def write(table: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(table, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def load(path: str | Path) -> dict[str, dict[str, int]]:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("version") != VERSION:
        raise ValueError(f"字频表 {path} 版本 {d.get('version')!r}，要的是 {VERSION}")
    return {g: {k: int(v) for k, v in c.items()} for g, c in (d.get("groups") or {}).items()}


def load_vols(path: str | Path) -> dict[str, dict[str, int]]:
    """{组: {成员: 有该刻形人裁的册数}}；旧表没有这一项 → 空（不卡册数）。"""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return {g: {k: int(v) for k, v in c.items()} for g, c in (d.get("vols") or {}).items()}


def fingerprint(path: str | Path | None) -> str:
    if not path or not Path(path).exists():
        return "missing"
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]


def decide(counts: dict[str, int] | None, members, major: int = MAJOR,
           vols: dict[str, int] | None = None, min_vols: int = 0) -> GroupVerdict:
    """主形人裁数 ≥ major 且其余成员都是 0（且给了册数时，主形来自 ≥ min_vols 册）→ 主形；否则弃权。
    `extra.counts` 原样留痕。"""
    if not counts:
        return GroupVerdict(None, why="abstain:no_table", via="freq")
    c = {ch: int(counts.get(ch, 0)) for ch in sorted(members)}
    top = max(c, key=lambda ch: (c[ch], ch))
    rest = sum(n for ch, n in c.items() if ch != top)
    if c[top] >= major and rest == 0:
        if vols is not None and min_vols and int(vols.get(top, 0)) < min_vols:
            return GroupVerdict(None, why="abstain:one_vol", via="freq", extra={"counts": c, "vols": dict(vols)})
        return GroupVerdict(top, why="agree", via="freq", extra={"counts": c})
    return GroupVerdict(None, why="abstain:mixed" if rest else "abstain:few", via="freq", extra={"counts": c})


def main(argv=None) -> int:
    from .registry import GROUPS
    ap = argparse.ArgumentParser(description="按人裁刻形统计异体组字频，冻结成表")
    ap.add_argument("workspace", type=Path)
    ap.add_argument("--out", type=Path, default=None, help="缺省 <工作区>/config/groups/freq.json")
    a = ap.parse_args(argv)
    groups = {g.id: g.members for g in GROUPS.values() if g.flow and "freq" in g.flow.solvers}
    table = build(a.workspace, groups)
    from ..core.workspace import data_root
    data = data_root(a.workspace) or a.workspace
    out = a.out or data / "config" / "groups" / "freq.json"
    write(table, out)
    shapes = human_shapes(a.workspace)
    for gid, c in table["groups"].items():
        v = decide(c, groups[gid])
        print(f"{gid}\t{' '.join(f'{k}{n}' for k, n in c.items())}\t→ {v.char or '弃权'}（{v.why}）")
        top = max(c, key=lambda ch: (c[ch], ch))
        if c[top] >= MAJOR:      # 次形只有几例：多半是标错，列出来请人看
            for ch, n in c.items():
                if ch != top and 0 < n <= 3:
                    print(f"\t次形 {ch}：" + " ".join(k for k, s in sorted(shapes.items()) if s == ch))
    print(f"写入 {out}（人裁格 {table['source']['cells']}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
