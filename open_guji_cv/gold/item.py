"""金标条目的统一信封。

既有纪律全部变成字段，不靠人记：
- `label_origin` 不可省（align 有噪声，清洗 / 分层 / 加权都靠它区分）；
- `stratum` + `stratum_weight`：按可疑度挑的批次不能拿来估总体比例；
- `status`：uncertain 评测跳过；stale 是上游重生后待重键的；
- `history`：每次改判记 why，对齐 relabel_history 的要求；
- `source_events`：这条金标由哪些人裁事件产生，可回溯。
"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field

LabelOrigin = Literal["human", "align", "synth", "model"]
Status = Literal["active", "stale", "uncertain", "retired"]


class Anchor(BaseModel):
    """§3.4：product_key 允许失效，bbox + content_sha 不失效。"""
    book: str | None = None
    page: int | None = None
    col: int | None = None
    slot: int | None = None
    space: str | None = None                                   # raw_page_px@top-right 等
    bbox: tuple[float, float, float, float] | None = None
    quad: list[tuple[float, float]] | None = None
    content_sha: str | None = None
    product_key: dict | None = None                            # {step, key, fingerprint}


class HistoryEntry(BaseModel):
    ts: str
    change: str
    why: str = ""


class GoldItem(BaseModel):
    id: str
    anchor: Anchor = Field(default_factory=Anchor)
    input: dict = Field(default_factory=dict)                  # {asset: sha, params: {...}}
    expected: dict = Field(default_factory=dict)               # 本步专属的金标内容
    label_origin: LabelOrigin = "human"
    pipeline_version: str | None = None
    stratum: str | None = None
    stratum_weight: float | None = None
    status: Status = "active"
    source_events: list[str] = Field(default_factory=list)
    history: list[HistoryEntry] = Field(default_factory=list)

    def touch(self, change: str, why: str = "") -> None:
        self.history.append(HistoryEntry(
            ts=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), change=change, why=why))
