"""古籍预处理主 Pipeline。

编排三阶段流程：
  Phase 1: 书级分析 → BookProfile
  Phase 2: 图像预处理 → 干净图像
  Phase 3: 版面检测 → 版面结构 JSON
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .profile import BookProfile
from .analyzers import get_all_analyzers
from .preprocessors import get_preprocessors
from .detectors.lines import LineDetector
from .detectors.borders import BorderDetector
from .detectors.columns import ColumnDetector
from .utils.image_io import imread, imwrite


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}


@dataclass
class ProcessResult:
    """单张图片（或子图）的处理结果。"""
    source_path: str
    sub_index: int = 0               # 子图索引（0=完整页或第一个子图）
    preprocessed: np.ndarray | None = None
    layout: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


class GujiPipeline:
    """古籍预处理主管线。

    用法:
        pipeline = GujiPipeline()

        # Phase 1: 分析一本书
        profile = pipeline.analyze("data/book1/")

        # Phase 2+3: 处理单张图片
        results = pipeline.preprocess("data/book1/3.png", profile)

        # 完整流程
        pipeline.process_book("data/book1/")
    """

    def __init__(self, output_dir: str = "output"):
        self.output_dir = Path(output_dir)
        self.line_detector = LineDetector()
        self.border_detector = BorderDetector()
        self.column_detector = ColumnDetector()

    # ─── Phase 1: 书级分析 ──────────────────────────────────────

    def analyze(self, book_folder: str, max_samples: int = 10) -> BookProfile:
        """分析一本书的版式特征，生成 BookProfile。

        Args:
            book_folder: 包含样本图片的文件夹路径
            max_samples: 最多使用多少张样本图片

        Returns:
            BookProfile 实例
        """
        folder = Path(book_folder)
        image_paths = self._find_images(folder, max_count=max_samples)

        if not image_paths:
            print(f"未找到图片: {folder}")
            return BookProfile()

        print(f"Phase 1: 分析 {len(image_paths)} 张样本图片...")

        # 加载样本图片
        images = []
        for p in image_paths:
            img = imread(str(p))
            if img is not None:
                images.append(img)

        if not images:
            print("  无法加载任何图片")
            return BookProfile()

        # 运行所有分析器
        all_results = {}
        all_confidences = {}

        for analyzer in get_all_analyzers():
            print(f"  运行分析器: {analyzer.name}")
            result = analyzer.analyze(images)

            # 提取置信度信息
            if "_confidence" in result:
                all_confidences.update(result.pop("_confidence"))

            all_results.update(result)

        # 构建 BookProfile
        all_results["auto_detected"] = True
        all_results["detection_confidence"] = all_confidences
        profile = BookProfile.from_dict(all_results)

        # 保存到文件
        profile_path = folder / "profile.json"
        profile.save(profile_path)
        print(f"  已保存 BookProfile: {profile_path}")
        print(f"  {profile}")

        return profile

    # ─── Phase 2: 图像预处理 ────────────────────────────────────

    def preprocess(self, image_path: str, profile: BookProfile
                   ) -> list[ProcessResult]:
        """对单张图片执行预处理和版面检测。

        Args:
            image_path: 图片文件路径
            profile: 当前书的 BookProfile

        Returns:
            ProcessResult 列表（通常 1 个，未剪切筒子页为 2 个）
        """
        img = imread(image_path)
        if img is None:
            print(f"  无法读取图片: {image_path}")
            return []

        print(f"  Phase 2: 预处理 {Path(image_path).name}")

        # 获取需要的预处理器
        preprocessors = get_preprocessors(profile)
        print(f"    启用预处理器: {[p.name for p in preprocessors]}")

        # 执行预处理管线
        current_images = [img]
        for pp in preprocessors:
            next_images = []
            for cur_img in current_images:
                result = pp.process(cur_img, profile)
                if isinstance(result, list):
                    next_images.extend(result)
                else:
                    next_images.append(result)
            current_images = next_images
            print(f"    {pp.name}: {len(current_images)} 张图像")

        # Phase 3: 版面检测
        results = []
        for i, processed_img in enumerate(current_images):
            print(f"  Phase 3: 版面检测 (子图 {i})")

            layout = self._detect_layout(processed_img, profile)

            result = ProcessResult(
                source_path=image_path,
                sub_index=i,
                preprocessed=processed_img,
                layout=layout,
                metadata={
                    "preprocessors_applied": [p.name for p in preprocessors],
                    "original_size": {"width": img.shape[1], "height": img.shape[0]},
                    "processed_size": {"width": processed_img.shape[1],
                                       "height": processed_img.shape[0]},
                },
            )
            results.append(result)

        return results

    def _detect_layout(self, image: np.ndarray,
                       profile: BookProfile) -> dict:
        """Phase 3: 检测版面结构。"""
        # 线段检测
        lsd_data = self.line_detector.detect(image)

        # 边框检测
        img_w = lsd_data["image_size"]["width"]
        img_h = lsd_data["image_size"]["height"]
        border_result = self.border_detector.detect(
            lsd_data, img_w, img_h, profile)

        # 列结构分析
        column_result = self.column_detector.analyze(border_result, profile)

        return {
            "lsd_summary": lsd_data["summary"],
            "borders": {k: v for k, v in border_result.items() if k != "debug"},
            "columns": column_result,
        }

    # ─── 完整流程 ─────────────────────────────────────────────

    def process_book(self, book_folder: str,
                     profile: BookProfile | None = None) -> None:
        """完整流程：分析 + 处理整本书。

        Args:
            book_folder: 古籍文件夹路径
            profile: 可选的已有 BookProfile（如果为 None 则自动分析）
        """
        folder = Path(book_folder)
        book_name = folder.name

        print(f"{'=' * 60}")
        print(f"处理古籍: {book_name}")
        print(f"{'=' * 60}")

        # 加载或生成 profile
        profile_path = folder / "profile.json"
        if profile is not None:
            pass
        elif profile_path.exists():
            print(f"加载已有 BookProfile: {profile_path}")
            profile = BookProfile.load(profile_path)
            print(f"  {profile}")
        else:
            profile = self.analyze(str(folder))

        # 处理每张图片
        image_paths = self._find_images(folder)
        out_dir = self.output_dir / book_name
        out_dir.mkdir(parents=True, exist_ok=True)

        for image_path in image_paths:
            stem = image_path.stem
            print(f"\n--- {image_path.name} ---")

            results = self.preprocess(str(image_path), profile)

            for result in results:
                suffix = f"_sub{result.sub_index}" if len(results) > 1 else ""

                # 保存预处理后的图像
                if result.preprocessed is not None:
                    out_img = out_dir / f"{stem}{suffix}_preprocessed.png"
                    imwrite(str(out_img), result.preprocessed)

                # 保存版面结构
                out_json = out_dir / f"{stem}{suffix}_layout.json"
                with open(out_json, "w", encoding="utf-8") as f:
                    json.dump(result.layout, f, ensure_ascii=False, indent=2)

        print(f"\n完成！输出目录: {out_dir}")

    # ─── 工具方法 ─────────────────────────────────────────────

    @staticmethod
    def _find_images(folder: Path, max_count: int | None = None) -> list[Path]:
        """在文件夹中查找图片文件。"""
        skip_suffixes = {"_lsd", "_borders", "_annotated", "_preprocessed"}
        images = sorted(
            f for f in folder.iterdir()
            if f.suffix.lower() in IMAGE_EXTENSIONS
            and not any(f.stem.endswith(s) for s in skip_suffixes)
        )
        if max_count is not None:
            images = images[:max_count]
        return images
