"""产物种类注册。import 本包即完成全部 KINDS 注册。

每种 numeric 产物一个 pydantic 模型，模型就是步骤间的接口契约：改字段先改这里，
写盘时校验，读盘时校验。图像类只有 ProductKindSpec，没有模型。
"""

from . import page, borders, columns, gate, cells, chars  # noqa: F401
