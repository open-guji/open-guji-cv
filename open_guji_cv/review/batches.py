"""批次登记：一批人裁的全部元信息。

`artifacts/README.md` 那张手写表格的机器版。URL 是持久资产——artifact 模式的批次
更新必须重发布到**同一 URL**，所以 url 存在这里、由控制台守着。

**发布前必须先收割**（手册纪律：不先读回就会覆盖掉未导出的裁决）：
`can_publish()` 在有未收割事件时返回 False，控制台据此把导出按钮变灰。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

TRANSPORTS = ("server", "artifact")
STATUSES = ("draft", "open", "harvested", "closed")


def default_batches_root() -> Path:
    env = os.environ.get("GUJI_BATCHES_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent / "review" / "batches"


@dataclass
class Batch:
    id: str
    title: str
    step: str                            # 这批题目属于哪一步（路由与金标分片按它走）
    kind: str = "verdict"                # 主要裁决类型（events.Kind）
    book: str | None = None
    transport: str = "server"            # server | artifact
    url: str | None = None               # artifact 模式的持久 URL
    shard: str | None = None             # 目标金标分片，如 border_detect/column-split
    cards_ref: str | None = None         # 卡片 id 冻结文件（*_cards.jsonl）
    n_cards: int = 0
    options: list[str] = field(default_factory=list)   # 裁决档位
    status: str = "draft"
    created_at: float = field(default_factory=time.time)
    harvested_at: float | None = None
    n_events: int = 0                    # 已收进 EventLog 的事件数
    n_consumed: int = 0                  # 已被路由消费的事件数
    notes: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["n_pending"] = max(0, self.n_events - self.n_consumed)
        d["progress"] = (round(self.n_events / self.n_cards, 3) if self.n_cards else None)
        return d

    def can_publish(self) -> tuple[bool, str]:
        """artifact 模式重发布前的闸：有未收割的裁决就不许发（会盖掉）。"""
        if self.transport != "artifact":
            return True, ""
        if self.status == "open" and self.url:
            return False, "线上可能有未收割的裁决，先 harvest 再重发"
        return True, ""


class BatchStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else default_batches_root()

    def path(self, batch_id: str) -> Path:
        return self.root / f"{batch_id}.json"

    def save(self, b: Batch) -> Path:
        p = self.path(b.id)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(asdict(b), ensure_ascii=False, indent=1), encoding="utf-8")
        return p

    def get(self, batch_id: str) -> Batch | None:
        p = self.path(batch_id)
        if not p.exists():
            return None
        d = json.loads(p.read_text(encoding="utf-8"))
        return Batch(**{k: v for k, v in d.items() if k in Batch.__dataclass_fields__})

    def list(self) -> list[Batch]:
        if not self.root.exists():
            return []
        out = [self.get(p.stem) for p in sorted(self.root.glob("*.json"))]
        return sorted([b for b in out if b], key=lambda b: b.created_at, reverse=True)

    def refresh_counts(self, b: Batch, log) -> Batch:
        """从 EventLog 回填事件数与消费数。log: feedback.EventLog"""
        evs = log.read(b.id)
        b.n_events = len(evs)
        done = log.consumed_ids("gold_add") | log.consumed_ids("glyphdb")
        b.n_consumed = sum(1 for e in evs if e.id in done)
        if b.n_events and b.status == "open":
            b.status = "harvested" if b.n_consumed >= b.n_events else "open"
        self.save(b)
        return b


def render_registry_markdown(batches: list[Batch]) -> str:
    """生成 artifacts/README.md 那张台账表（人读用；真源是 batches/*.json）。"""
    lines = ["# 审查批次台账（由 review/batches/*.json 生成，勿手改）", "",
             "| 批次 | 题目 | 步骤 | 传输 | 卡片 | 已裁 | 已消费 | 状态 | URL |",
             "|---|---|---|---|---|---|---|---|---|"]
    for b in batches:
        url = f"[链接]({b.url})" if b.url else "—"
        lines.append(f"| `{b.id}` | {b.title} | {b.step} | {b.transport} | {b.n_cards} | "
                     f"{b.n_events} | {b.n_consumed} | {b.status} | {url} |")
    return "\n".join(lines) + "\n"
