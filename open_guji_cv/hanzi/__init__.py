# -*- coding: utf-8 -*-
"""自建汉字关系库（替代字统网）：字、关系边、IDS 与部件、形近对，离线、按版本钉住。

设计见 `doc/design/汉字字形与关系库-总设计.md`；需求见同目录「需求起点」。
L0 包，只用标准库，不 import cv 的其他包（以后可整个目录搬去独立仓）。
不在任何 Step 的 `code_deps` 里：换库不让产物过期。
"""
from .db import Edge, HanziDB, shared  # noqa: F401
from .schema import FAMILY_RELS, RELS  # noqa: F401
