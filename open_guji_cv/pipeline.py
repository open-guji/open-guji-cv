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
from .detectors.ocr_detector import OcrDetector
from .detectors.char_grid import CharGridDetector
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

    def analyze(self, book_folder: str, max_samples: int = 10,
                skip_pages: list[int] | None = None) -> BookProfile:
        """分析一本书的版式特征，生成 BookProfile。"""
        folder = Path(book_folder)
        image_paths = self._find_images(folder, max_count=max_samples,
                                        skip_pages=skip_pages)

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
                     profile: BookProfile | None = None,
                     name_filter: set[str] | None = None,
                     keep_intermediate: bool = True,
                     intermediate_dir: str | None = None) -> None:
        """完整流程：分析 + 步骤化预处理整本书。

        每个步骤的输出保存到独立文件夹（s1_crop_spine/, s2_crop_border/, ...）。
        跳过的步骤不产生文件夹，下游步骤自动从最近的上游输出读取。

        Args:
            name_filter: 只处理 stem 在此集合中的图片
            keep_intermediate: 是否保留中间步骤输出（默认 True 向后兼容）
            intermediate_dir: 中间步骤输出目录（需配合 keep_intermediate=True）
        """
        import shutil

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

        # 当有 name_filter 时，后续步骤需要匹配派生文件名（如 split 产生的 _left/_right）
        current_filter = name_filter

        # 只在第一个步骤（读原始目录）时应用 skip_pages，后续步骤读的是已过滤的输出
        skip_pages_for_first = profile.skip_pages if profile.skip_pages else None

        for step in STEPS:
            if step.is_needed(profile):
                step_dir = out_dir / step.folder_name
                n_images = self._run_step(step, current_dir, step_dir, profile,
                                          name_filter=current_filter,
                                          skip_pages=skip_pages_for_first)
                current_dir = step_dir
                skip_pages_for_first = None  # 后续步骤不再需要 skip_pages
                # split 步骤会生成 stem_left / stem_right，更新 filter
                if current_filter is not None and step.name == "split":
                    current_filter = {
                        f"{s}_{suffix}"
                        for s in current_filter
                        for suffix in ("left", "right")
                    }
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

        # ── 后处理：整理输出 ──
        final_folder = manifest_executed[-1]["folder"] if manifest_executed else ""
        final_output_value = final_folder  # manifest 中记录的 final_output 值

        if not keep_intermediate and manifest_executed:
            # 将最终步骤的图片复制到输出根目录，删除中间步骤文件夹
            final_step_dir = out_dir / final_folder
            if final_step_dir.exists():
                for img in sorted(final_step_dir.iterdir()):
                    if img.suffix.lower() in IMAGE_EXTENSIONS:
                        shutil.copy2(img, out_dir / img.name)
                # 删除所有步骤文件夹
                for step_info in manifest_executed:
                    step_dir = out_dir / step_info["folder"]
                    if step_dir.exists():
                        shutil.rmtree(step_dir)
            final_output_value = "."
            print(f"  已整理最终图片到输出根目录，中间步骤已删除")

        elif keep_intermediate and intermediate_dir and manifest_executed:
            # 将中间步骤移动到指定目录，最终图片复制到输出根目录
            inter_book = Path(intermediate_dir) / book_name
            inter_book.mkdir(parents=True, exist_ok=True)
            final_step_dir = out_dir / final_folder
            if final_step_dir.exists():
                # 复制最终图片到输出根目录
                for img in sorted(final_step_dir.iterdir()):
                    if img.suffix.lower() in IMAGE_EXTENSIONS:
                        shutil.copy2(img, out_dir / img.name)
                # 移动所有步骤文件夹到中间目录
                for step_info in manifest_executed:
                    step_dir = out_dir / step_info["folder"]
                    if step_dir.exists():
                        target = inter_book / step_info["folder"]
                        if target.exists():
                            shutil.rmtree(target)
                        shutil.move(str(step_dir), str(target))
            final_output_value = "."
            print(f"  最终图片已整理到输出根目录")
            print(f"  中间步骤已移动到: {inter_book}")

        # ── 保存 manifest.json ──
        manifest = {
            "book": book_name,
            "profile": "profile.json",
            "steps_executed": manifest_executed,
            "steps_skipped": manifest_skipped,
            "final_output": final_output_value,
        }
        if keep_intermediate and intermediate_dir:
            manifest["intermediate_dir"] = str(Path(intermediate_dir) / book_name)
        manifest_path = out_dir / "manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        print(f"\n完成！输出目录: {out_dir}")
        if final_output_value == ".":
            print(f"  最终结果: 输出根目录")
        else:
            print(f"  最终结果: {final_output_value}/")

    def _run_step(self, step: StepDef, input_dir: Path,
                  output_dir: Path, profile: BookProfile,
                  name_filter: set[str] | None = None,
                  skip_pages: list[int] | None = None) -> int:
        """执行单个预处理步骤：读取 input_dir 中的图片，处理后写入 output_dir。

        Returns:
            输出图片数量
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        preprocessor = step.create_preprocessor()
        image_paths = self._find_images(input_dir, name_filter=name_filter,
                                        skip_pages=skip_pages)
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

    # ─── Phase 3: 字符网格检测 ──────────────────────────────

    def detect_char_grid(self, book_name: str,
                         profile: BookProfile | None = None,
                         name_filter: set[str] | None = None) -> None:
        """Phase 3: 对已完成 Phase 2 的图片做字符网格检测。

        读取 phase2_layout/ 中的 JSON 和 s6_binarize/ 中的图片，
        输出到 phase3_char_grid/ 目录。
        """
        out_dir = self.output_dir / book_name
        layout_dir = out_dir / "phase2_layout"
        binarize_dir = self._find_final_preprocess_dir(out_dir) or (out_dir / "s6_binarize")
        char_grid_dir = out_dir / "phase3_char_grid"
        char_grid_dir.mkdir(parents=True, exist_ok=True)

        # 加载 profile
        if profile is None:
            profile_path = out_dir / "profile.json"
            if profile_path.exists():
                profile = BookProfile.load(profile_path)
            else:
                print(f"未找到 profile.json: {profile_path}")
                return

        # 初始化检测器（延迟加载 OCR 模型）
        ocr_detector = OcrDetector()
        char_grid_detector = CharGridDetector(ocr_detector)

        # 查找所有 layout JSON
        layout_files = sorted(layout_dir.glob("*_layout.json"))
        if name_filter is not None:
            layout_files = [f for f in layout_files
                            if f.stem.replace("_layout", "") in name_filter]
        if not layout_files:
            print(f"未找到 layout JSON: {layout_dir}")
            return

        total = len(layout_files)
        print(f"\nPhase 3 字符网格检测: 共 {total} 张图片（含 OCR，耗时较长）")

        report_every = max(1, total // 10)  # 每 10% 汇总一次
        done = 0

        for layout_path in layout_files:
            # 推断图片文件名: 1_layout.json → 1.png
            stem = layout_path.stem.replace("_layout", "")
            img_path = binarize_dir / f"{stem}.png"
            if not img_path.exists():
                img_path = binarize_dir / f"{stem}.jpg"
            if not img_path.exists():
                print(f"  跳过 {stem}: 找不到对应图片")
                continue

            # 加载图片和 layout
            image = imread(str(img_path))
            if image is None:
                print(f"  [{done}/{total}] {stem}: 读取失败")
                continue

            with open(layout_path, "r", encoding="utf-8") as f:
                layout = json.load(f)

            # 执行字符网格检测（OCR 在此触发，是主要耗时点）
            result = char_grid_detector.detect(image, layout, profile)

            # 保存 JSON
            json_path = char_grid_dir / f"{stem}_char_grid.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            # 生成可视化
            vis_img = self._draw_char_grid(image, result)
            vis_path = char_grid_dir / f"{stem}_annotated.png"
            imwrite(str(vis_path), vis_img)

            n_chars = sum(
                sum(1 for c in col["cells"] if c["type"] == "char")
                for col in result["columns"]
            )
            n_empty = sum(
                sum(1 for c in col["cells"] if c["type"] == "empty")
                for col in result["columns"]
            )
            done += 1

            # 每张都打一行（图片少时）；图片多时只在 10% 节点打
            if total <= 20 or done % report_every == 0 or done == total:
                pct = done * 100 // total
                print(f"  [{done}/{total}] {pct:3d}%  {stem} → {n_chars} 字 / {n_empty} 空")

        print(f"Phase 3 完成！共处理 {done} 张，输出: {char_grid_dir}")

    def _draw_char_grid(self, image: np.ndarray, result: dict) -> np.ndarray:
        """在图像上绘制字符网格可视化。

        四种颜色：
        - 绿色: char（有文字的字符格）
        - 橙色: jiazhu（夹注字符格）
        - 灰色: empty（空白字符格）
        - 蓝色: margin（边距格，不占字符数）

        char/empty/jiazhu 格子右上角标注索引号。
        """
        if len(image.shape) == 2:
            vis = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        else:
            vis = image.copy()

        self._draw_char_grid_cells(vis, result)
        return vis

    def _detect_layout(self, image: np.ndarray,
                       profile: BookProfile) -> dict:
        """版面检测（Phase 2）。"""
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

    # ─── Phase 2: 版面检测（批量） ────────────────────────────

    def detect_layout_book(self, book_name: str,
                           profile: BookProfile | None = None,
                           name_filter: set[str] | None = None) -> None:
        """Phase 2: 对已完成预处理的图片做版面检测。

        读取最终预处理输出目录中的图片，输出到 phase2_layout/ 目录。
        """
        out_dir = self.output_dir / book_name

        # 确定输入目录
        binarize_dir = self._find_final_preprocess_dir(out_dir)
        if not binarize_dir or not binarize_dir.exists():
            print(f"未找到预处理输出目录，请先运行 preprocess 命令")
            return

        layout_dir = out_dir / "phase2_layout"
        layout_dir.mkdir(parents=True, exist_ok=True)

        # 加载 profile
        if profile is None:
            profile = self._load_profile_from_output(out_dir)
            if profile is None:
                return

        image_paths = self._find_images(binarize_dir, name_filter=name_filter)
        if not image_paths:
            print(f"未找到图片: {binarize_dir}")
            return

        total = len(image_paths)
        print(f"\nPhase 2 版面检测: 共 {total} 张图片")

        report_every = max(1, total // 10)  # 每 10% 汇总一次
        done = 0

        for img_path in image_paths:
            stem = img_path.stem

            image = imread(str(img_path))
            if image is None:
                print(f"  [{done}/{total}] {stem}: 读取失败")
                continue

            layout = self._detect_layout(image, profile)

            # 保存 layout JSON
            json_path = layout_dir / f"{stem}_layout.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(layout, f, ensure_ascii=False, indent=2)

            # 生成可视化
            vis_img = self._draw_layout(image, layout)
            vis_path = layout_dir / f"{stem}_annotated.png"
            imwrite(str(vis_path), vis_img)

            n_cols = len(layout.get("columns", {}).get("columns", []))
            done += 1

            # 每张都打一行（图片少时）；图片多时只在 10% 节点打
            if total <= 20 or done % report_every == 0 or done == total:
                pct = done * 100 // total
                print(f"  [{done}/{total}] {pct:3d}%  {stem} → {n_cols} 列")

        print(f"Phase 2 完成！共处理 {done} 张，输出: {layout_dir}")

    def detect_char_grid_single(self, image_path: str,
                                layout: dict,
                                profile: BookProfile) -> dict:
        """Phase 3: 对单张图片做字符网格检测。"""
        image = imread(image_path)
        if image is None:
            print(f"  无法读取图片: {image_path}")
            return {}

        ocr_detector = OcrDetector()
        char_grid_detector = CharGridDetector(ocr_detector)
        return char_grid_detector.detect(image, layout, profile)

    # ─── 完整管线 ─────────────────────────────────────────────

    def run_all(self, book_folder: str,
                profile: BookProfile | None = None,
                output_format: str = "char_grid",
                clean: bool = False,
                name_filter: set[str] | None = None) -> None:
        """完整管线：Phase 1 → 1.5 → 2 → 3。"""
        folder = Path(book_folder)
        book_name = folder.name

        n_info = f"（{len(name_filter)} 张）" if name_filter else ""
        print(f"{'=' * 60}")
        print(f"完整管线: {book_name} {n_info}")
        print(f"{'=' * 60}")

        # Phase 1: 分析（始终用全部样本）
        profile = self._load_or_analyze(folder, profile)

        # Phase 1.5: 预处理
        self.process_book(str(folder), profile=profile, name_filter=name_filter)

        # name_filter 在 split 后可能变化，计算预处理后的实际 filter
        preprocess_filter = name_filter
        if name_filter and profile.is_uncut:
            preprocess_filter = {
                f"{s}_{suffix}"
                for s in name_filter
                for suffix in ("left", "right")
            }

        # Phase 2: 版面检测
        self.detect_layout_book(book_name, profile=profile,
                                name_filter=preprocess_filter)

        # Phase 3: 字符网格
        self.detect_char_grid(book_name, profile=profile,
                              name_filter=preprocess_filter)

        # 整理最终输出：每张图生成三个文件
        out_dir = self.output_dir / book_name
        self._collect_results(out_dir, profile=profile,
                              name_filter=preprocess_filter)

        # 可选: 合并输出
        if output_format == "combined":
            self._write_combined_result(out_dir, book_name, profile)

        # 可选: 清理中间文件
        if clean:
            self._clean_intermediate(out_dir)

        print(f"\n{'=' * 60}")
        print(f"全部完成！输出: {out_dir / 'results'}")

    def _collect_results(self, out_dir: Path,
                         profile: BookProfile | None = None,
                         name_filter: set[str] | None = None) -> None:
        """整理最终输出：每张图片生成三个文件到 results/ 目录。

        1. {stem}.json          — 标准格式检测结果（对齐 guji_layout）
        2. {stem}_preprocessed.png — 预处理后图片（供后续 OCR 使用）
        3. {stem}_annotated.png — 合并标注图（列线 + 字符格子 + 序号）
        """
        import shutil

        results_dir = out_dir / "results"
        results_dir.mkdir(parents=True, exist_ok=True)

        binarize_dir = self._find_final_preprocess_dir(out_dir)
        layout_dir = out_dir / "phase2_layout"
        char_grid_dir = out_dir / "phase3_char_grid"

        # 加载 profile（用于 border_style 等信息）
        if profile is None:
            profile = self._load_profile_from_output(out_dir)

        # 以 char_grid JSON 为主索引
        grid_files = sorted(char_grid_dir.glob("*_char_grid.json"))
        if name_filter is not None:
            grid_files = [f for f in grid_files
                          if f.stem.replace("_char_grid", "") in name_filter]

        if not grid_files:
            return

        print(f"\n整理输出: {len(grid_files)} 张图片 → results/")

        for gf in grid_files:
            stem = gf.stem.replace("_char_grid", "")

            # 加载 char_grid 和 layout
            with open(gf, "r", encoding="utf-8") as f:
                char_grid = json.load(f)

            layout_path = layout_dir / f"{stem}_layout.json"
            layout = None
            if layout_path.exists():
                with open(layout_path, "r", encoding="utf-8") as f:
                    layout = json.load(f)

            # 1. JSON: 转换为标准格式
            result_json = self._format_result_json(
                stem, char_grid, layout, profile)
            json_path = results_dir / f"{stem}.json"
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result_json, f, ensure_ascii=False, indent=2)

            # 2. 预处理图片
            for ext in (".png", ".jpg", ".jpeg"):
                src_img = binarize_dir / f"{stem}{ext}"
                if src_img.exists():
                    shutil.copy2(src_img, results_dir / f"{stem}_preprocessed{ext}")
                    break

            # 3. 合并标注图（layout + char_grid 画在预处理图上）
            if binarize_dir and layout:
                img_path = None
                for ext in (".png", ".jpg", ".jpeg"):
                    candidate = binarize_dir / f"{stem}{ext}"
                    if candidate.exists():
                        img_path = candidate
                        break

                if img_path:
                    image = imread(str(img_path))
                    if image is not None:
                        vis = self._draw_combined(image, layout, char_grid)
                        imwrite(str(results_dir / f"{stem}_annotated.png"), vis)

            print(f"  {stem}: json + preprocessed + annotated")

        print(f"输出目录: {results_dir}")

    @staticmethod
    def _format_result_json(stem: str, char_grid: dict,
                            layout: dict | None,
                            profile: BookProfile | None) -> dict:
        """将内部 char_grid + layout 数据转换为标准输出格式。

        对齐 guji_layout 的 OCR 输入规范：
        - col_index 0-based
        - position 嵌套结构
        - characters 替代 cells
        - 包含 border 信息
        """
        img_size = char_grid["image_size"]

        # --- border ---
        border = None
        if layout:
            borders = layout.get("borders", {})
            inner_frame = borders.get("inner_frame", {})
            outer_frame = borders.get("outer_frame", {})

            def _extract_rect(frame: dict, key: str = "intercept") -> dict:
                """从 frame 中提取 top/bottom/left/right 值。"""
                rect = {}
                for side in ("top", "bottom", "left", "right"):
                    side_data = frame.get(side)
                    if side_data and key in side_data:
                        rect[side] = round(side_data[key], 2)
                    else:
                        rect[side] = 0.0
                return rect

            def _extract_outer_rect(frame: dict) -> dict:
                """从 outer_frame 中提取外框值（每边取 outer 层）。"""
                rect = {}
                for side in ("top", "bottom", "left", "right"):
                    side_data = frame.get(side, {})
                    outer = side_data.get("outer")
                    if outer and "intercept" in outer:
                        rect[side] = round(outer["intercept"], 2)
                    elif side_data.get("inner") and "intercept" in side_data["inner"]:
                        # 如果没有 outer 层，退回到 inner
                        rect[side] = round(side_data["inner"]["intercept"], 2)
                    else:
                        rect[side] = 0.0
                return rect

            border = {
                "style": profile.border_style if profile else "double",
                "outer": _extract_outer_rect(outer_frame),
                "inner": _extract_rect(inner_frame),
            }

        # --- columns ---
        columns = []
        for col in char_grid["columns"]:
            left_x = round(col["left_x"], 2)
            right_x = round(col["right_x"], 2)
            center_x = round((col["left_x"] + col["right_x"]) / 2, 2)

            characters = []
            for cell in col["cells"]:
                if cell["type"] == "margin":
                    continue

                cell_type = cell["type"]
                if cell_type == "jiazhu":
                    out_type = "jiazhu"
                elif cell_type == "char":
                    out_type = "normal"
                else:
                    out_type = "empty"

                ch = {
                    "char": cell.get("text") or "",
                    "row_index": cell["index"],
                    "position": {
                        "x": center_x,
                        "y_top": cell["y_top"],
                        "y_bottom": cell["y_bottom"],
                    },
                    "type": out_type,
                }
                if cell_type in ("char", "jiazhu") and cell.get("confidence") is not None:
                    ch["confidence"] = cell["confidence"]
                if cell.get("sub_col") is not None:
                    ch["sub_col"] = cell["sub_col"]

                characters.append(ch)

            col_data = {
                "col_index": col["index"] - 1,
                "position": {"left_x": left_x, "right_x": right_x},
                "characters": characters,
            }
            if col.get("has_jiazhu"):
                col_data["has_jiazhu"] = True
                col_data["jiazhu_ranges"] = col.get("jiazhu_ranges")
            columns.append(col_data)

        # --- 组装 ---
        # 推断图片文件名后缀（优先 jpg）
        img_file = f"{stem}.jpg"

        result = {
            "page_id": stem,
            "image": {
                "file": img_file,
                "width": img_size["width"],
                "height": img_size["height"],
            },
            "layout": {
                "lines_per_page": profile.lines_per_page if profile else len(columns),
                "chars_per_line": char_grid.get("chars_per_line"),
                "char_height": char_grid.get("char_height_estimated"),
                "writing_direction": "rtl_vertical",
            },
        }

        if border:
            result["border"] = border

        result["columns"] = columns

        return result

    def _draw_combined(self, image: np.ndarray, layout: dict,
                       char_grid: dict) -> np.ndarray:
        """在预处理图上绘制合并标注：列边框（Phase 2）+ 字符格子（Phase 3）。"""
        # 先画 layout（红色边框 + 绿色列线）
        vis = self._draw_layout(image, layout)
        # 再画 char_grid（格子 + 序号），直接在 vis 上叠加
        vis = self._draw_char_grid_on(vis, char_grid)
        return vis

    def _draw_char_grid_on(self, vis: np.ndarray, result: dict) -> np.ndarray:
        """在已有彩色图像上绘制字符网格（不做灰度转换）。"""
        self._draw_char_grid_cells(vis, result)
        return vis

    @staticmethod
    def _draw_char_grid_cells(vis: np.ndarray, result: dict) -> None:
        """在彩色图像上绘制字符网格格子、标号和夹注标注。

        四种颜色：
        - 绿色 (0,200,0): char
        - 橙色 (0,165,255): jiazhu
        - 灰色 (180,180,180): empty
        - 青蓝 (200,150,0): margin
        """
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.35
        font_thickness = 1

        # 第一遍：画格子分隔线
        for col in result["columns"]:
            left_x = int(col["left_x"])
            right_x = int(col["right_x"])

            cells = col["cells"]
            if cells:
                col_y_top = int(cells[0]["y_top"])
                col_y_bot = int(cells[-1]["y_bottom"])
                cv2.line(vis, (left_x, col_y_top), (left_x, col_y_bot),
                         (0, 200, 0), 1)
                cv2.line(vis, (right_x, col_y_top), (right_x, col_y_bot),
                         (0, 200, 0), 1)

            for cell in cells:
                y_top = int(cell["y_top"])
                y_bottom = int(cell["y_bottom"])
                cell_type = cell.get("type", "char")

                if cell_type == "margin":
                    color = (200, 150, 0)
                elif cell_type == "empty":
                    color = (180, 180, 180)
                elif cell_type == "jiazhu":
                    color = (0, 165, 255)  # 橙色
                else:
                    color = (0, 200, 0)

                cv2.line(vis, (left_x, y_top), (right_x, y_top), color, 2)
                cv2.line(vis, (left_x, y_bottom), (right_x, y_bottom),
                         color, 1)

        # 第二遍：画标号
        for col in result["columns"]:
            right_x = int(col["right_x"])

            for cell in col["cells"]:
                y_bottom = int(cell["y_bottom"])
                cell_type = cell.get("type", "char")

                if cell_type in ("char", "empty", "jiazhu") and "index" in cell:
                    sub_col = cell.get("sub_col")
                    if sub_col is not None:
                        label = f"{cell['index'] + 1}.{sub_col}"
                    else:
                        label = str(cell["index"] + 1)

                    if cell_type == "jiazhu":
                        label_color = (0, 165, 255)
                    elif cell_type == "char":
                        label_color = (0, 200, 0)
                    else:
                        label_color = (180, 180, 180)

                    (tw, th), _ = cv2.getTextSize(
                        label, font, font_scale, font_thickness)
                    tx = right_x - tw - 1
                    ty = y_bottom - 2
                    bg_top = y_bottom - th - 4
                    cv2.rectangle(vis, (tx - 1, bg_top), (right_x, y_bottom),
                                  (255, 255, 255), -1)
                    cv2.putText(vis, label, (tx, ty), font, font_scale,
                                label_color, font_thickness, cv2.LINE_AA)

        # 第三遍：标注夹注区域（橙色边框 + 分割线 + "JZ" 标签）
        for col in result["columns"]:
            if col.get("has_jiazhu") and col.get("jiazhu_ranges"):
                lx = int(col["left_x"])
                rx = int(col["right_x"])
                for jz in col["jiazhu_ranges"]:
                    jz_top = int(jz["y_top"])
                    jz_bot = int(jz["y_bottom"])
                    cv2.rectangle(vis, (lx - 1, jz_top),
                                  (rx + 1, jz_bot),
                                  (0, 165, 255), 2)
                    cv2.putText(vis, "JZ", (lx + 2, jz_top + 14),
                                font, 0.45, (0, 165, 255), 1, cv2.LINE_AA)

                    # 画分割线（虚线效果：短线段）
                    if "split_x" in jz:
                        sx = lx + int(jz["split_x"])
                        for y in range(jz_top, jz_bot, 6):
                            y_end = min(y + 3, jz_bot)
                            cv2.line(vis, (sx, y), (sx, y_end),
                                     (0, 165, 255), 1)

    def _write_combined_result(self, out_dir: Path,
                               book_name: str,
                               profile: BookProfile) -> None:
        """将所有页面的结果合并为一个 JSON 文件。

        从 results/ 目录读取已格式化的 JSON（标准格式）。
        """
        results_dir = out_dir / "results"
        result_files = sorted(
            f for f in results_dir.glob("*.json")
            if not f.stem.endswith("_char_grid")
        )

        pages = []
        for rf in result_files:
            with open(rf, "r", encoding="utf-8") as f:
                pages.append(json.load(f))

        result = {
            "book": book_name,
            "profile": profile.to_dict(),
            "pages": pages,
        }

        result_path = out_dir / "book_result.json"
        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"  合并结果: {result_path}")

    def _clean_intermediate(self, out_dir: Path) -> None:
        """清理中间步骤文件夹，只保留最终结果。"""
        import shutil
        keep = {"profile.json", "manifest.json",
                "phase3_char_grid", "book_result.json"}
        for item in out_dir.iterdir():
            if item.name not in keep:
                if item.is_dir():
                    shutil.rmtree(item)
                    print(f"  清理: {item.name}/")

    # ─── 可视化 ───────────────────────────────────────────────

    def _draw_layout(self, image: np.ndarray, layout: dict) -> np.ndarray:
        """在图像上绘制版面检测可视化。

        - 红色: 内边框（top/bottom/left/right）
        - 绿色: 列分隔线 + 列编号
        """
        if len(image.shape) == 2:
            vis = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        else:
            vis = image.copy()

        h, w = vis.shape[:2]
        borders = layout.get("borders", {})
        inner_frame = borders.get("inner_frame", {})

        # 绘制内边框（红色）
        for side_name in ("top", "bottom", "left", "right"):
            side = inner_frame.get(side_name)
            if not side:
                continue
            slope = side.get("slope", 0)
            intercept = side.get("intercept", 0)
            if side_name in ("top", "bottom"):
                # 水平线: y = slope * x + intercept
                y1 = int(slope * 0 + intercept)
                y2 = int(slope * w + intercept)
                cv2.line(vis, (0, y1), (w, y2), (0, 0, 255), 2)
            else:
                # 垂直线: x = slope * y + intercept
                x1 = int(slope * 0 + intercept)
                x2 = int(slope * h + intercept)
                cv2.line(vis, (x1, 0), (x2, h), (0, 0, 200), 2)

        # 绘制列（绿色）
        columns = layout.get("columns", {}).get("columns", [])
        col_top = int(inner_frame.get("top", {}).get("intercept", 0))
        col_bottom = int(inner_frame.get("bottom", {}).get("intercept", h))

        for col in columns:
            left_x = int(col["left_x"])
            right_x = int(col["right_x"])
            cv2.line(vis, (left_x, col_top), (left_x, col_bottom),
                     (0, 200, 0), 1)
            cv2.line(vis, (right_x, col_top), (right_x, col_bottom),
                     (0, 200, 0), 1)

            # 列编号
            cx = (left_x + right_x) // 2
            cv2.putText(vis, str(col["index"]),
                        (cx - 5, col_top - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 200, 0), 1)

        return vis

    # ─── 工具方法 ─────────────────────────────────────────────

    def _find_final_preprocess_dir(self, out_dir: Path) -> Path | None:
        """从 manifest.json 确定最终预处理输出目录。"""
        manifest_path = out_dir / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            final = manifest.get("final_output", "")
            if final == ".":
                return out_dir  # 图片直接在输出根目录
            if final:
                return out_dir / final

        # 回退：检查输出根目录是否直接包含图片
        root_images = [f for f in out_dir.iterdir()
                       if f.suffix.lower() in IMAGE_EXTENSIONS]
        if root_images:
            return out_dir

        # 回退：按步骤号降序查找存在的目录
        for step_num in [6, 5, 4, 3, 2, 1]:
            candidates = list(out_dir.glob(f"s{step_num}_*"))
            if candidates:
                return candidates[0]
        return None

    def _load_profile_from_output(self, out_dir: Path) -> BookProfile | None:
        """从输出目录加载 profile.json。"""
        profile_path = out_dir / "profile.json"
        if profile_path.exists():
            return BookProfile.load(profile_path)
        print(f"未找到 profile.json: {profile_path}")
        return None

    @staticmethod
    def _find_images(folder: Path, max_count: int | None = None,
                     name_filter: set[str] | None = None,
                     skip_pages: list[int] | None = None) -> list[Path]:
        """在文件夹中查找图片文件。

        Args:
            folder: 图片目录
            max_count: 最多返回的图片数
            name_filter: 只保留 stem 在此集合中的图片（如 {"v01_003", "v01_004"}）
            skip_pages: 跳过页码列表，按文件名末尾数字匹配（如 [1, 2]）
        """
        import re
        skip_suffixes = {"_lsd", "_borders", "_annotated", "_preprocessed"}
        images = sorted(
            f for f in folder.iterdir()
            if f.suffix.lower() in IMAGE_EXTENSIONS
            and not any(f.stem.endswith(s) for s in skip_suffixes)
        )
        if skip_pages:
            skip_set = set(skip_pages)
            filtered = []
            for f in images:
                nums = re.findall(r'\d+', f.stem)
                if nums and int(nums[-1]) in skip_set:
                    continue
                filtered.append(f)
            images = filtered
        if name_filter is not None:
            images = [f for f in images if f.stem in name_filter]
        if max_count is not None:
            images = images[:max_count]
        return images
