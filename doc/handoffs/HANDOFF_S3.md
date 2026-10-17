# HANDOFF S3：夹注段尾，Step3 与 Step4 格位口径统一 ＋ 反向通道「正文当小注」

卡：overview#436（根子 #434、#415）。cv 分支 `claude/S3-jiazhu-tail-1006`（基于 `76407d8`），
dataset 分支同名（基于 dataset main `59b5edf`）。没合 main，没开 PR。

## 一、查清的事实（和卡上的前提有出入）

1. **#434 vol04 p218c2:13/21 不是夹注段尾，整页没有夹注。**
   - p218 是叶 216 拆出来的半叶，左边带版心。Step1 把相邻两整列正文并成了第 2 列：列图宽 367px，正常约 185px。
   - 中间那条界行被 `gap_center` 当成夹注缝，3–12、16–20 格都记成了 `jiazhu_a/b`。
   - 13、21 格：Step3 有「列中界行」护栏（`_mid_rule_line`，vol03 p49c3 那条），这一列不做段端收编，按整格出。旧 Step4 的 v1 段端收编没有这道护栏，就拆成了 a/b，两步格位因此不一致。
   - 文本层原先「…上下|…諸傳」读对了，是碰巧：a=右列、b=左列的读序恰好等于两列正文的读序。14、15 两格其实也各装两个字，两步都没拆。
   - **根子在 Step1/列闸**：两倍宽的列被当成夹注列，豁免了列宽检查。不在本卡范围，建议另开卡。
2. **#415 vol02 p100c4:17「此」**：Step3 段尾多延一格，把它劈成 a/b。Step3 的疑似闸其实已经给它打了 `suspect_jiazhu_body`，但不能据此自动不拆：
   - 三册全部 `suspect` 格看图核过，共 11 格：
     - 9 格是真段尾单字：vol04「撫/大/裕/蘇/撫」，vol03「裕/裕/撫」，vol02 p97c9:21「府」；
     - 1 格是「此」；
     - 1 格是 vol04 p130c5:7「北」，见第 3 条。
   - 自动不拆会丢真小注。所以按卡做了人裁反向通道。
3. 顺带发现同型的另一种错：**vol04 p130c5:6–8「題北魏」**。整列都是正文（舊本題北魏關朗撰…），三格被连成一段假夹注，两步都拆了。它两步格位一致，不是段尾问题，所以没进 jiazhu-tail。可以用新通道人裁修，或者另立「假夹注段」测试集。

## 二、改了什么（cv）

| 处 | 改动 |
|---|---|
| `steps/cell_shrink.py` 1.6→**1.7** | 新参数 `jiazhu_from_step3`（缺省开）：extractor 拿到 `jiazhu_authority=step3` 时，**拆哪几格、每格发哪几半一律照 Step3**（`jiazhu_subs`）。v1 多拆的格摘掉 `jiazhu` 旗，按整格出。缝位两边都认的格仍用 extractor 自己量的，所以其余产物逐字节不变 |
| `clustering/extractor.py` | 上面那段的实现（不给 authority 时行为与旧版逐位相同，v1 链不受影响） |
| `utils/row_boundaries.py` + `steps/row_segment.py` 1.13→**1.14** | `segment_column(forced_main=…)`：人指认的格在连段、强制拆、段端收编之后从段里摘掉，按整格出，也不参与單行小注判定；与 `forced_jiazhu` 同在一格时它赢 |
| `feedback/lookup.py` | `resolved_forced_main`（`reason=main_as_jiazhu`，收 `…a/…b` 子格 key，同 key 取最新一条）；与 `resolved_forced_jiazhu` 共用 `_resolved_forced` |
| `feedback/routes.py` / `returns.py` | 该页 `row_segment` 失效；打回原因记 `jiazhu_split` |
| `feedback/collate_state.py` / `console/routers/step8.py` | Step8 复核卡新增勾「正文当小注（打回重切）」，勾上自动下重跑单 |
| `review/verdict_view.py` | 读回成 `main` 档 |
| 前端（定字台、细审、Step8） | 按钮「正文当小注」，快捷键 **M**；`dist` 已重建（`npm run build`，tsc 通过） |
| `doc/console_manual.md` §4.1b | 加一条 |
| `tests/test_jiazhu_step3_authority.py` | 11 条，全部自造数据 |

