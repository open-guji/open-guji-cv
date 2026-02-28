"""表格 OCR 识别 CLI 工具。

用法：
    python run_table_ocr.py <image_path> [--output <json_path>] [--debug <debug_img_path>]
    python run_table_ocr.py data/book7/06054854.cn_page_111.png
    python run_table_ocr.py data/book7/ --all
    python run_table_ocr.py data/book7/ --all --lang ch --device cpu

环境变量：
    PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK=True  跳过模型源检查
    PYTHONIOENCODING=utf-8                      Windows 中文输出
"""

import argparse
import json
import os
import sys
import glob
import time

os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")


def main():
    parser = argparse.ArgumentParser(description="古籍表格 OCR 识别")
    parser.add_argument("input", help="图像文件路径，或包含图像的目录")
    parser.add_argument("--output", "-o", help="JSON 输出路径（默认: output/table_ocr/<basename>.json）")
    parser.add_argument("--debug", "-d", action="store_true", help="保存 debug 可视化图")
    parser.add_argument("--all", "-a", action="store_true", help="处理目录下所有 PNG 文件")
    parser.add_argument("--scale", type=float, default=2.0, help="cell 放大倍数（默认 2.0）")
    parser.add_argument("--no-erase-lines", action="store_true", help="不擦除表格线")
    parser.add_argument("--charset", choices=["auto", "astro", "none"], default="auto",
                        help="字符集过滤模式: auto=按行自动, astro=全部天文, none=不过滤")
    parser.add_argument("--print", "-p", action="store_true", help="打印表格内容到终端")
    # OCR 配置参数
    parser.add_argument("--lang", default=None, help="OCR 语言（默认: chinese_cht）")
    parser.add_argument("--device", default=None, choices=["gpu", "cpu"], help="推理设备")
    parser.add_argument("--det-thresh", type=float, default=None, help="文本检测阈值")
    parser.add_argument("--det-box-thresh", type=float, default=None, help="文本检测框阈值")
    args = parser.parse_args()

    from src.detectors.table_detector import (
        TableDetector, YEAR_CHARS, WEEKDAY_CHARS, ASTRO_CHARS,
    )

    # 构建行字符集
    row_charsets = {}
    if args.charset == "auto":
        # 默认: 行0=年份, 行1=星期, 行2+=天文
        row_charsets = {0: YEAR_CHARS, 1: WEEKDAY_CHARS}
        for r in range(2, 100):  # 足够多的行
            row_charsets[r] = ASTRO_CHARS
    elif args.charset == "astro":
        for r in range(100):
            row_charsets[r] = ASTRO_CHARS

    # 构建 OCR 配置覆盖
    ocr_config = {}
    if args.lang is not None:
        ocr_config["lang"] = args.lang
    if args.device is not None:
        ocr_config["device"] = args.device
    if args.det_thresh is not None:
        ocr_config["text_det_thresh"] = args.det_thresh
    if args.det_box_thresh is not None:
        ocr_config["text_det_box_thresh"] = args.det_box_thresh

    detector = TableDetector(
        scale=args.scale,
        erase_lines=not args.no_erase_lines,
        row_charsets=row_charsets if args.charset != "none" else {},
        ocr_config=ocr_config if ocr_config else None,
    )

    # 收集要处理的文件
    if os.path.isdir(args.input) or args.all:
        input_dir = args.input if os.path.isdir(args.input) else os.path.dirname(args.input)
        files = sorted(glob.glob(os.path.join(input_dir, "*.png")))
        if not files:
            print(f"目录中没有 PNG 文件: {input_dir}")
            sys.exit(1)
    else:
        files = [args.input]

    out_dir = os.path.join("output", "table_ocr")
    os.makedirs(out_dir, exist_ok=True)

    for filepath in files:
        basename = os.path.splitext(os.path.basename(filepath))[0]
        print(f"\n{'='*60}")
        print(f"处理: {filepath}")

        t0 = time.time()

        # 检测 + OCR
        if args.debug:
            debug_path = os.path.join(out_dir, f"{basename}_debug.png")
            result = detector.detect_and_visualize(filepath, debug_path)
            if result:
                print(f"Debug 图: {debug_path}")
        else:
            result = detector.detect(filepath)

        elapsed = time.time() - t0

        if result is None:
            print(f"  未检测到表格 (耗时 {elapsed:.1f}s)")
            continue

        grid = result.grid
        print(f"  表格: {grid.cols} 列 x {grid.rows} 行 (耗时 {elapsed:.1f}s)")

        # 统计
        non_empty = sum(1 for c in result.cells if c.text)
        total = grid.rows * grid.cols
        print(f"  有内容 cell: {non_empty}/{total}")

        # 打印表格内容
        if args.print or len(files) == 1:
            for r in range(grid.rows):
                row_cells = [c for c in result.cells if c.row == r and c.text]
                if row_cells:
                    print(f"  --- 行 {r} ---")
                    for c in sorted(row_cells, key=lambda x: x.col):
                        print(f"    [{r},{c.col}] conf={c.confidence:.2f}  {c.text!r}")

        # 输出 JSON
        json_path = args.output if args.output and len(files) == 1 else \
            os.path.join(out_dir, f"{basename}.json")
        data = result.to_dict()
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  JSON: {json_path}")

    print(f"\n完成，共处理 {len(files)} 个文件")


if __name__ == "__main__":
    main()
