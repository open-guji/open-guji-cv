"""M7 上下文路 L1（GUJI-563 块 D）：静态规则层，**只在把握是 100% 时给字，否则弃权**。

规则文件 `config/groups/<组>/rules.yaml`（`schema: ctx_l1/1`）：

    group: ry
    rules:
      - {id: ry-date, char: 日, re: '月[初一二三四五六七八九十廿卅]{1,3}◎', note: 月X日, src: hand}
      - {id: ry-子曰-干支除外, char: null, re: '[甲乙丙丁戊己庚辛壬癸]子◎'}      # char: null＝否决，命中即整体弃权
    legacy: open_guji_cv.utils.ji_yi_si_clf:classify                            # 可选：收编已有的纯函数规则集

- 匹配串＝`left + "◎" + right`（窗口由调用方给，前后各 20 字、遇段界即停；□＝未知字，正则里别把它写进字类）；
  `re` 必须含 `◎`（目标位），用 `re.search`。
- 判法：任何否决命中 → 弃权（`why=abstain:veto:<id>`）；命中的给字规则（含 legacy）给出不同的字 → 弃权
  （`why=disagree:ctx_l1`）；没有命中 → 弃权（`abstain:ctx_l1`）。
- 本模块不被任何 Step 引用，不改产物指纹；规则文件内容哈希作 `fingerprint`。
"""
from __future__ import annotations

import hashlib
import importlib
import re
from dataclasses import dataclass
from pathlib import Path

from .protocol import GroupVerdict, JudgeInput

MARK = "◎"
WIDTH = 20
SCHEMA = "ctx_l1/1"


@dataclass(frozen=True)
class Rule:
    id: str
    char: str | None          # None＝否决
    pattern: re.Pattern
    note: str = ""
    src: str = ""


def _load_yaml(path: Path) -> dict:
    import yaml
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


class CtxL1Backend:
    name = "ctx_l1"

    def __init__(self, rules_path: str | Path, members: frozenset | None = None):
        p = Path(rules_path)
        raw = _load_yaml(p)
        if raw.get("schema") != SCHEMA:
            raise ValueError(f"{p}: schema 应为 {SCHEMA}")
        self.group = raw.get("group", "")
        self.fingerprint = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        self.rules: list[Rule] = []
        seen = set()
        for r in raw.get("rules") or []:
            rid, pat = r["id"], r["re"]
            if rid in seen:
                raise ValueError(f"{p}: 规则 id 重复 {rid}")
            seen.add(rid)
            if MARK not in pat:
                raise ValueError(f"{p}: 规则 {rid} 的 re 必须含 {MARK}")
            ch = r.get("char")
            if members is not None and ch is not None and ch not in members:
                raise ValueError(f"{p}: 规则 {rid} 的 char {ch!r} 不在组内")
            self.rules.append(Rule(rid, ch, re.compile(pat), r.get("note", ""), r.get("src", "")))
        self._legacy = None
        if raw.get("legacy"):
            mod, fn = raw["legacy"].split(":")
            self._legacy = getattr(importlib.import_module(mod), fn)

    def decide(self, left: str, right: str) -> tuple[str | None, str, list[str]]:
        """→ (字|None, why, 命中规则 id 们)。"""
        text = left + MARK + right
        hits: dict[str, list[str]] = {}
        for r in self.rules:
            if r.pattern.search(text):
                if r.char is None:
                    return None, f"abstain:veto:{r.id}", [r.id]
                hits.setdefault(r.char, []).append(r.id)
        if self._legacy is not None:
            ch, rule = self._legacy(left, right)
            if ch:
                hits.setdefault(ch, []).append("legacy:" + rule)
        if not hits:
            return None, "abstain:ctx_l1", []
        if len(hits) > 1:
            return None, "disagree:ctx_l1", [i for v in hits.values() for i in v]
        ch, ids = next(iter(hits.items()))
        return ch, "agree", ids

    def judge(self, spec, cell: JudgeInput) -> GroupVerdict:
        left, right = cell.window(WIDTH)
        ch, why, ids = self.decide(left, right)
        if ch is not None and spec is not None and ch not in spec.members:
            ch, why = None, "abstain:non_member"
        return GroupVerdict(char=ch, why=why, via="ctx_l1", extra={"rules": ids})
