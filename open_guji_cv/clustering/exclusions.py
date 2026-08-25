# -*- coding: utf-8 -*-
"""图块排除名单：被判为「切分有残留/被切坏」而不参与匹配与进库的实例。

## 为什么是名单而不是删除

2026-08-25 用户定的口径：**现在的扫描件质量低，后面会有更高质量的图；
所以现阶段有问题的图块一律保守处理，尽量移出测试集、移出库。**

「移出」做成名单而不是物理删，正是因为**后面会重扫**：重扫之后要能一条条
拿回来重判。删掉就再也不知道当初排除了谁、为什么排除，也没法对着新图
验证「这一条现在干净了没有」。名单是可逆的，删除不是。

## 谁来查这份名单

- 数据集构建（`build_match_pairs_dataset.py` 等）：建集时跳过；
- 评测脚本：对**已冻结**的集在评测时跳过（不必重建集就能生效，
  而且能同时报「排除前 / 排除后」两个数）；
- 进库准入与 `glyph.db` 撤库（`scripts/apply_crop_exclusions.py`）。

## 每条记什么

`instance_id` / `reason` / `evidence`（触发的旗标）/ `origin`（human 还是
gate）/ `round` / `date`。**origin 必须留着**：human 那批是人眼实锤，
gate 那批按出库裁决标定只有约 27% 是真有问题——两批的证据强度差着量级，
将来重扫复核时先复核 gate 那批。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "crop_exclusions.jsonl"


@lru_cache(maxsize=4)
def load_exclusions(path: str | Path = DEFAULT_PATH) -> dict[str, dict]:
    """→ {instance_id: 记录}。名单不存在时返回空字典（不是错误）。"""
    p = Path(path)
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["instance_id"]] = r
    return out


def excluded_ids(path: str | Path = DEFAULT_PATH,
                 origins: tuple[str, ...] | None = None) -> frozenset[str]:
    """排除名单的实例 id 集合；`origins` 可只取某几个来源（如只取 human）。"""
    ex = load_exclusions(path)
    if origins is None:
        return frozenset(ex)
    return frozenset(k for k, v in ex.items() if v.get("origin") in origins)
