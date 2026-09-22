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
    # 生僻字候选召回（C 刀 L1）：库/OCR/上下文都给不出答案的字位，字体模板能
    # 不能把答案捞进 top-10。主指标是**召回**不是准确率——目标是人在候选里点。
    # 位置参数是数据集分片目录（--dataset），不是分片父目录。
    _e("rare_char", "rare-char", arg_kind="none", out_flag="", pythonpath=True,
       title="生僻字候选", needs=("products",),
       extra=("--dataset", "../open-guji-dataset/rare-char"),
       note="要建 4600 字 × 4 字体的索引，首跑约 1-2 分钟"),
    # 零样本识别（拆字识别研究，见 doc/ocr_engine_and_zero_shot.md）：
    # 字形库 unseen 档（≤2 样本的 1,022 字种，模板从未见过其刻例）。
    _e("zero_shot", "glyph-bench", arg_kind="none", out_flag="", pythonpath=True,
       title="零样本·整字 vs 拆字", needs=("products", "heavy"),
       extra=("--n", "300"),
       note="HOG 检索 vs 手工拆字重排；重活，unseen 300 条约 5 分钟"),
    _e("zero_shot_fusion", "glyph-bench", arg_kind="none", out_flag="", pythonpath=True,
       title="零样本·HOG/CNN/融合", needs=("products", "heavy"),
       note="需要 cache/glyph_cnn/best.pt；全 unseen 1,327 条约 3 分钟"),
    # 类外评测：金标字落在 CNN classes **之外**的真刻例（2026-09-17 建）。
    # 上面那几个零样本集 100% 落在 classes 内，量不出类外泛化——而扩字表的收益
    # 全由 embedding 兑现，分类头对类外字 top-10 恒为 0。集与基线见
    # scripts/build_oov_bench.py、cache/oov_bench/baseline.json。
    _e("oov", "glyph-bench", arg_kind="none", out_flag="--json", pythonpath=True,
       title="类外泛化·emb", needs=("products", "heavy"),
       note="集在 cache/oov_bench（本地派生物，由 build_oov_bench.py 建，"
            "不在数据集仓）；314 条 / 138 字种"),
    # 固定退化协议（2026-09-21 补登记）：同一批真刻例加一组**写死**的扰动
    # （blur/erode/dilate/断墨/贴边/遮挡/钤印），分因素报各路稳定性。跟 `oov`
    # 同源同形：数据在 cache/ 的本地派生物、没有位置参数、报告走 `--json`。
    # `--set` 不进 extra——缺省 oov 就是这条要量的那一档，unseen 那档手跑。
    _e("degradation", "glyph-bench", arg_kind="none", out_flag="--json", pythonpath=True,
       title="固定退化·稳定性", needs=("products", "heavy"),
       note="集在 cache/oov_bench（--set oov，缺省）或 glyph-bench unseen 档；"
            "模板均值优先复用 cache/struct_probe/emb_*.npz，没有就现渲染"),
    # 粘连格线理想切点（用户在控制台「切线」页拖出来的），现役 Step2 列图坐标。
    _e("touching_cuts", "char-segmentation/touching-cuts", arg_kind="none", out_flag="--json", pythonpath=True,
       title="粘连切点误差", needs=("products",),
       note="只算 moved/ok；overlap 另计；col_h 对不上的报漂移"),
    # Step3 格线逐像素误差：旧坐标系金标用版框线性映射 + 互相关重锚定到现役列图
    # （见 doc/step3_touching_and_jiazhu.md §3.5）。分「现役 R2s 粘连 / 非粘连」两层报。
    _e("row_boundaries", "char-segmentation/row-boundaries", arg_kind="none", out_flag="--json", pythonpath=True,
       title="格线逐像素误差", needs=("products",),
       note="金标只有 2 页且是旧坐标系，重锚定后当趋势看；新坐标系金标见文档 §二"),
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
    # 外部大模型上下文裁决（Step6，2026-09-10 立项，未接生产）：位置参数不是
    # 数据集分片，是本仓自产的评测集文件 output/llm_context_evalset/evalset.json
    # （build_llm_context_evalset.py 从 context-correction 金标里挖出「现有
    # gated_ngram 判错」的槽位建出来的），所以 arg_kind=none、把路径放进 extra。
    # 注册表只挂安全默认 --provider mock（不发网络请求、不用花钱）；真跑 GLM/
    # 千问要设 GLM_API_KEY / DASHSCOPE_API_KEY，另外手动带 --provider 跑，
    # 见 open-guji/overview Step6-上下文裁决/方案-外部LLM.md。
    _e("llm_context", "llm_context_evalset", arg_kind="none", pythonpath=True,
       title="外部 LLM 上下文裁决（mock 默认）",
       extra=("output/llm_context_evalset/evalset.json", "--provider", "mock",
             "--prompt-version", "candidates"),
       note="注册表默认跑 mock（验证链路，不代表真实准确率）；"
           "真调用需要 API key，见方案文档"),
    _e("font_fallback", "char-ocr", arg_kind="book_out", pythonpath=True,
       title="字体回退", needs=("products", "engine")),
    _e("guard_ceiling", "glyph-match/triplets", arg_kind="none", pythonpath=True,
       title="护栏天花板", needs=("heavy", "dump"),
       note="没有位置参数；--dump 必填，输入是 eval_match_pairs --dump 的 npz"),
    # 下版框：金标路径写死在脚本里（frozen_absolute.jsonl），没有位置参数。
    _e("bottom_offset_gold", "border-detection/bottom-offset", arg_kind="none",
       out_flag="--json-out",
       note="金标路径写死在脚本里（frozen_absolute.jsonl），不接受位置参数；"
           "--hard-only 只跑困难页子集"),
    _e("bottom_offset_oneside", "border-detection/bottom-offset", arg_kind="none",
       out_flag="--json-out",
       note="下版框单侧口径（宁下勿上）；金标路径同 bottom_offset_gold，写死在脚本里"),
    _e("unsupported_layout", "page-type", arg_kind="none", out_flag="",
       needs=("products",),
       note="金标路径写死在脚本里（page-type/expected.json）；--book/--products 可选，"
           "不走注册表的位置参数机制；只读现成 cells 产物，不重跑管线"),
    # 结构感知识别（2026-09-21 合并进来的那条线；补进注册表，`test_registry_covers_every_eval_script`
    # 钉的就是「scripts/eval_*.py 一个都不许漏登记」）
    _e("struct_rerank", "rare-char", arg_kind="none", out_flag="--json", pythonpath=True,
       title="结构重排（M0）", needs=("model", "engine"),
       note="oov_bench 上量部件袋头一致性重排的开/关；主指标 top-10 与 top-1 **不掉**才算过，"
           "掉一个都不接。扫 权重 × top_m 两个旋钮，按 src 分层读"),
    _e("struct_heads", "rare-char", arg_kind="none", out_flag="--json", pythonpath=True,
       title="结构头 + 槽位部件头（Step A）", needs=("model", "engine"),
       note="要 --ckpt 指到带结构头的 checkpoint；量结构头准确率（独体字单列）、槽位头 top-3、"
           "三种重排的 top-1/top-10。通过线见脚本头"),
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
