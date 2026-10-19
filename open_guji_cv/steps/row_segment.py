"""Step3 单列文字切分：清理后列图 → 带类型的字格 + 读序。

包的是 `utils/row_boundaries.segment_column`。输入参数全部来自交接闸（页级 period / ref_w，
列级 content_x / border_top / border_bottom / top_slack）；n_body_slots 来自 Book / 参数。
产物坐标是列图坐标，另带经 Step2 逆映射回原图的 quad_page（规范空间）。
"""

from __future__ import annotations

from pydantic import BaseModel, model_validator

from ..core.book import _expand_pages
from ..core.spec import StepSpec, column_key
from ..core.step import RunContext, Step, register_step
from ..products.kinds.cells import CellRec, ColumnCells, CutPointCandidates, PageCells, SeamCandidate
from ..products.kinds.columns import PageWindows
from ..products.kinds.gate import GateManifest
from ..utils.cut_select import ckpt_fingerprint, get_judge
from ..utils.roster_glyph import load_scorer
from ..utils.roster_segment import segment_roster_page
from ..utils.row_boundaries import (NONUNIFORM_LAM, effective_body_slots,
                                    segment_column)
from ._warpmap import ColumnMapper


#: 逐列字数先验一次最多改几个字（差得更多多半是列错位或页对错，硬改会把整列切乱）
COLGOLD_MAX_DIFF = 2
_COLGOLD_CACHE: dict[tuple[str, str], dict] = {}


def _colgold_path(rel: str):
    from pathlib import Path
    from ..core.workspace import workspace_root
    p = Path(rel)
    if not p.is_absolute():
        root = workspace_root()
        p = (root / p) if root is not None else p
    return p


def load_colgold(rel: str, book: str) -> dict[tuple[int, int], dict]:
    """逐列字数表 → {(页, 列): 行}，只收本册、双源一致（`agree`）且无夹注的列。"""
    import json
    p = _colgold_path(rel)
    key = (str(p), book)
    if key not in _COLGOLD_CACHE:
        out = {}
        if p.exists():
            for ln in p.read_text(encoding="utf-8").splitlines():
                if not ln.strip():
                    continue
                r = json.loads(ln)
                if r.get("vol") == book and r.get("agree") and not r["dzg"].get("note"):
                    out[(int(r["page"]), int(r["col"]))] = r
        _COLGOLD_CACHE[key] = out
    return _COLGOLD_CACHE[key]


def apply_count_target(r, seg, n_body: int, want: int, tag: str,
                       max_diff: int = COLGOLD_MAX_DIFF, count=None):
    """按目标字数重切一列：`seg(n_body)` 是本列的 DP 调用，`r` 是按 `n_body` 切出的结果。

    切出字数 ≠ `want` 且差 ≤ `max_diff` → 格数减去差值重切一次；重切后字数**恰好**等于 `want` 才采用。
    含夹注的列不碰（夹注两小字占一格，字数换格数不是简单相减）。
    `count(cells)` 给「这一列算几个字」，缺省数非空格（`_n_chars`）。
    返回 (结果, 采用的格数, 旗)；旗以 `<tag>_prior` / `<tag>_conflict` 开头。"""
    count = count or _n_chars
    if r is None or _has_jiazhu(r.cells):
        return r, n_body, []
    got = count(r.cells)
    d = got - want
    if d == 0:
        return r, n_body, []
    if abs(d) > max_diff:
        return r, n_body, [f"{tag}_conflict：切出 {got} 字，目标 {want}，差 {d} 超过 {max_diff} 不套"]
    r2 = seg(n_body - d)
    if r2 is not None and count(r2.cells) == want and not _has_jiazhu(r2.cells):
        return r2, n_body - d, [f"{tag}_prior：字数 {got}→{want}（格数 {n_body}→{n_body - d}）"]
    return r, n_body, [f"{tag}_conflict：切出 {got} 字，目标 {want}，按差值重切仍对不上"]


_YOLO_CACHE: dict[str, object] = {}


