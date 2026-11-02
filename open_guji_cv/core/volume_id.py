"""册号：书 id、册序、各层的册号写法（2026-11-02，sheldon 定；A31）。

## 为什么

同一册在系统里有好几种写法：cv 册名（`vol04`、`bxgb`、`01`）、R2 页表与 IIIF（`04`）、book-text 章号
与进度表、待审单（`004`）。以前各处都从**册名字符串**现推（`vol04` → `004`），规则只认殿本的 `volNN`，
别的书走到这些地方就错：北行 `bxgb` 被推成章号 `000`，进度表写出错行。

## 规定

- 册序是整数，写在册 yaml 的 `volume:`；书 id 写在 `book_id:`（可写在工作区基础配置 `config/book_defaults.yaml`）。
- **位数按全书册数定，全书统一，最少 2 位**（`volume_width:`，写在基础配置）：99 册以内 2 位，100–999 册 3 位。
  R2 页表、IIIF、新书的 cv 册名都用这个位数（`vol_label`）。
- book-text 章号（`chapter_of`）缺省同册号位数；已上线的书（殿本、北行）章号是 3 位，基础配置写
  `chapter_width: 3`，不改——网站链接、精校票、待审单 rev 都挂在章号上。
- 册 yaml 没写 `volume` 的老册：册名是 `volNN` 的按 NN 算（章号 3 位，与以前一样）；册名是纯数字的按数字算；
  都不是就认不出（返回 None），调用方要显式给 `--chapter`，**不再推成 `000`**。

只读 yaml，不进任何 Step 的指纹。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_VOL = re.compile(r"vol(\d+)")
_NUM = re.compile(r"\d+")
LEGACY_CHAPTER_WIDTH = 3
MIN_WIDTH = 2


@dataclass(frozen=True)
class VolumeId:
    book: str                   # cv 册名
    book_id: str | None         # book-index 书 id（10 位）
    volume: int | None          # 册序（从 1 起）
    width: int                  # 册号位数（R2、IIIF、新书册名）
    chapter_width: int          # book-text 章号位数

    @property
    def label(self) -> str | None:
        return None if self.volume is None else vol_label(self.volume, self.width)

    @property
    def chapter(self) -> str | None:
        return None if self.volume is None else vol_label(self.volume, self.chapter_width)


def width_for(total: int) -> int:
    """全书册数 → 册号位数（最少 2 位）。"""
    return max(MIN_WIDTH, len(str(max(1, int(total)))))


def vol_label(n: int, width: int = MIN_WIDTH) -> str:
    return str(int(n)).zfill(max(MIN_WIDTH, int(width)))


def from_dict(book: str, d: dict | None) -> VolumeId:
    """册名 + 生效的册配置（册 yaml ∪ 基础配置）→ VolumeId。纯函数，单测用它。"""
    d = d or {}
    vol = d.get("volume")
    legacy = False
    if vol is None:
        m = _VOL.fullmatch(book or "")
        if m:
            vol, legacy = int(m.group(1)), True
        elif _NUM.fullmatch(book or ""):
            vol = int(book)
    vol = None if vol is None else int(vol)
    width = int(d.get("volume_width") or (len(book) if _NUM.fullmatch(book or "") else MIN_WIDTH))
    cw = d.get("chapter_width")
    cw = int(cw) if cw else (LEGACY_CHAPTER_WIDTH if legacy else width)
    bid = d.get("book_id")
    return VolumeId(book=book, book_id=str(bid) if bid else None, volume=vol,
                    width=max(MIN_WIDTH, width), chapter_width=max(MIN_WIDTH, cw))


def volume_of(book: str, books_dir: Path | None = None) -> VolumeId:
    """读工作区里这册的生效配置；读不到 yaml 就只按册名推。"""
    d: dict = {}
    try:
        from .book import _book_yaml_path
        from .book_config import effective_book_dict
        p = _book_yaml_path(book, books_dir)
        if p.exists():
            d = effective_book_dict(p, apply_override=False)
    except Exception:  # noqa: BLE001 —— 没设工作区、yaml 坏了：退回按册名推
        d = {}
    return from_dict(book, d)


def chapter_of(book: str, chapter: str | None = None, books_dir: Path | None = None) -> str | None:
    """book-text 章号：显式给了就用；否则按册配置；认不出 → None（不再推成 000）。"""
    if chapter:
        return chapter
    return volume_of(book, books_dir).chapter
