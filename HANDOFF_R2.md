# R2 交单（overview#433）：seed_admit 待审补放三通道 R1 / R4 / R5

分支 `claude/R2-review-rate-1006`，基于 cv main `d5e7b37`。没有合 main，也没有开 PR。

## 改了什么

| 文件 | 改动 |
|---|---|
| `open_guji_cv/steps/seed_admit.py` | 新参数 `lane_witness3`／`lane_coord`／`lane_seal`（缺省都关）。新页末一遍 `_review_lanes_pass`，接在 iron → ji_yi_si → rare_ref → shadow_veto/promote 之后。版本升到 1.13，`code_deps` 加 `clustering.witness_cells`、`report.witness` |
| `open_guji_cv/clustering/witness_cells.py`（新） | 一页字位对一家证人，得出每格在证人里的读法。配对口径照搬 `report/collate.diff_page`：8-gram 锚定，归一后 difflib，取 equal 段和等长 replace 段 |
| `open_guji_cv/core/step.py` | `_with_witness_fingerprint` 在 R1/R4 开着时，用 `references` 全部证人文件填 `lane_witness_fingerprint`，证人一改，本步就过期 |
| `open_guji_cv/report/slots.py` | 印章空格位判成非字放行（`admit=True, char=None`, `occluded.ref_blank`）时，文本层照样跳过、不占位 |
| `tests/test_seed_admit_lanes.py`（新） | 30 条，数据全是自造的，带 `no_cnn` |
| `research/review_lanes/replay.py`、`vs_human.py` | 在快照上重放三通道，并与人裁事件对照 |

### 三条通道

所有通道都只把待审格改成放行，不降级。人裁位、排除名单格不碰。己/已/巳 一族一律跳过，继续由 `ji_yi_si` 处理。字块空白、形未定、近似例（`context_blank_cell`/`form_open`/`approx_exemplar`）也不碰。放行格的记法：`channel = provenance = 通道名`；`doubts = ["lane_<通道名>"]`；原来的疑问挪进 `evidence.lane.prev_doubts`；另记 `evidence.no_glyph_lib = True`。这三条通道只出文本：v2 里机器放行本来就不写库，库只认人裁事件，所以这里只是标明来源。

- **R1 `witness3`**：整理本对位来自 `replace` 段，待审类别是对齐改字层／与整理本冲突／形近字（类别判法镜像 `review.cards.card_class`，测试逐类核过两边一致），并且 D、W、Y 三家证人、整理本字、坐标对位字五路语义全同，才放行，放的是整理本字。护栏：库首位与整理本字是已知异体对时不放，记 `evidence.lane_skip`，照旧送审。
- **R4 `coord_fallback`**：只碰「其余」类。两个条件满足一个就放：(a) 库首位 == 坐标对位字 == 主证人 D，放库首位；(b) 三家证人和坐标对位字全同，且库无护栏（never_match/conflict），放坐标对位字。库首位与坐标对位字是异体对时，两种都不放。
- **R5 `seal`**：只碰 `occluded_gate` 拦下的格。默认字来自坐标对位（`lane_seal_via`，缺省只认 `coord`）的，放默认字；坐标对位判成空格的，判非字。护栏：本列坐标对位字连起来含「總目」或「四庫全書」（`lane_seal_title_marks`）的，**整列**不放。
- R1/R4 还有一道共用护栏：同一列只要有一格被 #427 的 `ctx_garble_*` 拦过，整列不走 R1/R4。

### 证人从哪读

`align_ref` 用的是 legacy 策略，只读 `references[0]`（D）。W、Y 的逐格读法在 cv 产物里原来没有，这次由 `witness_cells` 在 seed_admit 里现算。证人列表来自 `align_ref._witnesses_for_book`，带进程级缓存。三路都接上了，不缺。`lane_witnesses` 可以指定只用哪几家（填文件名）。

## 数字

快照解到 scratchpad 里跑，没碰正式 products。重放方法：读回快照里的 seed_admit 页，原样跑 `_review_lanes_pass`。三通道接在所有现行通道之后，上游一格不变，所以结果等价于开着开关重落一次 seed_admit。

