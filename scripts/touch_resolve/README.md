# touch_resolve — 粘连切点「先认后切」实验（非生产代码）

**性质**：实验脚本，`open_guji_cv/` 包不 import 这里的任何文件，管线与控制台也不依赖它。
只读生产产物（workspace 的 products / cache / glyph.db），不写产物、不改金标。
产出一律落 `out/`（已 gitignore，可由脚本重算）；合成数据与模型在 `D:\data\touch_synth\`（不进 git）。

**结论正本**：overview 仓 `项目进展/图片初步数字化/进度/Step3-逐字切分/05-高级切分算法.md`「实验记录」节。
**协作备忘**：`NOTES.md`（2026-09-13 两个会话并行写同一目录时的分工与命名约定）。

| 文件 | 作用 |
|---|---|
| `common.py` | 金标 → 当下产物对位、双格窗口、各切法 → 半字图、模板源（本书刻例 / 字体）、CNN 薄包装 |
| `probe.py` | 坐标口径核对图 |
| `exp1_hypothesis.py` `exp1_misses.py` `exp1_label_suspects.py` | 实验一：识别 top-k 覆盖；漏网看图；金标字对可疑清单 |
| `gold_geometry.py` | 真实粘连点交错深度分布（校准合成器） |
| `templates.py` | 模板配准引擎（v2：(sx,sy) 缩放档 + 重叠罚）与像素归属、分模板贴合度 |
| `exp2_verify_partition.py` `exp2_summary.py` | 实验二：成对校验 |
| `exp3_partition_eval.py` `restrat.py` | 实验三：模板归属，err_px / blob 尺子；按 frame_ok 重分层 |
| `exp4_select.py` | 实验四（A）：身份条件选择器 |
| `exp4_glyph_purity.py` `exp5_identity_robustness.py` `restrat45.py` | 实验四（B）：字形库纯度；实验五：身份敏感度 |
| `synth_pairs.py` | 合成粘连对生成器（干净格叠放，逐像素真值 + 字标签） |
| `train_partition_unet.py` `train_partition_unet_v2.py` | 类别无关归属 U-Net（v1 负结果 / v2 现役） |
| `report.py` | 汇总成 `out/report.md` |

跑法：一律从仓根用 `.venv` 启动，例如 `.venv/Scripts/python scripts/touch_resolve/exp1_hypothesis.py`
（`Recognizer()` 依赖 CNN 检查点的相对路径）。实验依赖 `out/exp1/per_case.json`（识别 top-k）与
`out/frame_ok.json`（金标坐标系一致的 601 条），先跑 `exp1_hypothesis.py` 与 `restrat.py`。
