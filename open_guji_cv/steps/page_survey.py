"""Step0 页面预检：原图尺寸 → 按本册中位数标出异常页。任务卡 #54 第22条。

用户 09-27 21:40 定的诉求：「以后想想流程，需要先探测页面情况，把这种需要
拆分的要先拆了，然后再跑后边的，不然代价很大」。口径照抄整理团队已经在用的
`项目进展/新书整理/工具/page_survey.py`：宽或高偏离本册中位数 >1.3× 或
<0.7× 就标异常，形态按哪个方向偏猜一下（合扫/横拼/上下叠/偏小）。

**这一步只读原图尺寸（PIL 头信息，不解码像素），不碰任何上游产物**——
Step0 排在 Step1 之前就是要在最早、最便宜的地方拦。`consumes=("raw_page",)`
只是为了让指纹正常跟着原图走，不是真的要整张图解出来。

**闸在 `gates/border_detect_gate.py`，不在这里**：这一步只出数据（异常与否、
猜的形态），拦不拦、拦到什么程度是 Step1 出口闸的事——两件事分开才能做到
「缺省只记待办、不拦」（这一步永远产出，闸自己决定 `on_fail`）。

**已经拆好的页自动恢复正常**：判据现读当前原图的实际尺寸，不留历史状态；
页一旦被真的拆开/换成正常尺寸，下一次算这一步就直接是 `odd=False`，
不需要人去清什么"曾经异常"的标记。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from ..core.spec import StepSpec
from ..core.step import RunContext, Step, register_step
from ..products.kinds.page_survey import PageSurvey

#: >1.3× 或 <0.7× 本册中位数才算异常——口径与整理团队 `page_survey.py` 一致，
#: 改这两个数会让全书判据跟着漂，所以放进 Params 而不是硬编码常量。
RATIO_HIGH_DEFAULT = 1.3
RATIO_LOW_DEFAULT = 0.7


class PageSurveyParams(BaseModel):
    ratio_high: float = RATIO_HIGH_DEFAULT
    ratio_low: float = RATIO_LOW_DEFAULT
    whitelist: dict[int, str] = Field(default_factory=dict)
    """页号 → 白名单理由（如「卷端双叶横拼，确认无正文」）。**必须写理由**，
    空字符串不算数——`run_page` 会直接把空理由当成没配（见下）。命中白名单的页
    `odd` 照实记，但 `whitelisted=True`，闸（`border_detect_gate`）不拦。"""


def _page_size(path: Path) -> tuple[int, int] | None:
    """页面像素宽高，只读文件头，不解码整张图（PIL 的 `Image.open` 是惰性的）。
    读不到（缺页/坏文件）返回 None，调用方跳过——原图缺失是别的判据管的事，
    这里不该因为一页坏图让整册的中位数都算不出来。"""
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.size
    except Exception:
        return None


def _book_median_size(raw_dir: str, raw_pattern: str,
                      pages: tuple[int, ...]) -> tuple[float, float, dict[int, tuple[int, int]]] | None:
    """整册页面尺寸的中位数 + 逐页尺寸表。

    ⚠️ **不缓存**——"已经拆好的页自动恢复正常"要求每次都读当前原图的真实尺寸；
    缓存过一次就会看不到刚拆好的页（试过 `lru_cache`，被自己的回归测试当场
    抓到：拆完页 3 后同进程再问一次，`odd` 还是 `True`）。PIL 的 `Image.open`
    只读文件头不解码像素，几百页一次全扫也是毫秒级，不值得为这点性能拿
    正确性去换。
    """
    import statistics as st

    root = Path(raw_dir)
    sizes: dict[int, tuple[int, int]] = {}
    for pg in pages:
        p = root / raw_pattern.format(page=pg)
        sz = _page_size(p)
        if sz is not None:
            sizes[pg] = sz
    if len(sizes) < 3:      # 样本太少中位数没意义（单页/两页的书这一步直接不启用）
        return None
    mw = st.median(w for w, _ in sizes.values())
    mh = st.median(h for _, h in sizes.values())
    return mw, mh, sizes


def survey_book(book, pages: list[int] | None = None,
                ratio_high: float = RATIO_HIGH_DEFAULT,
                ratio_low: float = RATIO_LOW_DEFAULT) -> list[PageSurvey]:
    """`guji survey` 与 `run_page` 共用的核心：整册量一遍，返回每页的 `PageSurvey`
    （不含白名单信息——白名单是书级 params，这里只管尺寸判据本身）。"""
    pgs = tuple(sorted(pages if pages is not None else book.all_pages()))
    stat = _book_median_size(str(book.raw_dir), book.raw_pattern, pgs)
    out: list[PageSurvey] = []
    if stat is None:
        return out
    mw, mh, sizes = stat
    for pg in pgs:
        sz = sizes.get(pg)
        if sz is None:
            continue
        w, h = sz
        rw, rh = w / mw, h / mh
        odd = rw > ratio_high or rh > ratio_high or rw < ratio_low or rh < ratio_low
        kind = None
        if odd:
            kind = ("多叶合扫(2×2)" if rw > ratio_high and rh > ratio_high else
                   "双叶横拼(1×2)" if rw > ratio_high else
                   "上下叠(2×1)" if rh > ratio_high else "偏小(标签/残页)")
        out.append(PageSurvey(page=pg, width=w, height=h, median_width=mw, median_height=mh,
                              ratio_w=round(rw, 3), ratio_h=round(rh, 3), odd=odd, kind=kind,
                              p1_suspect=(pg == 1)))
    return out


@register_step
class PageSurveyStep(Step):
    spec = StepSpec(
        id="page_survey", title="Step0 页面预检", version="1.0", unit="page",
        consumes=("raw_page",), produces=("page_survey",), params=PageSurveyParams,
        # 阈值变了全书判据跟着变，`whitelist` 变了个别页的 `whitelisted` 跟着变——
        # 两个都不是"软参数"（不能改了却不让产物过期）。
    )

    def run_page(self, ctx: RunContext, page: int) -> dict[str, BaseModel]:
        p: PageSurveyParams = ctx.params_for(self)  # type: ignore[assignment]
        rows = survey_book(ctx.book, ctx.book.all_pages(), p.ratio_high, p.ratio_low)
        row = next((r for r in rows if r.page == page), None)
        if row is None:
            # 样本太少测不出中位数，或这一页读不到尺寸——不当异常，只是没判据。
            sz = _page_size(ctx.book.raw_path(page))
            w, h = sz if sz else (0, 0)
            row = PageSurvey(page=page, width=w, height=h, median_width=float(w),
                             median_height=float(h), ratio_w=1.0, ratio_h=1.0,
                             odd=False, p1_suspect=(page == 1))
        reason = (p.whitelist.get(page) or "").strip()
        if reason:
            row = row.model_copy(update={"whitelisted": True, "whitelist_reason": reason})
        return {"page_survey": row}
