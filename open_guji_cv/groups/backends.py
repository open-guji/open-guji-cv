"""判别后端适配器：**包住**现有判别函数，不改其算法、不重定义弃权语义。

| 适配器 | 包住 | 说明 |
|---|---|---|
| `JysRuleBackend` | `utils.ji_yi_si_clf.classify` | 己已巳规则路（前后各 30 字搭配），纯函数，无指纹 |
| `CtxTableBackend` | `utils.near_form_ctx.decide` | 己已巳语料决策表（前后 1–2 字），指纹＝表文件哈希 |
| `GroupClfTableBackend` | main 的 `steps.group_decide.lookup` 同一读法 | `group_clf/1` 答案表（B1 §2.1）；原样返回 `votes` 进 `extra` |
| `RyV2TableBackend` | `utils.ry_group.decide` | 日曰 ry-v2 答案表（旧格式） |
| `JysSuggestBackend` | `utils.ji_yi_si_clf.suggest` | 己已巳答案表（大模型两遍＋语料分类器，旧格式） |
| `RrImageBackend` | `utils.rr_clf.classify` | 入人八图像模型（numpy 随机森林），缺图抛 `PatchUnavailable` |

窗口只从 `JudgeInput.window` 取（文本类后端各自要的宽度不同：规则／表 30，近形表 2）。
`GroupClfTableBackend` 与 `steps.group_decide.lookup` 是两份读法（S0 不改 Step）；`tests/test_groups_backends.py`
有对拍测试盯着它们逐格一致，S2 会让 `group_decide` 改用这里的实现。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .protocol import GroupVerdict, JudgeInput, PatchUnavailable

CTX_WIDTH = 30


def _file_fp(path) -> str:
    p = Path(path) if path else None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p and p.exists() else ""


class JysRuleBackend:
    name = "rule"
    fingerprint = ""

    def judge(self, spec, cell: JudgeInput) -> GroupVerdict:
        from ..utils.ji_yi_si_clf import classify
        left, right = cell.window(CTX_WIDTH)
        ch, why = classify(left, right)
        return GroupVerdict(
            char=ch, why="agree" if ch else "abstain:rule", via="rule",
            extra={"rule": ch, "rule_why": why,
                   # 与现行 `seed_admit._ji_yi_si_clf_cell` 写进 evidence 的两块结构逐字一致（没有表、没有 llm 路时）
                   "clf_ev": {"rule": ch, "why": why, "via": "rule" if ch else None},
                   "ji_yi_si": {"char": ch, "why": why}})


class CtxTableBackend:
    name = "ctx_table"

    def __init__(self, purity: float = 0.98, min_n: int = 5, path: str | Path | None = None):
        self.purity, self.min_n, self.path = purity, min_n, (str(path) if path else None)
        from ..utils.near_form_ctx import CONFIG
        self.fingerprint = _file_fp(self.path or CONFIG)

    def judge(self, spec, cell: JudgeInput) -> GroupVerdict:
        from ..utils.near_form_ctx import decide
        left, right = cell.window(2)
        # 近形表要「连续已知的字」：碰到 □（未知）就停，不跨过空位拼接
        prev, nxt = left.rsplit("□", 1)[-1], right.split("□", 1)[0]
        ch, why = decide(prev, nxt, self.purity, self.min_n, self.path)
        return GroupVerdict(char=ch, why="agree" if ch else "abstain:ctx_table", via="ctx_table",
                            extra={"ctx_why": why})


class GroupClfTableBackend:
    """`group_clf/1` 答案表。弃权语义就是表里的：缺格／ctx 不符／ver 不符一律弃权并写明原因。"""
    name = "table"

    def __init__(self, table: dict | str | Path):
        if isinstance(table, dict):
            self._table, self.fingerprint = table, ""
        else:
            self._table = json.loads(Path(table).read_text(encoding="utf-8"))
            self.fingerprint = _file_fp(table)

    def judge(self, spec, cell: JudgeInput) -> GroupVerdict:
        from ..utils.ji_yi_si_clf import ctx_key
        t = self._table
        if t.get("schema") != "group_clf/1" or t.get("group") != spec.id:
            return GroupVerdict(None, why="ver_mismatch", via="table")
        e = (t.get("cells") or {}).get(cell.id)
        if not e:
            return GroupVerdict(None, why="cache_miss", via="table")
        left, right = cell.window(CTX_WIDTH)
        if e.get("ctx") != ctx_key(left, right, CTX_WIDTH):
            return GroupVerdict(None, why="ctx_mismatch", via="table")
        ch = e.get("char")
        if ch is not None and ch not in spec.members:
            ch = None
        return GroupVerdict(ch, conf=e.get("conf"), why=str(e.get("why") or ""), via="table",
                            extra={"votes": e.get("votes")})


#: ry-v2 旧表里的 why → group_clf/1 词汇（其余原样透传：cache_miss／ctx_mismatch／ver_mismatch／abstain:<来源>／disagree）
_RY_WHY = {"muse∧gemini 两遍一致": "agree", "haiku_veto": "veto:haiku"}


class RyV2TableBackend:
    name = "table"

    def __init__(self, path: str | Path):
        self.path = str(path)
        self.fingerprint = _file_fp(path)

    def judge(self, spec, cell: JudgeInput) -> GroupVerdict:
        from ..utils.ry_group import decide
        left, right = cell.window(CTX_WIDTH)
        res = decide(self.path, cell.id, left, right)
        if res is None:                       # 没配表：证据不写（与现行 `_ry_group_pass` 一致）
            return GroupVerdict(None, why="abstain:no_table", via="table", extra={"legacy": None})
        why = res.get("why") or ""
        return GroupVerdict(res.get("char"), why=_RY_WHY.get(why, why), via="table",
                            extra={"legacy": res, "votes": res.get("votes")})


class JysSuggestBackend:
    name = "table"

    def __init__(self, path: str | Path):
        self.path = str(path)
        self.fingerprint = _file_fp(path)

    def judge(self, spec, cell: JudgeInput) -> GroupVerdict:
        from ..utils.ji_yi_si_clf import suggest
        left, right = cell.window(CTX_WIDTH)
        sug = suggest(self.path, cell.id, left, right)
        if sug is None:
            return GroupVerdict(None, why="cache_miss", via="table", extra={"suggest": None})
        ch = sug.get("char")
        why = "agree" if ch else ("ctx_mismatch" if sug.get("why") == "ctx_mismatch" else "disagree")
        return GroupVerdict(ch, conf=sug.get("lr_margin"), why=why, via="table", extra={"suggest": sug})


class RrImageBackend:
    """入人八图像模型。**缺图不静默弃权**：`cell.patch` 缺或读不到抛 `PatchUnavailable`，由调用方按 skip／raise 处理并留痕。"""
    name = "image"

    def __init__(self, model_path: str | Path | None = None, p_thr: float = 0.5):
        self.model_path = str(model_path) if model_path else None
        self.p_thr = p_thr
        self._fp: str | None = None

    @property
    def fingerprint(self) -> str:
        """模型文件哈希；惰性算（`seed_admit` 每页都会构造后端，不能每次读一遍模型文件）。"""
        if self._fp is None:
            from ..utils import rr_clf
            self._fp = rr_clf.model_fingerprint(self.model_path) or ""
        return self._fp

    def judge(self, spec, cell: JudgeInput) -> GroupVerdict:
        from ..utils import rr_clf
        if cell.patch is None:
            raise PatchUnavailable(cell.id)
        c = rr_clf.classify(cell.patch(), self.model_path, self.p_thr)
        pick = c["pick"]
        why = "agree" if pick else ("abstain:gated" if c["gated"] else "abstain:low_p")
        return GroupVerdict(pick, conf=c["p"], why=why, via="image", extra={"legacy": c, "probs": c["probs"]})
