# HANDOFF Q3 — rare_candidates 云端无 GPU 的跑法与 rare_ref 未生效提示（overview#429）

分支：cv `claude/Q3-rare-perf-1006`（基于 main `9ce4328`）。**没有合 main，没有开 PR。**
两个提交，可以分开取舍：

| 提交 | 内容 | 产物过期 |
|---|---|---|
| A `272e9af` | 报警、`build-rare-index --jobs`、`cache warm`、runbook S5-b | **不过期**。没有动任何 Step 模块或 code_deps；18 个 Step 的 code_hash 前后逐个比对，全部一致 |
| B `4c1ca6b` | `cnn_candidates` 的真刻例原型缓存从一档改成两档 | 只有 **rare_candidates** 的 code_hash 变，别的步不变 |

关于 B 的影响：现在工作区里没有一册书开着读 5-b 的开关（rare_ref / rare_agree / shadow_promote），这一步对它们自动跳过，不会触发重算。真正受影响的只有将来开开关的册，而那些册本来就要跑 5-b。总管不要 B 的话，revert 这一个提交即可。

## 一、慢在哪（第 1 问）

在云端 4 核、15G、无 GPU 的会话里导入快照 `snap/96mid1ogzk/vol04/20261006T0716`，用 py-spy 抓 p3：

- **95.5% 的时间在第一页现建 CNN embedding 模板表**（`cnn_candidates._emb_index` → `build_emb_matrix`）。其中 CNN 前向 85.5%，字体渲染 9.1%。做法是字表乘 8 套字体，逐字渲染、前向，单进程单核，每秒约 25 字。
- vol04 有两档表：基集 cjk-a 29,689 字，升级档 ext-b 42,438 字。单核约 **46 分钟**，全算在第一页头上。#429 里「p3 18 分钟没完」就是这个。
- **不是 CNN 候选本身慢，也不是字体 HOG**。CNN 可用时 HOG 根本不跑。代码也**不假设有 GPU**。它假设的是**表已经预建**（`snap_autoimport.md`「大模板索引一律云端预建」），而云端会话 `models/glyph_cnn_r5/` 下只有 `best.pt`。按 key 去重分发用的 `idx/*` 分支，在两个仓里都没有。
- `--jobs 4` 没用上：这一步没有标 `parallel_safe`，按设计串行。

表在盘上以后，每页的成本是：
1. **逐格现切字块**，每页约 13 秒。快照只带 products，不带 `cache/`。
2. **真刻例原型缓存只有一档**。上一页走了升级档，就把基集那份挤掉了，下一页重建基集那份要约 30 秒，大约每 5 页碰上一次。
3. 真正算候选只要约 1.4 秒。

## 二、云端无 GPU 怎么跑（第 2 问）

整套写进了 runbook S5-b（`doc/runbook/整理一册书.md`），vol04 实测如下：

| 步骤 | 命令 | vol04 云端耗时 |
|---|---|---|
| 备表，任选一种 | 导现成的包：`guji snap import snap/96mid1ogzk/rare-index-vol08/20260928T1136 …`（两个 key 正好是 vol04 的）；或者自己建：`guji cache build-rare-index --book vol04 --jobs 4 -w $WS` | 自建 **10 分 9 秒**（单核约 46 分钟），合计峰值约 2.4 GB |
| 预渲字块 | `guji cache warm --book vol04 --pages all --jobs 4 -w $WS` | 121 页 288 秒，约每页 2.4 秒（串行约每页 13 秒） |
| 5-b | `guji pipeline keben_body_v2 vol04 --pages all --from rare_candidates --to rare_candidates -w $WS` | 带 B：200 页 316 秒，**约 6 分钟**；不带 B：约 25 分钟 |
| 重落 Step7 | `--from seed_admit` | — |

合计起来，从快照起步一册约 25 分钟。#429 原来估的是「几十小时」。

正确性核对：
- `build-rare-index --jobs` 建出的两张表，与 09-28 那份包**逐位相同**（`np.array_equal`，最大差 0.0）。分片建与单进程建逐位相同，有单测。
- `cache warm` 渲出的 499 个字块，与串行渲出的逐位相同。两种缓存的页戳齐全、与产物 sha 一致，`guji cache verify` 干净。worker 不写页戳，主进程先清掉对不上的、再补写，全程串行，因为 `_stamps.json` 是读-改-写，多进程同时写会丢戳。
- B 改前改后，p62–82 共 21 页的 5-b 产物**逐字节相同**。

各项任务要求的落实：
- **「能复用预建索引的就复用」**：可以复用，见上表第一行。纯附件包只落 `models/` 下的两张表，不碰 products。`--dry-run` 核过，计划正好是这两张。
- **「能做成 `parallel_safe` 的就做」**：**没做**。理由有两条：
  - 表预建、字块预渲以后，整册串行只要 6 分钟，并行收益不大；
  - 表没备好就并行的话，几个 worker 会同时现建同一张表，而 `_save_emb_index` 的临时文件名固定（`emb_<key>.npz.tmp.npz`），会互相踩。还有，标这个标记本身就要改 Step 模块。

  并行放到了不碰 Step 的两处：建表（`--jobs`）和预渲（`cache warm`）。
