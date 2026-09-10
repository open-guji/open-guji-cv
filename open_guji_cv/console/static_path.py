# -*- coding: utf-8 -*-
"""前端静态目录。`app.py`（挂 /static）与 `routers/registry.py`（发 index.html）
都要它，放这里省得两边各写一份、日后改一处漏一处。"""
from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).parent / "static"
