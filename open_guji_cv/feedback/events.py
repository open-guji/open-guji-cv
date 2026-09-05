"""统一反馈事件：信封、只追加的日志、幂等消费记账。

一条事件 = 「谁、在哪一批、对哪个单位、做了什么判断」。存
`<dataset>/feedback/events/<batch>.jsonl`，人产生、体积小、进 git。

**幂等**：消费者把已应用的事件 id 记在 `feedback/consumed/<consumer>.jsonl`，
再次收割同一批只应用新增的（手册「按 batch+seq 去重，不要整文件重灌」的机制化）。

**同一字位的多条事件按 (batch, seq) 升序应用、后到覆盖**——沿用 seed_queue 的纪律。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Iterable, Iterator, Literal

from pydantic import BaseModel, Field

# 人裁动作。前四种是 P1 就要用的；其余对齐既有 labels.jsonl / seed 事件的动词，
# 收割旧格式时映射到这里，不新造词。
Kind = Literal[
    "verdict",        # 一档裁决（ok / miss / extra / idk 之类，取值在 payload.verdict）
    "band",           # 拖出的边界（文字带左右、切分点…）
    "border_class",   # 类别裁决（clean / glued / none / idk）
    "recrop",         # 拖框重切（payload: old_bbox / new_bbox）
    "not_a_char",     # 判非字
    "confirm",        # 确认字（payload: char, admit）
    "relabel",        # 改判字
    "skip",           # 存疑跳过
    "mark",           # 实例级标记
    "flag",           # 簇级标记
    "split", "merge", # 簇操作
    "note",           # 纯文字批注
    "cutline",        # 拖切线：粘连格线的理想切点（payload: y / y_old / verdict / slot_above / slot_below）
]

Actor = Literal["user", "model", "align"]


class EventTarget(BaseModel):
    """事件指向的东西。step + key 是主键；anchor 让它在产物重生后仍可定位。"""
    step: str                       # 产出该单位的 Step id，如 border_detect
    unit: str = "page"              # book | page | column | cell
    key: str                        # 单位键（p0042c03s17）或卡片 id（cols:vol02:171）
    book: str | None = None
    page: int | None = None
    col: int | None = None
    slot: int | None = None
    anchor: dict | None = None      # §3.4 的锚点：space / bbox / quad / content_sha / product_key


class Event(BaseModel):
    id: str
    ts: str
    batch: str
    seq: int
    actor: Actor = "user"
    kind: Kind
    target: EventTarget
    payload: dict = Field(default_factory=dict)
    source_format: str | None = None   # 从旧格式收割来的，记原格式名：verdicts / seed / seg / marks

    @property
    def order(self) -> tuple[str, int]:
        return (self.batch, self.seq)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def make_event(batch: str, seq: int, kind: Kind, target: EventTarget, payload: dict | None = None,
               actor: Actor = "user", source_format: str | None = None, ts: str | None = None) -> Event:
    return Event(id=f"evt_{batch}_{seq:06d}", ts=ts or _now(), batch=batch, seq=seq, actor=actor,
                 kind=kind, target=target, payload=payload or {}, source_format=source_format)


def default_feedback_root() -> Path:
    """默认放数据集仓的 feedback/ 下（数据集仓独立存在，用相对路径找）。"""
    env = os.environ.get("GUJI_FEEDBACK_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent.parent / "open-guji-dataset" / "feedback"


class EventLog:
    """只追加的事件日志。一批一个文件，便于按批收割与回看。"""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else default_feedback_root()

    # ── 路径 ─────────────────────────────────────────────────────────
    @property
    def events_dir(self) -> Path:
        return self.root / "events"

    @property
    def consumed_dir(self) -> Path:
        return self.root / "consumed"

    def batch_path(self, batch: str) -> Path:
        return self.events_dir / f"{batch}.jsonl"

    # ── 读写 ─────────────────────────────────────────────────────────
    def append(self, events: Iterable[Event]) -> int:
        """追加；同 (batch, seq) 已存在的**跳过**（重复收割同一页面不会灌重）。"""
        events = list(events)
        if not events:
            return 0
        n = 0
        by_batch: dict[str, list[Event]] = {}
        for e in events:
            by_batch.setdefault(e.batch, []).append(e)
        for batch, evs in by_batch.items():
            path = self.batch_path(batch)
            path.parent.mkdir(parents=True, exist_ok=True)
            seen = {(e.batch, e.seq) for e in self.read(batch)}
            with open(path, "a", encoding="utf-8") as f:
                for e in sorted(evs, key=lambda x: x.seq):
                    if (e.batch, e.seq) in seen:
                        continue
                    f.write(json.dumps(e.model_dump(mode="json"), ensure_ascii=False,
                                       sort_keys=True) + "\n")
                    seen.add((e.batch, e.seq))
                    n += 1
        return n

    def read(self, batch: str) -> list[Event]:
        path = self.batch_path(batch)
        if not path.exists():
            return []
        out = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(Event.model_validate_json(line))
        return sorted(out, key=lambda e: e.order)

    def batches(self) -> list[str]:
        d = self.events_dir
        return sorted(p.stem for p in d.glob("*.jsonl")) if d.exists() else []

    def iter_all(self) -> Iterator[Event]:
        for b in self.batches():
            yield from self.read(b)

    def latest_seq(self, batch: str) -> int:
        evs = self.read(batch)
        return max((e.seq for e in evs), default=0)

    def resolve(self, batch: str | None = None) -> dict[str, Event]:
        """按 (batch, seq) 升序重放，返回每个 target.key 的**最终**事件（后到覆盖）。"""
        evs = self.read(batch) if batch else sorted(self.iter_all(), key=lambda e: e.order)
        out: dict[str, Event] = {}
        for e in evs:
            out[e.target.key] = e
        return out

    # ── 幂等消费 ─────────────────────────────────────────────────────
    def consumed_ids(self, consumer: str) -> set[str]:
        path = self.consumed_dir / f"{consumer}.jsonl"
        if not path.exists():
            return set()
        ids = set()
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    ids.add(json.loads(line)["event"])
        return ids

    def mark_consumed(self, consumer: str, events: Iterable[Event], note: str = "") -> int:
        events = list(events)
        if not events:
            return 0
        path = self.consumed_dir / f"{consumer}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = _now()
        with open(path, "a", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps({"event": e.id, "ts": ts, "note": note},
                                   ensure_ascii=False) + "\n")
        return len(events)

    def pending(self, consumer: str, batch: str | None = None) -> list[Event]:
        done = self.consumed_ids(consumer)
        evs = self.read(batch) if batch else sorted(self.iter_all(), key=lambda e: e.order)
        return [e for e in evs if e.id not in done]
