"""古籍预处理主 Pipeline。

统一的步骤化管线：
  s0: 书级分析 → BookProfile
  s1~s5: 图像预处理步骤 → 每步保存到独立文件夹
  最后: 版面检测 → 版面结构 JSON
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .profile import BookProfile
from .analyzers import get_all_analyzers
from .preprocessors import STEPS, StepDef
from .detectors.lines import LineDetector
from .detectors.borders import BorderDetector
from .detectors.columns import ColumnDetector
from .utils.image_io import imread, imwrite


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}


@dataclass
class ProcessResult:
    """单张图片（或子图）的处理结果。"""
    source_path: str
    sub_index: int = 0
    preprocessed: np.ndarray | None = None
    layout: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)


class GujiPipeline:
    """古籍预处理主管线。

    用法:
        pipeline = GujiPipeline()

        # 仅分析
        profile = pipeline.analyze("data/book1/")

        # 完整流程：分析 + 步骤化预处理
        pipeline.process_book("data/book1/")
    """

    def __init__(self, output_dir: str = "output"):
        self.output_dir = Path(output_dir)
        self.line_detector = LineDetector()
        self.border_detector = BorderDetector()
        self.column_detector = ColumnDetector()

    # ─── s0: 书级分析 ─────────────────────────────────────────

    def analyze(self, book_folder: str, max_samples: int = 10) -> BookProfile:
        """分析一本书的版式特征，生成 BookProfile。"""
        folder = Path(book_folder)
        image_paths = self._find_images(folder, max_count=max_samples)

        if not image_paths:
            print(f"未找到图片: {folder}")
            return BookProfile()

        print(f"s0 分析: {len(image_paths)} 张样本图片...")

        images = []
        for p in image_paths:
            img = imread(str(p))
            if img is not None:
                images.append(img)

        if not images:
            print("  无法加载任何图片")
            return BookProfile()

        all_results = {}
        all_confidences = {}

        for analyzer in get_all_analyzers():
            print(f"  运行分析器: {analyzer.name}")
            result = analyzer.analyze(images)
            if "_confidence" in result:
                all_confidences.update(result.pop("_confidence"))
            all_results.update(result)

        all_results["auto_detected"] = True
        all_results["detection_confidence"] = all_confidences
        profile = BookProfile.from_dict(all_results)

        # 保存 profile.json 到输出目录
        profile_path = folder / "profile.json"
        profile.save(profile_path)
        print(f"  已保存: {profile_path}")
        print(f"  {profile}")

        return profile

    # ─── 步骤化预处理 ─────────────────────────────────────────

    def process_book(self, book_folder: str,
                     profile: BookProfile | None = None) -> None:
        """完整流程：分析 + 步骤化预处理整本书。

        每个步骤的输出保存到独立文件夹（s1_crop_spine/, s2_crop_border/, ...）。
        跳过的步骤不产生文件夹，下游步骤自动从最近的上游输出读取。
        """
        folder = Path(book_folder)
        book_name = folder.name

        print(f"{'=' * 60}")
        print(f"处理古籍: {book_name}")
        print(f"{'=' * 60}")

        # ── s0: 加载或生成 profile ──
        profile = self._load_or_analyze(folder, profile)
        out_dir = self.output_dir / book_name
        out_dir.mkdir(parents=True, exist_ok=True)

        # 保存 profile 副本到输出目录
        profile.save(out_dir / "profile.json")

        # ── s1~s5: 逐步执行预处理 ──
        current_dir = folder  # 起始：原始图片目录
        manifest_executed = []
        manifest_skipped = []

        for step in STEPS:
            if step.is_needed(profile):
                step_dir = out_dir / step.folder_name
                n_images = self._run_step(step, current_dir, step_dir, profile)
                current_dir = step_dir
                manifest_executed.append({
                    "number": step.number,
                    "name": step.name,
                    "folder": step.folder_name,
                    "images": n_images,
                })
                print(f"  s{step.number} {step.name}: {n_images} 张图像 → {step.folder_name}/")
            else:
                manifest_skipped.append({
                    "number": step.number,
                    "name": step.name,
                    "reason": self._skip_reason(step, profile),
                })
                print(f"  s{step.number} {step.name}: 跳过 ({self._skip_reason(step, profile)})")

        # ── 保存 manifest.json ──
        final_folder = manifest_executed[-1]["folder"] if manifest_executed else ""
        manifest = {
            "book": book_name,
            "profile": "profile.json",
            "steps_executed": manifest_executed,
            "steps_skipped": manifest_skipped,
            "final_output": final_folder,
        }
        manifest_path = out_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        print(f"\n完成！输出目录: {out_dir}")
        print(f"  最终结果: {final_folder}/")

    def _run_step(self, step: StepDef, input_dir: Path,
                  output_dir: Path, profile: BookProfile) -> int:
        """执行单个预处理步骤：读取 input_dir 中的图片，处理后写入 output_dir。

        Returns:
            输出图片数量
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        preprocessor = step.create_preprocessor()
        image_paths = self._find_images(input_dir)
        n_output = 0

        for img_path in image_paths:
            img = imread(str(img_path))
            if img is None:
                continue

            result = preprocessor.process(img, profile)

            if isinstance(result, list):
                # 拆分步骤：result = [(suffix, image), ...]
                for suffix, sub_img in result:
                    out_name = f"{img_path.stem}_{suffix}.png"
                    imwrite(str(output_dir / out_name), sub_img)
                    n_output += 1
            else:
                # 单图输出：保持原文件名
                imwrite(str(output_dir / img_path.name), result)
                n_output += 1

        return n_output

    def _load_or_analyze(self, folder: Path,
                         profile: BookProfile | None) -> BookProfile:
        """加载已有 profile 或自动分析。"""
        if profile is not None:
            print(f"使用传入的 BookProfile: {profile}")
            return profile

        profile_path = folder / "profile.json"
        if profile_path.exists():
            print(f"加载已有 BookProfile: {profile_path}")
            profile = BookProfile.load(profile_path)
            print(f"  {profile}")
            return profile

        return self.analyze(str(folder))

    @staticmethod
    def _skip_reason(step: StepDef, profile: BookProfile) -> str:
        """生成步骤跳过的原因说明。"""
        if step.name == "crop_spine":
            return "无书脊阴影"
        if step.name == "split":
            return f"page_type={profile.page_type}"
        return "条件不满足"

    # ─── 向后兼容：单图预处理 ─────────────────────────────────

    def preprocess(self, image_path: str, profile: BookProfile
                   ) -> list[ProcessResult]:
        """对单张图片执行预处理和版面检测（向后兼容接口）。"""
        from .preprocessors import get_preprocessors

        img = imread(image_path)
        if img is None:
            print(f"  无法读取图片: {image_path}")
            return []

        preprocessors = get_preprocessors(profile)

        current_images = [img]
        for pp in preprocessors:
            next_images = []
            for cur_img in current_images:
                result = pp.process(cur_img, profile)
                if isinstance(result, list):
                    # 新格式: [(suffix, image), ...]
                    next_images.extend(sub_img for _, sub_img in result)
                else:
                    next_images.append(result)
            current_images = next_images

        results = []
        for i, processed_img in enumerate(current_images):
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
        """版面检测（Phase 3）。"""
        lsd_data = self.line_detector.detect(image)

        img_w = lsd_data["image_size"]["width"]
        img_h = lsd_data["image_size"]["height"]
        border_result = self.border_detector.detect(
            lsd_data, img_w, img_h, profile)

        column_result = self.column_detector.analyze(border_result, profile)

        return {
            "lsd_summary": lsd_data["summary"],
            "borders": {k: v for k, v in border_result.items() if k != "debug"},
            "columns": column_result,
        }

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
