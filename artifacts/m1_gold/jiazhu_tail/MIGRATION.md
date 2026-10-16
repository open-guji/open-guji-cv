# jiazhu_tail 金标迁移（M1 道 C 组，2026-09-30）

## 结论

| | 条数 |
|---|---|
| 原金标 `jiazhu-tail/expected.json` | 57（tail_a 46 / row 8 / reject 3），键 `(册,页,列,idx)`，`label_origin=model_visual` |
| **迁移到 v2**（`jiazhu-tail/expected_v2.json` 的 `items`） | **44**（tail_a 37 / row 4 / reject 3） |
| 已失效（`retired`） | 13 |

失效原因：

| 原因 | 条数 | 条目 |
|---|---|---|
| **用户排除页**（2026-08-25 用户定压缩职名页「不判读、不入测试集」） | 10 | vol01/89 ×2、vol01/90 ×7、vol02/159 ×1——这些条目本来就不该在金标里 |
| 目视结论与原标签不符 | 3 | vol01/184:5:7（v2 该格是双行小字，原标 tail_a）、vol01/184:9:8（该格是正文大字，原标 row）、vol02/100:4:16（该格是正文大字「此」，「條易」双行在它上一格，原标 row）——键偏一格或标签对不上，不硬改 |

## 为什么原来是假通过

`eval_jiazhu_tail.py` 现场重跑 v1 `CharExtractor.extract_page`，读 `output/<册>/phase3_char_grid`；云端没有 → `got` 为空，
57 条全报「? 格位消失」，但回归门 `ok = n_lost == 0 and n_swallow == 0` **不看消失数** →「回归门：通过」。
（`--v1` 现场复现：`实测 {}；丢字 0，吞正文 0，拆法迁移 0，消失 57；回归门：通过`。）

## 迁移判据（仍然是看图，不是看算法）

这分片**从来没保存图块、指纹、bbox**（标签是模型看接触表目视核对的）。能拿到的只有 v1 键 `(page, col, idx)`，
而 v1 键漂移是它的老病（README「已知局限」记过 vol02/145:5）。所以：

1. 先按用户排除页剔条（10 条）；
2. v1 `idx` → v2 `pos = idx+1`（recrop 上 31/31 旁证），取 (col, slot)；
3. 出联系表（`sheets/`）：v2 列图里该格及其上两格、下一格的**原图切片**，左缘用短线标 Step3 格界、红括号标被评格，
   **不叠任何算法判断**；逐条目视被评格是「a 行单个小字靠右」/「两个小字并排」/「一个正文大字」；
4. 目视结论与原 expect 一致才迁（`visual_check=consistent`）；结论登记在 `visual_review.json`（可复核）。
   47 条里 44 条一致、3 条不符。

锚位的一致率（44/47）本身也是 v1 键→v2 (col,slot) 这条映射的独立旁证。

## 评测与新基线

```
python scripts/eval_jiazhu_tail.py ../open-guji-dataset/char-segmentation
→ jiazhu-tail 44 条：实测 {'row': 4, 'tail_a': 37, 'reject': 3}；丢字 0，吞正文 0，拆法迁移 0，消失 0；回归门：通过
```
v2 口径：某 `(col, slot)` 上实例里同时有 sub=a、sub=b → row；只有 a → tail_a；都没有 → reject（与旧口径一一对应）。
**新增一条防线：格位消失数 >0 也判失败**（旧代码对消失静默放行，正是假通过的根因）。
（沙箱范围：vol01/vol02 的 44 条所在页，产物为 sandbox products；不含 vol03/bxgb。）

## 与 doc 上次值对照

- 分片 README 回归口径：不许丢字、不许吞正文；2026-08-28 裁边修复后 `doc/pipeline_handbook.md` §12 记「`jiazhu-tail` 丢字 **2→1**」；
  `doc/design/char_clustering_design.md` 收尾表：「jiazhu-tail 丢字 **0**（金标重键 2 条）」。
- v2：丢字 **0**、吞正文 **0**（44 条全部判对）。可比：同一条回归口径，v2 下 44/44 与目视一致；
  原 57 条里 10 条是排除页、3 条键漂移/标签存疑，所以**样本比旧的少 13 条**，不是同一批样本。

## 已知局限

- `label_origin=model_visual`：标签是模型目视，这次迁移的核对也是模型目视（同一来源、独立于算法）。**不是人工金标**，
  若要升级为人工，得另出审查页让人过一遍这 44 条。
- reject 只有 3 条（则/等/然类全尺寸正文）。
