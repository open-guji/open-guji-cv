"""`cases.json` + `answer_key.json` 载体：confusable-context（形近字上下文题集）。

题面与答案分放两个文件（出题时故意分开，防止把答案印在卡上——见 making-datasets.md
「别把机器的判断印在卡上」）。这里合起来读：题面进 `input`，答案进 `expected`。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..item import GoldItem
from .base import Adapter


class CasesAdapter(Adapter):
    name = "cases"

    @classmethod
    def sniff(cls, shard_dir: Path) -> bool:
        return (shard_dir / "cases.json").exists()

    def load(self, shard_dir: Path) -> list[GoldItem]:
        data = json.loads((shard_dir / "cases.json").read_text(encoding="utf-8"))
        cases = data.get("cases") if isinstance(data, dict) else data
        if not isinstance(cases, list):
            return []
        answers: dict = {}
        ak = shard_dir / "answer_key.json"
        if ak.exists():
            raw = json.loads(ak.read_text(encoding="utf-8"))
            answers = raw.get("answers", raw) if isinstance(raw, dict) else {}
        header = ({k: v for k, v in data.items() if k != "cases" and not isinstance(v, (list, dict))}
                  if isinstance(data, dict) else {})
        out: list[GoldItem] = []
        for i, c in enumerate(cases):
            if not isinstance(c, dict):
                continue
            cid = str(c.get("id") or c.get("case_id") or f"case{i:05d}")
            ans = answers.get(cid)
            item = self.to_item(cid, {"answer": ans} if ans is not None else {}, "cases.json")
            item.input["case"] = c
            if header:
                item.input["header"] = header
            if ans is None:
                item.status = "uncertain"      # 没答案的题不进指标
            out.append(item)
        return out
