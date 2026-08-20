"""M1 字符提取：Phase 3 字符网格 → 单字图块数据集（phase4_chars/）。

本模块之后，下游不再需要读取整页图像与版面 JSON。

输出：
  phase4_chars/
    index.jsonl                     每行一个 CharInstance
    patches/{page}/{col}_{idx}.png  灰度图块（bbox 外扩 padding）
    meta.json                       参数快照 + 统计
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path

import cv2
import numpy as np

from ..utils.image_io import imread, imwrite
from .ids import make_id

PADDING_RATIO = 0.08
MIN_INK_RATIO = 0.01

# 灰度源目录解析顺序：越靠前的越接近原始灰度（信息保留最多）。
# 注意：只有与 Phase 2/3 检测坐标系同尺寸的步骤才能入选
# （s3_crop 裁剪之后的步骤同尺寸；s4_enhance_lines 有画线增强，不作字形源）。
SOURCE_DIR_CANDIDATES = ("s5_split", "s4_deskew", "s3_crop", "s6_binarize")


@dataclass
class CharInstance:
    """单字实例元数据（index.jsonl 的一行）。"""
    id: str
    book: str
    page: str
    col: int
    idx: int
    bbox: tuple[float, float, float, float]   # 页面坐标 (x0, y0, x1, y1)，含 padding
    cell_type: str                            # "char"
    ocr_text: str | None                      # Phase3 整列 OCR 对位字（弱先验）
    ocr_confidence: float
    patch_path: str                           # 相对 phase4_chars/ 的路径
    ink_ratio: float
    height: float                             # bbox 高（不含 padding）
    width: float
    flags: list[str]                          # ["suspect_empty", "bad_seg", ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, line: str) -> "CharInstance":
        d = json.loads(line)
        d["bbox"] = tuple(d["bbox"])
        return cls(**d)


def _patch_ink_ratio(gray: np.ndarray) -> float:
    """Otsu 二值化后的暗像素占比（粗略墨迹密度，供分块与异常过滤）。"""
    if gray.size == 0:
        return 0.0
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return float(np.count_nonzero(binary)) / binary.size


class CharExtractor:
    """从整页灰度图 + phase3 网格 JSON 提取单字图块。"""

    def __init__(self, padding_ratio: float = PADDING_RATIO,
                 min_ink_ratio: float = MIN_INK_RATIO):
        self.padding_ratio = padding_ratio
        self.min_ink_ratio = min_ink_ratio

    # ── 纯函数核心 ────────────────────────────────────────

    def extract_page(self, page_img: np.ndarray, grid: dict,
                     book: str, page: str
                     ) -> list[tuple[CharInstance, np.ndarray]]:
        """输入整页图 + phase3 grid JSON，输出 (实例, 图块) 列表。

        坐标系约定：grid 中的坐标即 page_img 的像素坐标
        （Phase 3 在最终预处理图上检测，本函数输入必须是同一坐标系的图）。
        """
        if page_img.ndim == 3:
            page_img = cv2.cvtColor(page_img, cv2.COLOR_BGR2GRAY)
        img_h, img_w = page_img.shape[:2]
        results: list[tuple[CharInstance, np.ndarray]] = []

        for col in grid.get("columns", []):
            col_no = int(col["index"])
            left_x = float(col["left_x"])
            right_x = float(col["right_x"])
            col_w = right_x - left_x

            for cell in col.get("cells", []):
                if cell.get("type") != "char":
                    continue
                idx = int(cell["index"])
                y_top = float(cell["y_top"])
                y_bottom = float(cell["y_bottom"])
                cell_h = y_bottom - y_top

                # 垂直方向外扩（笔画出头）；水平方向内缩——列边界即界行位置，
                # 外扩会把界行竖线裹进图块，污染归一化的质心与外接框。
                pad_y = cell_h * self.padding_ratio
                shrink_x = min(col_w * 0.03, 4.0)
                x0 = max(0.0, left_x + shrink_x)
                x1 = min(float(img_w), right_x - shrink_x)
                y0 = max(0.0, y_top - pad_y)
                y1 = min(float(img_h), y_bottom + pad_y)

                ix0, iy0 = int(round(x0)), int(round(y0))
                ix1, iy1 = int(round(x1)), int(round(y1))
                if ix1 <= ix0 or iy1 <= iy0:
                    continue
                patch = page_img[iy0:iy1, ix0:ix1].copy()

                ink = _patch_ink_ratio(patch)
                flags: list[str] = []
                if ink < self.min_ink_ratio:
                    flags.append("suspect_empty")
                # 切分异常提示：字块长宽比离谱（粘连/切半）
                aspect = cell_h / max(col_w, 1e-6)
                if aspect > 1.8 or aspect < 0.3:
                    flags.append("bad_seg")

                inst = CharInstance(
                    id=make_id(book, page, col_no, idx),
                    book=book, page=page, col=col_no, idx=idx,
                    bbox=(x0, y0, x1, y1),
                    cell_type="char",
                    ocr_text=cell.get("text") or None,
                    ocr_confidence=float(cell.get("confidence", 0.0)),
                    patch_path=f"patches/{page}/{col_no}_{idx}.png",
                    ink_ratio=round(ink, 4),
                    height=round(cell_h, 2),
                    width=round(col_w, 2),
                    flags=flags,
                )
                results.append((inst, patch))
        return results

    # ── IO 壳 ────────────────────────────────────────────

    def run_book(self, book_out_dir: Path, source_dir: Path | None = None,
                 name_filter: set[str] | None = None) -> dict:
        """遍历 phase3_char_grid/*_char_grid.json，写 phase4_chars/。

        Args:
            book_out_dir: output/bookX/
            source_dir: 页面图目录；缺省时按 SOURCE_DIR_CANDIDATES 顺序解析。
        Returns:
            meta 统计 dict。
        """
        book_out_dir = Path(book_out_dir)
        book = book_out_dir.name
        grid_dir = book_out_dir / "phase3_char_grid"
        grid_files = sorted(grid_dir.glob("*_char_grid.json"))
        if name_filter is not None:
            grid_files = [f for f in grid_files
                          if f.stem.replace("_char_grid", "") in name_filter]
        if not grid_files:
            raise FileNotFoundError(f"未找到字符网格 JSON: {grid_dir}（请先运行 extract）")

        src = Path(source_dir) if source_dir else self._resolve_source_dir(book_out_dir)

        out_dir = book_out_dir / "phase4_chars"
        out_dir.mkdir(parents=True, exist_ok=True)

        n_pages = n_chars = n_flagged = 0
        index_path = out_dir / "index.jsonl"
        with open(index_path, "w", encoding="utf-8") as index_f:
            for gf in grid_files:
                page = gf.stem.replace("_char_grid", "")
                img_path = self._find_page_image(src, page)
                if img_path is None:
                    print(f"  跳过 {page}: 在 {src} 中找不到页面图")
                    continue
                page_img = imread(str(img_path))
                if page_img is None:
                    print(f"  跳过 {page}: 读取失败")
                    continue
                with open(gf, "r", encoding="utf-8") as f:
                    grid = json.load(f)

                page_patch_dir = out_dir / "patches" / page
                page_patch_dir.mkdir(parents=True, exist_ok=True)
                for inst, patch in self.extract_page(page_img, grid, book, page):
                    imwrite(str(out_dir / inst.patch_path), patch)
                    index_f.write(inst.to_json() + "\n")
                    n_chars += 1
                    if inst.flags:
                        n_flagged += 1
                n_pages += 1

        meta = {
            "book": book,
            "source_dir": str(src),
            "params": {"padding_ratio": self.padding_ratio,
                       "min_ink_ratio": self.min_ink_ratio},
            "stats": {"pages": n_pages, "chars": n_chars, "flagged": n_flagged},
        }
        with open(out_dir / "meta.json", "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        return meta

    @staticmethod
    def _resolve_source_dir(book_out_dir: Path) -> Path:
        for name in SOURCE_DIR_CANDIDATES:
            d = book_out_dir / name
            if d.is_dir() and any(d.glob("*.png")):
                return d
        # 兜底：预处理用了 --clean 时最终图直接在书目录下
        if any(book_out_dir.glob("*.png")):
            return book_out_dir
        raise FileNotFoundError(
            f"未找到页面图目录（尝试了 {SOURCE_DIR_CANDIDATES}），"
            f"请用 --input-dir 指定: {book_out_dir}")

    @staticmethod
    def _find_page_image(src: Path, page: str) -> Path | None:
        for ext in (".png", ".jpg", ".jpeg"):
            p = src / f"{page}{ext}"
            if p.exists():
                return p
        return None


def load_index(phase4_dir: Path) -> list[CharInstance]:
    """读取 phase4_chars/index.jsonl。"""
    path = Path(phase4_dir) / "index.jsonl"
    with open(path, "r", encoding="utf-8") as f:
        return [CharInstance.from_json(line) for line in f if line.strip()]
