"""CLI 入口：python -m open_guji_cv <command> [args]

Web 界面：
    ui                          启动浏览器界面

切分：
    cut            <folder>  检测切分类型并执行切分 → cut.json + 切分后图片

分析：
    recognize-profile <folder>  分析版式特征 → profile.json
    preprocess <folder>         图像预处理（裁剪 / 增强 / 二值化）
    extract    <folder>         版面 + 字符检测，输出结构化 JSON

一键运行：
    run        <folder>   依次执行以上三步

字符聚类识别（刻本，Phase 4~6，详见 .claude/doc/char_clustering_design.md）：
    chars      <folder>   M1 字符提取 → phase4_chars/
    cluster    <folder>   M2+M3 保守聚类 → phase5_clusters/
    label      <folder>   M4+M5 候选生成 + 上下文排序 → phase6_labels/
    refine     <folder>   M5+ 上下文自动修正（簇级边缘化 + 自举 n-gram）
    bench-ocr  <folder>   多 OCR 引擎黄金集准确率对比
    review     <folder>   M6 人工审查 Web 界面 → phase7_review/labels.jsonl
    update     <folder>   M7 消费标签 → 字形库 / 阈值标定 / 用字习惯 / 语料
    bench      <target>   合成数据集基准评测（verify / cluster）

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

def cmd_ui(args):
    """启动 Web 界面。"""
    from .web.server import start_server
    start_server(port=args.port, open_browser=not args.no_browser)


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


def _book_out_dir(args) -> Path:
    """聚类命令的书输出目录：-o/<book_name>/。path 仅用于取书名。"""
    return Path(args.output) / Path(args.path).name


def cmd_chars(args):
    """M1 字符提取：phase3 网格 → phase4_chars/ 单字图块数据集。"""
    from .clustering.extractor import CharExtractor

    extractor = CharExtractor(padding_ratio=args.padding)
    source_dir = Path(args.input_dir) if args.input_dir else None
    name_filter = None
    if getattr(args, "range", None):
        book_dir = Path(args.path)
        if book_dir.is_dir():
            name_filter = _parse_range(args.range, book_dir)
    meta = extractor.run_book(_book_out_dir(args), source_dir=source_dir,
                              name_filter=name_filter)
    print(f"字符提取完成: {meta['stats']}")


def cmd_segment(args):
    """刻本严格网格切分（Phase 3 替代，无 OCR）→ phase3_char_grid/。"""
    from .clustering.grid_segment import GridSegmenter

    profile_path = Path(args.path) / "profile.json"
    chars_per_line = args.chars_per_line
    n_cols = args.cols
    if profile_path.exists():
        prof = BookProfile.load(profile_path)
        chars_per_line = chars_per_line or prof.chars_per_line
        n_cols = n_cols if n_cols is not None else prof.lines_per_page
    if not chars_per_line:
        print("请用 --chars-per-line 指定每行字数（刻本先验）")
        sys.exit(1)

    seg = GridSegmenter(chars_per_line,
                        n_cols=n_cols or None,
                        empty_ink_ratio=args.empty_ink_ratio)
    source_dir = Path(args.input_dir) if args.input_dir else None
    meta = seg.run_book(_book_out_dir(args), source_dir=source_dir)
    print(f"网格切分完成: {meta['stats']}")


def cmd_cluster(args):
    """M2+M3 保守聚类：phase4_chars/ → phase5_clusters/。"""
    from .clustering.clusterer import ClusterParams, ConservativeClusterer

    params = ClusterParams(feature=args.feature,
                           theta_high=args.theta_high,
                           knn_k=args.knn_k)
    clusterer = ConservativeClusterer(params)
    clusterer.run_book(_book_out_dir(args), montage=not args.no_montage)


def cmd_label(args):
    """M4+M5：候选生成 + 上下文排序 → phase6_labels/。"""
    from .clustering.candidates import (CandidateGenerator, GlyphKnnSource,
                                        OcrSource, PriorSource)
    from .clustering.labeling import build_lm, rank_book
    from .clustering.variants import VariantMap

    variant_map = VariantMap.load(args.variants)
    book_out_dir = _book_out_dir(args)

    sources = []
    for name in args.sources.split(","):
        name = name.strip()
        if name == "prior":
            sources.append(PriorSource())
        elif name == "ocr":
            sources.append(OcrSource())
        elif name == "rapidocr":
            from .clustering.candidates import RapidOcrSource
            sources.append(RapidOcrSource())
        elif name == "vlm":
            from .clustering.candidates import VlmSeedSource
            if not args.vlm_seed:
                print("来源 vlm 需要 --vlm-seed 指定种子目录")
                sys.exit(1)
            sources.append(VlmSeedSource(
                args.vlm_seed,
                book_out_dir / "phase5_clusters" / "clusters.json"))
        elif name == "glyph":
            from .clustering.glyph_library import GlyphLibrary
            sources.append(GlyphKnnSource(
                GlyphLibrary(args.glyph_store),
                edition_hint=args.edition))
        else:
            print(f"未知候选来源: {name}（可选: prior,ocr,rapidocr,vlm,glyph）")
            sys.exit(1)

    print(f"候选生成（来源: {[s.name for s in sources]}）...")
    CandidateGenerator(sources, variant_map).run_book(book_out_dir)

    print("上下文排序 ...")
    lm = build_lm(args.lm_model, args.lm_corpus, variant_map)
    stats = rank_book(book_out_dir, lm, variant_map)
    print(f"完成: {stats}，输出: {book_out_dir / 'phase6_labels'}")


def cmd_refine(args):
    """M5+ 上下文自动修正：簇级边缘化 + 同书自举 n-gram，迭代重解码。"""
    from .clustering.context_refine import refine_book

    report = refine_book(_book_out_dir(args), rounds=args.rounds,
                         lm_order=args.lm_order, use_lm=args.with_lm)
    print(json.dumps(report, ensure_ascii=False, indent=1))


def cmd_bench_ocr(args):
    """多 OCR 引擎在黄金集上的准确率对比。"""
    from .clustering.ocr_bench import run_bench

    r = run_bench(_book_out_dir(args), args.engines.split(","),
                  limit=args.limit, mode=args.goldset)
    print(f"黄金集[{r['goldset_mode']}] {r['goldset_size']} 簇 / "
          f"{r['goldset_instances']} 实例")
    print(f"{'引擎':<18}{'top1':>9}{'topk':>9}{'加权':>9}{'字/秒':>9}")
    for k, v in r["engines"].items():
        print(f"{k:<18}{v.get('top1', 0):>9.1%}{v.get('topk', 0):>9.1%}"
              f"{v.get('top1_weighted', 0):>9.1%}"
              f"{v.get('chars_per_sec', 0):>9}")


def cmd_review(args):
    """M6 人工审查 Web 界面：可疑队列 / 簇视图 / 上下文视图。"""
    from .clustering.review.server import start_review_server

    book_out_dir = _book_out_dir(args)
    if not (book_out_dir / "phase5_clusters" / "clusters.json").exists():
        print(f"未找到聚类结果，请先运行: python -m open_guji_cv cluster {args.path}")
        sys.exit(1)
    start_review_server(book_out_dir, port=args.port,
                        open_browser=not args.no_browser)


def cmd_update(args):
    """M7 反馈更新：消费 labels.jsonl → 字形库/阈值/用字习惯/语料。"""
    from .clustering.feedback import run_update

    summary = run_update(_book_out_dir(args), args.glyph_store,
                         edition_tag=args.edition,
                         calibrate=not args.no_calibrate)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def cmd_bench(args):
    """合成数据集 benchmark → benchmarks/results/ JSON 报告。"""
    from .clustering.bench import BENCHES, write_report

    fn = BENCHES[args.target]
    kwargs = {"n_chars": args.n_chars, "n_per_char": args.n_per_char,
              "wear": args.wear, "seed": args.seed}
    if args.target == "cluster":
        kwargs["feature"] = args.feature
    report = fn(**kwargs)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    path = write_report(report, args.out)
    print(f"报告: {path}")


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

    # ── ui ───────────────────────────────────────────────
    p = sub.add_parser("ui", help="启动 Web 界面")
    p.add_argument("--port", type=int, default=8632, help="端口号（默认: 8632）")
    p.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")

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

    # ── chars（M1 字符提取）──────────────────────────────
    p = sub.add_parser("chars",
                       help="M1 字符提取 → phase4_chars/（需先 extract）")
    p.add_argument("path", help="古籍文件夹路径（用作输出子目录名）")
    p.add_argument("--input-dir", default=None,
                   help="页面图目录（默认自动解析 s5_split/s4_deskew/s6_binarize）")
    p.add_argument("--padding", type=float, default=0.08,
                   help="bbox 外扩比例（默认 0.08）")
    p.add_argument("--range", default=None, help="处理范围（如 3-6 或 1,3,5）")

    # ── segment（刻本网格切分）───────────────────────────
    p = sub.add_parser("segment",
                       help="刻本严格网格切分（Phase 3 替代，无 OCR，需先 extract --steps layout）")
    p.add_argument("path", help="古籍文件夹路径（用作输出子目录名）")
    p.add_argument("--chars-per-line", type=int, default=None,
                   help="每行字数（默认读 profile.json）")
    p.add_argument("--cols", type=int, default=None,
                   help="每半页列数，启用列网格拟合（默认读 profile 的 "
                        "lines_per_page；传 0 禁用，沿用 Phase 2 列检测）")
    p.add_argument("--empty-ink-ratio", type=float, default=0.02,
                   help="判空墨迹覆盖率阈值（默认 0.02）")
    p.add_argument("--input-dir", default=None, help="页面图目录")

    # ── cluster（M2+M3 保守聚类）─────────────────────────
    p = sub.add_parser("cluster",
                       help="M2+M3 保守聚类 → phase5_clusters/（需先 chars）")
    p.add_argument("path", help="古籍文件夹路径（用作输出子目录名）")
    p.add_argument("--feature", default="hog", choices=["raw", "hog"],
                   help="特征后端（默认 hog）")
    p.add_argument("--theta-high", type=float, default=0.80,
                   help="合并阈值（默认 0.80，可由标定更新）")
    p.add_argument("--knn-k", type=int, default=10,
                   help="近邻候选数（默认 10）")
    p.add_argument("--no-montage", action="store_true",
                   help="不生成簇蒙太奇图")

    # ── label（M4+M5 候选+排序）──────────────────────────
    p = sub.add_parser("label",
                       help="M4+M5 候选生成 + 上下文排序 → phase6_labels/（需先 cluster）")
    p.add_argument("path", help="古籍文件夹路径（用作输出子目录名）")
    p.add_argument("--sources", default="prior",
                   help="候选来源，逗号分隔：prior,ocr,rapidocr,vlm,glyph（默认 prior）；"
                        "rapidocr=PP-OCRv4 ONNX，模型随包分发无需下载")
    p.add_argument("--glyph-store", default="glyph_store",
                   help="字形库目录（来源含 glyph 时使用）")
    p.add_argument("--vlm-seed", default=None,
                   help="VLM 识别种子目录（来源含 vlm 时使用，"
                        "含 mapping.json + recognitions.json）")
    p.add_argument("--edition", default=None,
                   help="书版提示 edition_tag（同版书检索优先）")
    p.add_argument("--variants", default=None,
                   help="异体字映射表路径（默认 config/dicts/variants.tsv）")
    p.add_argument("--lm-model", default=None, help="已训练的 n-gram 模型路径")
    p.add_argument("--lm-corpus", default=None,
                   help="语料目录（*.txt，现场训练 n-gram；与 --lm-model 二选一）")

    # ── refine（M5+ 上下文自动修正）──────────────────────
    p = sub.add_parser("refine",
                       help="M5+ 上下文自动修正（簇级边缘化 + 自举 n-gram）")
    p.add_argument("path", help="古籍文件夹路径（用作输出子目录名）")
    p.add_argument("--rounds", type=int, default=2, help="迭代轮数（默认 2）")
    p.add_argument("--lm-order", type=int, default=3, help="n-gram 阶数")
    p.add_argument("--with-lm", action="store_true",
                   help="启用同书自举 n-gram（默认关闭：实测在缺乏外部"
                        "语料时净有害，见 context_refine 模块文档）")

    # ── bench-ocr（多引擎对比）───────────────────────────
    p = sub.add_parser("bench-ocr", help="多 OCR 引擎黄金集准确率对比")
    p.add_argument("path", help="古籍文件夹路径（用作输出子目录名）")
    p.add_argument("--engines", default="rapidocr,tesseract:chi_tra",
                   help="引擎列表，逗号分隔：rapidocr / rapidocr-raw / "
                        "tesseract:chi_tra / tesseract:chi_sim")
    p.add_argument("--goldset", default="vlm_only",
                   choices=["vlm_only", "consensus"],
                   help="黄金集模式；跨引擎对比须用 vlm_only（无偏）")
    p.add_argument("--limit", type=int, default=None, help="只测前 N 个")

    # ── review（M6 审查界面）─────────────────────────────
    p = sub.add_parser("review",
                       help="M6 人工审查 Web 界面（需先 cluster/label）")
    p.add_argument("path", help="古籍文件夹路径（用作输出子目录名）")
    p.add_argument("--port", type=int, default=8633, help="端口号（默认 8633）")
    p.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")

    # ── update（M7 反馈更新）─────────────────────────────
    p = sub.add_parser("update",
                       help="M7 消费审查标签 → 字形库/阈值标定/用字习惯/语料")
    p.add_argument("path", help="古籍文件夹路径（用作输出子目录名）")
    p.add_argument("--glyph-store", default="glyph_store", help="字形库目录")
    p.add_argument("--edition", default=None,
                   help="书版 edition_tag（默认=书名；同版多书标同 tag）")
    p.add_argument("--no-calibrate", action="store_true", help="跳过阈值标定")

    # ── bench（基准评测）─────────────────────────────────
    p = sub.add_parser("bench", help="合成数据集 benchmark → JSON 报告")
    p.add_argument("target", choices=["verify", "cluster"], help="评测目标")
    p.add_argument("--n-chars", type=int, default=50, help="字表大小")
    p.add_argument("--n-per-char", type=int, default=10, help="每字实例数")
    p.add_argument("--wear", type=float, default=0.5, help="磨损强度 0~1")
    p.add_argument("--feature", default="hog", choices=["raw", "hog"])
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", default="benchmarks/results", help="报告输出目录")

    # ── show-profile ─────────────────────────────────────
    p = sub.add_parser("show-profile",
                       help="显示 BookProfile")
    p.add_argument("path", help="古籍文件夹或 profile.json 路径")

    args = parser.parse_args()

    commands = {
        "ui":                cmd_ui,
        "cut":               cmd_cut,
        "recognize-profile": cmd_recognize_profile,
        "analyze":           cmd_recognize_profile,  # 兼容别名
        "preprocess":        cmd_preprocess,
        "extract":           cmd_extract,
        "run":               cmd_run,
        "segment":           cmd_segment,
        "chars":             cmd_chars,
        "cluster":           cmd_cluster,
        "label":             cmd_label,
        "refine":            cmd_refine,
        "bench-ocr":         cmd_bench_ocr,
        "review":            cmd_review,
        "update":            cmd_update,
        "bench":             cmd_bench,
        "show-profile":      cmd_show_profile,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
