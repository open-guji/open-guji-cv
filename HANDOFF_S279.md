# HANDOFF S#279：四庫 vol02 云端整册重算与出包（2026-09-29，模型 claude-sonnet-5-5 试用）

分支 `claude/S-recompute-vol02-0929`（cv，基于 main `8b0a295`），**没合 main**。任务书 overview#279。

## 1. 底和版本

| 项 | 值 |
|---|---|
| 旧产物底 | ws 分支 `products-snap/vol02-20260927`（旧格式 tar.zst，cv `cd04496`，188 页 Step1–7）。**vol02 在 ws 没有 `snap/…` 包**，所以没有可 `--supersedes` 的旧包 |
| 工作区 | ws main `7b05902f`（浅克隆） |
| cv | main `8b0a295`（任务书指定的 commit） |
| 字形库 | 按 ws `glyph_store` 重建到 `$WS/output/glyph.db`，指纹 `4224b3b258992fca`（与 vol03 那轮同值） |
| 沙箱 | `GUJI_PRODUCTS_DIR`/`GUJI_CACHE_DIR` 都在 scratchpad，**ws 一个文件没改** |

## 2. 重算账（`artifacts/s279_vol02_recompute/recompute_report.json`）

全书 188 页整册重跑：`pipeline --to cell_shrink --jobs 4`，再 `recheck` 点名，再 `pipeline --from glyph_match`。
跑完 `guji status vol02 --pages all`：**13 步 × 188 页全部新鲜**，失败 0。

| 步 | 字节变了的页（对旧底） | 备注 |
|---|---|---|
| border_detect | 49 | 10.6 min |
| border_detect_gate | 2 | |
| column_warp | 53 | |
| column_gate | 7 | |
| row_segment | 33 页 / 49 列 / 359 格 | 5.1 min |
| row_segment_gate | 6 | |
| cell_shrink | 23 页 / 33 列 / 147 格 | 2.1 min |
| glyph_match | 全 188（参数变了，指纹全变） | 19.8 min；`recheck --dead` + 181 个字点名 8565/30496 格（28.1%） |
| rare_candidates | 全 188 | 53.2 min，其中建 rare 模板索引（base 29,689 + escalate 42,438 字）约 42 min |
| align_ref / context_decide / seed_admit | 全 188 | 0.4 / 1.0 / 7.8 min |

page_survey 旧底里没有这一步，"188 页变了"只是新增。点名的 181 字 = 旧底时点（ws `051b94ae`）到现在 `glyph_store` 的 admissions（按字计数不等）∪ glyphs 记录（忽略 updated_at）变了的字。

**注意（负结果/环境）**：最初沙箱里没装 torch，Step3 的 U-Net 切点裁判（`cut judge 加载失败…按旧规则选切法`）和 Step5-b 的 CNN 都会静默退化。发现后**装了 CPU 版 torch 2.14.0，整个沙箱清空从旧底重跑**，上表全是装 torch 之后的数。日志里 `cut judge` 警告 0 条。云端新会话起 venv 时请把 `.[torch]` 装上。

## 3. 包（cv 仓分支，等总管转到 ws）

| cv 分支 | 内容 |
|---|---|
| `snaptmp/96mid1ogzk/vol02/20260929T1023` | Step0–4：page_survey、border_detect(+gate)、column_warp、column_gate、row_segment(+gate)、cell_shrink；1512 文件，37.8 MB |
| `snaptmp/96mid1ogzk/vol02/20260929T1024` | Step5–7：glyph_match、rare_candidates、align_ref、context_decide、seed_admit；945 文件 |

manifest 摘要（两包共同）：`format guji-snap/1`、`page_scope full`、`mode replace-steps`、188 页、每步 `ok 188`、`cv.commit 8b0a295576703064ea89ef5ca10130c8df022fc9`、`glyph_db_fingerprint 4224b3b258992fca`、`allow_downgrade false`、`supersedes []`；Step5–7 包记了 seed_admit 覆盖 `ji_yi_si_review=true`。

**转 ws 时分支名改回 `snap/96mid1ogzk/vol02/<同一时戳>`，提交原样不动**（manifest 里 `branch` 字段就是 snap/… 名）。