def _yolo(model_dir: str):
    from ..utils.yolo_tool_infer import YoloTool
    d = str(_colgold_path(model_dir))
    if d not in _YOLO_CACHE:
        _YOLO_CACHE[d] = YoloTool(d)
    return _YOLO_CACHE[d]


def _cover(box, y) -> float:
    iw = min(box[2], y[2]) - max(box[0], y[0])
    ih = min(box[3], y[3]) - max(box[1], y[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    return iw * ih / max(1e-6, (box[2] - box[0]) * (box[3] - box[1]))


def yolo_merge_pairs(ink_boxes: list, yolo_boxes: list, cover: float = 0.5, max_h: float = 1.3) -> int:
    """同列按读序排好的正文字格墨迹框（左上原点页坐标，`None` = 空格）× 本页 YOLO 字框 → 「一字两格」对数。

    `yolo_boxes` 已按置信度筛过；框高超过本页中位 `max_h` 倍的不用——YOLO 偶尔把两个字并成一个
    约两倍高的框，那种框会把两个真字误报成一对（研究文档 §四-4′：不加这条 100 页误报 7，加了 0）。
    一个格只配一对（配上之后跳过下一格）。"""
    if not yolo_boxes:
        return 0
    hs = sorted(b[3] - b[1] for b in yolo_boxes)
    mh = hs[len(hs) // 2]
    ys = [b for b in yolo_boxes if b[3] - b[1] <= max_h * mh]
    k, i = 0, 0
    while i + 1 < len(ink_boxes):
        a, b = ink_boxes[i], ink_boxes[i + 1]
        if a is not None and b is not None and any(_cover(a, y) >= cover and _cover(b, y) >= cover for y in ys):
            k += 1
            i += 2
        else:
            i += 1
    return k


def _ink_box(img, c, thr: int):
    """列图里一格的墨迹外接框（列图坐标）；格里没墨返回 None。"""
    import numpy as np
    y0, y1 = max(0, int(c.y0)), min(img.shape[0], int(round(c.y1)))
    x0, x1 = max(0, int(c.x0)), min(img.shape[1], int(round(c.x1)))
    if y1 <= y0 or x1 <= x0:
        return None
    m = img[y0:y1, x0:x1] < thr
    if not m.any():
        return None
    ys, xs = np.nonzero(m)
    return (x0 + xs.min(), y0 + ys.min(), x0 + xs.max() + 1, y0 + ys.max() + 1)


#: 金标说这一格该空、Step3 却给了 char 的格，墨占比低于此就不算字——那是列首/列尾残墨
#: （抬头位残框、虚线），Step4 会按 `tail_junk` 丢掉；按 Step3 原样计数会把本来对的列
#: 「纠」成少一字（vol04 抽 50 页首版实测：修好 2、改坏 47）。阈值在测试 B 100 页上量的：
#: 0.08 时「Step3 计数判错、Step4 其实对」只 1 列，判对 15、漏 5（doc/design/19 变更记录）。
COLGOLD_JUNK_INK = 0.08


def colgold_count(g: dict):
    """按金标格位计数：格位在金标字段（start+1 … start+n）里的非空格都算，之外的只算墨够的。"""
    lo, hi = int(g["start"] or 0) + 1, int(g["start"] or 0) + int(g["n"])

    def count(cells) -> int:
        return sum(1 for c in cells if c.kind != "blank"
                   and (lo <= c.slot <= hi or c.ink_ratio >= COLGOLD_JUNK_INK))
    return count


def _n_chars(cells) -> int:
    return sum(1 for c in cells if c.kind != "blank")


def _has_jiazhu(cells) -> bool:
    return any(c.kind.startswith("jiazhu") for c in cells)


class RowSegmentParams(BaseModel):
    n_body_slots: int | None = None      # None = Book.chars_per_line
    n_raised: int = 0                    # 抬头多出的格数；版式先验，raised 不自动推
    ink_threshold: int = 128
    min_ink_ratio: float = 0.01
    raise_tol: float = 2.0
    detect_jiazhu: bool = True
    only_admitted: bool = True           # 只切过闸的列
    seam_band: int = 20                  # 折线切分走廊半宽；0 = 关（utils/seam.py）
    cut_judge: str = "unet"              # 候选池裁判：unet（utils/cut_select.py，2026-09-14 起现役）| rule（只用旧规则）
    judge_fingerprint: str = ""          # 裁判权重指纹，自动填（进 Step 指纹：换权重 → Step3 产物自动 stale）
    detect_bottom_bar: bool = True       # 列里还躺着下版框线时下界改用它（row_boundaries.find_bottom_frame_bar）
    #: **职名页分支**（overview#450，S4，2026-10-06）：列在这里的页不走固定格数 DP，改走
    #: `utils/roster_segment`（不定字数、二维递归切）。默认空 = 关，别的书别的页产物逐字节不变。
    #: 只在册配置里点名开（`params: {row_segment: {roster_pages: ["89-132"]}}`），不自动判页型——
    #: 闸1 判不出职名页（见 row_segment_gate 模块头 L0u 一节），点名是人定的。
    roster_pages: list[int | str] = []
    #: **列端虚线残段记空白**（overview#376 后续，2026-10-07）：缺省关，关时产物逐字节不变。开了以后，
    #: 首格/末格/抬头格里墨的外接框竖向 ≤ `dash_h_frac`×period 且横向 ≤ `dash_w_frac`×列宽的，kind 记 `blank`
    #: 而不是没字的 `char`。阈值未经真图标定（云端没有原图），先按 S2 实测「虚线跨度 ≤29 行 ≈ 0.25 period」取。
    dash_blank: bool = False
    dash_h_frac: float = 0.3
    dash_w_frac: float = 0.25
    #: 职名页密排段**按本书字形库重切**（overview#450，2026-10-07，`utils/roster_glyph`）：
    #: 压扁粘连字几何上数不准字数，拿库里刻例比相似度定切法。默认关；开了才读库、才填指纹。
    roster_glyph_refine: bool = False
    roster_glyph_db: str = ""            # 空 = 工作区 output/glyph.db（core.workspace.glyph_db_path）
    roster_glyph_fingerprint: str = ""   # 库内容指纹，开关开着时自动填；soft：库变只记漂移不判过期（同 glyph_match）
    #: **逐列字数先验**（doc/design/19 块 C，2026-10-19）：工作区里的逐列字数金标表
    #: （`scripts/dzg_import.py colgold` 产出，相对工作区根，如 `corpus/daizhige/colgold.jsonl`）。
    #: 空 = 关，关时产物逐字节不变。开了以后：某列 DP 切出的字数与表里双源一致的字数不同，
    #: 就按差值调格数**重切一次**；重切后字数恰好对上才采用，否则留原结果、记 `colgold_conflict` 旗。
    #: 人裁 `column-slots` 优先（有人裁的列不碰）；夹注列本期不碰。只对殿本这类有双源金标的书有意义。
    colgold_prior: str = ""
    colgold_fingerprint: str = ""        # 表内容 sha，开关开着时自动填（表一改 → Step3 判过期）
    #: **原生 YOLO 并格闸**（doc/design/19 块 D，2026-10-19）：缺省关，关时不读模型、产物逐字节不变。
    #: 开了以后整页跑一遍 yolo-tool 两段模型（`utils/yolo_tool_infer`，onnxruntime），同列相邻两个
    #: 字格的墨迹框都有 ≥`yolo_cover` 落进同一个**正常高**（≤`yolo_max_h`×本页中位）的 YOLO 字框，
    #: 记一对「一字被切成两格」；有 k 对就把目标字数定为「现字数 − k」走 `apply_count_target` 重切，
    #: 字数恰好对上才采用。两个开关都开时先 D 后 C（D 改过的列 C 再按金标核一遍）。
    yolo_merge: bool = False
    yolo_model_dir: str = ""             # yolo-tool 的 model/ 目录（内含 type/ slide/ 两个 best.onnx）；相对工作区根或绝对路径
    yolo_fingerprint: str = ""           # 两份 onnx 的 sha，开关开着时自动填（换模型 → Step3 判过期）
    yolo_conf: float = 0.25
    yolo_cover: float = 0.5
    yolo_max_h: float = 1.3

    @model_validator(mode="after")
    def _fill_yolo_fingerprint(self):
        if self.yolo_merge and not self.yolo_fingerprint:
            d = _colgold_path(self.yolo_model_dir)
            if (d / "type" / "best.onnx").exists():
                from ..utils.yolo_tool_infer import model_fingerprint
                object.__setattr__(self, "yolo_fingerprint", model_fingerprint(d))
        return self

    @model_validator(mode="after")
    def _fill_colgold_fingerprint(self):
        if self.colgold_prior and not self.colgold_fingerprint:
            p = _colgold_path(self.colgold_prior)
            if p.exists():
                import hashlib
                object.__setattr__(self, "colgold_fingerprint", hashlib.sha256(p.read_bytes()).hexdigest()[:16])
        return self

    @model_validator(mode="after")
    def _fill_judge_fingerprint(self):
        # 与 glyph_match.GlyphMatchParams.db_fingerprint 同一套路：模型是外部可变状态，
        # 不进指纹的话换了权重产物还显示 fresh。权重缺失时为空串 → 与裁判可用时指纹不同。
        if self.cut_judge == "unet" and not self.judge_fingerprint:
            object.__setattr__(self, "judge_fingerprint", ckpt_fingerprint())
        # 字形库精修：只在开关开着时解析库路径、填指纹——关着时参数逐字段不变（同 seed_admit.human_fingerprint）
        if self.roster_glyph_refine:
            if not self.roster_glyph_db:
                from ..core.workspace import glyph_db_path
                object.__setattr__(self, "roster_glyph_db", str(glyph_db_path()))
            if not self.roster_glyph_fingerprint:
                from .glyph_match import db_fingerprint
                object.__setattr__(self, "roster_glyph_fingerprint", db_fingerprint(self.roster_glyph_db))
        return self


@register_step
class RowSegmentStep(Step):
    spec = StepSpec(
        id="row_segment", title="Step3 单列文字切分", version="1.18", unit="column",   # 1.18：逐列字数先验 colgold_prior、原生 YOLO 并格闸 yolo_merge（doc/design/19，都默认关）；1.17：职名页密排段按字形库重切 roster_glyph_refine（overview#450，默认关）；1.16：列端虚线残段记空白 dash_blank（overview#376，默认关）；1.15：职名页分支 roster_pages（overview#450，默认关）；1.14：人裁「正文当小注」的格从夹注段里摘掉、按整格出（forced_main，overview#415/#436）；1.13：人裁「小注当正文」的格强制按雙行小注从中间拆（forced_jiazhu，2026-09-30）；1.12：列里残留的下版框线当下界（overview#266）；1.11：單行小注自成 kind=jiazhu_solo（此前借 jiazhu_a 的壳）
        consumes=("gate_manifest", "column_windows", "column_image"), produces=("cells",),
        params=RowSegmentParams,
        code_deps=("open_guji_cv.utils.row_boundaries", "open_guji_cv.utils.jiazhu_split",
                   "open_guji_cv.utils.column_projection", "open_guji_cv.utils.seam",
                   "open_guji_cv.utils.cut_select", "open_guji_cv.utils.roster_segment",
                   "open_guji_cv.utils.roster_glyph"),
        soft_params=("roster_glyph_fingerprint",),
        path_params=("roster_glyph_db", "colgold_prior", "yolo_model_dir"),
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: RowSegmentParams = ctx.params_for(self)  # type: ignore[assignment]
        n_body = p.n_body_slots or ctx.book.chars_per_line
        gate: GateManifest = ctx.product("gate_manifest", page)
        wins: PageWindows = ctx.product("column_windows", page)
        page_w = wins.page_size[0]
        if p.roster_pages and page in set(_expand_pages(p.roster_pages)):
            return {"cells": self._run_roster(ctx, p, page, gate, wins)}
        # 人裁回流：workspace 裁决表里这本书已裁决的切点（feedback/lookup.py，
        # **不读 open-guji-dataset**），按 (页,列) 筛出 slot_above → kind 传给
        # segment_column 收敛候选。裁决不进指纹，该页下次重跑才生效（见 lookup 注）。
        from ..feedback.lookup import resolved_cuts as _resolved_cuts
        from ..feedback.lookup import resolved_slots as _resolved_slots
        book_resolved = _resolved_cuts(ctx.book.id)
        # 同一条回流路径的兄弟：逐列字数覆盖（`review/slot_count_cards.py`）。
        # `chars_per_line` 是页级版式常量，DP 硬切；少数列真的比常量多/少刻了
        # 一个字时（bxgb p33c19 实测 22 字 vs 常量 21），没有可靠的几何信号能
        # 自动探测（格高/period 比值测过，两个方向都不可靠，见
        # feedback_cell_height_not_merge_signal），只能人核对后写回。
        #
        # 同一条裁决还带 `uniform`（2026-09-20）：字数对了不等于**字距**均匀。
        # p33c19 就是字数 22 给对了、DP 仍把首字「尉」劈成两格——等距先验比
        # 墨量判据贵五倍（账见 row_boundaries.NONUNIFORM_LAM）。标了非均匀的列
        # 把 lam 降下来，其余列一字不动。
        book_slots = _resolved_slots(ctx.book.id)
        # 第三个兄弟：人指认的單行小注格（判据落空的那一型，见 lookup.resolved_solo_notes）
        from ..feedback.lookup import resolved_solo_notes as _resolved_solo
        book_solo = _resolved_solo(ctx.book.id)
        # 第四个兄弟（2026-09-30）：人指认的雙行小注格（判据没认出的短版本小注），不看判据从中间拆
        from ..feedback.lookup import resolved_forced_jiazhu as _resolved_forced_jz
        book_forced_jz = _resolved_forced_jz(ctx.book.id)
        # 第五个兄弟（2026-10-06，overview#415/#436）：反向——人指认的整宽正文格，Step3 别把它劈成 a/b
        from ..feedback.lookup import resolved_forced_main as _resolved_forced_main
        book_forced_main = _resolved_forced_main(ctx.book.id)
        # 候选池裁判（U-Net，进程内单例）；权重/torch 不可用时为 None → segment_column 按旧规则走
        judge = get_judge() if p.cut_judge == "unet" else None
        # 人拖过的切线钉住（lookup.resolved_pins，只收带页面坐标的裁决；生效时机同 resolved_cuts）
        from ..feedback.lookup import resolved_pins as _resolved_pins
        book_pins = _resolved_pins(ctx.book.id, ctx.store)
        colgold = load_colgold(p.colgold_prior, ctx.book.id) if p.colgold_prior else {}
        yolo_boxes: list = []
        if p.yolo_merge:
            import cv2
            raw = ctx.raw_page(page)
            bgr = cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR) if raw.ndim == 2 else raw
            _, ych = _yolo(p.yolo_model_dir).infer(bgr, slide_conf=p.yolo_conf)
            yolo_boxes = [(b.x0, b.y0, b.x1, b.y1) for b in ych if b.conf >= p.yolo_conf]
        out: list[ColumnCells] = []
        for gc in gate.columns:
            # 逐列格数：页级参数与闸给的 hint 取大者。hint 是「这一列墨跨度
            # 装得下几个字」（见 GateColumn.n_raised_hint）——同一页上有的抬头列
            # 多一格、有的不多，页级参数给不出这个差别，DP 只能丢掉首字。
            n_raised_col = max(p.n_raised, getattr(gc, "n_raised_hint", 0) or 0)
            # 版框装不下 n_body 格的页（vol01/5 只有 20 行）按实际行数切，见
            # row_boundaries.effective_body_slots
            n_body_col = effective_body_slots(n_body, gc.border_top, gc.border_bottom, gate.period)
            # 人裁逐列字数覆盖优先于上面两条自动判据——人是终审，跟
            # `_apply_resolved_cut` 里"人裁收敛成功就不再是升级"同一条纪律。
            slot_override = book_slots.get((page, gc.col))
            if slot_override is not None:
                n_body_col = slot_override.n_slots
            base = dict(col=gc.col, n_body_slots=n_body_col, n_raised=n_raised_col,
                        period=gate.period, ref_w=gate.ref_w, content_x=gc.content_x,
                        border_top=gc.border_top, border_bottom=gc.border_bottom,
                        top_slack=gc.top_slack)
            if p.only_admitted and not gc.admitted:
                out.append(ColumnCells(ok=False, error="未过交接闸: " + "; ".join(gc.reject), **base))
                continue
            if gate.period is None:
                out.append(ColumnCells(ok=False, error="页级 period 缺失", **base))
                continue
            img = ctx.image("column_image", column_key(page, gc.col))
            col_resolved = {slot: kind for (pg, col, slot), kind in book_resolved.items()
                            if pg == page and col == gc.col}
            def _seg(n_body: int):
                return segment_column(
                    img, period=gate.period, n_body_slots=n_body, n_raised=n_raised_col,
                    border_top=gc.border_top, border_bottom=gc.border_bottom, ref_w=gate.ref_w,
                    top_slack=gc.top_slack, content_x=gc.content_x,
                    ink_threshold=p.ink_threshold, min_ink_ratio=p.min_ink_ratio,
                    raise_tol=p.raise_tol, detect_jiazhu=p.detect_jiazhu, seam_band=p.seam_band,
                    resolved_cuts=col_resolved or None, cut_judge=judge,
                    pinned_cuts={s_: y_ for (pg_, c_, s_), y_ in book_pins.items()
                                 if pg_ == page and c_ == gc.col} or None,
                    forced_solo=book_solo.get((page, gc.col)),
                    forced_jiazhu=book_forced_jz.get((page, gc.col)),
                    forced_main=book_forced_main.get((page, gc.col)),
                    detect_bottom_bar=p.detect_bottom_bar,
                    **({"dash_blank": (p.dash_h_frac, p.dash_w_frac)} if p.dash_blank else {}),
                    **({} if slot_override is None or slot_override.uniform
                       else {"lam": NONUNIFORM_LAM}))
            r = _seg(n_body_col)
            prior_flags: list[str] = []
            g = colgold.get((page, gc.col))
            k_pairs = 0
            if r is not None and yolo_boxes and slot_override is None and not _has_jiazhu(r.cells):
                k_pairs = self._yolo_pairs(r, img, wins, gc.col, page_w, yolo_boxes, p)
            # 先 D 后 C：两者修好的列几乎不重叠（测试 B：C 修 10、D 修 11、并集 13），
            # 「有金标时只让 D 提议、金标定采不采」那版实测漏掉 D 独有的两列（设计变更记录）。
            if r is not None and k_pairs and slot_override is None:
                r, n_new, fl = apply_count_target(r, _seg, n_body_col, _n_chars(r.cells) - k_pairs, "yolo")
                prior_flags += fl
                if n_new != n_body_col:
                    n_body_col = n_new
                    base = dict(base, n_body_slots=n_body_col)
            if r is not None and g is not None and slot_override is None:
                r, n_new, fl = apply_count_target(r, _seg, n_body_col, int(g["dzg"]["n"]), "colgold",
                                                  count=colgold_count(g["dzg"]))
                prior_flags += fl
                if n_new != n_body_col:
                    n_body_col = n_new
                    base = dict(base, n_body_slots=n_body_col)
            if r is None:
                out.append(ColumnCells(ok=False, error="弹性 DP 无解", **base))
                continue
            wrec = wins.column(gc.col)
            mapper = None
            if wrec is not None:
                mapper = ColumnMapper(page_w, wrec.left_line.to_vline(), wrec.right_line.to_vline(),
                                      wrec.top_y, wrec.bottom_y)
            n_total = n_body_col + n_raised_col
            cells = []
            for c in r.cells:
                pos = _slot_to_pos(c.slot, n_raised_col)
                if not 1 <= pos <= n_total:
                    raise ValueError(f"slot {c.slot} 换算出的物理位置 {pos} 越界（总格数 {n_total}）")
                cells.append(CellRec(
                    slot=c.slot, pos=pos, y0=float(c.y0), y1=float(c.y1),
                    x0=float(c.x0), x1=float(c.x1), kind=c.kind, sub=c.sub, order=int(c.order),
                    gap_center=None if c.gap_center is None else float(c.gap_center),
                    ink_ratio=float(c.ink_ratio), raised=bool(c.raised),
                    suspect_jiazhu_body=bool(getattr(c, "suspect_jiazhu_body", False)),
                    seam_top=c.seam_top, seam_bottom=c.seam_bottom,
                    quad_page=(None if mapper is None else
                               [(round(x, 2), round(y, 2)) for x, y in mapper.quad_tr(c.x0, c.y0, c.x1, c.y1)]),
                ))
            flags: list[str] = list(prior_flags)
            if r.bottom_bar_y is not None:
                # 下界换成了列里认出的下版框线（2026-09-28，overview#266）。border_bottom
                # 一并改写：Step4 拿它当 frame_bottom 提示，把条带开到这里、在它附近找框——
                # 还给 Step2 的值，Step4 就在框下白纸上找框，找不到，框墨进图块。
                flags.append(f"bottom_bar：下版框线在列图 y={r.bottom_bar_y:.0f}，"
                             f"高出 border_bottom {base['border_bottom'] - r.bottom_bar_y:.0f} 行")
                base = dict(base, border_bottom=float(r.bottom_bar_y))
            out.append(ColumnCells(ok=True, boundaries=[float(b) for b in r.boundaries], flags=flags,
                                   cells=cells, cut_candidates=[
                                       CutPointCandidates(
                                           k=cp.k, y=cp.y, slot_above=cp.slot_above,
                                           slot_below=cp.slot_below, chosen=cp.chosen,
                                           chosen_by=cp.chosen_by,
                                           escalate=cp.escalate, escalate_reason=cp.escalate_reason,
                                           origin=cp.origin,
                                           candidates=[SeamCandidate(
                                               kind=c.kind, y=c.y, seam_ink=c.seam_ink,
                                               dev_max=c.dev_max, agree=c.agree, dis_unet=c.dis_unet)
                                               for c in cp.candidates],
                                       ) for cp in r.cut_candidates],
                                   **base))
        return {"cells": PageCells(page=page, period=gate.period, ref_w=gate.ref_w, columns=out)}


    @staticmethod
    def _yolo_pairs(r, img, wins, col: int, page_w: int, yolo_boxes: list, p) -> int:
        """本列 DP 结果里「一字两格」的对数（块 D）：正文格墨迹框映回原图（左上原点）后交给 yolo_merge_pairs。"""
        wr = wins.column(col)
        if wr is None:
            return 0
        mp = ColumnMapper(page_w, wr.left_line.to_vline(), wr.right_line.to_vline(), wr.top_y, wr.bottom_y)
        ink = []
        for c in sorted((c for c in r.cells if c.kind == "char"), key=lambda c: c.y0):
            ib = _ink_box(img, c, p.ink_threshold)
            if ib is None:
                ink.append(None)
                continue
            bx0, by0, bx1, by1 = mp.bbox_tr(*ib)
            ink.append((page_w - 1 - bx1, by0, page_w - 1 - bx0, by1))   # 规范空间（右上原点）→ 左上原点
        return yolo_merge_pairs(ink, yolo_boxes, p.yolo_cover, p.yolo_max_h)

    # ── 职名页分支 ────────────────────────────────────────────────────
    def _run_roster(self, ctx: RunContext, p: RowSegmentParams, page: int,
                    gate: GateManifest, wins: PageWindows) -> PageCells:
        """职名页：每列字数不定，`n_body_slots` = 本列实际位数，`boundaries` 为空（没有格线）。

        雙行小字配对成同一物理位：右行第 i 字（jiazhu_a）与左行第 i 字（jiazhu_b）共用 pos，
        `gap_center` = 两行之间的缝——Step4 按 pos 合成满宽格再从缝拆开，与正文雙行同一条路。
        列级 flags 一律带 `roster`（闸3 据此不按版式格数拦）；字数是推出来的列另带
        `roster_dense_guess`，相邻字 y 重叠的带 `roster_overlap`（见 utils/roster_segment）。"""
        page_w = wins.page_size[0]
        admitted = [gc for gc in gate.columns if gc.admitted or not p.only_admitted]
        imgs = [(ctx.image("column_image", column_key(page, gc.col)), gc.content_x) for gc in admitted]
        scorer = None
        if p.roster_glyph_refine:
            # 库缺失/为空时 scorer 为 None → 只走几何切分，不报错（职名页本来就有人核兜底）
            scorer = load_scorer(p.roster_glyph_db, p.roster_glyph_fingerprint)
        results = dict(zip((gc.col for gc in admitted),
                           segment_roster_page(imgs, ink_threshold=p.ink_threshold, scorer=scorer)))
        out: list[ColumnCells] = []
        for gc in gate.columns:
            base = dict(col=gc.col, n_raised=0, period=gate.period, ref_w=gate.ref_w,
                        content_x=gc.content_x, border_top=gc.border_top,
                        border_bottom=gc.border_bottom, top_slack=0.0)
            if gc.col not in results:
                out.append(ColumnCells(ok=False, n_body_slots=0,
                                       error="未过交接闸: " + "; ".join(gc.reject), **base))
                continue
            rc = results[gc.col]
            wrec = wins.column(gc.col)
            mapper = None
            if wrec is not None:
                mapper = ColumnMapper(page_w, wrec.left_line.to_vline(), wrec.right_line.to_vline(),
                                      wrec.top_y, wrec.bottom_y)
            # 物理位：正文字各占一位；雙行按「右行第 i 字 ↔ 左行第 i 字」配对共占一位
            pos_of: list[int] = []
            gap_of: list[float | None] = []
            pos, i, items = 0, 0, rc.items
            while i < len(items):
                if items[i].kind != "jiazhu_a":
                    pos += 1
                    pos_of.append(pos)
                    gap_of.append(None)
                    i += 1
                    continue
                j = i
                while j < len(items) and items[j].kind == "jiazhu_a":
                    j += 1
                k = j
                while k < len(items) and items[k].kind == "jiazhu_b":
                    k += 1
                a_run, b_run = items[i:j], items[j:k]
                gap = (min(it.x0 for it in a_run) + max((it.x1 for it in b_run),
                                                        default=min(it.x0 for it in a_run))) / 2.0
                n_pair = max(len(a_run), len(b_run))
                for n in range(len(a_run)):
                    pos_of.append(pos + 1 + n)
                    gap_of.append(gap)
                for n in range(len(b_run)):
                    pos_of.append(pos + 1 + n)
                    gap_of.append(gap)
                pos += n_pair
                i = k
            cells: list[CellRec] = []
            for order, (it, ps, gp) in enumerate(zip(items, pos_of, gap_of)):
                cells.append(CellRec(
                    slot=ps, pos=ps, y0=float(it.y0), y1=float(it.y1),
                    x0=float(it.x0), x1=float(it.x1), kind=it.kind,
                    sub={"jiazhu_a": "a", "jiazhu_b": "b"}.get(it.kind), order=order,
                    gap_center=gp, raised=False,
                    flags=["dense_guess"] if it.dense_guess else [],
                    quad_page=(None if mapper is None else
                               [(round(x, 2), round(y, 2))
                                for x, y in mapper.quad_tr(it.x0, it.y0, it.x1, it.y1)]),
                ))
            out.append(ColumnCells(ok=True, n_body_slots=pos, cells=cells, boundaries=[],
                                   em=float(rc.em), flags=["roster", *rc.flags], **base))
        return PageCells(page=page, period=gate.period, ref_w=gate.ref_w, columns=out)


def _slot_to_pos(slot: int, n_raised: int) -> int:
    """对外 slot（正文 1..n，抬头 -n_raised..-1，跳 0）→ 1 起的物理位置。"""
    return slot + n_raised + 1 if slot < 0 else slot + n_raised
