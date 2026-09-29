# HANDOFF S#266（续）：vol03 云端重算与出包

> 前十节（列尾框线、小注补拆、抬头列、p49、105–108 重切）在分支 `claude/S-banxin-p49-0929` 的同名文件里，已合 cv main（5582ac9）。
> 本文件只有第十一节，分支 `claude/S-recompute-vol03-0929`。

## 十一、vol03 云端重算与出包（2026-09-29，CV 总管派）

### 11.1 底和版本

| 项 | 值 |
|---|---|
| 产物底 | ws 分支 `snap/96mid1ogzk/vol03/20260928T1708-full` 的 products（1443 个文件逐个校过 sha，零差异） |
| 工作区 | ws main `b7153b5d`（105–108 重切图 + H 影子页 33 条人裁） |
| cv | main `3e33b13`：比 5582ac9 只多 H #272 的收回脚本和它的测试，不改任何 Step 代码。所以两个包都声明 `compatible_with: 5582ac9` |
| 字形库 | 按 ws 的 `glyph_store` 重建，放在 `$WS/output/glyph.db`（默认路径，gitignore），指纹 `4224b3b258992fca` |

只在沙箱里跑：`GUJI_PRODUCTS_DIR` / `GUJI_CACHE_DIR` 都指向 scratchpad，工作区一个文件都没改。

### 11.2 怎么做到「只算受影响的」，和没做到的地方

用 `guji pipeline keben_body_v2 vol03 --pages all --jobs 4` 整书跑，重算哪些页、哪些格由引擎的指纹和格级复用决定，没有手工挑页。原因有两个：

1. **Step1 必须 110 页全跑一遍**：快照的 manifest 是 cv b961082 写的，没记册配置原值。现行引擎把这种条目一律判「代码或册配置变了」。全跑下来，105 页的字节和快照一样，所以 Step2 只在 49、105–108 这 5 页上重跑。
2. **字形库必须放在默认路径**：glyph_match 的参数里有 `db_path`（它是硬参数，不是软参数）。库放在别处，`params_hash` 就对不上快照，格级复用一格都不会发生。放在默认路径后，params_hash 和快照一样（`b7ec5c17480527bd`）。

Step5-a 先点名：`guji recheck vol03 --pages all --chars <150 字> --dead`。
- 150 个字取自快照之后 ws 字形库 `admissions/glyphs/evictions` 的变动（5077a9bd..b7153b5d，含 H 的 27 条入库和几轮定时同步）。
- 结果是 106 页里 1,817 / 17,411 格被点名；`--dead` 一格没中。

**Step5-b 没法只算受影响的格。** 它的参数里有 `model_fingerprint`，其中「真刻例多原型」那一段按字形库**内容**算。库自快照以来变过，所以这一步的自身指纹全书都变了，格级复用的第一道闸过不去，110 页只能全算。这是现行设计的正常结果，不是漏标。Step6/7 本来就是按页算的纯文本步，也是全算。

### 11.3 每一步实际算了多少

墙钟 03:43–04:44 UTC，共 61.6 分钟，4 核。其中约 42.6 分钟是 Step5-b 第一次用时现建 embedding 模板索引（base 29,689 字 + escalate 42,438 字），都记在 p3 那一页上。

| 步 | 实跑页 | 字节变了的页 | 列 / 格 | 耗时 |
|---|---|---|---|---|
| page_survey | 4 | 4（105–108 尺寸） | | 0 |
| border_detect | 110 | 5 | | 6.3 min |
| border_detect_gate | 5 | 4 | | 0 |
| column_warp | 5 | 5 | | 0 |
| column_gate | 110 | 5 | | 0.5 min |
| row_segment | 110 | 75 | 除 49、105–108 外：**格线动了 101 列**（列尾框线约 100 列，含抬头列 4 列），另有 59 列只是列级元数据变（`bottom_bar` 标记、小注收编等），变了的格 291 个 | 2.8 min |
| row_segment_gate | 75 | 75 | | 0 |
| cell_shrink | 110 | 73 | 除 49、105–108 外：142 列 / 414 格 | 1.0 min |
| glyph_match | 106 | 106 | **复用 14,677 格，实算 2,745 格**（1,817 格点名 + 几何变了的格 + 105–108 整页 665 格） | 1.8 min |
| rare_candidates | 110 | 110 | 全算（原因见 11.2） | 48.4 min（去掉建索引约 5.8） |
| align_ref | 106 | 69 | | 0.3 min |
| context_decide | 106 | 105 | | 0.8 min |
| seed_admit | 110 | 106 | 参数变了：新增的几道闸，加上人裁指纹（H 的 33 条） | 4.0 min |

