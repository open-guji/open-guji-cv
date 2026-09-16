"""适配器基类与自动识别。"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..item import Anchor, GoldItem

# 常见的 book:page:col:idx 形态（与 feedback.harvest 同源，但这里只用于建 anchor）
_KEY_RE = re.compile(r"^(?P<book>vol\d+|book\d+)[:/](?P<page>\d+)(?::(?P<col>\d+))?(?::(?P<slot>-?\d+))?")


class Adapter(ABC):
    """把一个旧格式分片读成 GoldItem 列表。只读，不写。"""

    name: str = "base"

    @classmethod
    @abstractmethod
    def sniff(cls, shard_dir: Path) -> bool:
        """这个目录是不是本适配器认得的载体。"""

    @abstractmethod
    def load(self, shard_dir: Path) -> list[GoldItem]:
        ...

    # ── 公共小工具 ───────────────────────────────────────────────────
    @staticmethod
    def anchor_from(d: dict, key: str | None = None) -> Anchor:
        """尽力从条目字段或 key 里凑出锚点。凑不出就留空——留空好过猜错。"""
        book, page, col, slot = (d.get("book"), d.get("page"), d.get("col"), d.get("idx"))
        if slot is None:
            slot = d.get("slot")
        if book is None and key:
            m = _KEY_RE.match(key)
            if m:
                g = m.groupdict()
                book = g["book"]
                page = int(g["page"])
                col = int(g["col"]) if g.get("col") else None
                slot = int(g["slot"]) if g.get("slot") else None
        return Anchor(
            book=book,
            page=int(page) if isinstance(page, (int, str)) and str(page).lstrip("-").isdigit() else None,
            col=int(col) if isinstance(col, (int, str)) and str(col).lstrip("-").isdigit() else None,
            slot=int(slot) if isinstance(slot, (int, str)) and str(slot).lstrip("-").isdigit() else None,
            bbox=tuple(d["bbox"]) if isinstance(d.get("bbox"), (list, tuple)) and len(d["bbox"]) == 4 else None,
        )

    # 溯源字段：进 GoldItem 的专有位
    META_KEYS = {"source_item", "pipeline_version", "label_origin", "stratum",
                 "stratum_weight", "seed", "schema_version", "id", "book", "page",
                 "col", "idx", "slot"}
    # 输入/文档字段：进 input，不是金标内容本身
    INPUT_KEYS = {"input", "coord_space", "profile", "tags", "note", "notes",
                  "column_fingerprint", "source_image", "column_image", "producer",
                  "gold_definition", "report_header"}

    @staticmethod
    def split_meta(d: dict) -> tuple[dict, dict, dict]:
        """拆成 (溯源, 输入/文档, 金标内容)。

        `coord_space` 那种整段说明文字是**给人看的口径**，不是金标内容——混进
        `expected` 会让「金标改没改」的比较变成比较散文。
        """
        meta = {k: v for k, v in d.items() if k in Adapter.META_KEYS}
        inp = {k: v for k, v in d.items() if k in Adapter.INPUT_KEYS}
        rest = {k: v for k, v in d.items()
                if k not in Adapter.META_KEYS and k not in Adapter.INPUT_KEYS}
        return meta, inp, rest

    @staticmethod
    def to_item(item_id: str, d: dict, source: str) -> GoldItem:
        meta, inp, expected = Adapter.split_meta(d)
        origin = meta.get("label_origin") or "human"
        if origin not in ("human", "align", "synth", "model"):
            origin = "human"
        item_input: dict = {"legacy_source": source, **inp}
        if meta.get("seed"):
            item_input["seed"] = meta["seed"]
        if meta.get("source_item"):
            item_input["source_item"] = meta["source_item"]
        return GoldItem(
            id=item_id,
            anchor=Adapter.anchor_from(d, item_id),
            expected=expected,
            label_origin=origin,          # type: ignore[arg-type]
            pipeline_version=meta.get("pipeline_version"),
            stratum=meta.get("stratum"),
            stratum_weight=meta.get("stratum_weight"),
            input=item_input,
        )


def _adapters() -> list[type[Adapter]]:
    """顺序即优先级：samples/ 最具体，cases 次之，扁平与 verdicts 最后。"""
    from .cases import CasesAdapter
    from .flat_expected import FlatExpectedAdapter
    from .samples_dir import SamplesDirAdapter
    from .verdicts import VerdictsAdapter
    return [SamplesDirAdapter, CasesAdapter, FlatExpectedAdapter, VerdictsAdapter]


def detect(shard_dir: Path) -> type[Adapter] | None:
    """认这个分片是哪种载体；已迁成 items.jsonl 的返回 None（不需要适配器）。"""
    shard_dir = Path(shard_dir)
    if (shard_dir / "items.jsonl").exists():
        return None
    for cls in _adapters():
        if cls.sniff(shard_dir):
            return cls
    return None


def load_shard(shard_dir: Path) -> tuple[str, list[GoldItem]]:
    """读一个分片，返回 (载体名, 条目)。已迁的直接读 items.jsonl。"""
    shard_dir = Path(shard_dir)
    items_path = shard_dir / "items.jsonl"
    if items_path.exists():
        out = []
        with open(items_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(GoldItem.model_validate_json(line))
        return "items", out
    cls = detect(shard_dir)
    if cls is None:
        return "unknown", []
    return cls.name, cls().load(shard_dir)
