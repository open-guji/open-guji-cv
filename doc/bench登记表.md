# benchmark 登记表

每个小步一行，标准见 [验收标准.md](验收标准.md) S11、S12、B4。各线负责填自己的行、改了就更新；「住处」不是 cv `eval/` 或 manager 评测器的，算待搬（S11）。
2026-11-28 CV0 按审查时的现状起表，空格＝没有。2 切字各行 11-28 由 CV2 更新（脚本搬进 cv `eval/`，用法见 [2-切字/README.md](2-切字/README.md)「benchmark」）。

| 小步 | Step id | 负责 | bench（命令或脚本） | 住处 | 主指标 | 护栏（必须为 0／不增） | 测试集（dataset 分片） | 覆盖的书 | 基线报告 |
|---|---|---|---|---|---|---|---|---|---|
| 1a 页面预检 | `page_survey`、`invert_detect` | CV1 | | | | | page-type | 殿本 | |
| 1b 版框界行 | `border_detect`（`line_detect`、`block_detect`） | CV1 | `python -m open_guji_cv.eval.layout_bench` | cv `eval/` | 框线、界行误差；列数；页型 | 正文页判成非正文 | layout、border-detection | 殿本（W1 79 页）；史記、全唐文、脉经只有回归例 | |
| 1c 印章 | `seal_detect` | CV1 | | | | 印章漏认压字 | | | |
| 2a 拉直 | `column_warp`（现代 `column_crop`、自由版式 `column_trace`） | CV2 | `python -m open_guji_cv.eval.cut_bench run／score`（经 2d 量） | cv `eval/` | 列全对 | 好列改坏（`--against` 对→错翻转） | char-segmentation/cut-bench | 史記、全唐文、殿本、脉经（各 35–40 页）；缺朱楓林集、汉书 | [2-切字/基线-2026-11-28.md](2-切字/基线-2026-11-28.md) |
| 2b 字带左右边 | `column_band` | CV2 | `python -m open_guji_cv.eval.cut_ink band` | cv `eval/` | 字带余量（中位、p10） | 抹墨格 | char-segmentation/band-ink（v0.1，金标由人核格界＋连通域推出）；殿本旧集 text-band、side-rule | 史記、全唐文各 30 列（band-ink）；殿本（旧集） | [2-切字/基线-2026-11-28.md](2-切字/基线-2026-11-28.md) |
| 2c 列端字 | `column_end` | CV2 | `python -m open_guji_cv.eval.cut_frame --items cut-frame/items.jsonl` | cv `eval/` | IoU@0.9 | 切笔；新带渣 | char-segmentation/cut-frame、frame-end-crop | 史記、全唐文各 60 列；殿本 451 格（frame-end-crop） | [2-切字/基线-2026-11-28.md](2-切字/基线-2026-11-28.md) |
| 2 列几何、出口闸 | `column_geometry`、`cut_gate` | CV2 | `python -m open_guji_cv.eval.cut_bench gate` | cv `eval/` | 检出率、误报率（拦／拦或旗两档，按判据分报） | | char-segmentation/cut-bench（真值＝2d 列全对） | 史記、全唐文已量；殿本、脉经可跑未量 | [2-切字/基线-2026-11-28.md](2-切字/基线-2026-11-28.md) |
| 2d 字间切分 | `row_segment` | CV2 | `python -m open_guji_cv.eval.cut_bench score`；cut-lattice `score.py` | cv `eval/`；dataset cut-lattice | 列字数全对、列全对、格 F1 | 好列改坏 | char-segmentation/cut-bench（random／hard 分报）、cut-lattice、char-segmentation/book-columns | 殿本、史記、全唐文、脉经；缺朱楓林集、汉书 | [2-切字/基线-2026-11-28.md](2-切字/基线-2026-11-28.md)（史記、全唐文）；殿本、脉经见 ai-team `A22/cut-bench/基线-2026-11-23.md` |
| 2e 字框压缩 | `cell_shrink` | CV2 | `python -m open_guji_cv.eval.cut_frame`（shrink-ink 加 `--junk-tol 6`） | cv `eval/` | IoU@0.9 | 字身墨被切（切笔） | char-segmentation/shrink-ink（列中，v0.1）、cut-frame（列端） | 史記、全唐文各约 150 格（列中）＋各 60 列（列端）；殿本老分片 instances 等跑不起 | [2-切字/基线-2026-11-28.md](2-切字/基线-2026-11-28.md) |
| 3a 字形库匹配 | `glyph_match` | CV3 | `guji eval run @read-3a`；`@read-qtw-lib`（设 `GUJI_GLYPH_DB`）；`guji eval guard` | manager | same 精度、库外拒识、首位命中、对家误认 | 库外字误认 same；残损误放；nearform 对家误认；`guards/read.yaml` 17 条 | glyph-match/advset-*、damaged-*、nearform-qtw；guards/read.yaml | 殿本、史記、全唐文 | ai-team `A23/识字benchmark-2026-11-23/`（未钉库／模型 sha，缺口） |
| 3b 形近字组 | `glyph_near` | CV3 | `guji eval run @near`（`scripts/eval_near.py`；冻结 `scripts/build_near_bench.py`） | manager 评测器 `near` | 组内判对率、弃权率、触发量、覆盖率、方法一致率、ECE、每格耗时 | 组内误判（非弃权错判） | glyph-near/bench3b（三书 test＋fit 各一册，钉产物包标签与模型 sha256）；正式金标 char-groups/gold/<组> 标注暂停 | 殿本、史記、全唐文 | dataset `glyph-near/bench3b/baseline.json`；ai-team `CV/CV3/3b-bench-2026-11-28/` |
| （旧）生僻字候选 | `rare_candidates` | CV3 | `guji eval run @read-3b`（套名待改，与新 3b 撞名） | manager | emb 前 10 | | rare-char、char-clustering/samples/007-qtw-firstseen | 殿本、史記、全唐文 | |
| 3c 按图候选 | `glyph_candidate` | CV3 | `guji bench run read-3c-cands --book <书>`（实现 `eval/cands_bench.py`；旧 `guji eval run cands`、`scripts/eval_cands.py` 仍可用） | manager（已登记） | 甲层难格召回@1／10／30／50 | | char-candidates（甲层难格、乙层待审卡） | 殿本、史記、全唐文 | dataset `char-candidates/baseline.json` |
| 3d 其他特征 | `cell_traits` | CV3 | | | | | | | |
| 3e 看图大模型 | `glyph_vis` | CV3 | | | 触发量、答对率 | | | | |
| 识字收尾 | `glyph_analyzer` | CV3 | | | 未定格前 1／前 10、ECE | | | | |
| 4a 参照对位 | `align_ref` | CV4 | `python -m open_guji_cv.eval.decide_bench.score` 子步指标（`run` 一键） | cv `eval/decide_bench/` | 错位格数 | 好列被换坏 | decide-bench/small、large（金标按原图框锚定） | 殿本 vol01／vol02／vol04、史記 01–03、全唐文 004／005／008、脉经 01 | ai-team `A24/decide-bench/子步指标-基线报告-2026-11-28.md`（B4 待转进本仓 doc/） |
| 4b 上下文 | `context_decide`、`context_rank` | CV4 | `python -m open_guji_cv.eval.decide_bench.score` 子步指标；`guji bench run decide-4b-ctx --book <书>`（context_rank 重排与补字，CV3） | cv `eval/decide_bench/` | 前 1／前 3、伤害率 | 伤害率不增 | decide-bench/small、large；context-correction、confusable-context、char-candidates | 殿本为主 | ai-team `A24/decide-bench/子步指标-基线报告-2026-11-28.md`（B4 待转进本仓 doc/） |
| 4c 格况 | `cell_state` | CV4 | `python -m open_guji_cv.eval.decide_bench.score` 子步指标（4c 漏字，现从 evidence 反推；4c 独立产物接上后读 cell-state 金标） | cv `eval/decide_bench/` | 各状态精确率、召回率 | 有字判无字（漏字）为 0 | decide-bench/cell-state（char＋non_char，按书子目录，v0.1.0 起步） | 史記 03、全唐文 004、殿本 vol01（non_char 只有殿本）；缺 seal／occluded／seg_bad 金标，标注暂停（11-28） | ai-team `A24/decide-bench/子步指标-基线报告-2026-11-28.md`（B4 待转进本仓 doc/） |
| 4d 字组 | `group_decision` | CV4 | `python -m open_guji_cv.eval.decide_bench.score` 子步指标 | cv `eval/decide_bench/` | 判定率 | 判定格错字为 0 | decide-bench/small、large；char-groups（字组定向金标，扩殿本、史記暂缓：Sheldon 11-28 标注暂停） | 全唐文三组起步 | ai-team `A24/decide-bench/子步指标-基线报告-2026-11-28.md`（B4 待转进本仓 doc/） |
| 定字收尾 | `char_decide` | CV4 | `python -m open_guji_cv.eval.decide_bench.run`（冻结层）、`python -m open_guji_cv.eval.decide_bench.dyn`（动态层）、`python -m open_guji_cv.eval.decide_bench.score`（打分＋`--against` 翻转清单）；rough-bench | cv `eval/decide_bench/` | 放行率、拦住·首选对率 | 放错字为 0；翻转清单变坏格为 0 | decide-bench small（9,422）／large（11,355）；动态层沿用二者 | 殿本 vol01／vol02／vol04、史記 01–03、全唐文 004／005／008、脉经 01；按书报分 | ai-team `A24/decide-bench/子步指标-基线报告-2026-11-28.md`（B4 待转进本仓 doc/） |
| 定字 gate | `decide_gate` | CV4 | `python -m open_guji_cv.eval.decide_bench.gate_bench` | cv `eval/decide_bench/` | 检出率、误报率 | fail 数不增 | 事故回归例；decide-bench 产物盖回 | 殿本 | ai-team `A24/decide-bench/gate-bench-2026-11-28.md` |

