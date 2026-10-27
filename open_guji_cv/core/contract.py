# -*- coding: utf-8 -*-
"""pipeline 与 pipeline manager 之间的契约版本（设计：doc/design/拆分-pipeline与manager.md，契约正文：doc/契约.md）。

`CONTRACT_VERSION` 是整数，**只在下面四样的格式变了、manager 需要跟着改时加一**，与 cv 版本号无关：

1. 册配置（`books/<册>.yaml`、`config/book_defaults.yaml`）的字段集合与分层规则；
2. 产物目录布局与 `_manifest.jsonl` 条目字段、`products.kinds.*` 的 schema；
3. 人裁事件与裁决表的格式；
4. 命令行（`guji-cv`）的子命令、参数、`--json` 输出与退出码。

只加可选字段（老读者忽略即可）不算变，不加。manager 声明自己支持的契约范围，装的 pipeline 超出就拒跑。
本模块不在任何 Step 的 `code_deps` 里，改它不动 19 步 `code_hash`。
"""

from __future__ import annotations

import os

#: 当前契约版本。0 = 契约成文以前的所有 cv 版本（manifest 里没有 `contract_version` 字段的老条目也按 0 算）。
CONTRACT_VERSION = 1

#: manager 在调用 pipeline 的子进程里设这个环境变量，pipeline 原样记进 manifest（仅审计，不进指纹、不参与过期判定）。
MANAGER_VERSION_ENV = "GUJI_MANAGER_VERSION"


def manager_version() -> str | None:
    return os.environ.get(MANAGER_VERSION_ENV) or None
