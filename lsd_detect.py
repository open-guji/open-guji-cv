"""
LSD (Line Segment Detector) 线段检测脚本。

使用 OpenCV 内置的 LSD 算法对古籍扫描图片进行线段识别，
输出可视化标注图和 JSON 结果。

用法:
    PYTHONIOENCODING=utf-8 python lsd_detect.py [图片路径或文件夹]
    PYTHONIOENCODING=utf-8 python lsd_detect.py asset/四库总目武英殿1.png
    PYTHONIOENCODING=utf-8 python lsd_detect.py asset/
"""

import os
import sys
import json
import io
import argparse
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import cv2
import numpy as np


# ─── Helpers ─────────────────────────────────────────────────────


def _imread(image_path, flags=cv2.IMREAD_COLOR):
    """读取图片，支持 Windows 非 ASCII 路径。"""
    img = cv2.imread(image_path, flags)
    if img is None:
        buf = np.fromfile(image_path, dtype=np.uint8)
        img = cv2.imdecode(buf, flags)
    return img


def _imwrite(path, img):
    """写入图片，支持 Windows 非 ASCII 路径。"""
    ext = Path(path).suffix
    ok, buf = cv2.imencode(ext, img)
    if ok:
        buf.tofile(path)


# ─── LSD 检测 ────────────────────────────────────────────────────


def detect_lines_lsd(image_path, min_length=30, angle_tol=10):
    """使用 LSD 检测线段。

    Args:
        image_path: 图片路径
        min_length: 最小线段长度（像素）
        angle_tol: 判定水平/垂直的角度容差（度）

    Returns:
        (gray, all_lines, vertical_lines, horizontal_lines, other_lines)
    """
    gray = _imread(image_path, cv2.IMREAD_GRAYSCALE)
    if gray is None:
        raise FileNotFoundError(f"无法读取图片: {image_path}")

    h, w = gray.shape
    print(f"  图片尺寸: {w} x {h}")

    # 创建 LSD 检测器
    lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)

    # 检测线段
    lines, widths, precs, nfas = lsd.detect(gray)

    if lines is None:
        print("  未检测到任何线段")
        return gray, [], [], [], []

    print(f"  LSD 原始检测: {len(lines)} 条线段")

    # 解析和分类
    all_lines = []
    vertical_lines = []
    horizontal_lines = []
    other_lines = []

    for i, line in enumerate(lines):
        x1, y1, x2, y2 = line[0]
        dx = x2 - x1
        dy = y2 - y1
        length = np.sqrt(dx * dx + dy * dy)

        if length < min_length:
            continue

        width = float(widths[i][0]) if widths is not None else 1.0
        nfa = float(nfas[i][0]) if nfas is not None else 0.0

        # 计算与垂直方向的夹角
        angle_from_vert = abs(np.degrees(np.arctan2(abs(dx), abs(dy))))

        entry = {
            "x1": float(x1), "y1": float(y1),
            "x2": float(x2), "y2": float(y2),
            "length": float(length),
            "width": width,
            "nfa": nfa,
            "angle_from_vertical": float(angle_from_vert),
        }

        all_lines.append(entry)

        if angle_from_vert <= angle_tol:
            entry["type"] = "vertical"
            vertical_lines.append(entry)
        elif angle_from_vert >= (90 - angle_tol):
            entry["type"] = "horizontal"
            horizontal_lines.append(entry)
        else:
            entry["type"] = "other"
            other_lines.append(entry)

    print(f"  过滤后 (长度>={min_length}px): {len(all_lines)} 条")
    print(f"    垂直线: {len(vertical_lines)} 条")
    print(f"    水平线: {len(horizontal_lines)} 条")
    print(f"    其他:   {len(other_lines)} 条")

    return gray, all_lines, vertical_lines, horizontal_lines, other_lines


# ─── 可视化 ──────────────────────────────────────────────────────


COLORS = {
    "vertical":   (0, 0, 255),    # 红色 — 垂直线
    "horizontal": (255, 0, 0),    # 蓝色 — 水平线
    "other":      (0, 180, 0),    # 绿色 — 其他角度
}


