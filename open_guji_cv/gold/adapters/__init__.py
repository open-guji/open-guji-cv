"""旧格式适配器：让 GoldStore 先能**读**全部既有分片，再逐个迁成 items.jsonl。

四种载体（2026-09-03 普查）：

| 载体 | 形态 | 分片 |
|---|---|---|
| `samples_dir` | `samples/NNN/expected.json` 或 `samples/<key>.json` | book-profile、column-layout、page-geometry、cells、column-warp… 共 15 个 |
| `flat_expected` | 一个大 `expected.json`（数组或对象） | page-type、instances、glyph-match/{pairs,triplets} |
| `verdicts` | `verdicts_*.jsonl` 一行一裁决 | border-detection/column-split |
| `labels_dict` | 标注表写在 `scripts/build_*_dataset.py` 的字典里 | 只读，迁移时人工搬 |

适配器只做一件事：把各自的行/文件读成 `GoldItem`。**不猜语义**——认不出的字段
原样塞进 `expected`，让迁移的人看得见。迁完一个分片就把它的适配器从 `sniff` 里摘掉。
"""

from .base import Adapter, detect, load_shard  # noqa: F401
from .cases import CasesAdapter  # noqa: F401
from .flat_expected import FlatExpectedAdapter  # noqa: F401
from .samples_dir import SamplesDirAdapter  # noqa: F401
from .verdicts import VerdictsAdapter  # noqa: F401
