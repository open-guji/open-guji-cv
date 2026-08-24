"""字體渲染字形入庫（P1 語義候選層）。

把開源字體按字表渲染成 canonical 圖塊，作為**獨立來源**進字形庫：

- 每套字體一個 ``edition_tag``（``font:jigmo`` / ``font:iming`` …），
  ``sources.kind='font'``。``(edition_tag, char)`` 唯一鍵保證它和刻本
  字形永不合併，檢索時 ``GlyphDB.query(editions=[...], kinds=[...])``
  可以只挑其中一兩個庫比對，命中結果的 ``DBHit.edition_tag/kind``
  直接說明字形出自哪個庫。
- **不進 Git**：字體字形由「字體檔 + 字表」確定性重生成，
  ``export_store`` 跳過 kind='font' 的整條鏈；重建後用
  ``python -m open_guji_cv glyph-db import-font`` 重新灌。
  可復現所需的字體版本/字表記在 ``config/fonts/manifest.json``。

渲染幾何按 canonical 規範（glyph_canonical_format.md §4）：渲染到大
畫布、字面 ≤195px、四周留白，再 ``to_canonical(clean=False)`` 質心
居中——與刻本圖塊走同一條歸一路徑，兩邊才可比。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .canonical import CANON_SIZE, canonical_png, to_canonical
from .normalize import normalize_patch

RENDER_CANVAS = 384        # 渲染畫布（大於 canonical，留足白邊）
RENDER_TARGET = 190        # 目標字面高（≤ canonical 內容區 195px）
MIN_INK_PIXELS = 12        # 低於此視為空白/缺字（.notdef 多為全空或方框）


@dataclass
class FontSpec:
    """一套字體來源：可由多個 TTF 檔組成（如 Jigmo 分三檔覆蓋不同區段）。"""
    edition_tag: str          # font:jigmo
    font_paths: list[Path]    # 按優先序，先命中的檔勝出
    title: str = ""
    script_style: str = ""    # mincho / song / kai …
    license: str = ""
    notes: str = ""

    @property
    def source_id(self) -> str:
        return self.edition_tag


def font_codepoints(path: str | Path) -> set[int]:
    """字體 cmap → 碼位集合（只讀映射表，與 build_charset.py 同款）。"""
    from fontTools.ttLib import TTFont
    font = TTFont(str(path), fontNumber=0, lazy=True)
    cps: set[int] = set()
    for table in font["cmap"].tables:
        cps.update(table.cmap.keys())
    font.close()
    return cps


class FontRenderer:
    """單套字體（可多檔）的字形渲染器，緩存 PIL font 與 cmap。"""

    def __init__(self, font_paths: list[Path], target: int = RENDER_TARGET,
                 canvas: int = RENDER_CANVAS):
        from PIL import ImageFont
        self.canvas = canvas
        self.target = target
        self._fonts = []
        for p in font_paths:
            # size 給字面高的 1.15 倍：字體 em 框含上下留白，實際墨高
            # 通常只有 size 的 0.8~0.9，渲完再由 to_canonical 精確定尺
            self._fonts.append(
                (font_codepoints(p),
                 ImageFont.truetype(str(p), int(target * 1.15))))

    def has(self, char: str) -> bool:
        cp = ord(char)
        return any(cp in cps for cps, _ in self._fonts)

    def render(self, char: str) -> np.ndarray | None:
        """渲染單字 → canonical 256×256 灰度圖；缺字/空白返回 None。"""
        from PIL import Image, ImageDraw
        cp = ord(char)
        font = next((f for cps, f in self._fonts if cp in cps), None)
        if font is None:
            return None
        img = Image.new("L", (self.canvas, self.canvas), 255)
        draw = ImageDraw.Draw(img)
        bbox = draw.textbbox((0, 0), char, font=font)
        x = (self.canvas - (bbox[2] - bbox[0])) // 2 - bbox[0]
        y = (self.canvas - (bbox[3] - bbox[1])) // 2 - bbox[1]
        draw.text((x, y), char, fill=0, font=font)
        arr = np.asarray(img, dtype=np.uint8)
        if int((arr < 128).sum()) < MIN_INK_PIXELS:
            return None                      # 字體聲稱有、實際渲染為空
        # 字體本就乾淨，關掉為刻本切分寫的邊緣殘渣啟發式
        return to_canonical(arr, clean=False)


def import_font(db, spec: FontSpec, chars, batch_commit: int = 2000) -> dict:
    """按字表渲染一套字體並入庫（冪等：重跑覆寫同 instance_id）。

    每字一個實例、一個 glyph、一個 exemplar（role='render'）。
    glyph.status 一律 'sparse'——字體每字僅一形，下游據此降權。
    """
    renderer = FontRenderer([Path(p) for p in spec.font_paths])
    cur = db.conn.cursor()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    cur.execute(
        """INSERT INTO sources (source_id, collection, title, edition_tag,
             script_style, notes, kind, created_at)
           VALUES (?,?,?,?,?,?,'font',?)
           ON CONFLICT(source_id) DO UPDATE SET
             title=excluded.title, notes=excluded.notes,
             script_style=excluded.script_style, kind='font'""",
        (spec.source_id, "font", spec.title, spec.edition_tag,
         spec.script_style,
         json.dumps({"license": spec.license, "notes": spec.notes,
                     "fonts": [Path(p).name for p in spec.font_paths]},
                    ensure_ascii=False),
         now))

    n_ok = n_missing = 0
    for i, char in enumerate(chars):
        canon = renderer.render(char)
        if canon is None:
            n_missing += 1
            continue
        iid = f"{spec.edition_tag}:{ord(char):05X}"
        norm = normalize_patch(canon)
        if not norm.any():
            n_missing += 1
            continue
        cur.execute(
            """INSERT INTO instances (instance_id, source_id, page, col, idx,
                 bbox, patch_png, ink_ratio, width, height, quality_flags,
                 label, label_status, label_confidence, semantic, unicode_cp,
                 ids, updated_at)
               VALUES (?,?,'font',0,?,NULL,?,?,?,?,'[]',?,'rendered',1.0,
                       NULL,?,NULL,?)
               ON CONFLICT(instance_id) DO UPDATE SET
                 patch_png=excluded.patch_png, updated_at=excluded.updated_at""",
            (iid, spec.source_id, ord(char), canonical_png(canon, clean=False),
             float((canon < 128).mean()), float(CANON_SIZE), float(CANON_SIZE),
             char, ord(char), now))
        cur.execute(
            """INSERT INTO glyphs (edition_tag, char, semantic, unicode_cp,
                 ids, status, n_confirmed, updated_at)
               VALUES (?,?,NULL,?,NULL,'sparse',1,?)
               ON CONFLICT(edition_tag, char) DO UPDATE SET
                 updated_at=excluded.updated_at""",
            (spec.edition_tag, char, ord(char), now))
        gid = cur.execute(
            "SELECT glyph_id FROM glyphs WHERE edition_tag=? AND char=?",
            (spec.edition_tag, char)).fetchone()[0]
        cur.execute("INSERT OR REPLACE INTO exemplars VALUES (?,?,?,?)",
                    (gid, iid, "render", now))
        db._write_derived(cur, iid, norm)
        n_ok += 1
        if n_ok % batch_commit == 0:
            db.conn.commit()
    db.conn.commit()
    return {"edition": spec.edition_tag, "glyphs": n_ok,
            "missing": n_missing, "requested": len(chars)}


# ── 字表 ──────────────────────────────────────────────────

def load_charset(path: str | Path) -> list[str]:
    """字表檔 → 字列表。

    支持兩種格式：每行一個字的純文本，或 charset.ranges.tsv
    （``start<TAB>end`` 十六進制碼位區間，# 開頭為註釋）。
    """
    p = Path(path)
    chars: list[str] = []
    seen: set[int] = set()
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) >= 2 and all(_parse_cp(x) is not None for x in parts[:2]):
            lo, hi = _parse_cp(parts[0]), _parse_cp(parts[1])
            for cp in range(lo, hi + 1):
                if cp not in seen:
                    seen.add(cp)
                    chars.append(chr(cp))
        else:
            for ch in parts[0]:
                if ord(ch) not in seen:
                    seen.add(ord(ch))
                    chars.append(ch)
    return chars


def load_manifest(path: str | Path) -> tuple[list[FontSpec], dict]:
    """字體清單 JSON → (FontSpec 列表, 全局設定)。

    清單只記**去哪找字體**與版本信息，字體檔本身不進倉庫；
    ``font_paths`` 支持 ``$VAR`` 與 ``~`` 展開，缺檔的條目原樣返回，
    由調用方決定是跳過還是報錯。
    """
    import os
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    specs = []
    for f in data.get("fonts", []):
        paths = [Path(os.path.expandvars(p)).expanduser()
                 for p in f["font_paths"]]
        specs.append(FontSpec(
            edition_tag=f["edition_tag"], font_paths=paths,
            title=f.get("title", ""), script_style=f.get("script_style", ""),
            license=f.get("license", ""), notes=f.get("notes", "")))
    return specs, data


def import_fonts_from_manifest(db, manifest_path: str | Path,
                               only: str | None = None,
                               charset: str | Path | None = None,
                               limit: int | None = None) -> dict:
    """按清單批量導入字體字形。缺失字體檔的條目跳過並記在結果裡。"""
    specs, data = load_manifest(manifest_path)
    if only:
        specs = [s for s in specs if s.edition_tag == only]
        if not specs:
            raise SystemExit(f"清單裡沒有 edition_tag={only}")
    chars = load_charset(charset or data["charset"])
    if limit:
        chars = chars[:limit]
    results, skipped = [], []
    for spec in specs:
        missing_files = [str(p) for p in spec.font_paths if not p.exists()]
        if missing_files:
            skipped.append({"edition": spec.edition_tag,
                            "missing_files": missing_files})
            continue
        results.append(import_font(db, spec, chars))
    return {"charset_size": len(chars), "imported": results,
            "skipped": skipped}


def _parse_cp(s: str) -> int | None:
    """``U+4E00`` / ``0x4E00`` / ``4E00`` → 碼位；不是碼位返回 None。"""
    s = s.strip().removeprefix("U+").removeprefix("0x")
    if not s:
        return None
    try:
        return int(s, 16)
    except ValueError:
        return None
