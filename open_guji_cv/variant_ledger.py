"""本书用字账（层 4）：``config/variants/books/<edition>.json`` 的读取与查询。

这就是「关于本书常用哪个异体字的资料库」（variant_strategy.md §3.2）。**只由
``scripts/build_book_variants.py`` 从产物派生，永不手编**；本模块只读。

三层表里它居中：关系层（``variants.py``，字典知识，有噪声）→ **用字账**（这本书
刻了哪些形、整理本印了哪些形、转换对的次数与来源）→ 语义层（``VariantMap``，
LM / 准入用的代表字，从前两层派生）。

## 一条记录长什么样

```
"髮": {                               # 键 = canonical（跨书统一键）
  "canonical": "髮",
  "members": ["髪", "髮"],            # 组内在本书或整理本里出现过的形
  "forms": {
    "髪": {"book": {"products": 14, "db": 17, "human": 3, "align": 0},
           "ref": 0, "tier": "T1", "sources": ["twedu", "yitizi"]},
    "髮": {"book": {...}, "ref": 41, "tier": null, "sources": []}
  },
  "pairs": {"髪→髮": {"n": 17, "human": 3, "auto": 14,
                     "channels": {"match_replace": 14}, "first": "vol01:60:4:15"}},
  "ref_policy": "single",             # 整理本对这一组：single 归一 / multi 保留区分 / none
  "preferred": "髪"                    # 刻本最常刻的形
}
```

``book`` 四个计数分来源：``products``（v2 seed_admit 自动放行）、``db``（glyph.db
全部实例）、``human``（其中人裁的）、``align``（其中 v1 整理本对齐直接贴的标签——
最不可信，它本来就是整理本形）。**读数先看 human，再看 products/db，别信 align。**

## 用字账是先验不是规则

本书 髪 ×17 不禁止第 18 次刻 髮，只是让它进组视图而不是自动放行
（glyph_set_roadmap.md §6 的口径）。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

LEDGER_DIR = Path(__file__).resolve().parents[1] / "config" / "variants" / "books"
SCHEMA_VERSION = 1

#: 本项目现在只有一套书：武英殿本《欽定四庫全書總目》卷首（vol01 / vol02）。
#: 书目 yaml 的 ``edition`` 是 "keben" 这种粗类，不够当账本键，先用常量。
DEFAULT_EDITION = "wuyingdian_zongmu"

_HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿"
                  r"\U00020000-\U0003347f]")


def han_counter(text: str) -> Counter:
    """文本 → 汉字字频（含扩展区与兼容区；标点、空白、拉丁全不算）。"""
    return Counter(_HAN.findall(text))


def ledger_path(edition: str = DEFAULT_EDITION) -> Path:
    return LEDGER_DIR / f"{edition}.json"


class BookLedger:
    """只读查询。``groups`` 是文件里的 ``groups`` 节；``form_index`` 形 → canonical。"""

    def __init__(self, doc: dict):
        self.meta: dict = doc.get("meta", {})
        self.groups: dict[str, dict] = doc.get("groups", {})
        self.unknown_pairs: list[dict] = doc.get("unknown_pairs", [])
        idx: dict[str, str] = {}
        for canon, g in self.groups.items():
            for m in g.get("members", []):
                idx[m] = canon
        self.form_index = idx

    @classmethod
    def load(cls, edition: str = DEFAULT_EDITION,
             path: str | Path | None = None) -> "BookLedger":
        p = Path(path) if path else ledger_path(edition)
        if not p.exists():
            raise FileNotFoundError(
                f"找不到用字账 {p}——先跑 python scripts/build_book_variants.py")
        return cls(json.loads(p.read_text(encoding="utf-8")))

    @classmethod
    def load_or_empty(cls, edition: str = DEFAULT_EDITION) -> "BookLedger":
        """没有账本时返回空账（所有查询都答「不知道」），别让消费方崩。"""
        try:
            return cls.load(edition)
        except FileNotFoundError:
            return cls({"meta": {"edition": edition, "empty": True}, "groups": {}})

    def __len__(self) -> int:
        return len(self.groups)

    def group_of(self, form: str) -> dict | None:
        """形所在的组（没有记录 → None）。"""
        canon = self.form_index.get(form)
        return self.groups.get(canon) if canon else None

    def canonical(self, form: str) -> str:
        return self.form_index.get(form, form)

    def same_group(self, a: str, b: str) -> bool:
        ca, cb = self.form_index.get(a), self.form_index.get(b)
        return ca is not None and ca == cb

    def ref_policy(self, form: str) -> str | None:
        g = self.group_of(form)
        return g.get("ref_policy") if g else None

    def preferred_form(self, form: str) -> str | None:
        g = self.group_of(form)
        return g.get("preferred") if g else None

    def book_count(self, form: str, key: str = "db") -> int:
        g = self.group_of(form)
        if not g:
            return 0
        return int(g.get("forms", {}).get(form, {}).get("book", {}).get(key, 0))

    def human_confirmed(self, form: str) -> int:
        """这个形被人确认过几次（``book.human``）。首例判定用它。"""
        return self.book_count(form, "human")

    def pair(self, shape: str, reading: str) -> dict | None:
        """(刻本形 → 整理本形) 这对转换的记录（没有 → None）。"""
        g = self.group_of(shape)
        if not g:
            return None
        return g.get("pairs", {}).get(f"{shape}→{reading}")

    def pair_confirmed(self, shape: str, reading: str) -> bool:
        p = self.pair(shape, reading)
        return bool(p and p.get("human", 0) > 0)


@lru_cache(maxsize=4)
def ledger(edition: str = DEFAULT_EDITION) -> BookLedger:
    """进程内缓存的只读账本；文件没有时是空账。"""
    return BookLedger.load_or_empty(edition)
