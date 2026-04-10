"""CLI 入口：python -m open_guji_cv <command> [args]

切分：
    cut            <folder>  检测切分类型并执行切分 → cut.json + 切分后图片

分析：
    recognize-profile <folder>  分析版式特征 → profile.json
    preprocess <folder>         图像预处理（裁剪 / 增强 / 二值化）
    extract    <folder>         版面 + 字符检测，输出结构化 JSON

一键运行：
    run        <folder>   依次执行以上三步

工具：
    show-profile <path>   显示 BookProfile
"""

import io
import json
import re
import sys
import argparse
from pathlib import Path

if hasattr(sys.stdout, "buffer") and not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
elif hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from .pipeline import GujiPipeline, IMAGE_EXTENSIONS
from .profile import BookProfile


# ─── 工具函数 ──────────────────────────────────────────────

def _resolve_profile(path: Path, profile_arg: str | None) -> BookProfile:
    """优先用 --profile，否则从目录查找 profile.json。"""
    if profile_arg:
        return BookProfile.load(profile_arg)
    profile_path = (path if path.is_dir() else path.parent) / "profile.json"
    if profile_path.exists():
        return BookProfile.load(profile_path)
    print(f"未找到 profile.json，请先运行：python -m open_guji_cv analyze {path.parent}")
    sys.exit(1)


def _parse_range(range_str: str | None, folder: Path) -> set[str] | None:
    """解析 --range 参数，返回匹配的文件 stem 集合。

    支持格式：3-6 / 1,3,5 / 003-006
    """
    if not range_str:
        return None

    numbers: set[int] = set()
    for part in range_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            numbers.update(range(int(start), int(end) + 1))
        else:
            numbers.add(int(part))

    matched: set[str] = set()
    for f in folder.iterdir():
        if f.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        nums = re.findall(r'\d+', f.stem)
        if nums and int(nums[-1]) in numbers:
            matched.add(f.stem)

    if not matched:
        print(f"警告：--range {range_str} 未匹配到任何图片")
        sys.exit(1)
    return matched


# ─── 命令处理函数 ──────────────────────────────────────────

def cmd_cut(args):
    """检测切分类型并执行切分。

    输出：
    - cut.json: {"cut_type": "none"|"vertical_cut"|"horizontal_cut"}
    - 如果需要切分，生成切分后的图片文件：
      - vertical_cut: <name>_left.png, <name>_right.png
      - horizontal_cut: <name>_top.png, <name>_bottom.png
    """
    import cv2
    from .analyzers.cut_type import CutTypeAnalyzer

    path = Path(args.path)
    if not path.is_dir():
        print(f"cut 需要古籍文件夹路径: {path}")
        sys.exit(1)

    # 加载图片
    images = []
    image_files = []
    for f in sorted(path.iterdir()):
        if f.suffix.lower() in IMAGE_EXTENSIONS:
            img = cv2.imread(str(f))
            if img is not None:
                images.append(img)
                image_files.append(f)

    if not images:
        print(f"未找到图片: {path}")
        sys.exit(1)

    # 检测切分类型
    analyzer = CutTypeAnalyzer()
    result = analyzer.analyze(images)
    cut_type = result["cut_type"]
    confidence = result.get("_confidence", {}).get("cut_type", 0)

    # 保存 cut.json
    cut_data = {"cut_type": cut_type}
    cut_json_path = path / "cut.json"
    with open(cut_json_path, "w", encoding="utf-8") as f:
        json.dump(cut_data, f, ensure_ascii=False, indent=2)

    print(f"切分类型: {cut_type} (置信度: {confidence:.2f})")
    print(f"保存: {cut_json_path}")

    # 执行切分
    if cut_type == "none":
        print("无需切分")
        return

    output_dir = Path(args.output) / path.name
    output_dir.mkdir(parents=True, exist_ok=True)

    for img, img_file in zip(images, image_files):
        stem = img_file.stem
        h, w = img.shape[:2]

        if cut_type == "vertical_cut":
            mid_x = w // 2
            left = img[:, :mid_x]
            right = img[:, mid_x:]
            cv2.imwrite(str(output_dir / f"{stem}_left.png"), left)
            cv2.imwrite(str(output_dir / f"{stem}_right.png"), right)
        elif cut_type == "horizontal_cut":
            mid_y = h // 2
            top = img[:mid_y, :]
            bottom = img[mid_y:, :]
            cv2.imwrite(str(output_dir / f"{stem}_top.png"), top)
            cv2.imwrite(str(output_dir / f"{stem}_bottom.png"), bottom)

    print(f"切分完成: {len(image_files)} 张 -> {output_dir}")


