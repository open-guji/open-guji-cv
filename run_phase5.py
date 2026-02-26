"""Phase 5: 对欽定四庫全書簡明目錄全部 10 册运行 OCR pipeline。

输入：WSL 路径下的图片 + ce0X_page_layout.json（页面分类）
输出：每页一个 JSON，格式为 {page_index, columns: [{index, cells: [...]}]}

用法：
    # 运行册 1（先验证）
    python run_phase5.py --ce 1

    # 运行所有册
    python run_phase5.py --ce all

    # 运行多册
    python run_phase5.py --ce 2-5

    # 只运行指定页码范围（用于调试）
    python run_phase5.py --ce 1 --pages 24-30
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

# 设置编码
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")

# 项目根目录
PROJECT_ROOT = Path(__file__).parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.profile import BookProfile
from src.pipeline import GujiPipeline
from src.detectors.ocr_detector import OcrDetector
from src.detectors.char_grid import CharGridDetector
from src.utils.image_io import imread

# ─── 路径配置 ──────────────────────────────────────────────

WSL_BASE = Path("//wsl.localhost/Ubuntu/home/lishaodong/workspace/guji-resource")
BOOK_NAME = "欽定四庫全書簡明目錄·文淵閣本"
IMAGES_BASE = WSL_BASE / BOOK_NAME / "01_初始化" / "images"
CLASSIFY_BASE = WSL_BASE / BOOK_NAME / "03_信息提取"
OUTPUT_BASE = WSL_BASE / BOOK_NAME / "03_信息提取" / "ocr"

# 册号到目录名的映射
CE_DIR_NAMES = {
    1:  "06064237.cn",
    2:  "06064238.cn",
    3:  "06064239.cn",
    4:  "06064240.cn",
    5:  "06064241.cn",
    6:  "06064242.cn",
    7:  "06064243.cn",
    8:  "06064244.cn",
    9:  "06064245.cn",
    10: "06064246.cn",
}

# 固定 profile（所有册通用）
BOOK_PROFILE = BookProfile.from_dict({
    "color_mode": "bw",
    "page_type": "cut_half",
    "lines_per_page": 8,
    "border_style": "double",
    "border_wear": "medium",
    "chars_per_line": 21,
    "has_marginal_notes": False,
})


def load_skip_pages(ce_num: int) -> set[int]:
    """读取 ce0X_page_layout.json，返回需要跳过的页码集合。

    规则（Phase 5.1）：
    - 只跳过 cover, title_page（封面/书名页，非标准版式）
    - 其他所有页面（preface, toc, blank, content, volume_start 等）都要处理
    - 空白页检测到无内容时输出空 columns 的 JSON
    """
    classify_path = CLASSIFY_BASE / f"ce{ce_num:02d}_page_layout.json"
    if not classify_path.exists():
        print(f"  警告: 未找到分类文件 {classify_path}，所有页面视为需处理")
        return set()

    with open(classify_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    classifications = data.get("classifications", [])
    # 只跳过封面和书名页
    skip_types = {"cover", "title_page"}
    skip_pages = {item["page"] for item in classifications
                  if item.get("type") in skip_types}

    print(f"  分类文件: 跳过页={skip_pages}")

    return skip_pages


def get_image_paths(ce_num: int) -> list[tuple[int, Path]]:
    """获取册图片列表，返回 [(page_index, path), ...] 按页码排序。"""
    dir_name = CE_DIR_NAMES[ce_num]
    img_dir = IMAGES_BASE / dir_name / "images"
    if not img_dir.exists():
        print(f"  错误: 图片目录不存在: {img_dir}")
        return []

    result = []
    for f in sorted(img_dir.iterdir()):
        if f.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        # 从文件名提取页码：06064237.cn_0001.jpg -> 1
        try:
            page_num = int(f.stem.split("_")[-1])
            result.append((page_num, f))
        except ValueError:
            continue

    return sorted(result, key=lambda x: x[0])


def build_output_json(page_index: int, char_grid: dict) -> dict:
    """从 char_grid 结果构建符合 todo 格式的输出 JSON。

    格式：
    {
      "page_index": N,
      "columns": [
        {
          "index": 0,
          "left_x": ..., "right_x": ...,
          "has_jiazhu": bool,
          "jiazhu_ranges": [...],
          "ocr_text": "...",
          "cells": [
            {"type": "char"/"jiazhu"/"empty", "index": N, "sub_col": 1,
             "y_top": ..., "y_bottom": ..., "text": "...", "confidence": 0.9}
          ]
        }
      ]
    }
    """
    columns = []
    for col in char_grid["columns"]:
        # 只保留 char/jiazhu/empty（跳过 margin）
        cells = []
        for cell in col["cells"]:
            if cell["type"] == "margin":
                continue
            c = {
                "type": cell["type"],
                "index": cell["index"],
                "y_top": cell["y_top"],
                "y_bottom": cell["y_bottom"],
                "text": cell.get("text"),
                "confidence": cell.get("confidence", 0.0),
            }
            if cell.get("sub_col") is not None:
                c["sub_col"] = cell["sub_col"]
            cells.append(c)

        col_data = {
            "index": col["index"],
            "left_x": col["left_x"],
            "right_x": col["right_x"],
            "has_jiazhu": col.get("has_jiazhu", False),
            "jiazhu_ranges": col.get("jiazhu_ranges", []),
            "ocr_text": col.get("ocr_text", ""),
            "cells": cells,
        }
        columns.append(col_data)

    return {
        "page_index": page_index,
        "columns": columns,
    }


def run_ce(ce_num: int, pipeline: GujiPipeline,
           char_grid_detector: CharGridDetector,
           page_filter: set[int] | None = None) -> int:
    """对一册运行 OCR，返回处理的页数。

    Args:
        ce_num: 册号 (1-10)
        pipeline: GujiPipeline 实例（用于预处理和版面检测）
        char_grid_detector: CharGridDetector 实例
        page_filter: 如果指定，只处理这些页码
    """
    print(f"\n{'='*60}")
    print(f"册 {ce_num} ({CE_DIR_NAMES[ce_num]})")
    print(f"{'='*60}")

    # 加载页面分类（只跳过 cover/title_page）
    skip_pages = load_skip_pages(ce_num)

    # 预处理器（只创建一次，无状态，可复用）
    from src.preprocessors import get_preprocessors
    preprocessors = get_preprocessors(BOOK_PROFILE)

    # 获取图片列表
    img_list = get_image_paths(ce_num)
    if not img_list:
        print("  未找到图片，跳过")
        return 0

    print(f"  图片总数: {len(img_list)}")

    # 确定输出目录
    out_dir = OUTPUT_BASE / f"ce{ce_num:02d}"
    out_dir.mkdir(parents=True, exist_ok=True)

    n_processed = 0
    n_skipped = 0

    for page_idx, img_path in img_list:
        # 判断是否跳过
        if page_filter is not None and page_idx not in page_filter:
            continue

        # 封面/书名页跳过
        if page_idx in skip_pages:
            n_skipped += 1
            continue

        # 输出文件
        out_path = out_dir / f"page{page_idx:03d}.json"
        if out_path.exists():
            print(f"  page {page_idx:03d}: 已存在，跳过")
            n_processed += 1
            continue

        print(f"  page {page_idx:03d}: {img_path.name}...", end=" ", flush=True)

        # 读取图片（WSL UNC 路径需用 open+frombuffer 读取）
        try:
            buf = np.frombuffer(img_path.read_bytes(), dtype=np.uint8)
            image = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        except Exception:
            image = imread(str(img_path))
        if image is None:
            print("读取失败")
            continue

        try:
            # 预处理（内联，避免 WSL 路径问题）
            current_images = [image]
            for pp in preprocessors:
                next_images = []
                for cur_img in current_images:
                    result = pp.process(cur_img, BOOK_PROFILE)
                    if isinstance(result, list):
                        next_images.extend(sub_img for _, sub_img in result)
                    else:
                        next_images.append(result)
                current_images = next_images

            if not current_images:
                print("预处理失败")
                continue

            proc_image = current_images[0]

            # 版面检测
            layout = pipeline._detect_layout(proc_image, BOOK_PROFILE)
            if not layout:
                # 空白页或无法检测版面 → 输出空 columns JSON
                output = {"page_index": page_idx, "columns": []}
                with open(out_path, "w", encoding="utf-8") as f:
                    json.dump(output, f, ensure_ascii=False, indent=2)
                print("空页（无版面）")
                n_processed += 1
                continue

            # binarize 步骤输出灰度图，但 OCR 需要 BGR 彩色图
            if len(proc_image.shape) == 2:
                proc_image = cv2.cvtColor(proc_image, cv2.COLOR_GRAY2BGR)

            # Phase 3: 字符网格检测
            char_grid = char_grid_detector.detect(proc_image, layout, BOOK_PROFILE)

            # 构建输出 JSON
            output = build_output_json(page_idx, char_grid)

            # 保存
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)

            n_cols = len(output["columns"])
            n_jz = sum(1 for c in output["columns"] if c["has_jiazhu"])
            n_chars = sum(
                sum(1 for cell in c["cells"] if cell["type"] in ("char", "jiazhu"))
                for c in output["columns"]
            )
            print(f"OK ({n_cols}列, {n_chars}字, {n_jz}夹注列)")
            n_processed += 1

        except Exception as e:
            print(f"错误: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n  册 {ce_num} 完成: 处理 {n_processed} 页, 跳过 {n_skipped} 页")
    return n_processed


def parse_ce_arg(ce_arg: str) -> list[int]:
    """解析 --ce 参数，支持 'all', '1', '2-5', '1,3,5'。"""
    if ce_arg == "all":
        return list(range(1, 11))
    if "-" in ce_arg and "," not in ce_arg:
        start, end = ce_arg.split("-")
        return list(range(int(start), int(end) + 1))
    if "," in ce_arg:
        return [int(x) for x in ce_arg.split(",")]
    return [int(ce_arg)]


def parse_pages_arg(pages_arg: str | None) -> set[int] | None:
    """解析 --pages 参数，返回页码集合或 None（表示全部）。"""
    if pages_arg is None:
        return None
    if "-" in pages_arg:
        start, end = pages_arg.split("-")
        return set(range(int(start), int(end) + 1))
    if "," in pages_arg:
        return {int(x) for x in pages_arg.split(",")}
    return {int(pages_arg)}


def main():
    parser = argparse.ArgumentParser(description="Phase 5: 全册 OCR 运行")
    parser.add_argument("--ce", default="1",
                        help="册号: '1', '2-5', '1,3', 'all'")
    parser.add_argument("--pages", default=None,
                        help="页码范围（调试用）: '24-30', '25,27'")
    args = parser.parse_args()

    ce_list = parse_ce_arg(args.ce)
    page_filter = parse_pages_arg(args.pages)

    print(f"Phase 5 OCR 运行")
    print(f"  册: {ce_list}")
    print(f"  页面过滤: {page_filter if page_filter else '全部'}")
    print(f"  输出路径: {OUTPUT_BASE}")

    # 初始化（共享实例，避免重复加载模型）
    pipeline = GujiPipeline()
    ocr_detector = OcrDetector()
    char_grid_detector = CharGridDetector(ocr_detector)

    total = 0
    for ce_num in ce_list:
        n = run_ce(ce_num, pipeline, char_grid_detector, page_filter)
        total += n

    print(f"\n{'='*60}")
    print(f"全部完成！共处理 {total} 页")
    print(f"输出目录: {OUTPUT_BASE}")


if __name__ == "__main__":
    main()
