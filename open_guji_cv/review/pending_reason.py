"""待审原因 `PendingReason`：一格**为什么还在待审**（sheldon 2026-11-03 定）。

全项目唯一真源：本模块的 enum ＋ 同目录 `pending_reasons.yaml` 的配置。待审单、人裁事件、文意裁定、看图结论、
网站票、book-text 里一律写字段 `pending_reason`，值是本 enum 的英文名（如 `"group_abstain"`），不写中文、不写码。

- 配置里的 `code`（如 `Z01`）只是分类用的一个值：按大类排序、分组统计。码永不复用，改名走弃用。
- 每格只有一个主原因：按 `priority` 从小到大取第一个命中的。
- **不确定一律 `unknown`**（含历史数据回填、以后新增的数据），不留空：`parse()` 对空值、认不出的值都给 `UNKNOWN`。
- **这不是判定依据**。依据（证据）现在是 seed_admit 的疑问码 `why[]`，将来可能另立 enum，不并进这里。

别的仓（网站 TS、后台看板、guji-manager、book-text 校验器）用 `python -m open_guji_cv.review.pending_reason --json`
导出的副本，并各自加一条测试核对与本仓一致。
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path

import yaml

CONFIG_PATH = Path(__file__).with_name("pending_reasons.yaml")
FIELD = "pending_reason"


class PendingReason(str, Enum):
    """值＝名字的英文小写，写进所有数据里的就是这个值。顺序同 `pending_reasons.yaml`。"""

    SEG_PAGE_UNALIGNED = "seg_page_unaligned"
    SEG_COL_UNALIGNED = "seg_col_unaligned"
    COL_WIDTH_OUT_OF_BAND = "col_width_out_of_band"
    SEG_DEFECT = "seg_defect"
    OCCLUDED_WITH_REF = "occluded_with_ref"
    OCCLUDED_NO_REF = "occluded_no_ref"
    HARD_PAIR = "hard_pair"
    GROUP_ABSTAIN = "group_abstain"
    GROUP_CONFLICT = "group_conflict"
    GROUP_DEMOTED = "group_demoted"
    GROUP_REF_DISSENT = "group_ref_dissent"
    GROUP_WEAK = "group_weak"
    GROUP_FORM_OPEN = "group_form_open"
    NEAR_FORM_GUARD = "near_form_guard"
    VARIANT_PAIR = "variant_pair"
    LIB_MISSING = "lib_missing"
    LIB_SPARSE_DISSENT = "lib_sparse_dissent"
    LIB_SPARSE_AGREE = "lib_sparse_agree"
    LIB_UNRECOGNIZED = "lib_unrecognized"
    GARBLE_GATE = "garble_gate"
    REF_LACUNA = "ref_lacuna"
    REF_GAP = "ref_gap"
    REF_REPLACED = "ref_replaced"
    REF_MISMATCH = "ref_mismatch"
    RULING_CONFLICT = "ruling_conflict"
    VISION_FLAGGED = "vision_flagged"
    MACHINE_CHANGED = "machine_changed"
    RECHECK = "recheck"
    UNKNOWN = "unknown"

    def __str__(self) -> str:  # 写 json、拼字符串时就是英文名
        return self.value

    @property
    def spec(self) -> "ReasonSpec":
        return specs()[self]


class Category(str, Enum):
    SEGMENTATION = "segmentation"
    OCCLUSION = "occlusion"
    GROUP = "group"
    HARD_PAIR = "hard_pair"
    NEAR_FORM = "near_form"
    VARIANT = "variant"
    GLYPH_LIB = "glyph_lib"
    REFERENCE = "reference"
    MISMATCH = "mismatch"
    REVIEW = "review"


class Route(str, Enum):
    """去向：human 一定人审／llm 大模型统一过一遍（只收 high）／algo 先改算法／deferred 留到标点、专名阶段。"""

    HUMAN = "human"
    LLM = "llm"
    ALGO = "algo"
    DEFERRED = "deferred"


class Reviewer(str, Enum):
    """最终谁看：human／llm_then_human（大模型先过，其余回人）／none（不出单，算法放行或留后）。"""

    HUMAN = "human"
    LLM_THEN_HUMAN = "llm_then_human"
    NONE = "none"


class Ui(str, Enum):
    """网页卡片形态。"""

    PICK = "pick"
    CHOOSE3 = "choose3"
    FREE = "free"
    PAGE = "page"
    CONFIRM = "confirm"


@dataclass(frozen=True)
class ReasonSpec:
    reason: PendingReason
    code: str
    category: Category
    route: Route
    owner: str
    reviewer: Reviewer
    priority: int
    label: str
    hint: str
    ui: Ui
    detect: str
    legacy: dict = field(default_factory=dict)


def _load(path: Path = CONFIG_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def specs() -> dict[PendingReason, ReasonSpec]:
    """enum → 配置。yaml 与 enum 对不上（多、少、值不合法）直接报错，不静默。"""
    raw = _load()["reasons"]
    names = {r.value for r in PendingReason}
    if set(raw) != names:
        raise ValueError(f"pending_reasons.yaml 与 PendingReason 不一致：yaml 多 {sorted(set(raw) - names)}，"
                         f"缺 {sorted(names - set(raw))}")
    out = {}
    for name, v in raw.items():
        r = PendingReason(name)
        out[r] = ReasonSpec(
            reason=r, code=v["code"], category=Category(v["category"]), route=Route(v["route"]),
            owner=v["owner"], reviewer=Reviewer(v["reviewer"]), priority=int(v["priority"]),
            label=v["label"], hint=v["hint"], ui=Ui(v["ui"]), detect=v["detect"], legacy=v.get("legacy") or {})
    return out


def parse(value) -> PendingReason:
    """数据里读到的值 → enum。空、None、认不出的一律 `UNKNOWN`（不确定就写 unknown）。"""
    if isinstance(value, PendingReason):
        return value
    try:
        return PendingReason(str(value).strip()) if value else PendingReason.UNKNOWN
    except ValueError:
        return PendingReason.UNKNOWN


def by_code(code: str) -> PendingReason:
    for r, s in specs().items():
        if s.code == code:
            return r
    return PendingReason.UNKNOWN


def legacy_candidates(*, cause: str | None = None, cls: str | None = None) -> list[PendingReason]:
    """旧字段（cv 成因码 `cause`、卡片类别 `cls`）可能对应的新原因，按 priority 排。迁移旧数据用：只有一个就是它，多个要再看别的事实，
    一个都没有就是 `unknown`。"""
    hits = []
    for r, s in specs().items():
        if (cause and cause in (s.legacy.get("cause") or [])) or (cls and cls in (s.legacy.get("cls") or [])):
            hits.append(r)
    return sorted(hits, key=lambda r: specs()[r].priority)


def export() -> dict:
    """给别的仓用的副本（`--json`）：分类、去向、每个原因的全部配置。"""
    d = _load()
    return {
        "version": d["version"],
        "field": FIELD,
        "categories": d["categories"],
        "routes": d["routes"],
        "reasons": {r.value: {k: (v.value if isinstance(v, Enum) else v) for k, v in asdict(s).items() if k != "reason"}
                    for r, s in specs().items()},
    }


if __name__ == "__main__":
    import sys
    if "--json" in sys.argv:
        print(json.dumps(export(), ensure_ascii=False, indent=1))
    else:
        for r, s in sorted(specs().items(), key=lambda kv: kv[1].code):
            print(f"{s.code}\t{r.value}\t{s.route.value}\t{s.owner}\t{s.label}")