def cmd_recognize_profile(args):
    """分析版式特征，生成 profile.json。"""
    pipeline = GujiPipeline(output_dir=args.output)
    profile = pipeline.analyze(args.path)
    print(f"\n分析结果: {profile}")


def cmd_preprocess(args):
    """图像预处理（s1~s6）。"""
    path = Path(args.path)
    if not path.is_dir():
        print(f"preprocess 需要古籍文件夹路径: {path}")
        sys.exit(1)

    pipeline = GujiPipeline(output_dir=args.output)
    profile = BookProfile.load(args.profile) if args.profile else None
    name_filter = _parse_range(getattr(args, 'range', None), path)
    keep_intermediate = getattr(args, 'keep_intermediate', False)
    intermediate_dir = getattr(args, 'intermediate_dir', None)
    pipeline.process_book(str(path), profile=profile, name_filter=name_filter,
                          keep_intermediate=keep_intermediate,
                          intermediate_dir=intermediate_dir)


def cmd_extract(args):
    """版面 + 字符检测（Phase 2 + Phase 3），输出结构化 JSON。

    --steps layout  只做 Phase 2 版面检测
    --steps grid    只做 Phase 3 字符网格（需先有 layout）
    --steps all     两步都做（默认）

    当 --input-dir 指定时，从该目录读取预处理图片（而非 -o/<book_name>/），
    输出仍写到 -o/<book_name>/ 下。适用于输入和输出分离的场景。
    """
    path = Path(args.path)
    if not path.is_dir():
        print(f"extract 需要古籍文件夹路径: {path}")
        sys.exit(1)

    input_dir = Path(args.input_dir) if args.input_dir else None
    if input_dir and not input_dir.is_dir():
        print(f"输入目录不存在: {input_dir}")
        sys.exit(1)

    # 当指定 --input-dir 时，用 path.name 作为 book_name（用于输出子目录名）
    pipeline = GujiPipeline(output_dir=args.output)
    profile = BookProfile.load(args.profile) if args.profile else None
    # --range 过滤基于实际图片目录
    range_dir = input_dir if input_dir else path
    name_filter = _parse_range(getattr(args, 'range', None), range_dir)
    book_name = path.name
    steps = args.steps

    step_labels = {"layout": "版面检测", "grid": "字符网格+OCR", "all": "版面检测 + 字符网格+OCR"}
    print(f"{'=' * 60}")
    print(f"extract: {book_name}  [{step_labels[steps]}]")
    if input_dir:
        print(f"  输入: {input_dir}")
        print(f"  输出: {Path(args.output) / book_name}")
    print(f"{'=' * 60}")

    if steps in ("layout", "all"):
        pipeline.detect_layout_book(book_name, profile=profile,
                                    name_filter=name_filter, input_dir=input_dir)

    if steps in ("grid", "all"):
        pipeline.detect_char_grid(book_name, profile=profile,
                                  name_filter=name_filter, input_dir=input_dir)

    print(f"\n{'=' * 60}")
    print(f"extract 完成！")


def cmd_run(args):
    """完整管线：analyze → preprocess → extract。"""
    path = Path(args.path)
    if not path.is_dir():
        print(f"run 需要古籍文件夹路径: {path}")
        sys.exit(1)

    pipeline = GujiPipeline(output_dir=args.output)
    profile = BookProfile.load(args.profile) if args.profile else None
    name_filter = _parse_range(getattr(args, 'range', None), path)
    pipeline.run_all(
        str(path),
        profile=profile,
        output_format=args.format,
        clean=args.clean,
        name_filter=name_filter,
    )


