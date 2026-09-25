"""消费者：把事件落到该去的地方。

P1 只实现 `gold_add`（事件 → 金标条目），另外两个（glyphdb_admit / glyphdb_recrop）
先给出接口与显式的「未实现」，避免路由表里悄悄丢事件。

**幂等**：每个消费者只处理 `EventLog.pending(consumer)` 里的事件，处理完记账。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..gold.item import Anchor, GoldItem
from ..gold.store import GoldStore
from .events import Event, EventLog
from .routes import Destination, RouteTable
from ..utils.image_io import imread as cv_imread, imwrite as cv_imwrite


@dataclass
class ConsumeResult:
    consumer: str
    n_events: int = 0
    added: int = 0
    updated: int = 0
    skipped: int = 0
    no_lib: int = 0            # 正常裁决但按 no_glyph_lib 标志不建库的条数（非错误）
    errors: list[str] = None   # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []

    def to_dict(self) -> dict:
        return {"consumer": self.consumer, "events": self.n_events, "added": self.added,
                "updated": self.updated, "skipped": self.skipped, "no_lib": self.no_lib,
                "errors": self.errors}


# ── gold_add ─────────────────────────────────────────────────────────
#: 传输/审计用的元数据，**不属于金标内容**，一律不进 `expected`。
#: `question` 是路由分流用的（2026-09-18 加）；`client_ts`/`dwell_ms` 是量
#: 人裁耗时的（事件自己的 `ts` 是收割时间，量不出来）。
#: 走 `return p` 那条兜底分支的 kind（如 `n_body_slots`）会把 payload 原样
#: 透传，不剔掉的话这些键会混进金标——实测 `{"n_slots": 21, "question": ...}`。
_META_KEYS = ("question", "client_ts", "dwell_ms", "t")


def _expected_of(e: Event) -> dict:
    """事件 payload → 金标 expected。不同 kind 的金标内容不同。"""
    p = {k: v for k, v in e.payload.items() if k not in _META_KEYS}
    if e.kind == "verdict":
        return {"verdict": p.get("verdict")}
    if e.kind == "band":
        return {"band": p.get("band")}
    if e.kind == "border_class":
        # 上下端是**两个独立的问题**（列图上端框墨形态 / 下端框墨形态），
        # 列清理台一次裁两个，各自的答案在 `top_class` / `bot_class`。
        # 2026-09-18 之前这里只取 `border_class` 一个键，两个独立答案被整个丢掉
        # ——实测 bxgb column-warp 分片 31 条里 `top_class` 出现 0 次，
        # 全靠前端顺手多塞的拼接串 `"top=clean,bot=clean"` 兜住语义。那是巧合
        # 不是设计：串里 `bot=-` 表示「这一端没裁」，机器要靠解析字符串才知道。
        # 现在三个键都留：拼接串保持向后兼容（旧评测在读它），两个独立键是正解。
        # 阶段二拆成 `column_warp.column.end_class_top/bottom` 两个 question 之后，
        # 拼接串退役。
        out = {"border_class": p.get("border_class") or p.get("verdict")}
        for k in ("top_class", "bot_class"):
            if p.get(k):
                out[k] = p[k]
        return out
    if e.kind == "not_a_char":
        return {"quality": "not_text"}
    if e.kind == "confirm" and p.get("v") == "damaged":
        # 原图破损、字形不可辨（2026-09-19 用户定）。`quality="damaged"` 是
        # **第五档**，与既有四分类（clean / truncated / contaminated / not_text）
        # 并列：那四档说的是「切分/取块把图弄坏了」，这一档说的是**原刻就残**，
        # 切分再准也救不回来——归因不同，不能混进 contaminated。
        #
        # `guess` 是人看图后「最像的那个字」，可空。它**不是** `shape`：
        # shape 进字形库，guess 只进金标与文本层的括注 `□（？塊）`。
        # 形都不全，拿它当刻例会把破损形钉死成那个字（glyphdb_admit 本来就
        # 只认 v=="confirm"，这里再记一笔口径）。
        out: dict = {"quality": "damaged"}
        if p.get("guess"):
            out["guess"] = p["guess"]
        if p.get("note"):
            out["note"] = p["note"]
        return out
    if e.kind == "confirm" and p.get("v") == "seg_defect":
        # 切分缺陷：quality 沿用 char-segmentation/instances 的四分类
        # （clean / truncated / contaminated / not_text），不另造词。
        # 字形/文意若已填也一并留着——人看图时顺手认出的字不该丢。
        out = {"quality": p.get("quality") or "contaminated"}
        if p.get("defect"):
            out["defect"] = p["defect"]
        if p.get("shape"):
            out["shape"] = p["shape"]
        if p.get("reading"):
            out["reading"] = p["reading"]
        # `note` 要留住（2026-09-06）：四分类只说「这块图脏」，说不出**怎么脏**。
        # 夹注段卡标的缺陷（少格 / 多格 / ab 分错边）全靠它区分——丢了这一行，
        # 金标里就只剩一个 contaminated，将来没法按缺陷类型归因，也没法回查是哪一段。
        if p.get("note"):
            out["note"] = p["note"]
        return out
    if e.kind == "recrop":
        return {"old_bbox": p.get("old_bbox"), "corrected_bbox": p.get("new_bbox") or p.get("corrected_bbox")}
    if e.kind == "cutline":
        # 粘连格线的理想切点。verdict：moved（拖到 y）/ ok（现切点就对，y == y_old）/
        # overlap（上下字重叠，切在哪都伤字，y 是折中位置）/ idk（拿不准 → uncertain）。
        # 坐标是现役 Step2 列图（col_h 一并记，换了矫正就能察觉）。
        # tags：干扰因素（stain 污点在分界处 / border 界行或版框压进裁片 / residue 邻字残墨 / other），
        # 用户 2026-09-05 裁完第一批点名的两类特殊情况；评测里分开报，不混进像素误差。
        # polyline：折线模式下人点的点 [[x, y], …]（列图坐标）；y 仍是折线的平均高，直线口径的评测照用。
        # cand：verdict == "cand" 时**算法候选里被人选中的那一种**（straight / seam_narrow /
        # seam_wide）。这是攒给下游打分函数的样本——哪条缝被人看上了，比 y 更能说明问题
        # （2026-09-10）。
        # char_above/below：**整理本读法**（v2_align 的 `reading`）。
        # shape_above/below：v2 定字认的刻本形（`shape`）。两者不同即一次转换。
        # ⚠️ 2026-09-13 之前 `char_*` 存进来的其实是 `shape`（卡片取错了字段，
        # 标签却写着「整理本期望」）——那之前的历史事件里 `char_*` 要按 shape
        # 理解，且没有 `shape_*` 位。回读老金标做统计时别把两段混着算。
        return {k: p[k] for k in CUTLINE_KEYS if k in p and p[k] not in (None, "", [])}
    if e.kind == "border_offset":
        # 整页下版框坐标金标（`page_bottom_cards`）。verdict：moved（两端
        # 拖到 y_left/y_right）/ ok（现役线位置就对，等于 c.y_left/y_right）/
        # no_line（这页版框太淡看不出线）。两端各自可调（2026-09-12 改，
        # 起初只给整体平移，改不了现役斜率本身探错的情况）——两点坐标带
        # 齐斜率信息，不是单一偏移量。
        #
        # ⚠️ **以 `y_left_abs`/`y_right_abs`（原图绝对坐标）为准**
        # （用户 2026-09-13 定："坐标应该只基于原始图片"）。`y_left`/`y_right`
        # 是相对通栏带 `crop_top` 的，而 crop_top 由**算法输出**算出来——算法
        # 一改，历史金标的绝对位置就整体漂移：vol02/161 实测偏 83.2px（标注
        # 之后加了 `_fix_wild_angle` 角度护栏，恰好改动了该页下版框），人标
        # 对的线被换算到纯白处。同一个坑 09-12 那批已经栽过一次。相对坐标
        # 与 crop_top 仍一并存下，只为排查历史问题，**不要拿它当基准**。
        keys = ("y_left", "y_right", "y_left_abs", "y_right_abs", "crop_top", "verdict")
        return {k: p[k] for k in keys if k in p and p[k] not in (None, "")}
    if e.kind == "head_raise":
        # 列级抬头精标（overview `Step3-逐字切分/03-抬头综合优化.md`）。三件事
        # 一张卡：`raised` 这一列是不是抬头 / `n_raised` 抬高几格 / `head_cut`
        # 首字有没有被切掉。
        #
        # **`head_cut` 不是抬头的属性**，是顺带收的丢字维度：vol02 p11 c4/c5
        # 的首字「御」被 Step3 整个切在格外，而 Step9 渲染出来的文本读着通顺、
        # 不报阙文，**丢字在文本层完全看不见**，这是目前唯一能量到它的入口。
        # 别为它单开一轮标注。
        #
        # `n_raised` 只在 `raised == "yes"` 时有意义；判 no 的列不写这个键，
        # 免得金标里躺着一堆 `n_raised=0` 的假数据污染分布统计。
        keys = ("raised", "n_raised", "head_cut", "note")
        out = {k: p[k] for k in keys if k in p and p[k] not in (None, "")}
        if out.get("raised") != "yes":
            out.pop("n_raised", None)
        return out
    return p


def verdict_store() -> GoldStore:
    """`gold_add` 的默认落点：**workspace 的裁决表**（`core.workspace.verdicts_root()`），
    不是 open-guji-dataset。2026-09-13 用户裁定：运行时不写测试集仓；人裁先落
    workspace，`guji gold import` 显式挑一批进 dataset。消费者名字仍叫 gold_add
    ——改名会让 consumed/gold_add.jsonl 记账失效、全部事件重灌一遍。"""
    from ..core.workspace import verdicts_root
    return GoldStore(verdicts_root())


# 切线事件写进 touching-cuts 的全部键（正本在 gold/atomic.py，导入/导出也用它整组替换）。
from ..gold.atomic import CUTLINE_KEYS, merge_expected  # noqa: E402


def gold_add(events: list[tuple[Event, Destination]], store: GoldStore | None = None,
             why: str = "", dry_run: bool = False) -> ConsumeResult:
    store = store or verdict_store()
    res = ConsumeResult("gold_add", n_events=len(events))
    by_shard: dict[str, list[GoldItem]] = {}
    cutline_ids: dict[str, set[str]] = {}       # shard → 本批由切线事件产生的 item id
    for e, d in events:
        # `confirm` 事件同时路由给 glyphdb_admit 与这里：定字那部分归前者，
        # 切分缺陷那部分归这里。不分流的话，每条定字都会往 instances 金标里
        # 塞一条没有 quality 的空条目。
        if e.kind == "confirm" and e.payload.get("v") not in ("seg_defect", "damaged"):
            # `damaged`（原图破损）与 `seg_defect` 一样要落进 instances 金标：
            # 两者答的都是「这块图能不能用」，只是归因不同（原刻残 vs 切分坏）。
            res.skipped += 1
            continue
        if not d.shard:
            res.skipped += 1
            res.errors.append(f"{e.id}: 路由没给 shard")
            continue
        t = e.target
        expected = _expected_of(e)
        if e.kind == "cutline" and d.shard.endswith("/side-rule"):
            # 同一条切线事件路由到上游 side-rule 时，金标语义变成「这一格有界行残余」，
            # 不带切点字段（那是 touching-cuts 的事）。
            expected = {"side_rule": True, "note": e.payload.get("note") or "切线卡片：界行/版框压进裁片"}
        item = GoldItem(
            id=t.key,
            anchor=Anchor(book=t.book, page=t.page, col=t.col, slot=t.slot,
                          **(t.anchor or {})),
            expected=expected,
            label_origin="human" if e.actor == "user" else ("align" if e.actor == "align" else "model"),
            stratum=e.payload.get("stratum"),
            stratum_weight=e.payload.get("stratum_weight"),
            status="uncertain" if e.payload.get("verdict") in ("idk", "uncertain") else "active",
            source_events=[e.id],
        )
        if d.extra:
            item.input = {**item.input, **d.extra}
        by_shard.setdefault(d.shard, []).append(item)
        if e.kind == "cutline" and not d.shard.endswith("/side-rule"):
            cutline_ids.setdefault(d.shard, set()).add(item.id)
    for shard, items in by_shard.items():
        if dry_run:
            # 试算要和真消费口径一致：内容相同的不算「更新」，否则试算说会改 2 条、
            # 真跑却改 0 条，人会以为消费没生效。
            have = {i.id: i.expected for i in store.list(shard)}
            res.added += sum(1 for i in items if i.id not in have)
            res.updated += sum(1 for i in items
                               if i.id in have and have[i.id] != i.expected)
            continue
        # ⚠️ **合并 expected，不整体替换**（2026-09-04）。
        #
        # 同一个字位可能既有 v1 时代的金标（带 review_verdict / layout /
        # defect / healed 等字段），又有新的人裁事件。人裁说的只是「切分
        # 质量是 truncated 还是 clean」，凭什么把别人记的字段一起抹掉？
        # 实测：vol01:22:9:2 被人裁事件覆盖后，v1 的四个字段全没了，
        # `verify_gold_migration` 当成数据丢失报错——**报得对**。
        #
        # 所以按 id 取回旧 expected 打底，新值覆盖同名键，其余保留。
        prev = {i.id: i for i in store.list(shard)}
        for it in items:
            old = prev.get(it.id)
            if old is None:
                continue
            # 切线重裁：旧判定的几何字段**整组丢掉**，只保留非切线的遗留字段
            # （gold/atomic.py；2026-09-14 实锤：drift 重标改判 ok 的事件不带 polyline，
            # 旧坐标系折线原样留在 expected 里——评测优先读折线，等于金标没修。24 条）。
            it.expected = merge_expected(shard, old.expected, it.expected,
                                         atomic=it.id in cutline_ids.get(shard, ()))
            # `input` 同理：v1 条目把 seed / 载体信息记在这里，人裁事件不带
            # 这些字段，直接写就会把它们清空（upsert 是整体替换）。
            it.input = {**(old.input or {}), **(it.input or {})}
        a, u = store.upsert(shard, items, why or "由人裁事件自动落入")
        res.added += a
        res.updated += u
    return res


# ── 未实现的两个（显式报错，不静默吞事件）───────────────────────────
def glyphdb_admit(events, db_path: str | None = None,
                  dry_run: bool = False, binarize: bool = True, **kw) -> ConsumeResult:
    """`confirm` 事件 → GlyphDB 进库（2026-09-04 接入，此前是桩）。

    这是审查闭环的最后一环：控制台裁决 → Event → 路由 → 这里写库。
    此前只能手动跑 `seed-ingest`，人裁结果与控制台脱节。

    ## 字形 / 释读分开写（用户 2026-09-04 定）

    「碰到已/巳、人/入 这类，先读字形，但是文本录入要按文意录（最好能记录
    这个转换）」。事件 payload 因此带两个值：

    - `shape`：图上刻的形 → `admit_instance(shape=...)`，进 `glyphs` /
      `exemplars` / `GlyphMatcher` 的**字形索引**；
    - `reading`：文意读法 → `admit_instance(char=...)`，进 `admissions.char`
      与 `instances.semantic`。

    两者不同就是一次转换（`conversion=1`）。**字形永远照录**，连已/巳 也不
    例外——字形层的 near_form 护栏本来就是防「形状判据自己会认错」，字形库
    要是被释读污染，将来一个真刻成这形状、该读别的字的实例会错误继承这次的
    释读，字形匹配整条链就失真（charset_and_lm.md §四的实锤）。

    `not_a_char` / `skip` / `damaged` 事件不进库（判非字 / 存疑跳过 / 原图破损
    认不出）。三者都靠 `payload.v != "confirm"` 被下面那句过滤挡在外面。
    图块从 v2 的 `char_patch` 缓存取——那正是被裁决的那张图。

    ## `no_glyph_lib`：选字正常裁决，但这张图不建库（2026-09-09）

    字形有些无法修复的噪声（污墨、裂纹等），人仍能认出字、正常选字，但**这张
    图不该进字形匹配索引**——写进去等于让污染样本参与以后所有形近字的比对。
    审查卡片上勾了这个复选框的事件带 `no_glyph_lib=true`：照常算已裁决（不
    进 `res.skipped`/`res.errors`，不是错误），只是跳过 `admit_instance` 这
    一步，不落 `glyphs`/`exemplars`/matcher 索引。

    ## ⚠️ v2 的 id 必须加前缀，否则会污染 15332 条已有记录

    v1 的 `book:page:col:idx`（idx 从 0、含 margin 格）与 v2 的
    `book:page:col:slot`（slot 从 1）**长得一模一样但指的不是同一格**。
    实测 vol01/24 c1：库里 `vol01:24:1:2` 是「每」，v2 的 `1:2` 是「書」，
    整体差一格——170 个同 id 命中里 **0 个一致**。不隔离就是把 v1 的记录
    按 v2 的口径改写。所以 v2 事件一律以 `v2:` 开头存库，跟 v1 分居两个
    命名空间；将来要合并得先做真正的重键（阶段 B2），不是靠巧合对齐。
    """
    res = ConsumeResult("glyphdb_admit", n_events=len(events))
    admits = [(e, d) for e, d in events
              if e.kind == "confirm" and (e.payload.get("v") or "confirm") == "confirm"]
    res.skipped = len(events) - len(admits)
    if not admits:
        return res
    if dry_run:
        res.added = len(admits)
        return res

    from ..clustering.glyph_db import GlyphDB
    from ..core.workspace import glyph_db_path
    from ..products.cache import ImageCache
    from ..utils.binarized import binarize_page
    import cv2

    db = GlyphDB(str(glyph_db_path(db_path)))
    cache = ImageCache()
    for e, _dest in admits:
        shape = e.payload.get("shape") or e.payload.get("char")
        reading = e.payload.get("reading") or shape
        # 只有 己/已/巳 分字形与文意（用户 2026-09-04 定；审查页与组视图同规则）。
        # 其它字的 reading 一律跟随 shape——旧组视图曾对所有组填整理本字当文意
        # （「卽 读 即」×45），那批事件已清账，这里再守一道免得任何来源重犯。
        if shape and shape not in ("己", "已", "巳"):
            reading = shape
        if reading and (len(reading) != 1 or ord(reading) < 0x2E80):
            reading = shape                 # 拼音首字母那类（输入法没转）
        if not shape:
            res.errors.append(f"{e.target.key}: 事件没有字形，跳过")
            res.skipped += 1
            continue
        if e.payload.get("no_glyph_lib"):
            res.no_lib += 1
            continue
        book = e.target.book or (e.target.key.split(":")[0] if ":" in e.target.key else "")
        # 图块键：p{page}c{col}s{slot}[a|b]，与 Step4 落缓存时一致
        try:
            _b, pg, col, slot = e.target.key.split(":")
            sub = ""
            if slot and slot[-1] in "ab":
                slot, sub = slot[:-1], slot[-1]
            ckey = f"p{int(pg):04d}c{int(col):02d}s{int(slot)}{sub}"
        except Exception as exc:
            res.errors.append(f"{e.target.key}: 键解析不了（{exc}）")
            res.skipped += 1
            continue
        path = cache.get(book, "char_patch", ckey)
        if path is None:
            res.errors.append(f"{e.target.key}: 缓存里没有字块 {ckey}")
            res.skipped += 1
            continue
        img = cv_imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            res.errors.append(f"{e.target.key}: 图块读不出来")
            res.skipped += 1
            continue
        # **进库的一定是二值的**（用户 2026-09-16）：字块缓存存的是灰度裁片，
        # 灰度值会干扰后续比对，而且「用哪把尺子二值化」一路推迟到每次读取
        # （`_unpng` 固定阈 128 / `normalize_patch` Sauvola，两处可能不一致）。
        # 与播种（`seed_witness`）和整页副本（`utils/binarized`）**共用同一个
        # 二值化**，保证库里那张 = 人裁看到那张 = 播种进去那张。
        if binarize:
            # ⚠️ `edge_margin=0`（2026-09-19）。`binarize_page` 是给**整页**用的，2026-09-17 起
            # 最外 20px 强制判纸（挡扫描纸缘的浅灰渐变）；字块只有 64×88 上下，套上去等于
            # 把四边各 20px 的笔画全抹掉，只剩中间一小块。后果：09-18/19 入库的 405 条人裁
            # 刻例 canonical 里字高只有画布 0.12（正常 0.26）、归一后笔画断成碎片，拿字位
            # 自己的图块去查库，自身相似度中位 0.43、99% 低于 0.7——人裁 7 次的「宐」在
            # 候选里根本不出现，用户反映「很多字反复审了很多遍」。整页与字块共用同一把
            # Sauvola 尺子这条纪律不变，只是纸缘留白不属于字块。
            img = binarize_page(img, edge_margin=0)
        # v2 命名空间：见上面「id 必须加前缀」那节
        db_id = e.target.key if e.target.key.startswith("v2:") else f"v2:{e.target.key}"
        # 人裁改判要压过旧的人裁（2026-09-07）。admit_instance 的幂等闸只认主键：
        # 第一次裁 巳、后来改判 已，第二个事件被闸掉，库里永远是 巳——seed_admit 的
        # 人裁通道读库就跟着错，判据 E 报「存 巳 人裁 已」（29:4:19、80:5:7；更早
        # 蠹、32:7:10 也是它）。所以：库里已有**人裁**记录且字形或释读不同 → 撤旧再进。
        # 机器进的（provenance 非 human）本来就该被人裁覆盖，同样撤。
        prev = db.conn.execute(
            "SELECT a.provenance, a.char, g.char FROM admissions a "
            "  LEFT JOIN exemplars e ON e.instance_id = a.instance_id "
            "  LEFT JOIN glyphs g ON g.glyph_id = e.glyph_id "
            " WHERE a.instance_id = ?", (db_id,)).fetchone()
        if prev is not None and (prev[2] != shape or prev[1] != reading):
            from ..clustering.audit import evict_instance
            evict_instance(db, db_id)
            res.updated += 1
        # 同一格的机器副本（2026-09-25）：播种按 `<book>:p:c:s` 进库，人裁按
        # `v2:<book>:p:c:s` 进库，两者都是 v2 slot 坐标、是同一格。人裁到了就撤
        # 机器那份——不撤的话，人改判后机器那份带着旧字继续当刻例（北行实测已有
        # 17 格两份并存，碰巧都同字）。v1 来源（四庫 vol01 的 idx 坐标）同名不同格，不动。
        twin = db_id[3:]
        twin_src = twin.split(":", 1)[0]
        if db.conn.execute(
                "SELECT 1 FROM admissions a JOIN instances i USING(instance_id) "
                "  LEFT JOIN sources s ON s.source_id = i.source_id "
                " WHERE a.instance_id = ? AND a.provenance NOT LIKE 'human%' "
                "   AND COALESCE(s.pipeline_version, '') != 'v1'",
                (twin,)).fetchone() and twin_src != "v2":
            from ..clustering.audit import evict_instance
            evict_instance(db, twin)
            res.updated += 1
        ok = db.admit_instance(
            db_id, reading, cv2.imencode(".png", img)[1].tobytes(),
            provenance="human", shape=shape,
            evidence={"event": e.id, "batch": e.batch,
                      "conversion": bool(e.payload.get("conversion")),
                      "shape": shape, "reading": reading},
            page=str(e.target.page or ""), col=int(e.target.col or 0),
            idx=int(e.target.slot or 0))
        if ok:
            res.added += 1
            # v1 来源（四庫 vol01）的同一格在 idx = slot − 1 上，形状对得上才认（2026-09-25：
            # 四庫 177 格两份并存，其中 37 格 v1 标的字是错的）。机器那份撤掉，人裁的不动。
            from ..clustering.glyph_ledger import V1_TWIN_COV, v1_twin_id
            t = v1_twin_id(db_id)
            if t and t.split(":", 1)[0] != "v2":
                row = db.conn.execute(
                    "SELECT a.provenance FROM admissions a JOIN instances i USING(instance_id) "
                    "  JOIN sources s ON s.source_id = i.source_id "
                    " WHERE a.instance_id = ? AND s.pipeline_version = 'v1'", (t,)).fetchone()
                if row and not str(row[0]).startswith("human"):
                    from ..clustering.glyph_db import _unpng
                    from ..clustering.verify import verify_pair_elastic
                    n = dict(db.conn.execute(
                        "SELECT instance_id, data FROM derived WHERE kind='norm' "
                        "AND instance_id IN (?,?)", (db_id, t)))
                    if len(n) == 2 and verify_pair_elastic(
                            _unpng(n[db_id]), _unpng(n[t])).f1 >= V1_TWIN_COV:
                        from ..clustering.audit import evict_instance
                        evict_instance(db, t)
                        res.updated += 1
        else:
            res.skipped += 1        # admit_instance 的幂等闸：已进过库
    return res


def glyphdb_recrop(events, **kw) -> ConsumeResult:
    res = ConsumeResult("glyphdb_recrop", n_events=len(events), skipped=len(events))
    res.errors.append("glyphdb_recrop 尚未接入（P1 之后）：请照旧走 `seed-ingest` + build_recrop_shard.py")
    return res


def crop_exclude(events, list_path: str = "", dry_run: bool = False,
                 **kw) -> ConsumeResult:
    """`not_a_char` / `damaged` 事件 → 追加进 `config/crop_exclusions.jsonl`。
    `seg_defect` 自 2026-09-20 起**不进名单**（见下面那段注释：切坏与否交给 Step7 准入闸）。

    2026-09-05 补的缺口：此前人在卡片上点「有噪声」「字形不完整」「非字」，
    事件只落进 `char-segmentation/instances` 金标，**没有任何东西把它写进排除
    名单**——于是下一轮重跑，这一格照样出现在待审队列里，也没有闸拦着它将来
    进库。名单才是 `exclusions.py` 里那条「不进库也不出审查卡」的执行者。

    口径照 `exclusions.py` 模块头：**只追加不删除**（重扫之后按名单逐条复核），
    `origin="human"`（人眼实锤那一档，与 gate/pipeline-suspect 分开），
    `evidence` 记触发的判据（quality 与人顺手认出的字）。已在名单里的跳过。
    """
    import json
    from pathlib import Path

    from ..clustering.exclusions import default_path, load_exclusions

    res = ConsumeResult("crop_exclude", n_events=len(events))
    hits = []
    for e, _d in events:
        p = e.payload or {}
        if e.kind == "not_a_char" or (e.kind == "confirm" and p.get("v") == "not_a_char"):
            hits.append((e, "not_text", "not_a_char"))
        elif e.kind == "confirm" and p.get("v") == "damaged":
            # 原图破损、字形不可辨（2026-09-19 用户定）。这块图**永远**不该进字形库，
            # 也不该再出审查卡——人已经看过并了结了，与 `skip`（待办）相反。
            # `guess`（最像的那个字）只进金标与文本层的括注，不进库：形都不全，
            # 拿它当范本会把破损形钉成那个字的刻例。
            hits.append((e, "damaged", "damaged"))
        elif e.kind == "confirm" and p.get("v") == "seg_defect":
            # **seg_defect 不再进排除名单**（2026-09-20 用户定）。切坏/带残留的图块
            # 该不该进库，交给 Step7 准入闸判，名单只收「不是字」与「原刻残」。
            # 依据：bxgb 名单 131 条 seg_defect 全是真字（「舉手一揖」的 手），被 9.1
            # 当非字吃掉；复核后放出 127 条，准入闸自动放行 95 条**与整理本全一致**、
            # 挡下 32 条送人审——闸本来就分得开，名单在这里只是把真字藏起来。
            # 事件仍照常落 `char-segmentation/instances` 金标（quality 四分类给切分
            # 评测用），只是不再写这份名单。旧名单里的存量用
            # `scripts/apply_exclusion_recheck.py` 复核后撤。
            # （此前这里还挡 quality=="clean"——Step4 随机层把 clean 也当一档裁决，
            # 2026-09-11/12 曾把 clean 写进名单；现在整档不写，那条护栏一并失效。）
            continue
    res.skipped = len(events) - len(hits)
    if not hits:
        return res
    path = Path(list_path) if list_path else default_path()
    known = set(load_exclusions(path))
    rows = []
    for e, quality, reason in hits:
        iid = e.target.key
        if iid in known:
            res.skipped += 1
            continue
        known.add(iid)
        ev = [quality]
        p = e.payload or {}
        if p.get("shape"):
            ev.append(f"shape={p['shape']}")
        note = f"审查卡片人裁：{quality}"
        if reason == "damaged":
            # `guess` 进名单（不只进金标）：seed_admit 读的是名单，文本层要据此
            # 渲成 `□（？塊）`。存成 `guess=塊` 这种形状而不是塞进 shape——
            # 名单的 evidence 是给人看的账，shape 那个键别的地方当「进库字形」用。
            if p.get("guess"):
                ev.append(f"guess={p['guess']}")
                note = f"审查卡片人裁：原图破损，最像「{p['guess']}」"
            else:
                note = "审查卡片人裁：原图破损，认不出"
        rows.append({
            "date": (e.ts or "")[:10],
            "evidence": ev,
            "instance_id": iid,
            "note": note,
            "origin": "human",
            "reason": reason,
            "round": "r2",
            "source_event": e.id,
        })
    if dry_run:
        res.added = len(rows)
        return res
    if rows:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
        load_exclusions.cache_clear()
    res.added = len(rows)
    return res


def product_invalidate(events, product_store=None, dry_run: bool = False, **kw) -> ConsumeResult:
    """人裁落定 → 该页的某步产物显式失效（`ManifestEntry.invalidated`），引擎据此
    标 stale、下次跑批重算，下游沿 DAG 跟着过期。

    路由 `extra.step` 指定失效哪一步（cutline → row_segment）。只标不跑。
    没跑过的页（manifest 里没条目）算 skipped，不是错。

    ⚠️ 新接到既有路由上时，历史事件对这个消费者全是 pending——首次会把所有裁过的
    页一起标失效（vol02 就是 160 页 Step3 及下游）。要不追溯就先把历史事件对
    `product_invalidate` 记账（`guji events route --dry-run` 先看数）。
    """
    from ..core.spec import page_key
    from ..products.store import ProductStore

    st = product_store or ProductStore()
    res = ConsumeResult("product_invalidate", n_events=len(events))
    done: set[tuple[str, str, str]] = set()
    for e, d in events:
        step = (d.extra or {}).get("step")
        t = e.target
        book, page = t.book, t.page
        if (book is None or page is None) and t.unit == "cell":
            # 从 key 反解（2026-09-21）：写入方**多半不填** `book`/`page`——bxgb 实测
            # 1,558 条 cell 事件里 822 条（53%）两个字段都是 None，而 `key` 一直是
            # 完整的 `<book>:<页>:<列>:<格>`。`decided_cells` 早就为同一件事按 key
            # 前缀兜底了，这里没兜，于是过半的人裁**不触发产物失效**：裁决进了库，
            # seed_admit 不知道，待审列表照旧端出那张卡（09-20 报的「裁完再载入还在」
            # 就是这条路由缺席，补上路由之后又被这半数空字段挡掉一半）。
            parts = (t.key or "").split(":")
            if len(parts) >= 3 and parts[1].isdigit():
                book = book or parts[0]
                page = page if page is not None else int(parts[1])
        if not step or book is None or page is None:
            res.skipped += 1
            res.errors.append(f"{e.id}: 路由没给 extra.step，或事件没 book/page 且 key {t.key!r} 反解不出")
            continue
        key = (book, step, page_key(page))
        if key in done:
            continue
        done.add(key)
        if dry_run:
            res.added += 1
            continue
        if st.manifest(book, step).invalidate(key[2], f"人裁 {e.kind} {e.id}"):
            res.added += 1
        else:
            res.skipped += 1
    return res


CONSUMERS = {
    "gold_add": gold_add,
    "glyphdb_admit": glyphdb_admit,
    "glyphdb_recrop": glyphdb_recrop,
    "crop_exclude": crop_exclude,
    "product_invalidate": product_invalidate,
}

# Step8 复核裁决的三个出口（见 feedback/collate_consumers.py 模块头）。
# 单独一个模块、在这里并进来：它们回答的是「我们和证人谁对」，
# 与上面那批「这是什么字」不是一类，但走同一套路由与记账。
from .collate_consumers import COLLATE_CONSUMERS  # noqa: E402
CONSUMERS.update(COLLATE_CONSUMERS)

# 字形库体检裁决（2026-09-25，字形库 03）：问的是「库里这个刻例定的字对不对」。
from .glyph_audit import GLYPH_AUDIT_CONSUMERS  # noqa: E402
CONSUMERS.update(GLYPH_AUDIT_CONSUMERS)


def route_and_consume(log: EventLog, batch: str | None = None,
                      table: RouteTable | None = None,
                      store: GoldStore | None = None,
                      dry_run: bool = False, event_ids: set[str] | None = None,
                      **consumer_kw) -> dict:
    """把未消费的事件按路由表分发给各消费者；成功的记账。

    `consumer_kw` 透传给消费者（如 `glyphdb_admit` 的 `db_path`）——测试要
    指向库副本，别动真库。

    `event_ids`：只看这几条事件（控制台「写完直接消费」只该消费刚写进来的那几条）。
    2026-09-26 实测：不限定时，每存一条切线都把整批 419 条 × 12 个消费者重新过一遍
    路由表（11.5 万次规则匹配）、再各读一遍 MB 级的记账文件，一次保存 1–2 秒。
    路由结果按事件缓存，每条只算一次（原来每个消费者各算一遍）。"""
    table = table or RouteTable.load(log.root / "routes.yaml")
    results: list[ConsumeResult] = []
    evs_all = log.read(batch) if batch else sorted(log.iter_all(), key=lambda e: e.order)
    if event_ids is not None:
        evs_all = [e for e in evs_all if e.id in event_ids]
    dests = {e.id: table.destinations(e) for e in evs_all}
    for consumer, fn in CONSUMERS.items():
        mine = [e for e in evs_all if any(d.consumer == consumer for d in dests[e.id])]
        if not mine:
            continue
        done = log.consumed_ids(consumer)
        pairs = [(e, d) for e in mine if e.id not in done for d in dests[e.id] if d.consumer == consumer]
        if not pairs:
            continue
        res = (fn(pairs, store=store, dry_run=dry_run) if consumer == "gold_add"
               else fn(pairs, dry_run=dry_run, **consumer_kw))
        results.append(res)
        if not dry_run and not res.errors:
            # ⚠️ 一个事件命中同一消费者的多条路由（如 cutline+border 同时进
            # touching-cuts 与 side-rule，两条去向都是 gold_add）时，`pairs`
            # 里同一个事件会出现两次——`consumed/<consumer>.jsonl` 因此被
            # 写两行。`consumed_ids()` 用 set 收，不影响幂等判定，但账本本身
            # 失真（2026-09-10 金标对账道实测：`consumed/gold_add.jsonl` 里
            # `evt_vol02-cutline_000032`/`000042` 各记了两次，是「事件数 507
            # vs gold_add 记账 509」这 2 条差值的全部来源）。按事件 id 去重
            # 再记账，金标本身（各分片各写一条）不受影响。
            seen: dict[str, Event] = {}
            for e, _ in pairs:
                seen.setdefault(e.id, e)
            log.mark_consumed(consumer, seen.values(), note=batch or "")
    return {"batch": batch, "dry_run": dry_run,
            "results": [r.to_dict() for r in results],
            "unrouted": [e.id for e in evs_all if not dests[e.id]]}
