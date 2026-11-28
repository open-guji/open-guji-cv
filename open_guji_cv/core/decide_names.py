"""第四步收尾 `seed_admit` → `char_decide` 改名的**名字常量与兼容读口**（CV4 P3a-1，2026-11-28）。

背景（Sheldon 11-28 定）：第四步收尾不编号、叫 `char_decide`，接替 `seed_admit` 的全部功能。改名分两个版本发：

1. **本版（兼容读口）**：所有读 `seed_admit` 的地方都改成「新名优先、旧名兜底」，事件、参数键、产物目录与页键两个名字都认；
   **产物仍写 `seed_admit`，Step id、产物种类、参数类、指纹都不动**，各书产物不过期。
2. **更后一版（改名本身）**：Step id／产物目录／页顶层键／参数键／事件 `target.step` 改写 `char_decide`；
   只需把下面的 `ADMIT_STEP_ACTIVE` 改成 `"char_decide"`（再配合 Step 改名与 `guji-cv decide migrate-name`）。

本模块在 core，纯函数、不 import steps／feedback，**不在任何 Step 的 `code_deps` 里**（改它不动指纹）。
读口分三处，调用方按需拿：

- 产物：`final_page_dict(doc)`、`final_dir(products_root, book)`、`final_dirs(...)`（新目录优先；两目录并存以 `char_decide/` 为准）；
- 参数：`fold_admit_params(params)`（`char_decide:` 与 `seed_admit:` 两个键都认；同时写报错）；
- 事件：`is_admit_step(name)`、`same_admit_step(a, b)`（`feedback/decide_events.py` 在其上做 `decided_view` 等）。
"""

from __future__ import annotations

from pathlib import Path

#: 收尾的新名与旧名。**新名在前**：读的时候先新后旧。
NEW_ADMIT_STEP = "char_decide"
LEGACY_ADMIT_STEP = "seed_admit"
ADMIT_STEPS: tuple[str, ...] = (NEW_ADMIT_STEP, LEGACY_ADMIT_STEP)

#: **现在代码写的名字**（Step id、产物目录、产物种类、页顶层键、参数里生效的键、新事件的 `target.step`）。
#: 本版仍是旧名；改名那一版只改这一行（与 Step 的 `spec.id` 同步）。
ADMIT_STEP_ACTIVE = LEGACY_ADMIT_STEP


def is_admit_step(name: str | None) -> bool:
    """`name` 是不是收尾这一步（新旧名都算）。"""
    return name in ADMIT_STEPS


def same_admit_step(a: str | None, b: str | None) -> bool:
    """两个步名指不指同一步：同名，或者都是收尾的新旧名。"""
    return a == b or (is_admit_step(a) and is_admit_step(b))


def canonical_step(name: str) -> str:
    """把旧名归一成新名（读时归一用：按时间先后覆盖时，两个名字当同一步）；别的步名原样返回。"""
    return NEW_ADMIT_STEP if name == LEGACY_ADMIT_STEP else name


#: 收尾步**直接写**的送审原因（manager `pending_reasons.yaml` 里 owner＝CV4 的值，按 yaml 现状 2026-11-28 共 18 个，含已停用的 group_weak）。
#: 切分类（S）、遮挡类（D，P3b 4c 独立后改由 4c 状态给）、字形库 L02／L04、复审 X02–X04 仍由 manager 判，cv 不写（留 None）。
#: 说明见 `doc/4-定字/pending_reason.md`；判法在 `steps/char_decide_reasons.py`；与 manager 导出的对账测试：`tests/test_pending_reason_enum.py`。
FINAL_PENDING_REASONS: tuple[str, ...] = (
    "hard_pair", "group_abstain", "group_conflict", "group_demoted", "group_ref_dissent", "group_weak", "group_unconfirmed",
    "near_form_guard", "variant_pair", "variant_form_open", "lib_missing", "garble_gate", "glyph_pending", "ref_lacuna",
    "ref_gap", "ref_ocr_diff", "ref_final_diff", "ruling_conflict",
)


# ── 参数键 ───────────────────────────────────────────────────────────

def fold_admit_params(params: dict | None) -> dict | None:
    """一层参数 `{step_id: {字段: 值}}` 里收尾的两个键并成**现在生效的那个**（`ADMIT_STEP_ACTIVE`）。

    - 没写 `char_decide` 键 → 原对象原样返回（逐字节不变，旧册配置零影响）；
    - 只写了 `char_decide` → 搬到生效名下（不改入参）；
    - **两个键同时有 → ValueError**（不猜谁生效；值一样也报，逼着只留一处）。
    """
    if not isinstance(params, dict):
        return params
    present = [k for k in ADMIT_STEPS if k in params]
    if len(present) < 2 and (not present or present[0] == ADMIT_STEP_ACTIVE):
        return params
    if len(present) == 2:
        raise ValueError(
            f"参数里 {NEW_ADMIT_STEP}: 与 {LEGACY_ADMIT_STEP}: 同时写了：收尾步已改名 {NEW_ADMIT_STEP}，"
            f"同一层只留一处（过渡期两个键都认，但不许并存）")
    out = {k: v for k, v in params.items() if k not in ADMIT_STEPS}
    out[ADMIT_STEP_ACTIVE] = params[present[0]]
    return out


def admit_params_of(params: dict | None) -> dict | None:
    """读一层参数里收尾那一项（两个键都认，先 `char_decide` 后 `seed_admit`；并存报错）。没写 → None。"""
    folded = fold_admit_params(params)
    return folded.get(ADMIT_STEP_ACTIVE) if isinstance(folded, dict) else None


# ── 产物目录与页 JSON ────────────────────────────────────────────────

def final_page_dict(doc: dict, strict: bool = True) -> dict:
    """`products/<册>/<收尾步>/pNNNN.json` 读出来的整份 JSON → 收尾那一页的原始 dict（新键优先，旧键兜底）。

    两个键都在 → 取新键（以 `char_decide` 为准）。两个键都没有：`strict` 抛 KeyError（同原来 `doc["seed_admit"]`）；
    `strict=False` 当调用方传的已经是页内层，原样返回（原来 `page_doc.get("seed_admit", page_doc)` 的写法）。"""
    for k in ADMIT_STEPS:
        if k in doc:
            return doc[k]
    if strict:
        raise KeyError(f"页 JSON 里没有 {NEW_ADMIT_STEP}／{LEGACY_ADMIT_STEP} 键")
    return doc


def final_dirs(products_root: str | Path, book: str) -> list[Path]:
    """这册书实际存在的收尾产物目录，新名在前（两个都存在时 `final_dir` 只认第一个）。"""
    base = Path(products_root) / book
    return [base / s for s in ADMIT_STEPS if (base / s).is_dir()]


def final_dir(products_root: str | Path, book: str) -> Path | None:
    """读收尾产物该进哪个目录：`char_decide/` 在就用它，否则 `seed_admit/`；都没有 → None。
    **新旧并存时以 `char_decide/` 为准**，`seed_admit/` 只在没有新目录时读（`guji-cv status` 对并存另给警告）。"""
    ds = final_dirs(products_root, book)
    return ds[0] if ds else None


def both_dirs_exist(products_root: str | Path, book: str) -> bool:
    """新旧目录并存（迁移做了一半或旧残留）：status 据此警告。"""
    return len(final_dirs(products_root, book)) == 2
