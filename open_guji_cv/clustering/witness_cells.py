# -*- coding: utf-8 -*-
"""一页字位 × 一份证人 → 每个字位在证人里读作哪个字（overview#433，R2 道）。

seed_admit 的「三证人一致」「坐标对位兜底」两条放行通道（`SeedAdmitParams.lane_witness3` /
`lane_coord`）要逐格知道 daizhige 逐列本（D）、四库光盘版（W）、杳冥本（Y）各自在这一位写的什么。
`align_ref` 只用 `references[0]` 一家（legacy），产物里没有别家证人的逐格读法；9.3 对勘
（`report/collate.diff_page`）三家都对，但只出差异、且吃的是 Step7 之后的字位流。所以这里
照 `diff_page` 的配对口径单写一份，只出 `{字位 id: 证人字}`：

- 8-gram 锚定用 `clustering.align_eval.anchor_page`（与 9.3 同一把尺子），锚不上 → 空表；
- 归语义层再 difflib（归一后长度变了退回原字，同 `diff_page`）；
- `equal` 段逐位配；不等长 `replace` 段只配等长那一截，**页首**那段跟窗口末尾配齐
  （页首余量，`diff_page` 同款）；`insert`/`delete` 的位不配——证人在这一位「没有」，
  调用方当缺席（不是「证人说空格」）。

纯函数，不读产物、不碰库；证人装载与缓存在调用方（`steps.align_ref._witnesses_for_book`）。
"""
from __future__ import annotations

import difflib

from .align_eval import WINDOW_PAD, anchor_page


def witness_readings(seq: list[tuple[str, str]], text: str, index: dict,
                     normalize=None, pad: int = WINDOW_PAD) -> dict[str, str]:
    """`seq` = 本页按阅读顺序的 `(字位 id, 锚定字)`；`text`/`index` = 证人汉字流与 8-gram 索引。

    `normalize`：语义层归一函数（`VariantMap.normalize_text`），None = 按原字比。
    返回 `{字位 id: 证人在这一位的字}`；锚不上 → `{}`。"""
    if not seq:
        return {}
    q = "".join(c for _i, c in seq)
    offset = anchor_page(q, index)
    if offset is None:
        return {}
    lo, hi = max(0, offset - pad), min(len(text), offset + len(q) + pad)
    window = text[lo:hi]
    qn, wn = q, window
    if normalize is not None:
        qn, wn = normalize(q), normalize(window)
        if len(qn) != len(q) or len(wn) != len(window):
            qn, wn = q, window
    out: dict[str, str] = {}
    sm = difflib.SequenceMatcher(None, qn, wn, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                out[seq[i1 + k][0]] = window[j1 + k]
        elif tag == "replace":
            n = min(i2 - i1, j2 - j1)
            jb = (j2 - n) if i1 == 0 else j1
            for k in range(n):
                out[seq[i1 + k][0]] = window[jb + k]
    return out
