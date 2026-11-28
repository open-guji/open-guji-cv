"""产物种类注册。import 本包即完成全部 KINDS 注册。

每种 numeric 产物一个 pydantic 模型，模型就是步骤间的接口契约：改字段先改这里，
写盘时校验，读盘时校验。图像类只有 ProductKindSpec，没有模型。
"""

from . import page, borders, columns, gate, cells, chars, recog, row_segment_gate  # noqa: F401
from . import line_index  # noqa: F401  —— 现代印刷链 Step1 的列明细
from . import page_survey  # noqa: F401  —— Step0 页面预检（任务卡 #54 第22条）
from . import seals  # noqa: F401  —— 印章定位（2026-10-22）
from . import inverted  # noqa: F401  —— 反色带候选（2026-10-22）
from . import free_layout  # noqa: F401  —— 自由版式管线 keben_free 的三种产物（2026-10-27）
from . import read  # noqa: F401  —— 第三步识字重构：3b glyph_near、收尾 glyph_analyzer（2026-11-27）
from . import decide  # noqa: F401  —— 第四步定字的新产物：4b context_rank（2026-11-27）
from . import cell_state  # noqa: F401  —— 第四步 4c 格况（2026-11-28）
from . import group_decision  # noqa: F401  —— 第四步 4d 字组原料（2026-11-28）
from . import decide_gate  # noqa: F401  —— 第四步出口 gate 检测结果（只检测，2026-11-28）
