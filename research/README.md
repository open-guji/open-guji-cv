# research/：实验与一次性研究（不是生产代码）

> 2026-10-06 cv 大清理（overview#413）建立：把散在 `scripts/experiments/` 与根目录 `experiments/` 的实验收到一处。
> **这里的脚本不保证还能跑**：它们是当时某个问题的复现台、评测框架或数据核账。结论在各目录 README 或 overview 对应卡里。
> 生产代码不得 import 这里的东西；要复用，先把那段逻辑搬进 `open_guji_cv/` 并补测试。

| 目录 | 时间 | 内容 |
|---|---|---|
| `borrow_cnn_first/` | 09-27 | 借库书审卡装配结果落成规范 JSON，改前改后比 sha256（C 道 borrow_cnn_first） |
| `l2_seal_seg/` | 09-30 | 印章遮挡格的 Step4 字框是否被撑大：框宽/列宽、高/格高 |
| `muse_variant_audit/` | 10-02 | muse 批次 V1：异体关系表单来源边复核（overview#372；批次结果解冻后推这里） |
| `muse_variant_pilot/` | 09-27 | muse 判异体关系的试点与自动真值校准集 |
| `qtw_booklib/` | 09-27 | 全唐文书级库：四批人裁合并、代表图、导入与测量 |
| `qtw_solo_replace/` | 09-28 | 几套 seed_admit 书级参数产物对比（overview#155） |
| `relax_margin/` | 09-28 | 库 top1 置信度 × 领先幅度分档，量人裁与整理本一致率 |
| `ri_yue/` | 10-02 | 日/曰 能否按字形宽高比分开（R2） |
| `s266_tail_frame/` | 09-29 | vol03 列尾下版框线复现台与 A/B 审查页（overview#266） |
| `s279_vol02_recompute/` | 09-29 | vol02 整册重算后旧人裁重绑定核账（overview#279） |
| `step6_dict_ai/` | 09-27 | Step6 词典 + AI 排除法评测框架（北行日錄），含各模型跑数 |
| `stroke_disc/` | 09-26 | 小笔画判别器：verify 的 cov/wmax 能否分开铁证冲突与一致 |
| `scripts_oneoff/` | 10-06 | 从 `scripts/` 挪来的 21 个一次性脚本：修数据（evict、relabel、backfill、rebind、repair）、迁移（migrate_*）、一次性评测与 A/B（eval_*、*_ab） |
| `yolo_tool_probe/` | 10-02 | yolo_tool 的 YOLO 模型在四庫 vol03 上的探针（F1） |

**生产模型的出处**（代码 docstring 引用这里）：

| 目录 | 内容 |
|---|---|
| `touch_resolve/` | 切点判官 U-Net 的训练与验证（`utils/cut_select.py` 用的模型） |
| `metric_loss/` | 字形 CNN `glyph_cnn_r5` 的训练（`clustering/cnn_candidates.py` 用的模型） |
| `shadow_admit/` | 影子放行模型（梯度提升树）训练、评估与审卡导出（`review/shadow.py`） |
| `pagetype_model/` | 页型判别模型（`gates/border_detect_gate.py`） |
| `replace_gate/` | Step5-d `replace` 段采信闸的数据与训练 |
| `context_guard/` | context 通道护栏的标定 |
| `rare_downstream/` | 生僻字候选下游消费的沙箱实测（`steps/align_ref.py`） |
| `align_anchor_recall/` | 整理本锚定召回诊断（`steps/align_ref.py`） |
| `qtw_libfail/` | 全唐文库缺字诊断（`review/borrow_first.py`） |
| `seal_nolib/` | 印章遮挡格不进库（`tests/test_seal_nolib.py` 引用） |
| `verdict_drift_check.py` | 人裁入库图块与现图块的漂移核查（`feedback/lookup.py`） |
