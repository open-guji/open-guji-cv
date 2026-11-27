"""册号：书 id、册序、各层的册号写法（2026-11-02，sheldon 定；A31）。

## 为什么

同一册在系统里有好几种写法：cv 册名（`vol04`、`bxgb`、`01`）、R2 页表与 IIIF（`04`）、book-text 章号
与进度表、待审单（`004`）。以前各处都从**册名字符串**现推（`vol04` → `004`），规则只认殿本的 `volNN`，
别的书走到这些地方就错：北行 `bxgb` 被推成章号 `000`，进度表写出错行。

## 规定

- 册序是整数，写在册 yaml 的 `volume:`；书 id 写在 `book_id:`（可写在工作区基础配置 `config/book_defaults.yaml`）。
- **位数按全书总册数定，全书统一**（2026-11-27 用户定，取代 11-02 的「最少 2 位」）：1–9 册 1 位，10–99 册 2 位，
  100–999 册 3 位（`width_for`）。写在基础配置 `volume_width:`；可另写 `volume_total:`（全书册数）供核对。
- 一部书只有这一个位数：R2 页表、IIIF、新书 cv 册名、book-text 章号、待审单与 rev、进度表、网站地址都用它。
  `chapter_width` 作废：没写就等于 `volume_width`；迁移期间还没改号的书（殿本、史記、脉经、北行、朱楓林集）
  照旧写着，照旧生效，`chapter_mismatch` 为真。
- **册的身份是整数册序，补零只是写法**：比对册号一律按数值（`same_volume`），1、01、001 是同一册。
- 没写 `volume_width` 的老书：册名纯数字的按册名长度，否则 2 位（不静默改号）。
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
LEGACY_DEFAULT_WIDTH = 2    # 没写 volume_width、册名又不是纯数字的老书
MIN_WIDTH = 1


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

    @property
    def chapter_mismatch(self) -> bool:
        """章号位数与册号位数不同（还没按 11-27 规矩迁移的书）。"""
        return self.chapter_width != self.width


def width_for(total: int) -> int:
    """全书册数 → 册号位数：1–9 册 1 位，10–99 册 2 位，100–999 册 3 位（用户 11-27）。"""
    return len(str(max(1, int(total))))


def vol_label(n: int, width: int = LEGACY_DEFAULT_WIDTH) -> str:
    return str(int(n)).zfill(max(MIN_WIDTH, int(width)))


def same_volume(a: str | int | None, b: str | int | None) -> bool:
    """两个册号是否同一册：字面相同，或都是纯数字、数值相同（1、01、001 同一册）。"""
    if a is None or b is None:
        return False
    a, b = str(a), str(b)
    return a == b or (_NUM.fullmatch(a) is not None and _NUM.fullmatch(b) is not None and int(a) == int(b))


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
    width = int(d.get("volume_width") or (len(book) if _NUM.fullmatch(book or "") else LEGACY_DEFAULT_WIDTH))
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
