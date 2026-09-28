# -*- coding: utf-8 -*-
"""控制台进程里不许现建大模板索引（服务器值守 2026-09-28，用户 overview#237）。

## 为什么

字体 HOG 索引（`font_candidates._index`）与 CNN embedding 索引
（`cnn_candidates._emb_index`）都是「字表 × 字体」渲染后提特征，缺盘时现建：
服务器实测 HOG 大表（28,115 字）峰值 **5.58 GB**、embedding 大表约 3 GB、几十分钟。
控制台的内存上限是 3–4 G，只要触发一次就被 cgroup 节流到连一张字块图都取不出来，
用户看到的是「提交很久、图出不来、卡住了」。字体指纹、字表（整理本语料）、
checkpoint 任一变化都会让 key 变、旧盘失效——换一本书审、发一版代码都可能触发。

## 做法

控制台的 EnvironmentFile 设 `GUJI_FORBID_INLINE_INDEX=1`：缺盘的**大**表直接抛
`IndexNotBuilt`（HTTP 503「暂不可用」），不建；由离线命令预建后再用：

    guji cache build-rare-index --book <书> -w <工作区>     # CNN embedding（生僻字面板/5-b）
    guji cache build-font-index -w <工作区>                 # 字体 HOG（仅 CNN 不可用时才用得到）

小表（`variant_form` 组内 2–4 字的 closed-set 之类）照常现建——毫秒级、不占内存。
跑批与 CLI 不设这个变量，行为不变。
"""
from __future__ import annotations

import os

#: 超过这么多字的表才拦。组内异体 closed-set、IDS 兜底那些都是个位数到几百字。
INLINE_LIMIT = 2000


def forbid_inline_build(kind: str, n_chars: int, path) -> None:
    """缺盘时调用：设了 `GUJI_FORBID_INLINE_INDEX=1` 且表够大 → 抛 `IndexNotBuilt`。"""
    if os.environ.get("GUJI_FORBID_INLINE_INDEX") != "1" or n_chars <= INLINE_LIMIT:
        return
    from ..errors import IndexNotBuilt
    raise IndexNotBuilt(
        f"{kind} 索引没有预建（{n_chars} 字，缺 {path}），控制台不现建"
        f"（现建要几 GB 内存，会拖死平台）。请离线预建："
        f"`guji cache build-rare-index`／`build-font-index`。")