**产物过期**：`row_segment`、`cell_shrink` 两步版本都升了，各书这两步及下游判过期（用户已同意）。
重算后的实际变化只有 vol04 p218c2 两格，见下文。

## 三、量（沙箱：workspace main 原图 + 现场重跑 Step1→4；base = `76407d8` worktree，new = 本分支）

### jiazhu-tail（`scripts/eval_jiazhu_tail.py`，47 条 = 原 44 + 新 3）

| | 正确 | 吞正文 | 丢字 | 拆法迁移 | 消失 | 回归门 |
|---|---|---|---|---|---|---|
| base | 44/47 | 3（100:4:17、218:2:13、218:2:21） | 0 | 0 | 0 | 失败 |
| new（无人裁） | 46/47 | 1（100:4:17，等人裁） | 0 | 0 | 0 | 失败 |
| new + 沙箱人裁 `main_as_jiazhu` @ `vol02:100:4:17a` | **47/47** | 0 | 0 | 0 | 0 | **通过** |

原 44 条前后都是 44/44，**没有回归**。
p100:17 在正式工作区要等人在控制台按 M（或 Step8 勾「正文当小注」）并重跑该页才会过。沙箱里重切后得到的整格字块就是完整的「此」。

### touching-cuts（`scripts/eval_touching_cuts.py`）

| 册 | base | new |
|---|---|---|
| vol02 | n=204，≤3px 91.2%，≤5px 94.6%，mean 0.8 | 相同 |
| vol03 | n=5，≤3px 80.0%，mean 6.0 | 相同 |

Step3 产物前后逐页逐字节相同（vol02 188/188、vol03 110/110、vol04 221/221 页），切点不可能变。
vol01（789 条）和 bxgb（240 条）的原图不在沙箱，没跑；这一改动对 Step3 在没有人裁时是零改动，同样不会变。

### column-layout

这是 Step1/2 的列几何，本卡没动 Step1/2。三册 `border_detect`、`column_warp`、`column_gate` 产物前后**逐字节相同**（519/519 页）。仓里没有 v2 口径的 column-layout 评测脚本（只有退役 v1 的 `quick_bench.sh`），所以只给了产物等同的证明。

### 三册两步格位不一致的格数（`slot → sub 集合` 不同、且至少一边拆了）

| 册 | 格位数 | base 不一致 | new 不一致 | Step4 实例变化 |
|---|---|---|---|---|
| vol02（188 页） | 35168 | 0 | 0 | 30553/30553 不变 |
| vol03（110 页，工作区原图全部） | 20123 | 0 | 0 | 17758/17758 不变 |
| vol04（221 页） | 41150 | **2**（218:2:13、218:2:21，非正文页） | **0** | 只有这 2 格由 a/b 变整格，其余 35255 不变 |

同型「Step3 与 Step4 格位不一致」在三册里只有这 2 格，都已进集。

### 全量测试

`.venv/bin/python -m pytest tests/ -q -s -p no:cacheprovider`：

| 分支 | 通过 | 跳过 | error |
|---|---|---|---|
| 本分支 | **2702** | 6 | 1 |
| base `76407d8` | 2691 | 6 | 1 |

这 1 个 error 两边一样，是**既有问题**：`tests/variants/test_variants_query.py::test_load_reads_directed` teardown 时，守卫查到 `models/glyph_cnn_r5/emb_*.npz` 被某个测试写进了生产缓存目录。单独跑 `tests/variants/` 32 条全过，查不出是哪个测试写的。差的 11 条就是新增的测试。

## 四、留给后面的

1. 正式工作区：在 vol02 p100c4 的 `17a`（或 `17b`）上标「正文当小注」，然后 `guji pipeline keben_body_v2 vol02 --from row_segment --pages 100 -w <书目录>`。#415 那条「17a 判非字」的临时处理随之失效。
2. vol04 p218 的 Step1 列切错（两列并一列）要另开卡；p130c5「題北魏」假夹注段可以先用新通道人裁。
3. 测试守卫那个既有的 `emb_*.npz` 泄漏，值得单独查。
