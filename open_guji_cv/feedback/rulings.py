"""大模型的文意裁定（sheldon 2026-10-28）：L3 在线问过的格，答案存成裁定事件，下次直接用，不再问。

和人裁、看图结论（`vision.py`）同一个事件库、同一套格式与追加纪律，只是**来源是模型**：`kind="ctx_ruling"`、
`actor="model"`、`payload.source="llm"`，落 `<feedback>/rulings/<批次>.jsonl`（不进 `events/`——读人裁的地方几十处直接扫
`events/`，分目录是缺省安全；`events.counts_as_human` 也不认它）。同步走 `datastore.scope`（stream=rulings）。

**管线怎么用**（`groups/ctx_llm.judge`）：先 `RulingStore.get(组, 提示词版本, 前文, 后文)` 查，有就按它的结果走，
没有才调用大模型，问完 `put` 回来。人裁的字另走 `human_chars`，同一格有人裁就不会走到 L3。

**键是窗口内容，不是格号**：`(组, sha256(前文[-20:] | 后文[:20]))`，格号只记在 `payload.cell` 和 `target.key` 里给人看、
给审核页预填用。换图源重切后格号变了，同一上下文照样命中；同一上下文在别的册、别的页出现也共用一条（省钱）。
所以读口用 `raw=True`、不过换图源的页表 rev 判据——那条判据管的是“按格号取”的事件，这里不按格号取。
提示词换了版本（`prompt_ver`）才作废：同一窗口取版本相符的最新一条（`replay_key` 后到覆盖）；模型换了不作废，
要重问请换提示词版本或删事件。

事件 payload：`source="llm"`、`group`、`char`（组内字，或 None）、`other`（大模型认为组内字都不是）、`conf`(high/mid/low)、`why`（≤60 字）、
`model`、`prompt_ver`、`ctx{left,right,hash}`、`cell`、`tok{in,out,cache_read}`。弃权（低把握、其他）也记，免得反复问。
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from .events import Event, EventLog, EventTarget, make_event, replay_key

KIND = "ctx_ruling"
SOURCE = "llm"
OTHER = "其他"
WIDTH = 20


class RulingLog(EventLog):
    """裁定日志：同 `EventLog` 的格式与追加纪律，落 `<feedback>/rulings/`。"""

    @property
    def events_dir(self) -> Path:
        return self.root / "rulings"

    @property
    def consumed_dir(self) -> Path:
        return self.root / "rulings_consumed"


def ctx_hash(left: str, right: str) -> str:
    s = (left or "")[-WIDTH:] + "|" + (right or "")[:WIDTH]
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:24]


def _book(cell: str | None) -> str | None:
    return cell.split(":", 1)[0] if cell and ":" in cell else None


class RulingStore:
    """读写裁定。`root` 缺省取 `default_feedback_root()`；没有 feedback 目录（没配工作区）时只在内存里记，不落盘。"""

    def __init__(self, root: str | Path | None = None, persist: bool = True):
        self.log = RulingLog(Path(root) if root else None)
        self.persist = persist
        self._idx: dict | None = None
        self._batch = f"llm-ctx-{time.strftime('%Y%m%d', time.gmtime())}"

    def _load(self) -> dict:
        if self._idx is None:
            idx: dict = {}
            if self.log.events_dir.exists():
                evs = [e for e in self.log.iter_all(raw=True) if e.kind == KIND]
                for e in sorted(evs, key=replay_key):             # 后到覆盖
                    p = e.payload
                    idx[(p.get("group"), (p.get("ctx") or {}).get("hash"), p.get("prompt_ver"))] = p
            self._idx = idx
        return self._idx

    def get(self, group: str, prompt_ver: str, left: str, right: str) -> dict | None:
        """→ 裁定 payload（含 char/conf/why/model/tok），没有 → None。"""
        return self._load().get((group, ctx_hash(left, right), prompt_ver))

    def put(self, group: str, prompt_ver: str, left: str, right: str, *, char, conf, why: str, model: str,
            cell: str | None = None, tok: dict | None = None) -> dict:
        left, right = (left or "")[-WIDTH:], (right or "")[:WIDTH]
        other = char == OTHER                      # “组内字都不是”：char 留空、other=True（字形字段只收单字）
        payload = {"source": SOURCE, "group": group, "char": None if other else char, "other": other, "conf": conf, "why": (why or "")[:60],
                   "model": model, "prompt_ver": prompt_ver, "cell": cell, "tok": tok or {},
                   "ctx": {"left": left, "right": right, "hash": ctx_hash(left, right)}}
        self._load()[(group, payload["ctx"]["hash"], prompt_ver)] = payload
        if self.persist:
            seq = max((e.seq for e in self.log.read(self._batch, raw=True)), default=0) + 1
            key = cell or f"ctx:{payload['ctx']['hash']}"
            ev = make_event(self._batch, seq, KIND, EventTarget(step="seed_admit", unit="cell", key=key,
                                                                book=_book(cell)), payload, actor="model")
            self.log.append([ev])
        return payload


class RulingCache:
    """`groups.ctx_llm.judge` 的缓存接口（lookup／store）接到裁定库上。"""

    def __init__(self, store: RulingStore):
        self.store_ = store

    def lookup(self, group, prompt_ver, model, left, right):
        p = self.store_.get(group, prompt_ver, left, right)
        if p is None:
            return None
        return {"char": OTHER if p.get("other") else p.get("char"), "conf": p.get("conf"), "why": p.get("why"), "model": p.get("model"),
                "tok": p.get("tok") or {}}

    def store(self, group, prompt_ver, model, left, right, e: dict, cell=None) -> None:
        self.store_.put(group, prompt_ver, left, right, char=e.get("char"), conf=e.get("conf"), why=e.get("why") or "",
                        model=e.get("model") or model, cell=cell, tok=e.get("tok"))