### vol04（`snap/96mid1ogzk/vol04/20261006T0941`）

基线待审 1,457 格，正文 34,604 格，与卡上逐类相同。

| 通道 | 放行 | 卡上模拟 |
|---|---|---|
| R1 三证人一致 | **686**（对齐改字层 535、与整理本冲突 91、形近字 60） | 670 |
| R4 坐标对位兜底 | **57** | 60 |
| R5 印章区 | **215**（出字 152、判非字 63） | 233 |
| 合计 | **958，剩 499（1.44%）** | 963，剩 494 |

另有 13 格被异体护栏留下（R1 1 格、R4 12 格）。

**与看图结论（`reports/vol04/看图结论.jsonl`）对照**：与放行格只重叠 6 格（全在 R4），6 格都对。加列级乱码护栏之前重叠 11 格、错 5 格（p217 第 3 列乱码列 4 格，加 118:2:4），现在都不放了。118:2:4 重看原图其实是足旁的「䟽」，放「䟽」是对的。看图结论里没有 R1、R5 的样本。

**我自己看图**（从原图裁字块，固定种子随机抽样）：

| 通道 | 抽样 | 对 | 异体形不对 | 看不准 | 错字 |
|---|---|---|---|---|---|
| R1 | 80 | 77 | 2（图上像「煇」放成「輝」；像「鈌」放成「缺」） | 1（38:7:20「翻」） | 0 |
| R4 | 20 | 20 | 0 | 0 | 0 |
| R5 出字 | 12 | 12 | 0 | 0 | 0 |
| R5 非字 | 8 | 8 | 0 | 0 | 0 |

R1 的错字率在抽样里是 0。异体形不对的约 2.5%，按 686 格估约 17 格，原因是库首位不是该异体，护栏认不出。

### vol03（人裁对照）

seed_admit 用 `20260930T0457`；glyph_match、align_ref 用 `20260928T1708-full`（同 C1 的口径）。人裁取 `feedback/events` 里 actor=user 的末次裁决。

| 通道 | 放行 | 有人裁 | 对 | 异体 | 错 |
|---|---|---|---|---|---|
| R1 | 202 | 182 | 182 | 0 | 0 |
| R4 | 15 | 13 | 13 | 0 | 0 |
| R5 | 8 | 8 | 8 | 0 | 0 |

vol03 待审 316 → 91（0.52%）。**误放 0**。R4 曾有 9 格异体（库「彝」，人裁「𢑴」），加了「库首位与坐标对位字是异体对就不放」之后都留下了。

注意：vol03 对齐改字层的人裁大多出自网格页，网格缺省采信整理本，所以 R1「182/182 对」对整理本字有一定偏向，不是完全独立的验证。

## 要拍板 / 待办

1. **默认开不开**：卡上原计划「先实现，抽 100 格人裁，确认后默认开」。我的看图抽样错字为 0，但 R1 约有 2.5% 的异体会被改成整理本字形。建议先只在 vol04 的 yaml 打开三个开关，整理那边抽 100 格人裁后再定。
2. **R1 异体漏网**：煇/輝 这类刻本异体，库首位不是它（库给的是揮），所以靠「库首位与整理本字是已知异体对」这条护栏拦不住。要拦，得加一条判据，比如整理本字的 cov 很低时送审。这次没有做。
3. **R5 的 `align` 来源**（p130 卷/舊本題朗撰唐趙，8 格）缺省不放。卡上说看过是对的，要放就在 yaml 写 `lane_seal_via: coord,align`。
4. **己/已/巳 以杳冥本为主**：按卡上建议记一笔，这次没做。
5. **顺手发现，不在本单范围**：`cell_shrink` 产物的 `bbox_page`，x 是从页右边量的（镜像）。拿原图按 bbox_page 裁，要先换算成 `W - x`。

### vol04 yaml 打开方式

```yaml
params:
  seed_admit:
    lane_witness3: true
    lane_coord: true
    lane_seal: true
```

打开后只需重落 seed_admit 一步。回退：删掉这三行，再重落 seed_admit。

## 测试

- 新增 `tests/test_seed_admit_lanes.py`，30 条全过。
- 全量结果见下一节。
