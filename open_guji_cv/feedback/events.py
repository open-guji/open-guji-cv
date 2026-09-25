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
#: ⚠️ **枚举里有 9 个值没有任何前端出口**（2026-09-18 实测：扫全部事件日志 +
#: 前端源码 + 路由表）。别照着它推断「系统支持哪些裁决」——真正的分类真源是
#: `feedback/questions.py` 的问题登记表，`kind` 只是传输层的粗分类。
#:
#: 其中两个容易看走眼：`not_a_char` 与 `skip` **确实在用**，但身份是
#: `payload.v` 的取值（前端整批发 `kind="confirm"`，靠 `v` 二次分流），
#: 不是 kind。后端两条路都认（`consumers.py` 里
#: `e.kind == "not_a_char" or (e.kind == "confirm" and p.get("v") == "not_a_char")`），
#: 走的一直是后一条。
#:
#: **不删这些值**：`Kind` 是 `Literal`，删了之后任何遗留事件（含别人机器上的、
#: 未推送的日志）在 `gold rebuild` 重放时会直接校验失败——而重放是金标的重建
#: 路径，炸在这里等于金标重建不了。标注比删除安全，"误导"这个实际问题靠注释解决。
Kind = Literal[
    "verdict",        # 一档裁决（ok / miss / extra / idk 之类，取值在 payload.verdict）
    "band",           # 拖出的边界（文字带左右、切分点…）
    "border_class",   # 类别裁决（clean / glued / none / idk）
    "recrop",         # 【无出口】拖框重切。消费器 `glyphdb_recrop` 自己就报
                      #   "尚未接入（P1 之后）"，路由表那条规则是死的
    "not_a_char",     # 【无 kind 出口，但语义在用】判非字——实走 confirm + payload.v
    "confirm",        # 确认字（payload: char, admit）
    "relabel",        # 【无出口】改判字
    "skip",           # 【无 kind 出口，但语义在用】存疑跳过——实走 confirm + payload.v
    "damaged",        # 【无 kind 出口，但语义在用】原图破损、字形不可辨——实走 confirm
                      #   + payload.v；payload 另带 guess（最像的那个字，可空）。
                      #   与 skip 的区别：skip 是「我还没想好」（待办），damaged 是
                      #   「看过了，图就这样，认不出」（已了结，文本出 □）。
    "mark",           # 【无出口】实例级标记
    "flag",           # 【无出口】簇级标记
    "split", "merge", # 【无出口】簇操作
    "note",           # 【无出口】纯文字批注
    "cutline",        # 拖切线：粘连格线的理想切点（payload: y / y_old / verdict / slot_above / slot_below）
    "border_offset",  # 整页拖版框：下版框整页坐标金标（payload: y_left / y_right / verdict）
    "head_raise",     # 列级抬头精标（payload: raised / n_raised / head_cut / note）
    "n_body_slots",   # 逐列字数人裁：chars_per_line 常量在个别列不成立时的覆盖（payload: n_slots）
    # ── Step8 复核裁决（2026-09-22）。问的不是「这是什么字」而是「我们和证人谁对」。
    "collate_ok",     # 维持我方转写：看过图了，我们和证人就是不一样。只记账，
                      #   作用是**下轮不再出这张卡**（否则每次重跑重看同样 71 条）。
    "char_convention",# 本书通例（payload: pair, kind∈人名/物品/通假/避諱/正俗, note）
                      #   → books/<id>.yaml 的 char_conventions。**本书专属**：
                      #   完/元 在别的书里就是两个字，进全局表会污染。
    "mark_jiajie",    # 标为通假（payload: pair）→ jiajie.tsv。异体与通假是**两类**：
                      #   异体是同一个字的不同写法（衞/衛），通假是借字（早/蚤、甫/父）。
                      #   自动判据分不开，新字对先落异体层，人点「这是通假」才搬。
    "variant_deny",   # 推翻一条「异体」边（payload: pair）→ variants.deny.tsv。
                      #   **跨书**负样本：关系图会错（治/冶、輨/轄 实证）。
    # ── Step8 两层分类（2026-09-24）。见 feedback/collate_state.py。
    "collate_verdict",# 把一个字位挪进某一类（payload: pair, who∈ours/theirs/neither/空,
                      #   cat∈variant/jiajie/taboo/other, fix, final, ctx 快照）。**逐字位**、
                      #   后到覆盖，who 空 = 退回待审。改字那部分另写一条带 via 的 confirm。
    "unmark_jiajie",  # 撤一条通假字对（payload: pair, book）→ 从 jiajie.tsv 删掉本书标的那行。
    # ── 字形库体检（2026-09-25，字形库 03）。见 feedback/glyph_audit.py。
    "glyph_audit",    # 库里一个刻例定的字对不对（payload: v∈ok/near_form/evict/relabel,
                      #   instance_id, key, target, char, peer, peer_char, flags）
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
    """`GUJI_FEEDBACK_DIR` > `GUJI_WORKSPACE`/feedback > 仓内 feedback（core.workspace）。

    09-03 设计放在 open-guji-dataset/feedback/，09-13 改归 workspace（用户裁定：
    人裁事件是这本书审查过程的账，运行时不该写测试集仓）。"""
    from ..core.workspace import feedback_root
    return feedback_root()


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

    #: 批次名里不能进文件名的字符 → 统一换成 `-`。
    #:
    #: 2026-09-16 吃过一次亏：定字面板的批次名默认是 `<book>-<pages>-decide`，
    #: 用户把页码框填成 `list:regress_vol02_p1_30`（点名清单模式），批次名就带了冒号。
    #: **Windows 上冒号是 NTFS 数据流分隔符**——`open("…/list:x.jsonl","a")` 不报错，
    #: 而是往名为 `list` 的 0 字节文件里写一条隐藏流 `x.jsonl`。于是：裁了 30 条、
    #: 面板显示正常、`ls` 看不到任何 jsonl、下次读回来是空的。静默丢数据，最坏的一种。
    #: （那批数据事后用 `Get-Content -Stream` 捞回来了，见 vol02-regress-p1-30-decide.jsonl）
    _BAD_IN_NAME = ':*?"<>|/\\\x00'

    @classmethod
    def safe_batch_name(cls, batch: str) -> str:
        """批次名 → 可安全当文件名的形式。只改文件名，事件里的 `batch` 字段保持原样。"""
        out = "".join("-" if c in cls._BAD_IN_NAME else c for c in batch)
        return out.strip(". ") or "batch"

    def batch_path(self, batch: str) -> Path:
        return self.events_dir / f"{self.safe_batch_name(batch)}.jsonl"

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

    def compact(self, batch: str, dry_run: bool = False) -> dict:
        """同一 target.key 的重复裁决只留**最后一条**（用户 2026-09-16）。

        重放语义（后到覆盖）一直是对的，日志膨胀才是问题：定字面板以前每点一次
        「提交裁决」，就把 `verdicts.current` 里**全部**裁决重写一遍——包括刚从
        服务端读回、本轮根本没动过的那些。实测 bxgb：1620 条 confirm 只覆盖 312
        个字位，`bxgb:3:1:19` 累计写了 13 次。前端已改成只发本轮动过的，这个方法
        是把**已经攒下的**重复压掉。

        ⚠️ **保留被留下那条的原 `id` 与 `seq`，绝不重编号**。幂等记账
        （`consumed/<consumer>.jsonl`）认的就是 `evt_<batch>_<seq>` 这个 id，
        重编会让已消费的事件对不上账，被当成新事件**再消费一遍**——压实本是
        为了消重，结果在下游制造重复，那就反了。

        分组键是 `(kind, target.unit, target.key)`：`cutline` 与字位裁决的 key
        形状相同（`bxgb:39:19:12`）而 unit 不同，混在一起会互相顶掉。
        """
        evs = self.read(batch)
        if not evs:
            return {"batch": batch, "before": 0, "after": 0, "removed": 0, "dry_run": dry_run}
        keep: dict[tuple, Event] = {}
        for e in evs:                       # read() 已按 (batch, seq) 升序 → 后到覆盖
            keep[(e.kind, e.target.unit, e.target.key)] = e
        kept_ids = {e.id for e in keep.values()}
        out = [e for e in evs if e.id in kept_ids]
        res = {"batch": batch, "before": len(evs), "after": len(out),
               "removed": len(evs) - len(out), "dry_run": dry_run}
        if dry_run or not res["removed"]:
            return res
        path = self.batch_path(batch)
        tmp = path.with_suffix(".jsonl.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            for e in out:                   # 原顺序、原 id、原 seq
                f.write(json.dumps(e.model_dump(mode="json"), ensure_ascii=False,
                                   sort_keys=True) + "\n")
        os.replace(tmp, path)               # 原子替换：中途挂掉不会留半个日志
        return res

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
    def consumers(self) -> list[str]:
        """记账目录里实际存在的消费者名。

        2026-09-18 加：`refresh_counts` 原先写死 `{"gold_add", "glyphdb"}` 两个名字，
        而真实记账文件叫 **`glyphdb_admit`**——`consumed_ids("glyphdb")` 恒返回空集，
        定字裁决的消费数一直算作 0；另外还漏了 `crop_exclude` / `product_invalidate`。
        写死名字就会随消费者改名而静默失准，改成按目录实际内容取。
        """
        d = self.consumed_dir
        if not d.exists():
            return []
        return sorted(p.stem for p in d.glob("*.jsonl"))

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
