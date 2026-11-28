# benchmark 登记表

每个小步一行，标准见 [验收标准.md](验收标准.md) S11、S12、B4。各线负责填自己的行、改了就更新；「住处」不是 cv `eval/` 或 manager 评测器的，算待搬（S11）。
2026-11-28 CV0 按审查时的现状起表，空格＝没有。

| 小步 | Step id | 负责 | bench（命令或脚本） | 住处 | 主指标 | 护栏（必须为 0／不增） | 测试集（dataset 分片） | 覆盖的书 | 基线报告 |
|---|---|---|---|---|---|---|---|---|---|
| 1a 页面预检 | `page_survey`、`invert_detect` | CV1 | | | | | page-type | 殿本 | |
| 1b 版框界行 | `border_detect`（`line_detect`、`block_detect`） | CV1 | `python -m open_guji_cv.eval.layout_bench` | cv `eval/` | 框线、界行误差；列数；页型 | 正文页判成非正文 | layout、border-detection | 殿本（W1 79 页）；史記、全唐文、脉经只有回归例 | |
| 1c 印章 | `seal_detect` | CV1 | | | | 印章漏认压字 | | | |
| 2a 拉直 | `column_warp` | CV2 | `cut_bench.py` | ai-team（待搬） | 列全对 | 好列改坏 | page-geometry、column-layout | 四书试点各 5 页 | ai-team `A22/cut-bench/基线-2026-11-23.md` |
| 2b 字带左右边 | `column_band` | CV2 | | | | | char-segmentation/text-band、side-rule | 殿本 | |
| 2c 列端字 | `column_end` | CV2 | cut-frame 脚本 | ai-team（待搬） | 列端格干净率 | 切笔 | 列端金标 v0、frame-end-crop | 史記、全唐文各 40 列；殿本 451 格 | |
| 2 列几何、出口闸 | `column_geometry`、`cut_gate` | CV2 | | | 检出率、误报率 | | | | |
| 2d 字间切分 | `row_segment` | CV2 | `cut_bench.py` | ai-team（待搬） | 列字数全对、列全对、格 F1 | 好列改坏 | cut-lattice、char-segmentation/book-columns | 殿本、史記、全唐文、脉经 | 同 2a |
| 2e 字框压缩 | `cell_shrink` | CV2 | manager 老评测器（多数跑不起） | manager | | 字身墨被切 | char-segmentation 各分片 | 殿本为主 | |
| 3a 字形库匹配 | `glyph_match` | CV3 | `guji eval run @read-3a`；`@read-qtw-lib`（设 `GUJI_GLYPH_DB`）；`guji eval guard` | manager | same 精度、库外拒识、首位命中、对家误认 | 库外字误认 same；残损误放；nearform 对家误认；`guards/read.yaml` 17 条 | glyph-match/advset-*、damaged-*、nearform-qtw；guards/read.yaml | 殿本、史記、全唐文 | ai-team `A23/识字benchmark-2026-11-23/`（未钉库／模型 sha，缺口） |
| 3b 形近字组 | `glyph_near` | CV3 | `guji eval run @near`（`scripts/eval_near.py`，11-28 建设中） | manager（建设中） | 组内判对率、触发量、覆盖率、方法一致率、校准误差 | 组内误判 | char-groups（3b 分片建设中；正式金标 gold/<组> 标注暂停） | 殿本、史記、全唐文 | 建设中 |
| （旧）生僻字候选 | `rare_candidates` | CV3 | `guji eval run @read-3b`（套名待改，与新 3b 撞名） | manager | emb 前 10 | | rare-char、char-clustering/samples/007-qtw-firstseen | 殿本、史記、全唐文 | |
| 3c 按图候选 | `glyph_candidate` | CV3 | `guji eval run cands`（`scripts/eval_cands.py`） | manager（已登记） | 甲层难格召回@1／10／30／50 | | char-candidates（甲层难格、乙层待审卡） | 殿本、史記、全唐文 | dataset `char-candidates/baseline.json` |
| 3d 其他特征 | `cell_traits` | CV3 | | | | | | | |
| 3e 看图大模型 | `glyph_vis` | CV3 | | | 触发量、答对率 | | | | |
| 识字收尾 | `glyph_analyzer` | CV3 | | | 未定格前 1／前 10、ECE | | | | |
| 4a 参照对位 | `align_ref` | CV4 | decide-bench `score.py` 子步指标 | ai-team（待搬） | 错位格数 | 好列被换坏 | decide-bench | 殿本、史記 03 部分、脉经 01 | ai-team `A24/decide-bench/子步指标-基线报告-2026-11-28.md` |
| 4b 上下文 | `context_decide`、`context_rank` | CV4 | decide-bench；候选线脚本 | ai-team（待搬） | 前 1／前 3、伤害率 | | context-correction、confusable-context、char-candidates | 殿本为主 | 同上 |
| 4c 格况 | `cell_state` | CV4 | decide-bench 子步指标 | ai-team（待搬） | 各状态精确率、召回率 | 有字判无字（漏字） | 待建 decide-bench/cell-state | | 同上 |
| 4d 字组 | `group_decision` | CV4 | decide-bench 子步指标 | ai-team（待搬） | 判定率 | 判定格错字 | char-groups、字组定向金标 | 全唐文三组起步 | 同上 |
| 定字收尾 | `char_decide` | CV4 | decide-bench `run.py`／`score.py`；rough-bench | ai-team（待搬） | 放行率、拦住·首选对 | 放错字 | decide-bench small／large、动态层 | 殿本、史記 03、脉经 01 | 同上 |
| 定字 gate | `decide_gate` | CV4 | `gate_bench.py` | ai-team（待搬） | 检出率、误报率 | fail 数不增 | 事故回归例 | 殿本 | ai-team `A24/decide-bench/gate-bench-2026-11-28.md` |
