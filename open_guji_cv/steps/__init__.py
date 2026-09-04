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
"""

from ..products import kinds  # noqa: F401  —— 先注册产物种类
from . import (border_detect, column_warp, column_gate, row_segment,  # noqa: F401
               cell_shrink, glyph_match, ocr_candidates, context_decide)
