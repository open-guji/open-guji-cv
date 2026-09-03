"""评测器注册表：把 27 个 `eval_*.py` 的调用契约记成数据。

**不改脚本**，只把差异写下来：
- 位置参数传的路径不同：分片根（多数）、`samples/` 子目录（column-layout）、
  册产物目录（eval_font_fallback）；
- 报告选项三种写法：`--out`（多数）、`--json-out`（pagetype / geometry）、无（column-warp）；
- 有的要 `PYTHONPATH=.`，有的要 GPU / OCR 引擎。

`needs` 标出跑得起来的前提，控制台据此把跑不了的置灰而不是让人点了才失败：
    products  要 output/<book>/ 下的产物
    heavy     分钟级以上（聚类 / OCR / 大矩阵）
    engine    要 OCR 引擎或 GPU
    corpus    要语料文件
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

OutFlag = Literal["--out", "--json-out", "--report", ""]
# 位置参数传什么：
#   shard         分片根目录（多数）
#   shard_samples 分片下的 samples/ 子目录（column-layout）
#   shard_parent  **分片的父目录**——脚本自己拼子目录名。char-segmentation 下
#                 seam / side-rule / text-band / page-crop / crop-margin / char-drop
#                 等一批都是这样，传完整路径会拼成 char-segmentation/seam/seam
#   book_out      册产物目录 output/<book>
#   none          没有位置参数
ArgKind = Literal["shard", "shard_samples", "shard_parent", "book_out", "file", "none"]


@dataclass(frozen=True)
class EvalSpec:
    id: str                      # 脚本名去掉 eval_ 前缀
    script: str                  # scripts/ 下的文件名
    shard: str                   # 默认评的金标分片（相对数据集根）
    arg_kind: ArgKind = "shard"  # 位置参数传什么
    out_flag: OutFlag = "--out"
    extra: tuple[str, ...] = ()  # 固定要带的选项
    needs: tuple[str, ...] = ()
    pythonpath: bool = False     # 要不要 PYTHONPATH=.
    title: str = ""
    note: str = ""

    def argv(self, dataset_root: Path, report_path: Path | None = None) -> list[str]:
        """拼命令行。

        ⚠️ **`--out` 有两种互相冲突的语义**（实测踩过）：多数脚本是报告路径，
        但 char-segmentation 下那批（char_drop / left_cut / seam / text_band…）
        的 `--out` 是**产物根目录**，默认 `output`。给它们传报告路径会让脚本去
        `report.json/vol01/phase3_char_grid/` 找产物，静默扫到 0 页，然后印
        「回归门：通过」——**假通过比失败危险得多**。所以那批的 out_flag 置空。

        ⚠️ 绝不透传 `--update`：那会**覆写金标 expected.json**。
        """
        import sys
        cmd = [sys.executable, f"scripts/{self.script}"]
        target = self.target(dataset_root)
        if target is not None:
            cmd.append(str(target))
        cmd += list(self.extra)
        assert "--update" not in cmd, f"{self.id}: --update 会覆写金标，不许透传"
        if report_path and self.out_flag:
            cmd += [self.out_flag, str(report_path)]
        return cmd

    def target(self, dataset_root: Path) -> Path | None:
        if self.arg_kind == "none":
            return None
        p = dataset_root / self.shard
        if self.arg_kind == "shard_samples":
            return p / "samples"
        if self.arg_kind == "shard_parent":
            return p.parent
        return p


def _e(id, shard, **kw) -> EvalSpec:
    return EvalSpec(id=id, script=f"eval_{id}.py", shard=shard, **kw)


# ── 注册表 ───────────────────────────────────────────────────────────
# 先收「金标与产物都在本地、跑得动」的那批；重活与需引擎的标 needs，
# 控制台照样列出来但不默认跑。
EVALS: dict[str, EvalSpec] = {s.id: s for s in [
    # 切分链（v2 主攻）
    _e("pagetype", "page-type", out_flag="--json-out", pythonpath=True,
       title="页型闸门", note="主指标 lost_rate 零容忍：该切却跳过 = 静默丢数据"),
    _e("geometry", "page-geometry", out_flag="--json-out", pythonpath=True,
       title="版面几何", needs=("products",)),
    _e("layout", "column-layout", arg_kind="shard_samples", pythonpath=True,
       title="行列识别", note="位置参数是 samples/ 子目录，不是分片根"),
    _e("column_warp", "char-segmentation/column-warp", out_flag="", pythonpath=True,
       title="Step2 单列矫正", needs=("products",),
       note="没有报告选项，只印 stdout；列图从 input.column_image 重建"),
    _e("instance_quality", "char-segmentation/instances", pythonpath=True,
       title="图块自检", needs=("products",),
       note="分确定层 / 疑似层报，别合成一个数"),
    _e("frame_strip", "char-segmentation/frame-strip", arg_kind="shard_parent", pythonpath=True,
       title="列端去框", needs=("products",)),
    _e("side_rule", "char-segmentation/side-rule", arg_kind="shard_parent", out_flag="", pythonpath=True,
       title="侧边去线", needs=("products",),
       note="⚠ 它的 --out 是**产物根目录**不是报告路径，所以不给报告选项"),
    _e("jiazhu_tail", "char-segmentation/jiazhu-tail", arg_kind="shard_parent", out_flag="", pythonpath=True,
       title="夹注段端", needs=("products",)),
    _e("left_cut", "char-segmentation/left-cut", arg_kind="shard_parent", out_flag="", pythonpath=True,
       title="左缘救援", needs=("products",)),
    _e("right_cut", "char-segmentation/right-cut", arg_kind="shard_parent", out_flag="", pythonpath=True,
       title="右缘救援", needs=("products",)),
    _e("seam", "char-segmentation/seam", arg_kind="shard_parent", out_flag="", pythonpath=True,
       title="格线落点", needs=("products",)),
    _e("text_band", "char-segmentation/text-band", arg_kind="shard_parent", out_flag="", pythonpath=True,
       title="版面窗口", needs=("products",)),
    _e("page_crop", "char-segmentation/page-crop", arg_kind="shard_parent", out_flag="", pythonpath=True,
       title="上游裁切", needs=("products",)),
    _e("char_drop", "char-segmentation/char-drop", arg_kind="shard_parent", out_flag="", pythonpath=True,
       title="字墨丢失", needs=("products",)),
    _e("truncation", "char-segmentation/truncation", arg_kind="shard_parent", out_flag="", pythonpath=True,
       title="字身截断", needs=("products",)),
    _e("crop_margin", "char-segmentation/crop-margin", arg_kind="shard_parent", out_flag="", pythonpath=True,
       title="裁边", needs=("products", "intermediate"),
       note="⚠ 必须给 --intermediate-dir（s1~s6 的中间产物目录），否则只回显既存金标、不评测"),
    _e("recrop", "char-segmentation/instances", pythonpath=True,
       title="重切回归", needs=("products",), note="只看 seed=review_recrop 那批"),
    # 归一化 / 聚类 / 匹配 / 识别（多为重活）
    _e("normalize", "char-normalization", pythonpath=True,
       title="归一化回归门", note="纯函数 golden，最快"),
    _e("clustering", "char-clustering", pythonpath=True,
       title="保守聚类", needs=("products", "heavy")),
    _e("match_triplets", "glyph-match/triplets", out_flag="--report", pythonpath=True,
       title="匹配排序", needs=("heavy",)),
    _e("match_pairs", "glyph-match/pairs", pythonpath=True,
       title="匹配阈值", needs=("heavy",)),
    _e("db_match", "glyph-match/pairs", pythonpath=True,
       title="库匹配", needs=("products", "heavy")),
    _e("char_ocr", "char-ocr", pythonpath=True,
       title="单字识别", needs=("products", "engine", "heavy"),
       note="⚠ 同上，--out 默认写进数据集仓；且需 rapidocr"),
    _e("context_correction", "context-correction", pythonpath=True,
       title="上下文裁决", needs=("corpus", "heavy"),
       note="⚠ 不传 --out 会把 report.json 写进数据集仓，必须显式给报告路径"),
    _e("confusable_lm", "confusable-context", pythonpath=True,
       title="形近字上下文", needs=("corpus", "heavy"),
       note="位置参数是 cases.json 文件"),
    _e("font_fallback", "char-ocr", arg_kind="book_out", pythonpath=True,
       title="字体回退", needs=("products", "engine")),
    _e("guard_ceiling", "glyph-match/triplets", arg_kind="none", pythonpath=True,
       title="护栏天花板", needs=("heavy", "dump"),
       note="没有位置参数；--dump 必填，输入是 eval_match_pairs --dump 的 npz"),
]}


def find_eval(key: str) -> EvalSpec | None:
    """按 id 或分片名找评测器。"""
    if key in EVALS:
        return EVALS[key]
    return next((s for s in EVALS.values() if s.shard == key), None)


def evals_for_shard(shard: str) -> list[EvalSpec]:
    return [s for s in EVALS.values() if s.shard == shard]


def runnable(spec: EvalSpec, allow: tuple[str, ...] = ("products",)) -> tuple[bool, str]:
    """这个评测器现在能不能跑。allow 里的前提视为已满足。"""
    blocked = [n for n in spec.needs if n not in allow]
    if not blocked:
        return True, ""
    names = {"products": "需要产物", "heavy": "重活（分钟级以上）",
             "engine": "需要 OCR 引擎 / GPU", "corpus": "需要语料",
             "intermediate": "需要 s1~s6 中间产物目录", "dump": "需要上游评测器的 npz"}
    return False, "；".join(names.get(b, b) for b in blocked)
