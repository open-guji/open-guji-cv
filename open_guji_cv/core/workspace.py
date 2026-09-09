# -*- coding: utf-8 -*-
"""工作区路径解析：把「引擎」与「某本书的数据」分开。

## 为什么有这个模块

`open-guji-cv` 是识别引擎，不该自带某一本书的原图与字形库。
《四庫全書總目》那套数据（原图 134 MB、字形库 88 MB、产物 86 MB）已迁到
`siku-zongmu-workspace` 私有仓；引擎这边只留一个小样本库供测试。

于是路径要能指向别处。解析顺序（先到先得）：

1. 环境变量 —— `GUJI_GLYPH_DB` / `GUJI_GLYPH_STORE` / `GUJI_WORKSPACE`
2. 册配置 —— `books/<book>.yaml` 里的 `glyph_db` / `glyph_store`（可相对 workspace）
3. 仓内默认 —— `output/glyph.db`、`output/glyph_store/`（样本库，够跑测试）

`GUJI_WORKSPACE` 是最省事的一个：指到工作区仓根，库与产物都按约定布局往下找。

## 用法

```bash
# 跑真书：指向工作区仓
export GUJI_WORKSPACE=/d/workspace/siku-zongmu-workspace
guji pipeline keben_body_v2 vol01 --pages dev_set

# 跑测试：什么都不设，用仓内样本库
pytest tests/ -s -p no:cacheprovider
```

⚠️ **库路径变了，产物就该过期**——`glyph_match` / `seed_admit` 的指纹带库指纹，
换库等于换了上游。这是对的，不是 bug。
"""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# 工作区内的约定布局（与仓内 output/ 保持一致，迁移时不必改结构）
GLYPH_DB_REL = "output/glyph.db"
GLYPH_STORE_REL = "output/glyph_store"


def workspace_root() -> Path | None:
    """`GUJI_WORKSPACE` 指向的工作区仓根；没设返回 None（用仓内默认）。"""
    env = os.environ.get("GUJI_WORKSPACE")
    return Path(env).expanduser().resolve() if env else None


def _resolve(env_key: str, rel: str, override: str | Path | None = None) -> Path:
    """环境变量 > 显式覆盖 > 工作区 > 仓内默认。"""
    env = os.environ.get(env_key)
    if env:
        return Path(env).expanduser()
    if override:
        p = Path(override).expanduser()
        # 相对路径按工作区解释，没有工作区就按仓根
        return p if p.is_absolute() else (workspace_root() or REPO_ROOT) / p
    ws = workspace_root()
    if ws:
        return ws / rel
    return REPO_ROOT / rel


def glyph_db_path(override: str | Path | None = None) -> Path:
    """字形库 SQLite 索引。可重建，不进 git。"""
    return _resolve("GUJI_GLYPH_DB", GLYPH_DB_REL, override)


def glyph_store_path(override: str | Path | None = None) -> Path:
    """字形库真源（PNG + JSONL），进 git。"""
    return _resolve("GUJI_GLYPH_STORE", GLYPH_STORE_REL, override)


def raw_root(override: str | Path | None = None) -> Path:
    """原图根目录。册配置里的 `raw_dir` 相对它解释。"""
    env = os.environ.get("GUJI_RAW_ROOT")
    if env:
        return Path(env).expanduser()
    if override:
        p = Path(override).expanduser()
        return p if p.is_absolute() else (workspace_root() or REPO_ROOT) / p
    return workspace_root() or REPO_ROOT


def describe() -> dict[str, str]:
    """当前解析结果，供控制台与诊断打印——路径错了要看得见。"""
    ws = workspace_root()
    return {
        "workspace": str(ws) if ws else "(未设 GUJI_WORKSPACE，用仓内默认)",
        "glyph_db": str(glyph_db_path()),
        "glyph_store": str(glyph_store_path()),
        "raw_root": str(raw_root()),
    }
