"""逐页进库（种子）协议的**接口契约**（glyph_db_first_design.md §3.5）。

本模块是流程侧（seed 命令）与审查页面侧（review UI）唯一的耦合点：
双方只通过这里定义的疑问码、队列条目、决策事件三样东西对话。
改字段先改这里，两侧同步跟进——不要在任何一侧私加字段。

数据流：

    seed 命令（流程侧）
      每页逐字位：OCR 载体 × 整理本对齐 双信号 + 六条疑问判定
        无疑问 → 直接进库（align provenance），也落一条 auto_admitted
                 记录（审计用）
        库×整理本通道（五轮实审定型；此前 OCR prob 的 strong_dual/
                 triple 通道已废——OCR 置信度校准不可靠，只供候选）：
                 库完美匹配（verify same，cov≥0.992）继承的字与整理本
                 （过闸对齐或免闸参考）同字 → 直接进库
                 （note=match_ref），degraded_crop 单独不拦；
                 db_inconsistent 仍拦。near_form 在**过闸对齐 × 库 top
                 一致**时穿透（2026-08-24，75 条家族人裁回放 35/35），
                 免闸参考仍拦
        有疑问 → SeedItem(status=pending_review) 进 queue.jsonl
    审查页面（页面侧）
      按页读 queue.jsonl 的 pending_review 项 → 用户单键裁决 →
      发出 GUJI-SEED-EVENT 决策事件（与 artifact_export 的
      GUJI-EVENT 机制同构）
    seed-ingest（流程侧）
      回收事件 → confirmed 的以 human provenance 进库；rejected/
      not_a_char 记档不进库；每页清完推进 progress.json

集成澄清（2026-08-23，两侧首轮实现后定案）：

- **免审的判据是 status，不是 doubts 空**：单信号高置信（无对齐字、
  OCR prob ≥ 阈）六条疑问全不命中但双信号不齐 → 仍
  ``status=pending_review``（doubts=[], note="single_signal"）。
  只有 ``status=auto_admitted`` 才是免审进库。
- **事件应用纪律**：同一 instance_id 的多条事件按 seq 升序应用、
  后到覆盖（页面撤销 confirm 时发 skip 事件把字位退回队列）。
  已进库实例的再改判只更新队列行、不重写库（admissions 幂等闸）；
  库条目改判走设计 §3 的重放机制，将来需要时另加 amend 语义。
- **progress.json 字段**：``pages: {页号: {total, auto, pending, done}}``
  + ``pointer``（最早未 done 的页号，全部完成为 null）+ ``book`` +
  ``updated_at``。页面侧按 pointer 取缺省页。
- **auto_admitted 与 pending 同落 queue.jsonl**（审计与全书推进度
  同一口径），页面侧只出 pending_review/skipped。
- ``ocr.topk`` 元素为 ``[char, prob]`` 双元列表（与 match.candidates
  的 ``[char, cov]`` 同构）。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

# ── 疑问码（§3.5 的六条触发，编号对齐设计文档的表）───────────────────
DOUBT_SIGNAL_CONFLICT = "signal_conflict"    # 1 OCR ≠ 对齐字（归一后仍不同）
DOUBT_WEAK_SINGLE = "weak_single"            # 2 单信号且 OCR prob 低
DOUBT_DEGRADED_CROP = "degraded_crop"        # 3 crop_quality 判 degraded
DOUBT_NEAR_FORM = "near_form"                # 4 字属 never-match 形近家族
DOUBT_DB_INCONSISTENT = "db_inconsistent"    # 5 与库内同字条目 verify 全 diff
DOUBT_REPLACE_ALIGN = "replace_align"        # 6 对齐来自 replace 层

ALL_DOUBTS = (DOUBT_SIGNAL_CONFLICT, DOUBT_WEAK_SINGLE, DOUBT_DEGRADED_CROP,
              DOUBT_NEAR_FORM, DOUBT_DB_INCONSISTENT, DOUBT_REPLACE_ALIGN)

# 疑问码 → 审查页面上给用户看的一句话说明
DOUBT_LABELS = {
    DOUBT_SIGNAL_CONFLICT: "OCR 与整理本不一致，必有一错",
    DOUBT_WEAK_SINGLE: "只有 OCR 单信号且置信度低",
    DOUBT_DEGRADED_CROP: "图块有残留/截断，可能不是完整的字",
    DOUBT_NEAR_FORM: "形近字家族成员，两个信号源都容易犯同样的错",
    DOUBT_DB_INCONSISTENT: "与库内已有同字刻例形状对不上",
    DOUBT_REPLACE_ALIGN: "对齐标签来自 replace 层（OCR 与整理本不一致的位置）",
}

# ── 条目状态 ─────────────────────────────────────────────────────────
STATUS_AUTO = "auto_admitted"        # 双信号一致且零疑问，已 align 进库
STATUS_PENDING = "pending_review"    # 等用户裁决
STATUS_CONFIRMED = "confirmed"       # 用户确认，已 human 进库
STATUS_LABEL_ONLY = "confirmed_label_only"
#                                    # 用户确认了**字**但字形不入库：图块混有
#                                    # 无法剥离的残余，当范例会毒化匹配。
#                                    # 定字进转写/标注结果，字形不进 GlyphDB。
STATUS_REJECTED = "rejected"         # 用户改判成别的字（decided_char 为准）
STATUS_NOT_A_CHAR = "not_a_char"     # 用户判非字（版框/残带），不进库
STATUS_RECROPPED = "confirmed_recropped"   # 已废（2026-08-24 起重切是纯
#                                    # 几何事件，不再有独立状态；旧队列
#                                    # 行可能残留此值，读取侧仍需认识）
STATUS_SKIPPED = "skipped"           # 用户存疑跳过，留在队列


@dataclass
class SeedItem:
    """队列一行 = 一个字位的完整证据包。审查页面所需信息必须全在此，
    页面不回管线拿数据（自包含 HTML 的既有纪律）。"""
    instance_id: str                 # book:page:col:idx
    book: str
    page: str
    col: int
    idx: int
    patch_path: str                  # 相对 phase4_chars/ 的原图路径
    tier: str                        # clean | degraded（crop_quality）
    ocr: dict | None = None          # {"char": str, "prob": float, "topk": [[c,p]..]}
    align: dict | None = None        # {"char": str, "op": "equal"|"replace"}
    proposed: str | None = None      # 双信号一致时的拟进库字（唯一候选优先展示）
    doubts: list[str] = field(default_factory=list)   # 空 = 免审
    match: dict | None = None        # MatchResult.to_dict()（对当时的库）
    context: dict | None = None      # 审查上下文（2026-08-23 二轮加）：
    #   col_ocr: 该列 OCR 载体全文（空识别 □ 占位）
    #   col_ref: 该列整理本参考文（免闸对齐 page_reference；无对应 ·）
    #   pos:     当前字在列中的位置（0 起，供高亮）
    #   ref_char/ref_op: 本字位的整理本参考字与对齐 op（参考≠金标：
    #            免闸对齐噪声大，页面须与过闸的 align 字段区分展示）
    #   prev_ocr/prev_ref: 上一列末 ≤5 字（三轮加：列首字的上下文要
    #            接上一列）；next_ocr/next_ref: 下一列首 ≤5 字（列尾同理）
    intrusion: list[str] = field(default_factory=list)
    #   版面线侵入码（crop_quality.detect_intrusion，2026-08-24 加）：
    #   rule_bar_left/right（竖界行）、frame_bar_top/bottom（横版框、邻字
    #   压线）。**只作提示，不参与准入裁决**——用户实审里这类图块的字
    #   多半仍能认，该走「仅定字·不入库」还是照常进库由人定；这里的
    #   价值是让审查页把「为什么这块脏」说出来，并让缺陷能按列聚集
    #   回流上游（scripts/report_intrusions.py）。
    status: str = STATUS_PENDING
    decided_char: str | None = None  # confirmed/rejected 后的最终字
    provenance: str | None = None    # 进库时的 provenance: align | human
    note: str | None = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> "SeedItem":
        d = json.loads(line)
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__
                      if k in d} | {"doubts": d.get("doubts") or []})


# ── 决策事件（审查页面 → seed-ingest）────────────────────────────────
# 页面以文本行发事件，与 artifact_export 的 GUJI-EVENT 三层持久化机制
# 同构，前缀区分避免混流：
#
#     GUJI-SEED-EVENT {"op": "confirm", "instance_id": "vol01:4:1:3",
#                      "char": "欽", "batch": "vol01-seed-p4", "seq": 7,
#                      "ts": "..."}
#
# op 取值：
#   confirm    确认 char（来自候选或手输）→ status=confirmed，human 进库。
#              可带 "admit": false（**仅定字·不入库**）：图块混有无法
#              剥离的残余时，字收进标注结果、字形不进 GlyphDB →
#              status=confirmed_label_only。缺省 admit=true。
#   not_a_char 非字 → status=not_a_char，不进库
#   skip       存疑跳过 → status=skipped，留队列下批再出
#   recrop     **重切**：带 "bbox": [x0,y0,x1,y1]（页图绝对坐标，浮点）。
#              切分错位时（格线整体偏移，把本字的头切掉、又吃进下一字）
#              光改字没用——图块本身就是错的，收进库会毒化匹配。
#              **纯几何事件**（2026-08-24 定案，用户实审反馈）：只改
#              图块，不定字、不推进裁决——重切完用户仍照常独立选字。
#              事件里若带 "char"/"admit" 是首版 UI 的脏字段，ingest
#              侧一律忽略。
#              实锤：vol01:5:2:15「言」——框整体下移约 35px，上边切掉
#              亠头、下边吃进「等」的头两笔。
# (batch, seq) 供去重；char 仅 confirm 需要。
# 应用纪律（两通道，2026-08-24 重设计）：recrop 是几何通道，
# confirm/not_a_char/skip 是裁决通道，**互不覆盖**。同一 instance_id：
#   几何通道取 seq 最大的 recrop，先应用（重裁 patch、改 index.jsonl
#   bbox、已进库的实例同步刷新库内真源与派生）；
#   裁决通道取 seq 最大的 confirm/not_a_char/skip，后应用（confirm 读
#   的因此已是重切后的图块字节）。
# 这样「recrop → 之后任意时刻 confirm」与「confirm → 之后 recrop」
# 都存重切后的字形——存库的必须是重切形，不是原始错形。
SEED_EVENT_PREFIX = "GUJI-SEED-EVENT"


def parse_seed_events(text: str) -> list[dict]:
    """从页面回收文本中解析种子决策事件，按 (batch, seq) 去重（后到覆盖）。"""
    out: dict[tuple, dict] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith(SEED_EVENT_PREFIX):
            continue
        try:
            ev = json.loads(line[len(SEED_EVENT_PREFIX):].strip())
        except json.JSONDecodeError:
            continue
        if ev.get("op") not in ("confirm", "not_a_char", "skip", "recrop"):
            continue
        if ev["op"] == "recrop":
            bb = ev.get("bbox")
            if not (isinstance(bb, list) and len(bb) == 4
                    and all(isinstance(v, (int, float)) for v in bb)
                    and bb[2] > bb[0] and bb[3] > bb[1]):
                continue                      # 坏 bbox 不如不改
        if not ev.get("instance_id"):
            continue
        out[(ev.get("batch"), ev.get("seq"))] = ev
    return list(out.values())
