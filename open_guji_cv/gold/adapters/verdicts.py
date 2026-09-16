"""`verdicts_*.jsonl` 载体：一行一裁决，`{id, verdict, t}`。

多轮并存时（verdicts_r1 / r2…）**按文件名顺序读，后一轮覆盖前一轮**——续裁的语义
就是这样（`build_border_gold_reviews.py --verdicts` 拿上一轮喂下一轮）。
每条记下它来自哪一轮，便于回看。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..item import GoldItem
from .base import Adapter


class VerdictsAdapter(Adapter):
    name = "verdicts"

    @classmethod
    def sniff(cls, shard_dir: Path) -> bool:
        return any(shard_dir.glob("verdicts*.jsonl"))

    def load(self, shard_dir: Path) -> list[GoldItem]:
        by_id: dict[str, GoldItem] = {}
        for path in sorted(shard_dir.glob("verdicts*.jsonl")):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    cid = str(d.get("id") or "")
                    if not cid:
                        continue
                    verdict = d.get("verdict")
                    item = self.to_item(cid, {"verdict": verdict}, path.name)
                    item.input["round"] = path.stem
                    if verdict in ("idk", "uncertain"):
                        item.status = "uncertain"
                    by_id[cid] = item            # 后一轮覆盖
        return list(by_id.values())
