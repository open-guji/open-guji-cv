"""Step 适配层。import 本包即注册全部 Step（KINDS 在 products.kinds 里先注册）。

怎么加一个新 Step
-----------------
1. 在 products/kinds/ 里声明它的产物种类（numeric 给 pydantic 模型，图像给 ProductKindSpec）；
2. 新建 steps/<id>.py：定义 params 模型、`StepSpec`（consumes / produces / version / code_deps），
   继承 `core.step.Step`，实现 `run_page`；产图像的再实现 `render`；
3. 在下面 import 它；把 id 写进 pipelines/*.yaml 的合法拓扑位置。

三条铁律：
- **不改算法只包壳**：run_page 里只调现有函数，参数从 `ctx.params_for(self)` 与 `ctx.book` 拿；
- **不写图像产物**：图像只 `ctx.cache.put`，并保证 `render` 能确定性再生；
- **改契约先改模型**：产物字段变了先改 kinds/，再升 spec.version。

不产出内容、只判定上一步产物够不够格进下一步的，是「闸」而不是 Step——
写在 `gates/` 里，见那个包的说明；不要写进这里、不要塞进 pipeline yaml。
"""

from ..products import kinds  # noqa: F401  —— 先注册产物种类
from . import (border_detect, column_warp, row_segment,  # noqa: F401
               cell_shrink, glyph_match, ocr_candidates, context_decide,
               align_ref, seed_admit)
from .. import gates  # noqa: F401  —— 闸挂在对应 Step 的 spec 上，必须晚于上面几行
