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
    # 闸1 的三类页级裁决（2026-09-18 拆开）。此前一条 `verdict + border_detect`
    # 通吃，**三个问题落进同一个分片**：cols 问「界行在不在缝上」(ok/miss/extra)、
    # head 问「这页有没有抬头」(yes/no)、outer 问「外沿线准不准」(ok/in/out/none)。
    # 实测污染：siku column-split 分片 205 条里有 **70 条是 head 的 yes/no**
    # ——档位完全不同，拿这个分片评测会把 70 条答非所问的条目算进去。
    # 靠 `payload.question` 分流；前端三种卡各自声明自己问的是什么。
    # `question` 是《计划书-控制台四板块统一》§2.2 的一等字段，阶段二会正式化，
    # 这里先以 payload 落地（止血优先，不提前引入机制）。
    {"match": {"kind": "verdict", "target.step": "border_detect",
               "payload.question": "border_detect.page.has_head_raise"},
     "to": [{"consumer": "gold_add", "shard": "border-detection/head-raise-presence"}]},
    {"match": {"kind": "verdict", "target.step": "border_detect",
               "payload.question": "border_detect.page.outer_edge"},
     "to": [{"consumer": "gold_add", "shard": "border-detection/outer-edge"}]},
    {"match": {"kind": "verdict", "target.step": "border_detect",
               "payload.question": "border_detect.page.vline_on_seam"},
     "to": [{"consumer": "gold_add", "shard": "border-detection/column-split"}]},
    # ── 历史事件（2026-09-18 之前，没有 `question`）按卡片 id 前缀分流 ──
    # `gold rebuild` 会重放整个事件日志，这三条保证重放结果与新裁的一致；
    # 存量 70 条 head 裁决正是靠它们从 column-split 迁出的。
    # `payload.question: None` = 「没带 question」，与上面三条互斥，
    # 不写的话带 question 的事件会同时命中专用规则和兜底，落进两个分片。
    {"match": {"kind": "verdict", "target.step": "border_detect",
               "payload.question": None, "target.key": "prefix:head:"},
     "to": [{"consumer": "gold_add", "shard": "border-detection/head-raise-presence"}]},
    {"match": {"kind": "verdict", "target.step": "border_detect",
               "payload.question": None, "target.key": "prefix:outer:"},
     "to": [{"consumer": "gold_add", "shard": "border-detection/outer-edge"}]},
    # 其余（`cols:` 前缀与更早的无前缀 id）仍落 column-split——那是它本来的归属。
    {"match": {"kind": "verdict", "target.step": "border_detect",
               "payload.question": None,
               "target.key": "not-prefix:head:|outer:"},
     "to": [{"consumer": "gold_add", "shard": "border-detection/column-split"}]},
    {"match": {"kind": "band", "target.step": "column_warp"},
     "to": [{"consumer": "gold_add", "shard": "char-segmentation/column-warp"}]},
    {"match": {"kind": "border_class", "target.step": "column_warp"},
     "to": [{"consumer": "gold_add", "shard": "char-segmentation/column-warp"}]},
    {"match": {"kind": "verdict", "target.step": "row_segment"},
     "to": [{"consumer": "gold_add", "shard": "char-segmentation/row-boundaries"}]},
    # ⚠️ 下面两条**当前没有事件会命中**（2026-09-18 实测：事件日志与前端源码都没有
    # 以它们为 kind 的出口）。留着不删的理由各不相同：
    # - `recrop`：消费器 `glyphdb_recrop` 自己就报「尚未接入（P1 之后）」，
    #   整条链路是半成品。删了规则等于把这件未办的事抹掉痕迹。
    # - `not_a_char`：语义**在用**，但走的是 `confirm` + `payload.v == "not_a_char"`
    #   那条（见下面 confirm 规则里的 crop_exclude）。这条 kind 级规则是早期
    #   设计的残留，`consumers.crop_exclude` 至今两条都认。
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
     "to": [{"consumer": "gold_add", "shard": "char-segmentation/touching-cuts"},
            # 裁决落定 → 该页 Step3 产物显式失效（2026-09-13 人裁回流）：
            # segment_column 下次重跑时按裁决表收敛候选，不失效就永远等不到重跑
            {"consumer": "product_invalidate", "extra": {"step": "row_segment"}}]},
    # 切线卡片上标了「界行/版框压进裁片」的，同时反馈给上游：这一格是 side-rule（侧边界行
    # 残余）的正样本——用户 2026-09-05：「带边框的应该反馈到上游，我们希望边框都被清除了」。
    {"match": {"kind": "cutline", "payload.tags": "border"},
     "to": [{"consumer": "gold_add", "shard": "char-segmentation/side-rule",
             "extra": {"seed": "cutline_border"}}]},
    # 整页拖版框（2026-09-12）：下版框整页坐标金标，`01-下版框根修先造
    # 金标.md` 点名要的「口径统一的直接坐标金标」，与既有 border-detection
    # 14 页金标（外延/内沿/中心口径混杂）分开存，避免再次污染。
    {"match": {"kind": "border_offset"},
     "to": [{"consumer": "gold_add", "shard": "border-detection/bottom-offset"}]},
    # 列级抬头精标（2026-09-12，overview `Step3-逐字切分/03-抬头综合优化.md`）。
    # **单独一个 kind，不复用 `verdict`**：`verdict` + `target.step=row_segment`
    # 已经被上面那条规则占着，会把列级抬头一并灌进 `char-segmentation/row-boundaries`
    # ——那个分片是旧坐标系、**已退役**。新开分片跟页级
    # `border-detection/head-raise-presence` 也分开存：两级的锚点粒度不同
    # （页 vs 列），塞一个分片里 eval 口径会打架。
    {"match": {"kind": "head_raise"},
     "to": [{"consumer": "gold_add", "shard": "char-segmentation/head-raise-columns"}]},
    # 逐列字数人裁（2026-09-18，`review/slot_count_cards.py`）：`chars_per_line`
    # 页级常量在个别列不成立（比如实际比常量多一个字）时的兜底。同 cutline 一条
    # 双消费者：落金标 + 该页 Step3 显式失效，下次重跑 `feedback/lookup.resolved_slots()`
    # 读回来覆盖 `effective_body_slots` 算出的格数。
    {"match": {"kind": "n_body_slots"},
     "to": [{"consumer": "gold_add", "shard": "char-segmentation/column-slots"},
            {"consumer": "product_invalidate", "extra": {"step": "row_segment"}}]},
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
            # `"prefix:xxx"` 写法（2026-09-18）：值以 xxx 开头就算命中。
            # 只为**历史事件**而加——2026-09-18 之前的 cols/head/outer 裁决没有
            # `payload.question`，唯一能分辨它们的就是卡片 id 前缀（`head:` /
            # `outer:`）。给历史事件日志补字段等于改真源，风险远大于在路由层按
            # 既成事实的前缀分流，所以走这条。新事件一律靠 `question`，
            # 阶段二统一卡片 id（去前缀）之后，这些 prefix 规则连同前缀一起退役。
            if isinstance(want, str) and want.startswith("prefix:"):
                if not (isinstance(got, str) and got.startswith(want[7:])):
                    return False
                continue
            # `"not-prefix:a|b"` —— 都不以这些前缀开头才算命中。兜底规则要用它把
            # 已有专用去向的前缀排掉：`match` 是「所有条件与」，表达不了「非」，
            # 而 `destinations` 把**每条**命中规则的去向累加，不是首条命中即止
            # ——少了这个，一条历史 head 裁决会同时落进 head-raise-presence 和
            # column-split 两个分片（实测确认过，不是假想）。
            if isinstance(want, str) and want.startswith("not-prefix:"):
                pres = [x for x in want[11:].split("|") if x]
                if isinstance(got, str) and any(got.startswith(x) for x in pres):
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
