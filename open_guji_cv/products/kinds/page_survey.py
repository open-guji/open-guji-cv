"""page_survey：Step0 页面预检（numeric，页级）。任务卡 #54 第22条。

用户 09-27 21:40 定的诉求：「先探测页面情况，把需要拆分的先拆了，再跑后边
的，不然代价很大」——照 `新书整理/工具/page_survey.py` 的口径（宽高比按
本册中位数量，>1.3× 或 <0.7× 算异常），只不过挪进引擎按 Step 跑、有产物
留痕，不用人另外手跑一遍脚本。

**只判尺寸，不判内容**：合扫两叶、单叶未裁、书脊标签这几类都在物理尺寸
上跟正文页明显不同，这一步够用；真要分辨「异常但其实是正文」（比如宽表格
横排页）留给人看 `kind` 字段自己判断，这一步不猜。

第 1 页另眼看待——书脊/封面页常年是这类异常的大头，`p1_suspect` 独立
标记，不占用 `odd` 的判据（`odd` 只按尺寸比）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ...core.spec import ProductKindSpec, RAW_TR
from ...core.step import register_kind


class PageSurvey(BaseModel):
    page: int
    width: int
    height: int
    median_width: float
    median_height: float
    ratio_w: float
    """`width / median_width`。"""
    ratio_h: float
    odd: bool = False
    """宽或高偏离本册中位数超过阈值（缺省 1.3×/0.7×，见 `PageSurveyParams`）。"""
    kind: str | None = None
    """`odd=True` 时的形态猜测：多叶合扫(2×2) / 双叶横拼(1×2) / 上下叠(2×1) /
    偏小(标签/残页)——口径抄自 `page_survey.py`。"""
    p1_suspect: bool = False
    """页号为 1 时总标一下——书脊/封面页常年是异常大头，不管尺寸判据怎么说。"""
    whitelisted: bool = False
    """命中书 yaml 白名单（`params.page_survey.whitelist`）时为真：`odd` 照记，
    但闸不拦（无论 `block` 开关开没开）。"""
    whitelist_reason: str = ""


PAGE_SURVEY = register_kind(ProductKindSpec(
    id="page_survey", title="Step0 页面预检", storage="numeric", unit="page",
    schema=PageSurvey, coord_space=RAW_TR))
