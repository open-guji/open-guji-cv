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
| `yolo_tool_probe/` | 10-02 | yolo_tool 的 YOLO 模型在四庫 vol03 上的探针（F1） |

**还没搬进来的**（被生产代码的 docstring 引用为出处，随 Step 模块整理一起搬，免得产物指纹无谓变动）：
`experiments/touch_resolve`（切点 U-Net 训练）、`experiments/metric_loss`（字形 CNN r5 训练）、
`scripts/experiments/` 下的 `shadow_admit`、`replace_gate`、`pagetype_model`、`context_guard`、`rare_downstream`、
`align_anchor_recall`、`qtw_libfail`、`seal_nolib`、`verdict_drift_check.py`。