做法：`guji snap pack … --ws-repo <scratchpad 里新建的空 git 库> --no-push` 在本地生成两个孤儿分支，再 fetch 成 `snaptmp/…` 推到 cv 仓。pack 前先 `--dry-run` 过，计划与实际一致。

### 导入注意
1. 先导 `20260929T1023` 再导 `20260929T1024`（后者上游是前者的 cell_shrink）。
2. `compatible_with` 为空（cv.commit 是 8b0a295）：服务器 cv 若已前进且 cv 兼容闸不认，请总管按 vol03 那轮惯例判断后决定是否补声明，我没有依据擅自写。
3. Step5–7 包的 rare_candidates / seed_admit 指纹依赖 ws `glyph_store` 内容；服务器 ws 若在 `7b05902f` 之后又被定时同步改过，这两步在服务器上会判过期，但服务器现有那份也是旧库算的，新鲜页数不该变少。真触发防降级闸别直接 `--force`，先问。
4. 包不带图，vol02 原图没换过。

## 4. 旧人裁补锚（`artifacts/s279_vol02_recompute/`）

vol02 与 vol03 不一样，结论要说清楚：

- vol02 的 4441 条逐格 confirm 事件，**事件里 `target.anchor` 全是 null**（只有 2 条带 product_key），没有 seed_admit 指纹，所以任务书的准入闸「seed_admit 指纹与快照一致」**对它们成立不了**。
- ws 里现有 `feedback/anchors/vol02.jsonl`（4441 行：3502 条非空，来自 `backfill:ink`/`backfill:ctx`，用字块图像素反查原图；939 条 anchor=null）。非空锚的坐标在**原图**上，不依赖 Step3，快照导入后照样有效。
- 所以 **`anchors_vol02_all.jsonl` 是空文件（0 行）**：按闸没有可补的行，没有降低标准硬补。合并时**不需要动 ws 的 vol02.jsonl**。
- 用现行 `bindings.compute_page` + 现有补锚对新产物算了一遍（`rebind_table_vol02.jsonl`，脚本 `scripts/experiments/s279_vol02_recompute/rebind_vol02.py`）：

| 状态 | 条数 |
|---|---|
| valid | 3415 |
| rebound | 82（全在 Step3 没变的页上——这是页内位移的正常重绑，不算异常，供总管留意） |
| review | 5（全是 vol02:34:3:19 '古' 同一格的 5 条重复裁决，IoU 0.743） |
| unanchored（补锚档里 anchor=null） | 939 |

- 939 条无锚里 **215 条落在 Step3 变了的 33 页上**（seg_defect 172 / confirm 25 / not_a_char 12 / skip 6），这批快照导入后只能靠现行规则认，认不上回待审。清单在 `needs_review.md` B 节。
- 另有 699 条 cutline（列级，525 条无 product_key），本轮没有对照列号：vol02 没有原图重切，Step1 分列变了的页只有 border_detect 的 49 页，逐条核列号超出这次范围，**未做**。

## 5. 需要用户复核的旧裁决
`artifacts/s279_vol02_recompute/needs_review.md`：A 节 5 条 review（同一格），B 节 215 条无锚且页上 Step3 变了。

## 6. 拿不准的地方
1. **无锚的 939 条**要不要另想办法补（比如按 ts 定版本，或人重裁）——我没补，保守。
2. compatible_with 留空（见 3.2）。
3. rebound 82 条在 Step3 未变的页上重绑，原因没深究（可能是补锚 IoU 阈值边缘或 cell_shrink 微变）。
4. cutline 未核（见 4）。
5. 旧底是 `cd04496` 的旧格式包，"字节变了"对比的基线不是 ws 上任何 snap/ 包。
6. 云端 CPU torch 与服务器 torch 版本可能不同，U-Net 判官输出理论上可能有浮点级差异，没验证。

## 7. 文件
`artifacts/s279_vol02_recompute/{recompute_report.json,anchors_vol02_all.jsonl,rebind_table_vol02.jsonl,needs_review.md}`；`scripts/experiments/s279_vol02_recompute/{recompute_report.py,rebind_vol02.py}`。