跑完后 `guji status vol03 --pages all`：13 步都是 110/110 新鲜。glyph_match 有 4 页「漂移」（p1、p2、p57、p58），这 4 页没有被点名的字、几何也没变，没有重写，状态仍算新鲜。

账本：`artifacts/s266_vol03_recompute/recompute_report.json`（脚本 `scripts/experiments/s266_tail_frame/recompute_report.py`）。

### 11.4 包（cv 仓分支，等总管转到 ws）

| cv 分支 | 提交 | 内容 |
|---|---|---|
| `snaptmp/96mid1ogzk/vol03/20260929T0450` | `c376032a` | Step0–4：page_survey、border_detect(+gate)、column_warp、column_gate、row_segment(+gate)、cell_shrink；888 个文件，21 MB；`supersedes: snap/96mid1ogzk/vol03/20260928T1708-full` |
| `snaptmp/96mid1ogzk/vol03/20260929T0451` | `649358ef` | Step5–7：glyph_match、rare_candidates、align_ref、context_decide、seed_admit；555 个文件 |

两个包的 manifest 共同点：
- `format guji-snap/1`、`page_scope full`、`mode replace-steps`；
- 110 页每一步都是 `ok 110`；
- `cv.commit 3e33b13…`，`compatible_with ["5582ac9"]`；
- `glyph_db_fingerprint 4224b3b258992fca`、`allow_downgrade false`；
- Step5–7 包记了 `seed_admit` 的覆盖 `ji_yi_si_review=true`（来自书 yaml）。

按惯例（CV 总管 09-27 定）拆成 Step1–4、Step5–7 两包；dry-run 先跑过，计划与实际一致。

**转到 ws 时分支要改回 `snap/96mid1ogzk/vol03/<同一时戳>`，提交原样不动**：manifest 里的 `branch` 字段写的就是 `snap/…` 这个名字。

**重绑定文件没放进包分支**：导入会逐个文件校 sha，「多、少、错都拒」，多一个文件整包就判终态失败。这些文件放在本分支 `artifacts/s266_vol03_recompute/`。

### 11.5 值守导入要注意

1. **先让服务器的 ws 到 `b7153b5d` 或更新，再导入。** page_survey 的上游是原图 sha（新的 p105 是 `14b0b54e…`，旧的是 `e9765bb6…`）。原图没换过来的话，105–108 在服务器上会判过期，Step0 起新鲜页数变少，防降级闸会把整包换回。包里**不带图**，也不需要带：图已经在 ws main 里了。
2. **先导 0450 再导 0451。** 0451 的上游是 0450 里的 cell_shrink。watch 按 manifest 的 `created` 排序，0450 先建，会先导；手动导入也请按这个顺序。
3. **应该用不着 `--force`。** 下面三项上，我这边的指纹和服务器应该一致：
   - 字形库在默认路径，glyph_match 的 params_hash 与快照相同；
   - context_decide 的语料路径和快照同为 `/home/user/guji-workspace/…`，params_hash 也相同；
   - 真刻例原型按库内容算。

   例外：如果服务器那边的四庫 `glyph_store` 在 `b7153b5d` 之后又被定时同步改过，0451 里的 rare_candidates 和 seed_admit 在服务器上会判过期。但服务器现有那份也是对着旧库算的，同样过期，新鲜页数不会变少，所以也不该触发降级闸。真触发了请先问我或用户，别直接 `--force`。
4. **0450 作废了 `20260928T1708-full`。** 那个包服务器如果已经导过，没有影响；如果还没导，导入会跳过它（0450+0451 已经覆盖了它的全部步）。

### 11.6 旧人裁重绑定（事件文件一个没改）

