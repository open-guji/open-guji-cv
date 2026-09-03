"""扁平 `expected.json` / `samples.jsonl` 载体。

实测（2026-09-03）有**三种**结构，不能一概而论：

1. **数组**：每条自带 book/page/col/idx —— page-type、instances、jiazhu-tail、side-rule…
2. **对象即表**：键就是 id —— frame-strip 那种
3. **报告式**：顶层是阈值与统计（`heavy_threshold`、`n_segs`…），真正的条目在某个
   数组字段里（`pages` / `columns` / `dropped` / `instances`…）—— seam、text-band、
   page-crop、left-cut、right-cut、crop-margin、char-drop、truncation、glyph-match/pairs。
   **这类必须钻进去取条目**，否则会把阈值名当成条目 id（第一版就是这么错的）。

id 的选取顺序：条目自带 `id` → 由 book/page/col/idx 拼 → 数组下标（最后手段）。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..item import GoldItem
from .base import Adapter

# 报告式结构里承载条目的字段名（按优先级）
_ENTRY_KEYS = ("samples", "items", "rows", "entries", "pages", "short_pages", "columns",
               "instances", "dropped", "cases", "cells", "seams")
# 一望而知是统计/阈值而非条目的键（用来判断「这是不是报告式」）
_SCALAR_META = {"schema_version", "source_item", "pipeline_version", "label_origin", "seed",
                "note", "n_segs", "n_seams", "n_heavy", "median", "p90", "page_rate",
                "n_body_pages", "n_char_cells", "n_dropped", "ink_row_ratio"}


def _compose_id(d: dict, fallback: str) -> str:
    if d.get("id"):
        return str(d["id"])
    parts = [str(d[k]) for k in ("book", "page", "col", "idx") if d.get(k) is not None]
    if len(parts) >= 2:
        return ":".join(parts)
    return fallback


class FlatExpectedAdapter(Adapter):
    name = "flat_expected"

    @classmethod
    def sniff(cls, shard_dir: Path) -> bool:
        return (shard_dir / "expected.json").exists() or (shard_dir / "samples.jsonl").exists()

    def load(self, shard_dir: Path) -> list[GoldItem]:
        jl = shard_dir / "samples.jsonl"
        if jl.exists():
            out = []
            with open(jl, encoding="utf-8") as f:
                for i, line in enumerate(f):
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    if isinstance(d, dict):
                        out.append(self.to_item(_compose_id(d, f"row{i:05d}"), d, "samples.jsonl"))
            return out

        path = shard_dir / "expected.json"
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [self.to_item(_compose_id(d, f"row{i:05d}"), d, "expected.json")
                    for i, d in enumerate(data) if isinstance(d, dict)]
        if not isinstance(data, dict):
            return []

        # 报告式：钻进承载条目的字段。它可能是数组，也可能是**按页号索引的字典**
        # （seam / page-crop / text-band / crop-margin 都是后者），还可能是数组的数组
        # （char-drop 的 dropped 是 [book, page, col, ...] 这种位置元组）。
        for key in _ENTRY_KEYS:
            v = data.get(key)
            if not v:
                continue
            header = {k: x for k, x in data.items() if k != key and not isinstance(x, (list, dict))}
            out: list[GoldItem] = []
            if isinstance(v, list):
                for i, d in enumerate(v):
                    if isinstance(d, dict):
                        out.append(self.to_item(_compose_id(d, f"{key}{i:05d}"), d,
                                                f"expected.json:{key}"))
                    elif isinstance(d, (list, tuple)):
                        # 位置元组：前两项惯例是 book / page
                        rec = {"row": list(d)}
                        if len(d) >= 2:
                            rec["book"], rec["page"] = d[0], d[1]
                        cid = ":".join(str(x) for x in d[:4]) or f"{key}{i:05d}"
                        out.append(self.to_item(cid, rec, f"expected.json:{key}"))
            elif isinstance(v, dict):
                for k, d in v.items():
                    rec = d if isinstance(d, dict) else {"value": d}
                    out.append(self.to_item(str(k), rec, f"expected.json:{key}"))
            if out:
                if header:
                    for it in out:
                        it.input["report_header"] = header
                return out

        # 对象即表：值必须是 dict 才当条目，否则整份是报告、无条目可取
        entries = {k: v for k, v in data.items() if isinstance(v, dict) and k not in _SCALAR_META}
        return [self.to_item(str(k), v, "expected.json") for k, v in entries.items()]
