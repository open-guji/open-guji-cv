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
    review-export <folder>  导出审查批次为自包含 HTML（Artifact/GitHub Pages）
    review-ingest <folder>  回收页面审查事件 → labels.jsonl
    seed       <folder>   逐页进库（种子）：双信号+六条疑问判定 → phase9_seed/
    seed-ingest <folder>  回收种子审查事件 → human 进库 + 队列状态更新
    update     <folder>   M7 消费标签 → 字形库 / 阈值标定 / 用字习惯 / 语料
    glyph-db   <action>   M8 跨书字形数据库
                          （import / import-font / drop-edition / stats / export / rebuild）
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

    extractor = CharExtractor(padding_ratio=args.padding,
                              strategy=args.strategy)
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
                           verify_method=args.verify_method,
                           cov_high=args.cov_high,
                           miss_wmax=args.miss_wmax,
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
            # GlyphDB（M8 升级，见 glyph_db.py）取代了早期的 GlyphLibrary
            # JSONL 直读：glyph_store/glyphs.jsonl 的 schema 已改过（如
            # 'ids' 字段），GlyphLibrary 按旧 schema 解析会直接抛异常。
            # GlyphDB.query() 签名与 GlyphKnnSource 需要的完全一致
            # （返回带 char/f1/verdict 的命中），SQLite 索引缺失时
            # 从 Git 真源（store 目录）现场重建一次即可。
            from .clustering.glyph_db import GlyphDB, rebuild_from_store
            store = Path(args.glyph_store)
            db_path = store / "glyphdb.sqlite"
            if not db_path.exists():
                print(f"字形库索引缺失，从 {store} 重建 ...")
                rebuild_from_store(store, db_path)
            sources.append(GlyphKnnSource(
                GlyphDB(db_path),
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


def cmd_recognize(args):
    """字形库优先识别第一段（glyph_db_first_design §2）：逐图块匹配库。

    same 档（完美匹配）直接继承库条目的字 = 识别完成；unsure/diff 档
    只落证据与候选先验，等 OCR+上下文分支接线（设计 §7 第 4 步）。
    输出 phase8_match/matches.jsonl（每行一个实例的 MatchResult 证据）。
    """
    from .clustering.extractor import load_index
    from .clustering.glyph_db import GlyphDB, _unpng
    from .clustering.match import GlyphMatcher
    from .clustering.normalize import normalize_patch

    book_out_dir = _book_out_dir(args)
    root = book_out_dir / "phase4_chars"
    matcher = GlyphMatcher(k=args.knn_k)

    db = GlyphDB(args.db)
    cur = db.conn.cursor()
    sql = """SELECT g.char, e.instance_id, d.data
             FROM exemplars e
             JOIN glyphs g ON g.glyph_id = e.glyph_id
             JOIN derived d ON d.instance_id = e.instance_id AND d.kind='norm'"""
    dbargs: tuple = ()
    if args.edition:
        sql += " WHERE g.edition_tag = ?"
        dbargs = (args.edition,)
    for char, iid, data in cur.execute(sql, dbargs).fetchall():
        matcher.add(iid, char, _unpng(data))
    db.close()
    print(f"库载入 {len(matcher)} 个已验证刻例")

    out_dir = book_out_dir / "phase8_match"
    out_dir.mkdir(parents=True, exist_ok=True)
    recs = [r for r in load_index(root) if r.cell_type == "char"]
    n_same = n_unsure = n_diff = 0
    import cv2 as _cv2
    with open(out_dir / "matches.jsonl", "w", encoding="utf-8") as f:
        for n, rec in enumerate(recs, 1):
            gray = _cv2.imread(str(root / rec.patch_path), _cv2.IMREAD_GRAYSCALE)
            if gray is None:
                continue
            r = matcher.match(normalize_patch(gray))
            n_same += r.verdict == "same"
            n_unsure += r.verdict == "unsure"
            n_diff += r.verdict == "diff"
            row = {"id": rec.id, **r.to_dict()}
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            if n % 2000 == 0:
                print(f"  {n}/{len(recs)}  same {n_same} unsure {n_unsure} diff {n_diff}",
                      flush=True)
    total = max(1, n_same + n_unsure + n_diff)
    summary = {"n": total, "same": n_same, "unsure": n_unsure, "diff": n_diff,
               "coverage": round(n_same / total, 4), "db_size": len(matcher)}
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


def _general_corpus_paths(args):
    """--general-corpus 解析：显式路径 > 自动发现 corpus/external/*.txt；
    传 none 关闭混合。"""
    if args.general_corpus:
        if any(str(p).lower() == "none" for p in args.general_corpus):
            return None
        return args.general_corpus
    found = sorted(Path("corpus/external").glob("*.txt"))
    return found or None


def cmd_seed(args):
    """逐页进库（种子，设计 §3.5）：双信号 + 六条疑问判定 → phase9_seed/。

    双信号一致零疑问 → align provenance 直接进库；其余进审查队列
    （queue.jsonl），等 seed-ingest 回收裁决。断点续跑按页粒度。
    """
    from .clustering.glyph_db import GlyphDB
    from .clustering.seeding import seed_book

    book_out_dir = _book_out_dir(args)
    pages = None
    if args.pages == "body":
        gold_path = Path(args.page_type)
        if not gold_path.exists():
            print(f"页型金标不存在: {gold_path}（--pages all 可跳过正文筛选）")
            sys.exit(1)
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        book = book_out_dir.name
        pages = {g["page"] for g in gold
                 if g["book"] == book and g["page_type"] == "body"}
        if not pages:
            print(f"金标里没有 {book} 的正文页")
            sys.exit(1)

    db = GlyphDB(args.db)
    try:
        summary = seed_book(book_out_dir, db, args.corpus, pages=pages,
                            carrier_path=args.ocr_carrier,
                            max_pages=args.max_pages,
                            prob_threshold=args.prob_threshold,
                            context_margin=args.context_margin,
                            solo_cov=args.match_solo_cov,
                            general_corpus=_general_corpus_paths(args),
                            font_store=(None if str(args.font_store).lower()
                                        == "none" else args.font_store),
                            font_editions=[e.strip() for e in
                                           args.font_editions.split(",")
                                           if e.strip()],
                            edition=args.edition)
    finally:
        db.close()
    print(json.dumps(summary, ensure_ascii=False, indent=1))


def cmd_seed_ingest(args):
    """回收种子审查事件（GUJI-SEED-EVENT 行）→ human 进库 + 队列更新。"""
    from .clustering.glyph_db import GlyphDB
    from .clustering.seed_queue import parse_seed_events
    from .clustering.seeding import ingest_decisions

    events = parse_seed_events(Path(args.events).read_text(encoding="utf-8"))
    if not events:
        print("文件里没有可用的 GUJI-SEED-EVENT 行")
        sys.exit(1)
    db = GlyphDB(args.db)
    try:
        summary = ingest_decisions(_book_out_dir(args), db, events,
                                   edition=args.edition)
    finally:
        db.close()
    print(json.dumps(summary, ensure_ascii=False, indent=1))


def cmd_seed_scrub(args):
    """对既有种子队列的待审行复扫空白/非字（新增检测规则后回填存量）。"""
    from .clustering.seeding import scrub_nonchar

    print(json.dumps(scrub_nonchar(_book_out_dir(args)),
                     ensure_ascii=False, indent=1))


def cmd_refine(args):
    """M5+ 上下文自动修正：簇级边缘化 + 同书自举 n-gram，迭代重解码。"""
    from .clustering.context_refine import refine_book

    report = refine_book(_book_out_dir(args), rounds=args.rounds,
                         lm_order=args.lm_order, use_lm=args.with_lm,
                         external_corpus=args.corpus,
                         general_corpus=args.general_corpus,
                         general_weight=args.general_weight,
                         lam=args.lam)
    print(json.dumps(report, ensure_ascii=False, indent=1))


def cmd_eval_align(args):
    """参考文本对齐评测：真实字准确率（非"汉字率"），多册可合并计。"""
    from .clustering.align_eval import evaluate_books, top_confusions, build_ngram_index
    from pathlib import Path as _Path

    books = args.books or [args.path]
    text_dirs = {b: Path(args.output) / b / "phase6_labels" / "text" for b in books}
    missing = [b for b, d in text_dirs.items() if not d.is_dir()]
    if missing:
        print(f"缺少转写文本，请先跑 label/refine: {missing}")
        sys.exit(1)

    report = evaluate_books(text_dirs, args.corpus)
    for name, b in report["books"].items():
        print(f"{name}: 对齐 {b['n_anchored']}/{b['n_pages']} 页，"
              f"{b['total_matched']}/{b['total_chars']} 字，"
              f"准确率 {b['accuracy']:.2%}")
    o = report["overall"]
    print(f"合计: {o['total_matched']}/{o['total_chars']} 字，"
          f"准确率 {o['accuracy']:.2%}")

    if args.confusions:
        corpus = Path(args.corpus).read_text(encoding="utf-8")
        index = build_ngram_index(corpus)
        merged: dict[str, int] = {}
        for d in text_dirs.values():
            for k, n in top_confusions(d, corpus, index, top_k=args.confusions):
                merged[k] = merged.get(k, 0) + n
        top = sorted(merged.items(), key=lambda x: -x[1])[:args.confusions]
        print(f"\n混淆头部（转写→参考，仅计等长替换）：")
        for k, n in top:
            print(f"  {k} ×{n}")

    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                  encoding="utf-8")
        print(f"→ {args.out}")


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


def cmd_review_export(args):
    """无命令行审查：导出自包含 HTML 批次（Artifact / GitHub Pages）。"""
    from .clustering.review.artifact_export import export_batch

    book_out_dir = _book_out_dir(args)
    if not (book_out_dir / "phase5_clusters" / "clusters.json").exists():
        print(f"未找到聚类结果，请先运行: python -m open_guji_cv cluster {args.path}")
        sys.exit(1)
    extra = [Path(args.output) / Path(x).name for x in (args.also or [])]
    out = export_batch([book_out_dir] + extra, out_path=args.out,
                       limit=args.limit, sort=args.sort, title=args.title)
    size = out.stat().st_size
    print(f"批次页面: {out}  ({size / 1e6:.1f} MB)")


def cmd_review_ingest(args):
    """无命令行审查：从保存后的页面/粘贴文本回收事件 → labels.jsonl。"""
    from .clustering.review.artifact_export import ingest_events

    text = Path(args.file).read_text(encoding="utf-8")
    books = [_book_out_dir(args)] + [Path(args.output) / Path(x).name
                                     for x in (args.also or [])]
    summary = [ingest_events(b, text) for b in books]
    print(json.dumps(summary if len(summary) > 1 else summary[0],
                     ensure_ascii=False, indent=2))
    if summary["new"]:
        print(f"下一步: python -m open_guji_cv update {args.path}")


def cmd_glyph_db(args):
    """M8 跨书字形数据库：import 收尾入库 / stats 概览。"""
    from .clustering.glyph_db import GlyphDB

    db = GlyphDB(Path(args.store) / "glyphdb.sqlite")
    try:
        if args.action == "export":
            from .clustering.glyph_db import export_store
            summary = export_store(db, args.store)
        elif args.action == "rebuild":
            from .clustering.glyph_db import rebuild_from_store
            db.close()
            summary = rebuild_from_store(args.store,
                                         Path(args.store) / "glyphdb.sqlite")
            db = None
        elif args.action == "drop-edition":
            if not args.edition:
                print("drop-edition 需要 --edition"); sys.exit(1)
            summary = db.drop_edition(args.edition)
        elif args.action == "import-font":
            from .clustering.font_glyphs import import_fonts_from_manifest
            summary = import_fonts_from_manifest(
                db, args.manifest, only=args.edition,
                charset=args.charset, limit=args.limit,
                jobs=args.jobs)
        elif args.action == "import":
            if not args.path:
                print("import 需要书目录参数"); sys.exit(1)
            meta = {"collection": args.collection,
                    "script_style": args.script_style,
                    "title": args.title}
            summary = db.import_book(_book_out_dir(args),
                                     edition_tag=args.edition,
                                     source_meta=meta)
        else:
            summary = db.stats()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        if db is not None:
            db.close()


def cmd_update(args):
    """M7 反馈更新：消费 labels.jsonl → 字形库/阈值/用字习惯/语料。"""
    from .clustering.feedback import run_update

    summary = run_update(_book_out_dir(args), args.glyph_store,
                         edition_tag=args.edition,
                         calibrate=not args.no_calibrate)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def cmd_seg_bench(args):
    """格内净化 benchmark：各归属算法在同一批样本上的可复现对比。"""
    import json as _json
    from .clustering.seg_eval import STRATEGIES, format_report, run_dataset

    names = args.strategies.split(",") if args.strategies else None
    strategies = ({k: STRATEGIES[k] for k in names} if names else None)
    report = run_dataset(Path(args.samples), strategies)
    print(f"样本 {report['n_cases']} 组")
    print(format_report(report))
    if args.out:
        Path(args.out).write_text(_json.dumps(report, ensure_ascii=False,
                                              indent=2), encoding="utf-8")
        print(f"→ {args.out}")


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
    p.add_argument("--strategy", default="component_owner",
                   choices=("component_owner", "padding_box"),
                   help="格内墨迹归属算法（默认列级连通体归属；"
                        "padding_box 为旧的裁框做法，供对照与回滚）")
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
    p.add_argument("--verify-method", default="elastic",
                   choices=["elastic", "coverage", "overlap"],
                   help="配准判据（默认 elastic=软覆盖+分块弹性对齐；"
                        "coverage=旧的 r=2 硬膨胀覆盖率；overlap=更旧的 F1 对照）")
    p.add_argument("--cov-high", type=float, default=None,
                   help="合并覆盖率闸（默认跟随判据的聚类侧标定："
                        "elastic 0.988 / coverage 0.992）")
    p.add_argument("--miss-wmax", type=float, default=12,
                   help="coverage 判据的 12×12 窗口残差上限（默认 12px）")
    p.add_argument("--theta-high", type=float, default=0.80,
                   help="overlap 判据的合并阈值（默认 0.80）")
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

    # ── recognize（字形库优先识别，第一段）───────────────
    p = sub.add_parser("recognize",
                       help="字形库优先识别：逐图块匹配 GlyphDB → phase8_match/"
                            "（same 档=识别完成；unsure/diff 落证据待裁决）")
    p.add_argument("path", help="古籍文件夹路径（用作输出子目录名）")
    p.add_argument("--db", default="glyph.db", help="GlyphDB SQLite 路径")
    p.add_argument("--edition", default=None, help="限定 edition_tag（同版匹配）")
    p.add_argument("--knn-k", type=int, default=10, help="近邻候选数（默认 10）")

    # ── seed / seed-ingest（逐页进库，设计 §3.5）─────────
    p = sub.add_parser("seed",
                       help="逐页进库（种子）：双信号+六条疑问判定 → "
                            "phase9_seed/（需先 chars + OCR 载体）")
    p.add_argument("path", help="古籍文件夹路径（用作输出子目录名）")
    p.add_argument("--db", required=True, help="GlyphDB SQLite 路径")
    p.add_argument("--corpus", required=True, action="append",
                   help="整理本参考文本路径（可给多次：主整理本 + 自补的"
                        "奏折/上谕文本，内部拼接后锚定/参考/LM 同源）")
    p.add_argument("--context-margin", type=float, default=0.70,
                   help="上下文通道的 margin 准入阈（用户实审 303 条裁决"
                        "重标定：≥0.70 全对；默认 0.70）")
    p.add_argument("--general-corpus", action="append", default=None,
                   help="通用语料路径（可给多次；缺省自动发现 corpus/"
                        "external/*.txt）。与本书语料线性混合成上下文 LM"
                        "（本书 0.9 / 通用 0.1，charset_and_lm.md §二）；"
                        "给 --general-corpus none 可关闭混合")
    p.add_argument("--font-store", default="glyph_store",
                   help="字体字形库（glyph-db import-font 建的），刻本库匹配"
                        "不上时从这里找备选；给 none 关闭")
    p.add_argument("--font-editions", default="font:iming",
                   help="用哪几套字体（逗号分隔）。字体只作候选源，永不"
                        "参与准入裁决——实测 recall@1 仅两成，分布不可分")
    p.add_argument("--match-solo-cov", type=float, default=0.99,
                   help="库匹配单独通道的 cov 阈：无整理本锚定时，库内"
                        "形状验证 cov ≥ 此值直接进库（默认 0.99；0.98 "
                        "首日即出压线错例 揀/棟，用户裁定收紧）")
    p.add_argument("--pages", default="body", choices=["body", "all"],
                   help="body=只跑金标正文页（默认）；all=索引里的全部页")
    p.add_argument("--page-type",
                   default="../open-guji-dataset/page-type/expected.json",
                   help="页型金标路径（--pages body 时使用）")
    p.add_argument("--ocr-carrier", default=None,
                   help="OCR 载体 jsonl（默认 phase4_chars/ocr_carrier.jsonl）")
    p.add_argument("--max-pages", type=int, default=None,
                   help="本次最多处理的页数（断点续跑分批推进用）")
    p.add_argument("--prob-threshold", type=float, default=0.85,
                   help="weak_single 的 OCR prob 阈（默认 0.85，待 char-ocr 集标定）")
    p.add_argument("--edition", default=None,
                   help="edition_tag（默认=书名；同版多书标同 tag）")

    p = sub.add_parser("seed-scrub",
                       help="对种子队列待审行复扫空白/非字（规则升级后回填存量）")
    p.add_argument("path", help="古籍文件夹路径（用作输出子目录名）")

    p = sub.add_parser("seed-ingest",
                       help="回收种子审查事件（GUJI-SEED-EVENT）→ human 进库")
    p.add_argument("path", help="古籍文件夹路径（用作输出子目录名）")
    p.add_argument("--db", required=True, help="GlyphDB SQLite 路径")
    p.add_argument("--events", required=True,
                   help="含 GUJI-SEED-EVENT 行的文本/HTML 文件")
    p.add_argument("--edition", default=None, help="edition_tag（默认=书名）")

    # ── refine（M5+ 上下文自动修正）──────────────────────
    p = sub.add_parser("refine",
                       help="M5+ 上下文自动修正（簇级边缘化 + 自举 n-gram）")
    p.add_argument("path", help="古籍文件夹路径（用作输出子目录名）")
    p.add_argument("--rounds", type=int, default=2, help="迭代轮数（默认 2）")
    p.add_argument("--lm-order", type=int, default=3, help="n-gram 阶数")
    p.add_argument("--with-lm", action="store_true",
                   help="启用同书自举 n-gram（默认关闭：实测在缺乏外部"
                        "语料时净有害，见 context_refine 模块文档）")
    p.add_argument("--corpus", default=None,
                   help="本书/本版语料（目录或 txt）：高权重 LM 分量 + 本版用字习惯")
    p.add_argument("--general-corpus", default=None,
                   help="通用古文语料（目录或 txt）：低权重 LM 分量。"
                        "体裁要对得上被测书（实测经解语料对上谕页毫无收益，"
                        "诏令奏议语料 +1.21%%）")
    p.add_argument("--general-weight", type=float, default=0.1,
                   help="通用分量的权重（默认 0.1，本书分量取 1-w）")
    p.add_argument("--lam", type=float, default=0.65,
                   help="OCR 项与 LM 项的配比（默认 0.65；context-correction "
                        "实测 0.55 给 LM 过多话语权，有害翻转翻倍）")

    # ── bench-ocr（多引擎对比）───────────────────────────
    p = sub.add_parser("eval-align",
                       help="参考文本对齐评测：真实字准确率（需先 label/refine）")
    p.add_argument("path", help="古籍文件夹路径（单册时用；多册见 --books）")
    p.add_argument("--corpus", required=True, help="整理本参考文本路径")
    p.add_argument("--books", nargs="*", default=None,
                   help="多册合并评测（覆盖 path），如 vol01 vol02")
    p.add_argument("--confusions", type=int, default=0,
                   help="报告混淆头部 top-N（0=不报）")
    p.add_argument("--out", default=None, help="报告写入 JSON 路径")

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

    # ── review-export / review-ingest（无命令行审查）─────
    p = sub.add_parser("review-export",
                       help="导出审查批次为自包含 HTML（Artifact/GitHub Pages）")
    p.add_argument("path", help="古籍文件夹路径（用作输出子目录名）")
    p.add_argument("--limit", type=int, default=400, help="批次簇数上限")
    p.add_argument("--sort", default="gain", choices=["gain", "low_conf"],
                   help="排序：gain=预期收益降序 / low_conf=置信度升序")
    p.add_argument("--out", default=None, help="输出 HTML 路径")
    p.add_argument("--title", default=None, help="页面标题")
    p.add_argument("--also", nargs="*", default=None,
                   help="并入批次的其他书目录（多册合并审查）")

    p = sub.add_parser("review-ingest",
                       help="从保存后的审查页面/粘贴文本回收事件 → labels.jsonl")
    p.add_argument("path", help="古籍文件夹路径（用作输出子目录名）")
    p.add_argument("--file", required=True, help="含 GUJI-EVENT 行的文本/HTML 文件")
    p.add_argument("--also", nargs="*", default=None,
                   help="一并回收的其他书目录（多册批次）")

    # ── glyph-db（M8 跨书字形数据库）─────────────────────
    p = sub.add_parser("glyph-db", help="跨书字形数据库（SQLite）")
    p.add_argument("action",
                   choices=["import", "stats", "export", "rebuild",
                            "import-font", "drop-edition"])
    p.add_argument("path", nargs="?", help="书文件夹路径（import 用）")
    p.add_argument("--store", default="glyph_store", help="字形库目录")
    p.add_argument("--edition", default=None,
                   help="版本 edition_tag（import 默认=书名；"
                        "import-font 用于只导 manifest 里的某一套字体）")
    p.add_argument("--manifest", default="config/fonts/manifest.json",
                   help="字体清单（import-font 用）")
    p.add_argument("--charset", default=None,
                   help="字表文件（import-font 用，默认取 manifest 里的）")
    p.add_argument("--limit", type=int, default=None,
                   help="只导前 N 个字（import-font 冒烟测试用）")
    p.add_argument("--jobs", type=int, default=1,
                   help="import-font 并行渲染进程数（渲染+归一是纯 CPU；"
                        "写库仍单线程）")
    p.add_argument("--collection", default=None, help="丛书（如 武英殿聚珍版）")
    p.add_argument("--script-style", default=None, help="字体（宋体刻/写刻/手写）")
    p.add_argument("--title", default=None, help="书名")

    # ── update（M7 反馈更新）─────────────────────────────
    p = sub.add_parser("update",
                       help="M7 消费审查标签 → 字形库/阈值标定/用字习惯/语料")
    p.add_argument("path", help="古籍文件夹路径（用作输出子目录名）")
    p.add_argument("--glyph-store", default="glyph_store", help="字形库目录")
    p.add_argument("--edition", default=None,
                   help="书版 edition_tag（默认=书名；同版多书标同 tag）")
    p.add_argument("--no-calibrate", action="store_true", help="跳过阈值标定")

    # ── bench（基准评测）─────────────────────────────────
    p = sub.add_parser("seg-bench",
                       help="格内净化 benchmark（多归属算法对比）")
    p.add_argument("samples", help="样本目录（每个子目录含 strip/gold/case.json）")
    p.add_argument("--strategies", default=None,
                   help="逗号分隔的策略名，默认全跑")
    p.add_argument("--out", default=None, help="报告写入 JSON 路径")

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
        "seg-bench":         cmd_seg_bench,
        "chars":             cmd_chars,
        "cluster":           cmd_cluster,
        "label":             cmd_label,
        "recognize":         cmd_recognize,
        "seed":              cmd_seed,
        "seed-scrub":        cmd_seed_scrub,
        "seed-ingest":       cmd_seed_ingest,
        "refine":            cmd_refine,
        "eval-align":        cmd_eval_align,
        "bench-ocr":         cmd_bench_ocr,
        "review":            cmd_review,
        "review-export":     cmd_review_export,
        "review-ingest":     cmd_review_ingest,
        "glyph-db":          cmd_glyph_db,
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
