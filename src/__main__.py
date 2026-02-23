"""CLI 入口：python -m guji_preprocess <command> [args]

命令:
    analyze <book_folder>       分析一本书，生成 profile.json
    process <path>              处理一本书或单张图片
    show-profile <book_folder>  显示 BookProfile
"""

import io
import sys
import argparse
from pathlib import Path

if hasattr(sys.stdout, "buffer") and not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
elif hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from .pipeline import GujiPipeline
from .profile import BookProfile


def cmd_analyze(args):
    """分析一本书的版式特征。"""
    pipeline = GujiPipeline(output_dir=args.output)
    profile = pipeline.analyze(args.path)
    print(f"\n分析结果: {profile}")


def cmd_process(args):
    """处理一本书或单张图片。"""
    path = Path(args.path)
    pipeline = GujiPipeline(output_dir=args.output)

    if path.is_dir():
        # 处理整本书
        profile = None
        if args.profile:
            profile = BookProfile.load(args.profile)
        pipeline.process_book(str(path), profile=profile)
    elif path.is_file():
        # 处理单张图片
        if not args.profile:
            # 尝试从同目录加载 profile
            profile_path = path.parent / "profile.json"
            if profile_path.exists():
                profile = BookProfile.load(profile_path)
            else:
                print(f"未找到 profile.json，先运行 analyze 命令")
                print(f"  python -m guji_preprocess analyze {path.parent}")
                sys.exit(1)
        else:
            profile = BookProfile.load(args.profile)

        results = pipeline.preprocess(str(path), profile)
        for r in results:
            print(f"  子图{r.sub_index}: "
                  f"尺寸={r.metadata.get('processed_size', '?')}")
    else:
        print(f"路径不存在: {path}")
        sys.exit(1)


def cmd_show_profile(args):
    """显示 BookProfile。"""
    path = Path(args.path)
    if path.is_dir():
        path = path / "profile.json"

    if not path.exists():
        print(f"未找到 profile: {path}")
        print(f"请先运行: python -m guji_preprocess analyze {path.parent}")
        sys.exit(1)

    profile = BookProfile.load(path)
    import json
    print(json.dumps(profile.to_dict(), ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(
        prog="guji_preprocess",
        description="古籍图像预处理框架")
    parser.add_argument("-o", "--output", default="output",
                        help="输出目录（默认: output）")

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # analyze
    p_analyze = subparsers.add_parser("analyze", help="分析古籍版式特征")
    p_analyze.add_argument("path", help="古籍文件夹路径")

    # process
    p_process = subparsers.add_parser("process", help="处理古籍图片")
    p_process.add_argument("path", help="古籍文件夹或图片路径")
    p_process.add_argument("--profile", default=None,
                           help="指定 profile.json 路径")

    # show-profile
    p_show = subparsers.add_parser("show-profile", help="显示 BookProfile")
    p_show.add_argument("path", help="古籍文件夹或 profile.json 路径")

    args = parser.parse_args()

    if args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "process":
        cmd_process(args)
    elif args.command == "show-profile":
        cmd_show_profile(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
