"""CLI 入口：python -m src <command> [args]

命令:
    analyze        <folder>         Phase 1: 分析版式特征
    preprocess     <path>           Phase 1.5: 预处理（s1~s6）
    detect-layout  <path>           Phase 2: 版面检测
    detect-grid    <path>           Phase 3: 字符网格检测
    run            <folder>         完整管线（Phase 1→3）
    show-profile   <path>           显示 BookProfile
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
from .utils.image_io import imread, imwrite


# ─── 工具函数 ──────────────────────────────────────────────

def _resolve_profile(image_path: Path, profile_arg: str | None) -> BookProfile:
    """解析 profile：优先用 --profile 参数，否则从同目录查找。"""
    if profile_arg:
        return BookProfile.load(profile_arg)

    profile_path = image_path.parent / "profile.json"
    if profile_path.exists():
        return BookProfile.load(profile_path)

    print(f"未找到 profile.json，先运行 analyze 命令")
    print(f"  python -m src analyze {image_path.parent}")
    sys.exit(1)


def _parse_range(range_str: str | None, folder: Path) -> set[str] | None:
    """解析 --range 参数，返回匹配的文件 stem 集合。

    支持格式:
        3-6        → 匹配文件名中包含 003~006 的图片
        1,3,5      → 匹配包含 001, 003, 005 的图片
        003-006    → 同上
    """
    if not range_str:
        return None

    # 解析数字列表
    numbers = set()
    for part in range_str.split(","):
        part = part.strip()
        if "-" in part:
            start, end = part.split("-", 1)
            for n in range(int(start), int(end) + 1):
                numbers.add(n)
        else:
            numbers.add(int(part))

    # 扫描文件夹，找到匹配的 stem
    matched = set()
    for f in folder.iterdir():
        if f.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        # 提取文件名中的数字部分
        nums_in_name = re.findall(r'\d+', f.stem)
        if nums_in_name:
            # 用最后一个数字匹配（如 v01_003 → 3）
            file_num = int(nums_in_name[-1])
            if file_num in numbers:
                matched.add(f.stem)

    if not matched:
        print(f"警告: --range {range_str} 未匹配到任何图片")
        sys.exit(1)

    return matched


# ─── 命令处理函数 ──────────────────────────────────────────

def cmd_analyze(args):
    """Phase 1: 分析版式特征。"""
    pipeline = GujiPipeline(output_dir=args.output)
    profile = pipeline.analyze(args.path)
    print(f"\n分析结果: {profile}")


def cmd_preprocess(args):
    """Phase 1.5: 预处理整本书或单张图片。"""
    path = Path(args.path)
    pipeline = GujiPipeline(output_dir=args.output)

    if path.is_dir():
        profile = BookProfile.load(args.profile) if args.profile else None
        name_filter = _parse_range(getattr(args, 'range', None), path)
        pipeline.process_book(str(path), profile=profile,
                              name_filter=name_filter)
    elif path.is_file():
        profile = _resolve_profile(path, args.profile)

        out_dir = Path(args.output) / path.parent.name
        out_dir.mkdir(parents=True, exist_ok=True)

        results = pipeline.preprocess(str(path), profile)
        for r in results:
            stem = path.stem
            if len(results) > 1:
                stem = f"{stem}_{r.sub_index}"

            img_name = f"{stem}_preprocessed.png"
            imwrite(str(out_dir / img_name), r.preprocessed)

            layout_name = f"{stem}_layout.json"
            with open(out_dir / layout_name, "w", encoding="utf-8") as f:
                json.dump(r.layout, f, ensure_ascii=False, indent=2)

            print(f"  子图{r.sub_index}: "
                  f"尺寸={r.metadata.get('processed_size', '?')}")
            print(f"    → {out_dir / img_name}")
            print(f"    → {out_dir / layout_name}")
    else:
        print(f"路径不存在: {path}")
        sys.exit(1)


def cmd_detect_layout(args):
    """Phase 2: 版面检测。"""
    path = Path(args.path)
    pipeline = GujiPipeline(output_dir=args.output)

    if path.is_dir():
        book_name = path.name
        profile = BookProfile.load(args.profile) if args.profile else None
        name_filter = _parse_range(getattr(args, 'range', None), path)
        pipeline.detect_layout_book(book_name, profile=profile,
                                    name_filter=name_filter)
    elif path.is_file():
        profile = _resolve_profile(path, args.profile)
        layout = pipeline._detect_layout(imread(str(path)), profile)

        out_dir = Path(args.output) / path.parent.name
        out_dir.mkdir(parents=True, exist_ok=True)

        json_path = out_dir / f"{path.stem}_layout.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(layout, f, ensure_ascii=False, indent=2)
        print(f"  → {json_path}")

        image = imread(str(path))
        if image is not None:
            vis = pipeline._draw_layout(image, layout)
            vis_path = out_dir / f"{path.stem}_annotated.png"
            imwrite(str(vis_path), vis)
            print(f"  → {vis_path}")
    else:
        print(f"路径不存在: {path}")
        sys.exit(1)


def cmd_detect_grid(args):
    """Phase 3: 字符网格检测。"""
    path = Path(args.path)
    pipeline = GujiPipeline(output_dir=args.output)

    if path.is_dir():
        book_name = path.name
        profile = BookProfile.load(args.profile) if args.profile else None
        name_filter = _parse_range(getattr(args, 'range', None), path)
        pipeline.detect_char_grid(book_name, profile=profile,
                                  name_filter=name_filter)
    elif path.is_file():
        if not args.layout:
            print("单图模式需要 --layout 指定 layout JSON 路径")
            print("  python -m src detect-grid image.png --layout image_layout.json")
            sys.exit(1)

        profile = _resolve_profile(path, args.profile)

        with open(args.layout, "r", encoding="utf-8") as f:
            layout = json.load(f)

        result = pipeline.detect_char_grid_single(str(path), layout, profile)

        out_dir = Path(args.output) / path.parent.name
        out_dir.mkdir(parents=True, exist_ok=True)

        json_path = out_dir / f"{path.stem}_char_grid.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"  → {json_path}")

        image = imread(str(path))
        if image is not None:
            vis = pipeline._draw_char_grid(image, result)
            vis_path = out_dir / f"{path.stem}_annotated.png"
            imwrite(str(vis_path), vis)
            print(f"  → {vis_path}")
    else:
        print(f"路径不存在: {path}")
        sys.exit(1)


def cmd_run(args):
    """完整管线：Phase 1 → 1.5 → 2 → 3。"""
    path = Path(args.path)
    if not path.is_dir():
        print(f"run 命令需要古籍文件夹路径: {path}")
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
        print(f"请先运行: python -m src analyze {path.parent}")
        sys.exit(1)

    profile = BookProfile.load(path)
    print(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2))


# ─── 辅助：给 parser 添加通用选项 ─────────────────────────

def _add_range_arg(parser: argparse.ArgumentParser) -> None:
    """给 subparser 添加 --range 选项。"""
    parser.add_argument("--range", default=None,
                        help="指定处理的图片范围（如 3-6 或 1,3,5）")


# ─── 主入口 ───────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="guji_ocr",
        description="古籍图像 OCR 分析框架")
    parser.add_argument("-o", "--output", default="output",
                        help="输出目录（默认: output）")

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # analyze
    p_analyze = subparsers.add_parser("analyze",
                                      help="Phase 1: 分析古籍版式特征")
    p_analyze.add_argument("path", help="古籍文件夹路径")

    # preprocess
    p_preprocess = subparsers.add_parser("preprocess",
                                         help="Phase 1.5: 预处理古籍图片")
    p_preprocess.add_argument("path", help="古籍文件夹或图片路径")
    p_preprocess.add_argument("--profile", default=None,
                               help="指定 profile.json 路径")
    _add_range_arg(p_preprocess)

    # preprocess 的别名（向后兼容）
    p_process = subparsers.add_parser(
        "process", aliases=[],
        help="同 preprocess（向后兼容）")
    p_process.add_argument("path", help="古籍文件夹或图片路径")
    p_process.add_argument("--profile", default=None,
                            help="指定 profile.json 路径")
    _add_range_arg(p_process)

    # detect-layout
    p_layout = subparsers.add_parser("detect-layout",
                                      help="Phase 2: 版面检测")
    p_layout.add_argument("path", help="古籍文件夹或图片路径")
    p_layout.add_argument("--profile", default=None,
                           help="指定 profile.json 路径")
    _add_range_arg(p_layout)

    # detect-grid
    p_grid = subparsers.add_parser("detect-grid",
                                    help="Phase 3: 字符网格检测")
    p_grid.add_argument("path", help="古籍文件夹或图片路径")
    p_grid.add_argument("--profile", default=None,
                         help="指定 profile.json 路径")
    p_grid.add_argument("--layout", default=None,
                         help="layout JSON 路径（单图模式必需）")
    _add_range_arg(p_grid)

    # run
    p_run = subparsers.add_parser("run",
                                   help="完整管线: 全部阶段")
    p_run.add_argument("path", help="古籍文件夹路径")
    p_run.add_argument("--profile", default=None,
                        help="指定 profile.json 路径")
    p_run.add_argument("--format", choices=["char_grid", "combined"],
                        default="char_grid",
                        help="输出格式（默认: char_grid）")
    p_run.add_argument("--clean", action="store_true",
                        help="完成后清理中间文件")
    _add_range_arg(p_run)

    # show-profile
    p_show = subparsers.add_parser("show-profile",
                                    help="显示 BookProfile")
    p_show.add_argument("path", help="古籍文件夹或 profile.json 路径")

    args = parser.parse_args()

    commands = {
        "analyze": cmd_analyze,
        "preprocess": cmd_preprocess,
        "process": cmd_preprocess,
        "detect-layout": cmd_detect_layout,
        "detect-grid": cmd_detect_grid,
        "run": cmd_run,
        "show-profile": cmd_show_profile,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
