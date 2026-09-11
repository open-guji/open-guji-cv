"""闸模块：往已注册 Step 的 spec 上挂 GateSpec。import 本包即完成全部挂载。

怎么加一道闸
-----------
1. 闸的 Step 类照旧写（继承 `core.step.Step`，`consumes`/`produces`/`params`
   跟普通 Step 一样定义，落盘目录 = 它自己的 `spec.id`，与被挂的 Step 分开，
   指纹/新鲜度独立算，不共用）；
2. 用 `@register_step` 注册它——跟普通 Step 一样进 `STEPS` 全局表，只是不
   出现在任何 pipeline yaml 的 `steps:` 列表里；
3. 用 `core.step.attach_gate(owner_step_id, GateSpec(id=..., ...))` 把它接到
   出口 Step 的 spec 上——引擎跑完 owner 之后自动跟着跑这道闸
   （见 `core.engine.Engine.run`），控制台/`status()` 也会按闸自己的 id 单独
   报一行新鲜度。

本包必须在它要挂的 Step 已经注册之后才 import——下面先 `import ..steps` 是
保证这个顺序的**兜底**，不能只靠调用方记得先 import steps：`steps/__init__.py`
末尾也会 `from .. import gates`，两边循环 import 都安全（Python 对同一个
正在 import 的模块只执行一次，第二次拿到的是当时已有的那部分——`column_warp`
在 steps/__init__.py 里排在那行 `from .. import gates` 之前，所以无论从哪边
先进来，等真正跑到 `attach_gate` 时 `column_warp` 都已经注册好了）。
"""

from .. import steps as _steps  # noqa: F401 —— 兜底：确保 Step 先注册
from . import border_detect_gate  # noqa: F401
from . import column_gate  # noqa: F401
from . import row_segment_gate  # noqa: F401
