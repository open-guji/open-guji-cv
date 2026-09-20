# -*- coding: utf-8 -*-
"""问题登记表 —— 「对这个对象问什么」的唯一真源。

## 为什么要有这张表

此前「一次裁决属于哪一类」是靠三样东西拼出来的：`kind`（受控枚举）、
卡片 id 前缀（`head:` / `outer:` / `cols:`）、以及 `payload.v` 之类的二级字段。
三者都不是为分类设计的，于是同一个 `kind` 承载了不同语义：

- `verdict` + `border_detect` 一条路由通吃 cols / head / outer 三个问题，
  三种答案枚举（ok|miss|extra、yes|no、ok|in|out|none）落进同一个分片——
  实测 70 条 head 的 yes/no 混在 column-split 的 ok/miss/extra 里（2026-09-18 已修）；
- `border_class` 既是页级卡的答案、又是列清理台上下两端的答案，
  而上下端其实是**两个独立的问题**；
- `confirm` 靠 `payload.v` 在消费器里二次分流成「定字」与「切分缺陷」两件事。

**一个 `question` = 一个问题**：问谁（unit）、答什么（答案类型与枚举）、
落哪个金标分片。`kind` 退化成传输层的粗分类，不再承担语义。

## 这张表管什么、不管什么

**管**（声明式，是数据不是代码）：答案枚举、金标分片、从 payload 取哪些键。

**不管**：那些靠踩坑换来的转换规则——`n_raised` 只在 `raised == "yes"` 时
才有意义、下版框要以 `y_left_abs` 为准而非相对坐标、`char_*` 在 2026-09-13
之前存的其实是 `shape`。这些留在 `consumers._expected_of` 里，连同解释它们
存在理由的注释一起。**硬把它们塞进数据结构会丢掉「为什么」**，而那恰恰是
这些规则唯一的价值。

## 命名法

    <step>.<对象>.<问什么>

`<step>` 是产出该对象的 Step id，`<对象>` 是 unit（page/column/cell/boundary），
`<问什么>` 用小写下划线。见《计划书-控制台四板块统一》§2.2。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Question:
    """一个问题。`id` 是唯一键，前端随裁决发 `payload.question`。"""

    id: str
    unit: str                       # page | column | cell | boundary
    shard: str | None               # 落哪个金标分片；None = 不进金标（如只进 glyph.db）
    title: str                      # 一句话：问的是什么
    answers: tuple[str, ...] = ()   # 受控答案；空 = 非枚举（坐标/整数/复合）
    kind: str = "verdict"           # 传输层 kind，保持与既有事件链路兼容
    expected_keys: tuple[str, ...] = ()
    """从 payload 取哪些键进 `expected`。空 = 由 `_expected_of` 的专用分支处理
    （那些带特殊规则的，见模块头「不管什么」）。"""
    note: str = ""


#: 已知问题。**新增裁决台必须先在这里登记**，否则路由无从分流。
QUESTIONS: tuple[Question, ...] = (
    # ── Step1 边框界行 ───────────────────────────────────────────
    Question(
        id="border_detect.page.vline_on_seam", unit="page",
        shard="border-detection/column-split",
        title="界行是不是都落在字缝上",
        answers=("ok", "miss", "extra", "idk"),
        expected_keys=("verdict",),
    ),
    Question(
        id="border_detect.page.has_head_raise", unit="page",
        shard="border-detection/head-raise-presence",
        title="这一页有没有抬头（版框线本身有台阶）",
        answers=("yes", "no", "idk"),
        expected_keys=("verdict",),
        note="量的是 Step1 `detect_head_raise()` 的召回率，所以卡上**不叠**算法结果"
             "——印了机器判断人就会顺着点。与列级的 head_raise 是粗细两档，锚点"
             "粒度不同（页 vs 列），不能塞一个分片。",
    ),
    Question(
        id="border_detect.page.outer_edge", unit="page",
        shard="border-detection/outer-edge",
        title="外框最外沿那条线的位置准不准",
        answers=("ok", "in", "out", "none", "idk"),
        expected_keys=("verdict",),
    ),
    Question(
        id="border_bottom.page.offset_y", unit="page",
        shard="border-detection/bottom-offset",
        title="整页下版框该在哪（两端各一个 y）",
        kind="border_offset",
        note="坐标以 `y_left_abs`/`y_right_abs`（原图绝对坐标）为准，"
             "取键规则见 `_expected_of`。",
    ),

    # ── Step2 单列射影 ───────────────────────────────────────────
    Question(
        id="column_warp.column.side_band", unit="column",
        shard="char-segmentation/column-warp",
        title="左右文字带切得对不对",
        answers=("clean", "eat", "mixed", "idk"),
        kind="band",
        expected_keys=("band",),
    ),
    Question(
        id="column_warp.column.end_class_top", unit="column",
        shard="char-segmentation/column-warp",
        title="列图上端的框墨形态",
        answers=("clean", "none", "glued", "idk"),
        kind="border_class",
        expected_keys=("top_class",),
    ),
    Question(
        id="column_warp.column.end_class_bottom", unit="column",
        shard="char-segmentation/column-warp",
        title="列图下端的框墨形态",
        answers=("clean", "none", "glued", "idk"),
        kind="border_class",
        expected_keys=("bot_class",),
    ),
    Question(
        id="column_warp.page.border_class", unit="page",
        shard="char-segmentation/column-warp",
        title="单列矫正·上下版框核校（一卡一端）",
        answers=("clean", "glued", "none", "idk"),
        kind="border_class",
        expected_keys=("border_class",),
    ),

    # ── Step3 逐字切分 ───────────────────────────────────────────
    Question(
        id="row_segment.boundary.cut_y", unit="boundary",
        shard="char-segmentation/touching-cuts",
        title="这条格线该切在哪",
        kind="cutline",
        note="答案是坐标 + 切法，取键见 `_expected_of` 的 CUTLINE_KEYS。"
             "`payload.tags∋border` 时另有一路进 side-rule 分片。",
    ),
    Question(
        id="row_segment.column.n_body_slots", unit="column",
        shard="char-segmentation/column-slots",
        title="这一列实际有几个正文字格",
        kind="n_body_slots",
        expected_keys=("n_slots",),
        note="版式常量在个别列不成立时的覆盖。没有可靠的纯信号判据——"
             "格高/period 比值两个方向都有假阳性/假阴性，只能人裁。",
    ),
    Question(
        id="row_segment.column.head_raise", unit="column",
        shard="char-segmentation/head-raise-columns",
        title="列级抬头精标（是否抬头 / 几格 / 首字有没有被切）",
        kind="head_raise",
        note="`n_raised` 只在 `raised == 'yes'` 时写入，见 `_expected_of`。",
    ),

    # ── Step8 落库反馈 ───────────────────────────────────────────
    Question(
        id="seed_admit.cell.is_char", unit="cell",
        shard=None,
        title="这一格是不是这个字（定字）",
        kind="confirm",
        note="不进金标分片，直接进 glyph.db（`glyphdb_admit` 消费者）。"
             "与下面的 seg_quality 是**两件事**：前者答「这是什么字」，"
             "后者答「这块图能不能用」，同一批事件同时喂给两个消费者、各取所需。",
    ),
    Question(
        id="seed_admit.cell.seg_quality", unit="cell",
        shard="char-segmentation/instances",
        title="这块图切得干不干净",
        answers=("clean", "truncated", "contaminated", "not_text"),
        kind="confirm",
        note="走 `payload.v == 'seg_defect'` 进来，取键见 `_expected_of`。",
    ),
    Question(
        id="seed_admit.cell.damaged", unit="cell",
        shard="char-segmentation/instances",
        title="原图破损、字形不可辨（最像哪个字）",
        answers=("damaged",),
        kind="confirm",
        note="走 `payload.v == 'damaged'` 进来，payload 另带 `guess`（最像的那个字，"
             "可空）。与 `seg_quality` 的四档是**两件事**：那四档归因于切分/取块，"
             "这一档归因于**原刻就残**，切分再准也救不回来，所以 quality 独立成第五档、"
             "不混进 contaminated。不进字形库（形都不全，当刻例会把破损形钉死成那个字）；"
             "文本层出 `□`，`guess` 只作括注 `□（？塊）`。",
    ),
)

BY_ID: dict[str, Question] = {q.id: q for q in QUESTIONS}


def get(qid: str | None) -> Question | None:
    return BY_ID.get(qid) if qid else None


def shard_of(qid: str | None) -> str | None:
    q = get(qid)
    return q.shard if q else None


def validate(qid: str, answer: str) -> bool:
    """答案在不在该问题的受控枚举里。非枚举问题（坐标/整数）一律放行。"""
    q = get(qid)
    if q is None:
        return False
    return True if not q.answers else answer in q.answers


def default_batch(book: str, qid: str | None = None, variant: str = "",
                  kind: str | None = None) -> str:
    """这次裁决默认记到哪个批次。

    ## 形状

        <book>-<step 段>[-<variant>]

    `step 段` 取自 question id 的第一段（`row_segment.boundary.cut_y` → `row_segment`）；
    `qid` 给不出时用 `kind` 兜底。`variant` 给同一步下需要分账的批次用
    （如切线的 `blocking` 与全量分开记）。

    ## **不带日期**

    计划书原稿写的是 `<book>-<step>-<yyyymmdd>`，**实测否掉了**：
    「读回本批已裁」是按批次名查的，批次名一天一换，跨天就读不回昨天的裁决
    ——人刷新页面会看到自己裁过的卡重新变成未裁。bxgb 实测 cutline 的裁决
    横跨 2026-09-16/17/18 三天却在同一批次里，按日期切会被打散成 3 个。
    同型事故 `ColumnReviewPanel` 那条注释记过一次（批次名带页范围，同一批
    裁决分到两个批次，读回失灵）。

    ## 为什么是「默认值」而不是强制

    多数面板允许人手填批次名（`batchInput.trim() || 默认值`），那是有用的
    ——分轮次、分标注人时要能自己开一批。这里统一的是**默认值的算法**，
    不是剥夺覆盖能力。

    ## ⚠️ 现有 11 处前端**不要**改用这个（2026-09-18 实测结论）

    计划书 §2.2(3) 原本要「11 处前端硬编码删除」，改造前先量了一遍代价：
    bxgb 的 10 个批次会**全部改名、1149 条裁决读不回**；更糟的是新规则把
    `bxgb-cutline` / `bxgb-cutline-blocking` / `bxgb-slotcount-*` 合并成
    同一个 `bxgb-row_segment`，**分账信息丢失**——而那三批本就是按用途分开记的。

    根因是计划书那条假设错了：批次的实际分界不是「哪个 step」，而是
    「哪一轮、哪个台、什么范围」，这是**人的组织方式**，不该由 step 推导。
    所以本函数只作为**新增裁决台的默认值**；存量台保持原名不动。
    真要统一，得先有批次别名/迁移机制，那是另一件事。
    """
    seg = (qid or "").split(".")[0] if qid else (kind or "review")
    parts = [book, seg] + ([variant] if variant else [])
    return "-".join(p for p in parts if p)