- **「只对库里没有的格算」的开关**：**没做**。慢不在格数上，在一次性建表和切图上。只算部分格省不了建表；表建好以后算候选本来就只要每页 1.4 秒。

## 三、rare_ref 开着但 5-b 没跑时的提示（第 3 问）

做在 engine 和 CLI 里，**没碰 seed_admit 模块，也没动放行逻辑**：
- `guji status`：在那一步下面印
  `⚠ rare_ref 开着但 rare_candidates 缺 N 页，这些页 rare_ref 通道未生效（先跑 --from rare_candidates --to rare_candidates）`；
- 跑批日志开头：
  `⚠️ seed_admit：rare_ref 开着，但 rare_candidates 缺 4/20 页（p101,p102,p103,p104）——这些页 rare_ref 通道未生效……`。
  vol04 实测点名的就是没跑 5-b 的那 4 页。

实现是通用的：`StepSpec.optional_consumes_when` 里任一开关开着、上游却没有产物，就会报（rare_agree、shadow_promote、ocr_candidates 同样适用）。另外，`guji pipeline` 要跑 rare_candidates 而表没预建时，会先提示缺哪张表、多少字、预计多久、怎么备。

有了 5-b 以后 rare_ref 的效果（本地产物，**没推**，留给整理那边量对错）：p3–12 有 14 格走 rare_ref 放行，p95–100 有 15 格。#429 原来那次 p3–12 是 0 格。

## 四、改了哪些文件

- A：
  - `open_guji_cv/core/spec.py`：新增 `gated_optional_on`，`_gate_on` 抽成模块函数；
  - `open_guji_cv/core/engine.py`：新增 `Engine.optional_gaps`，跑批日志与 `status` 带上 `optional_gaps`；
  - `open_guji_cv/cli_v2.py`：status 打印、pipeline 缺表提示、`cache warm`、`build-rare-index --jobs`；
  - 新文件 `open_guji_cv/ops/rare_index_build.py`、`open_guji_cv/ops/cache_warm.py`；
  - runbook S5-b；
  - 测试：`tests/test_rare_downstream.py` 加一条，新增 `tests/test_rare_index_build.py`、`tests/test_cache_warm.py`。
- B：
  - `open_guji_cv/clustering/cnn_candidates.py`：`_real_slots` 两档 LRU，`_real_cs` 改成属性，老测试里 `cnn._real_cs = None` 清缓存的写法照样有效；
  - 新增 `tests/test_real_proto_cache.py`；
  - runbook 耗时按 B 更新。

## 五、测试

`python -m pytest tests/ -q -s -p no:cacheprovider` 的结果：2634 passed, 6 skipped, 1 error。

那 1 个 error 是 `tests/variants/test_variants_query.py::test_load_reads_directed` 上挂的 models/ 卫生守卫：测试过程中 `models/glyph_cnn_r5/` 下多出一个 `emb_ceade3a26972fd9c.npz`（2.5 KB）。这是 `variant_form.image_ranks_for` 走 `shared()` 真 checkpoint 时，对 2–3 个字的组内字表落的小表。**这个 error 是本道之前就有的**：在干净的 main `9ce4328` 工作树上跑全量，同样是 2628 passed、1 error，错在同一个测试、同一个文件。所以不是本分支带进来的，本道没修。要修的话，是某条 seed_admit 或 variant_form 测试得改用 `cnn_test_ckpt`。

## 六、要拍板的事

1. **B 要不要**：要的话，rare_candidates 判过期（目前没有消费者，不会触发重算）。不要就 revert B，vol04 整册 5-b 约 25 分钟。
2. **`_save_emb_index` 的临时文件名固定**：多进程同时冷建同一个 key 时会互相踩。目前靠书级跑批锁和「先预建」规避；要改就得动 `cnn_candidates`。这次没改。
3. **预建表的分发**：`idx/*` 分支两个仓里都没有，现在能用的只有 09-28 那份老式附件包。要不要拿 `guji snap pack … --rare-index` 把四庫这两张表正式挂成 `idx/rare_emb/<key>`，由总管定。本道没推任何 idx 或 snap 分支。

## 六·补：Z17 那个 `models-snap/rare-index-sk-20260927`（#430 并入的线索）

guji-workspace 里的这个分支，两张表的**内容与现行表逐位相同**，sha 与 vol08 包一致。但**文件名是 09-27 的旧 key**：`6138816db38c8cc0`、`0bdf23c3928fd2ba`，那时 key 里还带 mtime。现行 key 是 `c58003867002d48b`、`bec61ba15252b3bc`。所以照 NOTE.md 原名落盘不会命中，要按新 key 改名才行；它也不是 `idx/*` 格式，`snap import-index` 导不了。p3 在表在盘上时是 36.6 秒（进程第一页的预热），之后的页见第二节。

## 七、没做的事

- 没有推任何书的 products 和快照。vol04 的 5-b、seed_admit 只在本会话本地算过。
- 没有改 vol04.yaml。本地为了测试临时加了 `rare_ref: true`，没有推。