def draw_result(image_path, all_lines, output_path):
    """将检测到的线段绘制到原图上。"""
    img = _imread(image_path)
    if img is None:
        return

    overlay = img.copy()

    for line in all_lines:
        color = COLORS.get(line["type"], (128, 128, 128))
        pt1 = (int(line["x1"]), int(line["y1"]))
        pt2 = (int(line["x2"]), int(line["y2"]))
        thickness = max(1, min(3, int(line["width"])))
        cv2.line(overlay, pt1, pt2, color, thickness)

    result = cv2.addWeighted(overlay, 0.7, img, 0.3, 0)

    # 添加图例
    legend_y = 30
    for label, color in COLORS.items():
        cv2.line(result, (10, legend_y), (40, legend_y), color, 2)
        label_text = {"vertical": "Vertical", "horizontal": "Horizontal",
                      "other": "Other"}[label]
        cv2.putText(result, label_text, (50, legend_y + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        legend_y += 25

    _imwrite(output_path, result)
    print(f"  已保存标注图: {output_path}")


# ─── 主程序 ──────────────────────────────────────────────────────


def process_image(image_path, min_length=30, angle_tol=10):
    """处理单张图片的完整流程。"""
    gray, all_lines, v_lines, h_lines, o_lines = detect_lines_lsd(
        image_path, min_length=min_length, angle_tol=angle_tol)

    h, w = gray.shape

    result = {
        "image_size": {"width": w, "height": h},
        "params": {"min_length": min_length, "angle_tol": angle_tol},
        "summary": {
            "total": len(all_lines),
            "vertical": len(v_lines),
            "horizontal": len(h_lines),
            "other": len(o_lines),
        },
        "lines": all_lines,
    }

    return result


def main():
    parser = argparse.ArgumentParser(
        description="LSD 线段检测 — 古籍图像线段识别")
    parser.add_argument("path", nargs="?", default=None,
                        help="图片文件或文件夹路径（默认: asset/）")
    parser.add_argument("-o", "--output", default="output/lsd",
                        help="输出文件夹（默认: output/lsd）")
    parser.add_argument("--min-length", type=int, default=30,
                        help="最小线段长度，单位像素（默认: 30）")
    parser.add_argument("--angle-tol", type=float, default=10,
                        help="水平/垂直判定角度容差，单位度（默认: 10）")
    args = parser.parse_args()

    # 查找图片
    if args.path:
        target = Path(args.path)
        if target.is_file():
            files = [str(target)]
        elif target.is_dir():
            exts = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
            files = sorted(str(f) for f in target.iterdir()
                           if f.suffix.lower() in exts
                           and "_lsd" not in f.stem
                           and "_borders" not in f.stem)
        else:
            print(f"路径不存在: {target}")
            sys.exit(1)
    else:
        folder = Path(__file__).parent / "asset"
        exts = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
        files = sorted(str(f) for f in folder.iterdir()
                       if f.suffix.lower() in exts
                       and "_lsd" not in f.stem
                       and "_borders" not in f.stem)

    if not files:
        print("未找到图片。")
        sys.exit(1)

    # 创建输出文件夹
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"找到 {len(files)} 张图片。")
    print(f"输出目录: {out_dir}\n")

    for image_path in files:
        base = Path(image_path).stem
        print(f"{'=' * 60}")
        print(f"处理: {os.path.basename(image_path)}")
        print(f"{'=' * 60}")

        result = process_image(image_path,
                               min_length=args.min_length,
                               angle_tol=args.angle_tol)

        # 摘要
        s = result["summary"]
        print(f"\n  --- 结果 ---")
        print(f"  总线段数: {s['total']}")
        print(f"  垂直线: {s['vertical']}, 水平线: {s['horizontal']}, 其他: {s['other']}")

        # 保存标注图
        out_img = out_dir / f"{base}_lsd.jpg"
        draw_result(image_path, result["lines"], str(out_img))

        # 保存 JSON
        out_json = out_dir / f"{base}_lsd.json"
        with open(str(out_json), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"  已保存 JSON: {out_json}")
        print()


if __name__ == "__main__":
    main()