def cmd_show_profile(args):
    """显示 BookProfile。"""
    path = Path(args.path)
    if path.is_dir():
        path = path / "profile.json"
    if not path.exists():
        print(f"未找到 profile: {path}")
        print(f"请先运行: python -m open_guji_cv analyze {path.parent}")
        sys.exit(1)
    profile = BookProfile.load(path)
    print(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2))


# ─── 辅助 ─────────────────────────────────────────────────

def _add_common_args(p: argparse.ArgumentParser) -> None:
    """添加 --profile 和 --range 选项。"""
    p.add_argument("--profile", default=None, help="指定 profile.json 路径")
    p.add_argument("--range", default=None,
                   help="处理范围（如 3-6 或 1,3,5）")


# ─── 主入口 ───────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="guji-cv",
        description="古籍图像 OCR 分析框架",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python -m open_guji_cv recognize-profile data/book1/
  python -m open_guji_cv preprocess data/book1/ --range 1-5
  python -m open_guji_cv extract data/book1/ --steps layout
  python -m open_guji_cv extract data/book1/
  python -m open_guji_cv run data/book1/
""")
    parser.add_argument("-o", "--output", default="output",
                        help="输出目录（默认: output）")

    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # ── cut ──────────────────────────────────────────────
    p = sub.add_parser("cut",
                       help="检测切分类型并执行切分 → cut.json")
    p.add_argument("path", help="古籍文件夹路径")

    # ── recognize-profile ─────────────────────────────────
    p = sub.add_parser("recognize-profile",
                       help="分析版式特征 → profile.json",
                       aliases=["analyze"])
    p.add_argument("path", help="古籍文件夹路径")

    # ── preprocess ───────────────────────────────────────
    p = sub.add_parser("preprocess",
                       help="图像预处理（裁剪 / 增强 / 二值化）")
    p.add_argument("path", help="古籍文件夹路径")
    p.add_argument("--keep-intermediate", action="store_true",
                   help="保留中间步骤输出（默认只保留最终结果）")
    p.add_argument("--intermediate-dir", default=None,
                   help="中间步骤输出目录（需配合 --keep-intermediate）")
    _add_common_args(p)

    # ── extract ──────────────────────────────────────────
    p = sub.add_parser("extract",
                       help="版面 + 字符检测，输出结构化 JSON")
    p.add_argument("path", help="古籍文件夹路径（用作输出子目录名）")
    p.add_argument("--input-dir", default=None,
                   help="输入图片目录（默认从 -o/<book_name>/ 下查找预处理结果）")
    p.add_argument("--steps", choices=["layout", "grid", "all"],
                   default="all",
                   help="子步骤：layout=版面检测，grid=字符网格，all=全部（默认）")
    _add_common_args(p)

    # ── run ──────────────────────────────────────────────
    p = sub.add_parser("run",
                       help="完整管线：analyze → preprocess → extract")
    p.add_argument("path", help="古籍文件夹路径")
    p.add_argument("--format", choices=["char_grid", "combined"],
                   default="char_grid",
                   help="输出格式（默认: char_grid）")
    p.add_argument("--clean", action="store_true",
                   help="完成后删除中间文件")
    _add_common_args(p)

    # ── show-profile ─────────────────────────────────────
    p = sub.add_parser("show-profile",
                       help="显示 BookProfile")
    p.add_argument("path", help="古籍文件夹或 profile.json 路径")

    args = parser.parse_args()

    commands = {
        "cut":               cmd_cut,
        "recognize-profile": cmd_recognize_profile,
        "analyze":           cmd_recognize_profile,  # 兼容别名
        "preprocess":        cmd_preprocess,
        "extract":           cmd_extract,
        "run":               cmd_run,
        "show-profile":      cmd_show_profile,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