## 统一接口（CV0，2026-11-28 起）

各 bench 收进一个登记表 `open_guji_cv/eval/bench.py`（`BenchSpec`／`BenchCtx`／`BenchResult`），实现放 `eval/benches/<名>.py`；命令走 guji-manager `guji bench list|fetch|run|ab|guard|show`，资源由 manager 按书备齐。结果目录 `bench-results/<bench>/<书>/<时间>/`（`result.json` schema 1、`items.jsonl`、`report.md`），status 只有 ok／regressed／skipped／no_gold，跑崩记 failed。已接：`cut-2d`（2d 行、CV2）、`decide`（定字收尾行、CV4）、`read-3c-cands`（3c 行）、`decide-4b-ctx`（4b 行 context_rank，CV3）；其余各行由负责线 P1 接，接完把 bench id 写进本表「bench」列。分派与接入验收见 ai-team `domain/CV/规范/bench统一接口-2026-11-28.md`。

## 第四步脚本说明（CV4，2026-11-28）

`open_guji_cv/eval/decide_bench/` 的四个脚本都是命令行入口，`python -m open_guji_cv.eval.decide_bench.<名> --help` 看参数；金标在 open-guji-dataset `decide-bench/`。

- **主指标**：`wrong_admit`（放错字，**必须为 0**）、`variant_admit`、`admit_rate`、`review_top1_ok`；`score` 另按书出 4a／4b／4c／4d 子步指标和每格「错因位置」。
- **按书报分**：所有输出按书分行（册号跨书重名时用 `工作区id/册`）。
- **翻转清单**：`score --against <上次结果>` 出好转／变坏／其它；`run --params` 出 B 对 A 的翻转。变坏格数 0 才自合。
- **干净环境**：`run` 要备好工作区（册配置、书仓 `code/`、模型、钉版字形库、原图），见 dataset `decide-bench/README.md`；`score`、`gate_bench` 只读产物目录。`tests/test_decide_bench_eval.py` 守脚本能起、cell-state 构建可重复。
- **cell-state 分片**：`build_cell_state` 从 small 与 instances 已有人裁生成，不新增标注。

