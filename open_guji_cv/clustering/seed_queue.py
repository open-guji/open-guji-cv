"""逐页进库（种子）协议的**接口契约**（glyph_db_first_design.md §3.5）。

本模块是流程侧（seed 命令）与审查页面侧（review UI）唯一的耦合点：
双方只通过这里定义的疑问码、队列条目、决策事件三样东西对话。
改字段先改这里，两侧同步跟进——不要在任何一侧私加字段。

数据流：

    seed 命令（流程侧）
      每页逐字位：OCR 载体 × 整理本对齐 双信号 + 六条疑问判定
        无疑问 → 直接进库（align provenance），也落一条 auto_admitted
                 记录（审计用）
        强信号通道（三轮实审后加）：OCR prob ≥ strong_prob（默认
                 0.995）且与整理本一致（过闸对齐或免闸参考）时，
                 degraded_crop 单独不拦、直接进库（note=strong_dual）；
                 near_form / db_inconsistent 仍拦
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
# (batch, seq) 供去重；char 仅 confirm 需要。
# 应用纪律：同一 instance_id 的多条事件按 seq 升序、**后到覆盖**——
# ingest 侧只应用每个字位 seq 最大的事件（confirm 后被 skip 撤销的，
# 最终以 skip 为准、不进库）。
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
        if ev.get("op") not in ("confirm", "not_a_char", "skip"):
            continue
        if not ev.get("instance_id"):
            continue
        out[(ev.get("batch"), ev.get("seq"))] = ev
    return list(out.values())
