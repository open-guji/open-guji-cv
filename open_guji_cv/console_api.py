# -*- coding: utf-8 -*-
"""（拆分 P6，2026-11-04）控制台门面已搬去 guji-manager：`guji_manager.console_api`。

本文件只留转发，给还没把 import 换成 `guji_manager.console_api` 的 guji-console 老版本用；
控制台换完、各机装上新控制台后删掉。不放任何名字表，也不放逻辑。
"""
from __future__ import annotations

import importlib
from typing import Any


def _target():
    try:
        return importlib.import_module("guji_manager.console_api")
    except ModuleNotFoundError as e:
        if e.name and e.name.startswith("guji_manager"):
            raise ImportError("控制台门面已搬去 guji-manager（≥0.4.0），本机没装或版本太旧"
                              "（装法见 cv scripts/ensure_manager.sh）") from e
        raise


def __getattr__(name: str) -> Any:
    if name.startswith("__") and name.endswith("__") and name != "__all__":
        raise AttributeError(name)
    return getattr(_target(), name)


def __dir__() -> list[str]:
    return list(_target().__all__)
