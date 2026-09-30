# frame_strip 金标迁移（M1·A 道）
原 `expected.json` **65 条**（另 13 条 p32/p33 已在 `retired_headraise.json`）。v1 图块路径 `output/<册>/phase4_chars/patches/…` 已退役，旧脚本输出「0 个样本（65 个格位已消失）」= 空跑。
判据：人看过的图块原图在 `instances/patches/<册>_<页>_<列>_<idx>.png`（且 instances 里同格有 review_r3 人裁 clean/contaminated，与 frame 标注一致）；
拿它对 v2 `cell_shrink` 图块做二值墨 NCC 模板匹配，NCC≥0.90 + 位移≤4px + 尺寸差≤12px 才算「图还在」（`patch_identity.py`）。
- 迁入（可计分）**8**：带框 3 / 干净 5；
- 失效 **57**：`no_saved_patch` 47（没存人看的图，无从证明）+ `image_changed` 10（有图但 v2 切出来不是那张，NCC 0.34~0.87 或位移/尺寸超限）。
逐条见 `migration_report.json`（scored 带 NCC，skipped 带原因）。金标文件本身未改；评测现场过闸。