49、105–108 上的旧人裁共 **31 条**：15 条逐格 confirm（all-decide 9 + shadow-review 6）、16 条 cutline。事件里的 `target.anchor` 只有 product_key、没有框。现行 `bindings.compute_page` 会先查补锚档 `feedback/anchors/<book>.jsonl`，查不到才去翻 `_prev/` 历史。快照导入会把历史换掉，而 105–108 的原图也换了，旧框和新图对不上。

所以做法是按**补锚档格式**给这些事件补新原图坐标系下的框：
- 框取自快照 Step3 里这一格的 `quad_page`；
- 105–108 按裁切位移换算。

**这里补测出一个以前漏掉的位移**：下块两页 107、108 重切后整体上移了 170px。用新旧原图做模板匹配实测，四页匹配分都是 1.000：

| 页 | dx | dy |
|---|---|---|
| 105 | −151 | 0 |
| 106 | 0 | 0 |
| 107 | −156 | −170 |
| 108 | 0 | −170 |

已补进 `artifacts/s266_col_remap_vol03.json` 的 `page_y_shift`。当初的列号对照只比了列中心 x，所以没发现。

再拿现行绑定规则在新产物上算了一遍（`rebind_table_vol03_s266.jsonl`）：
- **105–108 上落在有对应列的 7 条逐格裁决全部绑上**（6 条定字 + 1 条 seg_defect），valid 5、rebound 2（105:4:3→105:5:3、107:8:17→107:9:17），IoU 都 ≥ 0.92。105–108 另有 2 条 shadow-review 的 seg_defect（106:1:6、107:9:16）落在 null 列上，判 void。
- **49 上 6 条判 review**：49 的 Step1 分列改了，那几格的框确实变了。其中 5 条是 seg_defect，本来就是报切分有问题的格，该回待审；另 1 条是 49:3:1 的 not_a_char，旧第 3 列在新分列里没有对应。
- **要用户复核的 13 条**见 `artifacts/s266_vol03_recompute/needs_review.md`：
  - 旧列在新分列里没有对应（null）的 8 条：49:3:1、106:1:6、107:9:16，以及 cutline 107:9:2、105:9:1、105:9:2、105:9:3、107:4:2。比上一轮估的 5 条多，因为这次把 cutline 和 shadow-review 也算进来了；
  - 另有 49 上 5 条 seg_defect 判 review。

落地方法：把 `anchors_vol03_s266.jsonl`（15 行）作为 `feedback/anchors/vol03.jsonl` 放进 ws。这个文件现在还不存在，放进去后 `load_backfill` 自动读取，绑定缓存按签名自动重算。cutline 是列级事件，不进绑定行，只作为 `return_*` 字段折进已有行；它们的新列号在 `rebind_table` 的 `new_col` 栏。

**顺带一个更大的风险（范围外，供总管定）**：vol03 全书有 675 条逐格裁决没有框。快照导入后 `_prev/` 就没了，Step3 变了的 60 页上，这些老裁决只能靠字形库里存的图块来认，认不上的回待审。

我用同一方法给其中 **446 条**补了锚，只补 seed_admit 指纹和快照一致、确定是对着快照那版裁的：`anchors_vol03_all.jsonl`（它包含上面那 15 条中的 14 条，106:1:6 指纹对不上、没补）。新产物上 valid 428、rebound 2、review 15、void 1。review 的基本是 seg_defect 那几格，已经拆成雙行小注 a/b，或者列尾动了，比如 42:3:8、69:5:7–9、43:4:21、28:2:20，回待审是对的。

另外 229 条是对着别的版本裁的，没补，留给现行规则。要不要用 `_all` 替代 `_s266`，由总管或用户定。**保守默认只用 `_s266`。**

### 11.7 文件

- `artifacts/s266_vol03_recompute/`：`recompute_report.json`、`anchors_vol03_{s266,all}.jsonl`、`rebind_table_vol03_{s266,all}.jsonl`、`needs_review.md`
- `artifacts/s266_col_remap_vol03.json`：补了 `page_y_shift`
- `scripts/experiments/s266_tail_frame/rebind_vol03.py`、`recompute_report.py`
