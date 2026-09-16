"""`samples/` 载体。三种形态都认（2026-09-03 实测）：

    A 编号目录：samples/001/{expected.json | case.json, info.json, *.png}
               book-profile、char-normalization、cells（用 case.json）…
    B 扁平文件：samples/vol01_11_c1.json（金标即整份 JSON）
               column-warp、page-geometry、column-layout…
    C 单个汇总文件：samples/edges.json（整份是一张表）—— cell-truncation

A、B 的 id 就是目录名 / 文件 stem——已有的重键脚本、报告、README 都按这个名字引用，
换 id 会切断可追溯性。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..item import GoldItem
from .base import Adapter

# 编号目录里承载金标的文件名（按优先级）
_GOLD_FILES = ("expected.json", "case.json", "gold.json")
# 形态 C 里承载条目的字段名
_TABLE_KEYS = ("edges", "samples", "items", "rows")


def _is_table(path) -> bool:
    """这个 JSON 是「一张表」还是「一个样本」。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:   # noqa: BLE001
        return False
    if isinstance(data, list):
        return True
    if isinstance(data, dict):
        return any(isinstance(data.get(k), list) and data[k] and isinstance(data[k][0], dict)
                   for k in _TABLE_KEYS)
    return False


class SamplesDirAdapter(Adapter):
    name = "samples_dir"

    @classmethod
    def sniff(cls, shard_dir: Path) -> bool:
        d = shard_dir / "samples"
        if not d.is_dir():
            return False
        for p in d.iterdir():
            if p.is_dir() and any((p / f).exists() for f in _GOLD_FILES):
                return True
            if p.suffix == ".json":
                return True
        return False

    def load(self, shard_dir: Path) -> list[GoldItem]:
        out: list[GoldItem] = []
        samples = shard_dir / "samples"
        entries = sorted(samples.iterdir())
        # 形态 C：samples/ 下只有一个 JSON，**且它内部是一张表**（顶层数组，或有
        # edges/samples/... 这样的条目数组）。只有一个样本文件的分片不算——那是形态 B
        # 恰好只有一条，id 必须仍是文件名。
        json_files = [p for p in entries if p.suffix == ".json"]
        if len(entries) == 1 and len(json_files) == 1 and _is_table(json_files[0]):
            data = json.loads(json_files[0].read_text(encoding="utf-8"))
            src = f"samples/{json_files[0].name}"
            if isinstance(data, list):
                return [self.to_item(str(d.get("id") or f"row{i:05d}"), d, src)
                        for i, d in enumerate(data) if isinstance(d, dict)]
            if isinstance(data, dict):
                for key in ("edges", "samples", "items", "rows"):
                    v = data.get(key)
                    if isinstance(v, list) and v and isinstance(v[0], dict):
                        return [self.to_item(str(d.get("id") or f"{key}{i:05d}"), d, f"{src}:{key}")
                                for i, d in enumerate(v)]
                return [self.to_item(str(k), v if isinstance(v, dict) else {"value": v}, src)
                        for k, v in data.items()]
            return []

        for p in entries:
            if p.is_dir():
                exp = next((p / f for f in _GOLD_FILES if (p / f).exists()), None)
                if exp is None:
                    continue
                d = json.loads(exp.read_text(encoding="utf-8"))
                info_path = p / "info.json"
                info = json.loads(info_path.read_text(encoding="utf-8")) if info_path.exists() else {}
                item = self.to_item(p.name, d if isinstance(d, dict) else {"value": d},
                                    f"samples/{p.name}/{exp.name}")
                if info:
                    item.input["info"] = info
                    # info.json 里常有 source / source_file / tags，是有用的溯源
                    if info.get("source_item") and not item.pipeline_version:
                        item.input.setdefault("source_item", info["source_item"])
                imgs = [f.name for f in p.iterdir() if f.suffix.lower() in (".png", ".jpg", ".jpeg")]
                if imgs:
                    item.input["images"] = sorted(imgs)
                out.append(item)
            elif p.suffix == ".json":
                d = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(d, dict):
                    continue
                out.append(self.to_item(p.stem, d, f"samples/{p.name}"))
        return out
