"""发前清格（书级钩子）的缺省实现：不清，字块原样发。

2026-11-10 SJ（Sheldon 定「严格防切错」、切分快筛的装饰类）：格框不动、格号不变，出字块前把不属于本格的墨抹白——
上下邻格伸进框里的边角残笔、界行竖线、版框横线。这一步得排在字形库收样本之前。哪些墨算外来、抹到什么程度是书的事
（写本连笔多、刻本少），所以做成书级钩子：缺省什么都不做，殿本等书产物不变；史記书仓 `code/patch_clean.py` 覆盖。

覆盖本模块的书级代码要给出同名的 `clean_column`：

    clean_column(img, pairs, ink_threshold=128) -> pairs

- `img`：本列列图（灰度，`cell_shrink` 抽字用的那张，已剥内框细线）。
- `pairs`：`CharExtractor.extract_page` 的结果 `[(CharInstance, patch | None), …]`；`inst.bbox` 是列图坐标、与 patch 一一对应。
- 返回同长同序的新表：只许抹白 patch 里的像素、按剩下的墨收紧 patch 与 `inst.bbox`（并更新 `inst.ink_ratio`），
  不许增删格、不许改 `idx`/`sub`/`cell_type`。职名列（`_roster_crops`）不走本钩子。
"""
from __future__ import annotations

#: None＝不清（缺省）。
clean_column = None
