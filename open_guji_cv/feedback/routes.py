"""路由表：kind × target.step → 消费者。

review_feedback_loops.md 三条环（向上切分层 / 向下匹配栈 / 本步准入）的机器化。
表在 `feedback/routes.yaml`（跟事件放一起，随数据集仓走）；缺文件时用下面的内置默认。

匹配规则：`match` 里写的每个键都要相等才算命中；`target.step` 这种点号路径按属性取值。
一条事件可以命中多条规则（分别路由给不同消费者），互不影响。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .events import Event

# 内置默认表 —— 与设计 §3.6 的 routes.yaml 一致
DEFAULT_ROUTES: list[dict] = [
    {"match": {"kind": "verdict", "target.step": "border_detect"},
     "to": [{"consumer": "gold_add", "shard": "border-detection/column-split"}]},
    {"match": {"kind": "band", "target.step": "column_warp"},
     "to": [{"consumer": "gold_add", "shard": "char-segmentation/column-warp"}]},
    {"match": {"kind": "border_class", "target.step": "column_warp"},
     "to": [{"consumer": "gold_add", "shard": "char-segmentation/column-warp"}]},
    {"match": {"kind": "verdict", "target.step": "row_segment"},
     "to": [{"consumer": "gold_add", "shard": "char-segmentation/row-boundaries"}]},
    {"match": {"kind": "recrop"},
     "to": [{"consumer": "glyphdb_recrop"},
            {"consumer": "gold_add", "shard": "char-segmentation/instances",
             "extra": {"seed": "review_recrop"}}]},
    {"match": {"kind": "not_a_char"},
     "to": [{"consumer": "gold_add", "shard": "char-segmentation/instances"},
            # 判非字的图块同时进排除名单：不进库、下轮也不再出卡（2026-09-05）
            {"consumer": "crop_exclude"}]},
    # 拖切线（2026-09-05）：粘连格线的理想切点，落 touching-cuts 金标（现役 Step2 列图坐标）
    {"match": {"kind": "cutline"},
     "to": [{"consumer": "gold_add", "shard": "char-segmentation/touching-cuts"}]},
    # 切线卡片上标了「界行/版框压进裁片」的，同时反馈给上游：这一格是 side-rule（侧边界行
    # 残余）的正样本——用户 2026-09-05：「带边框的应该反馈到上游，我们希望边框都被清除了」。
    {"match": {"kind": "cutline", "payload.tags": "border"},
     "to": [{"consumer": "gold_add", "shard": "char-segmentation/side-rule",
             "extra": {"seed": "cutline_border"}}]},
    {"match": {"kind": "confirm"},
     "to": [{"consumer": "glyphdb_admit"},
            # 切分缺陷（payload.v == "seg_defect"）也走 confirm 这条线进来，
            # 由 gold_add 落进 instances 金标——那批 144 条 truncated +
            # 128 条 contaminated 就是它的既有同伴。定字裁决与切分缺陷是
            # **两件事**：前者答「这是什么字」，后者答「这块图能不能用」，
            # 所以同一批事件要同时喂给两个消费者，各取所需
            # （glyphdb_admit 只认 v=="confirm"，gold_add 只认 seg_defect）。
            {"consumer": "gold_add", "shard": "char-segmentation/instances"},
            # 第三个去处（2026-09-05 补）：切坏的图块进排除名单。此前只落金标，
            # 没人把它写进 crop_exclusions.jsonl，于是「标了缺陷」和「以后别再用
            # 这块图」之间是断的——下一轮重跑照样出卡，也没有闸拦着它进库。
            # crop_exclude 只认 seg_defect / not_a_char，定字的 confirm 一律跳过。
            {"consumer": "crop_exclude"}]},
]


@dataclass
class Destination:
    consumer: str
    shard: str | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class Route:
    match: dict
    to: list[Destination]

    def hits(self, e: Event) -> bool:
        for path, want in self.match.items():
            got = _get(e, path)
            # 实际值是列表（如 payload.tags）时，规则写一个标量表示"包含"
            if isinstance(got, list) and not isinstance(want, list):
                if want not in got:
                    return False
                continue
            if got != want:
                return False
        return True


def _get(e: Event, path: str) -> Any:
    obj: Any = e
    for part in path.split("."):
        obj = getattr(obj, part, None) if not isinstance(obj, dict) else obj.get(part)
        if obj is None:
            return None
    return obj


class RouteTable:
    def __init__(self, routes: list[Route]):
        self.routes = routes

    @classmethod
    def load(cls, path: Path | None = None) -> "RouteTable":
        raw = DEFAULT_ROUTES
        if path and path.exists():
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        routes = []
        for r in raw:
            dests = [Destination(consumer=d["consumer"], shard=d.get("shard"),
                                 extra=d.get("extra") or {}) for d in r.get("to", [])]
            routes.append(Route(match=r.get("match") or {}, to=dests))
        return cls(routes)

    def destinations(self, e: Event) -> list[Destination]:
        out: list[Destination] = []
        for r in self.routes:
            if r.hits(e):
                out.extend(r.to)
        return out

    def plan(self, events: list[Event]) -> dict[str, list[tuple[Event, Destination]]]:
        """按消费者分组：{consumer: [(事件, 去向), ...]}；没有去向的事件不出现。"""
        plan: dict[str, list[tuple[Event, Destination]]] = {}
        for e in events:
            for d in self.destinations(e):
                plan.setdefault(d.consumer, []).append((e, d))
        return plan

    def unrouted(self, events: list[Event]) -> list[Event]:
        return [e for e in events if not self.destinations(e)]
