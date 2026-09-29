# HANDOFF K238b（fp-migrate 第二轮）· 分支 claude/K-fpmigrate2-0929

## ⚠️ 最前：关于「cells 口径不一致」——我没有找到证据，前提本身有误
- `cells` 这个 kind 由 **row_segment** 产出（`steps/row_segment.py: produces=("cells",)`）；
  **cell_shrink 产的是 `char_index` / `char_patch`**，不产 `cells`。
  `align_ref` 的 `cells` 是 optional_consumes，`Engine._upstream_sha` 经 `pipeline.producer_of("cells")`
  取 row_segment 的 sha。所以 manifest 里 `upstream.cells == 现 row_segment sha` 是**设计如此、完全正常**，
  不说明云端与服务器口径不同。`fp-migrate` 用的就是 `eng.upstream_shas`，与 `Engine.fingerprint`
  同一函数，脚本口径与当初跑批口径一致。云端 `--to cell_shrink` / `recheck` / `--from glyph_match`
  分段跑走同一个 Engine，指纹公式不因分段而变（recheck 只写 manifest 的格级 invalidated，不动 sha）。
- 值守比对的只是 `cells` 与 `glyph_match` 两个键。真正不等的很可能是**别的键**——
  `align_ref`/`context_decide`/`seed_admit` 都有可选上游 `ocr_candidates`、`rare_candidates`，
  `rare_candidates` 还受开关 `rare_topk` / `rare_agree` 控制（`live_optional_consumes`，取自**当前机器**的
  `params_for`）。「记录里有、现算没有」或反之，整条 upstream 就不相等。可疑点（**均未证实，我读不到服务器数据**）：
  1. 服务器上 rare_topk/rare_agree（册配置或管线 yaml）与云端跑批时不同 → 键集不同；
  2. `_upstream_sha` 对可选上游用「文件在不在」判断：服务器导入后 ocr_/rare_candidates 产物在/不在与记录时不同。
  vol03 的 70/40 拆分若是「有没有 rare/ocr 产物的页」就符合 2。**请值守跑 `--explain` 定案**（见下）。
- 若 `--explain` 显示差异在 `rare_candidates`/`ocr_candidates` 键，那是这两步在两边的**真实差异**
  （产物不同或开关不同），下游三步的过期是真的，**不能洗成新鲜**——脚本也确实没洗。

## rare_candidates 过期的原因（读代码得出，未在服务器验证）
它没有 path_params，但 `params.model_fingerprint`（进 params_hash）里有随机器变的量：
1. **real_proto 开着时**：`real_proto_fingerprint` 把 spec 原文 `store:<绝对路径>` 拼进哈希
   （`cnn_candidates.py:347`），路径来自 `workspace_root()`；云端与服务器工作区路径不同 ⇒ 指纹必不同。
   这是最像的：内容指纹修过 mtime，路径这一项漏了。
2. `struct_probe` 字段的路径原文直接在 params_hash 里（没登记 path_params）——若 yaml 设了它同样随机器变。
3. `template_set_fingerprint`：按外部模板目录**在不在/文件数**取 stamp，两台机器数据不齐会不同（当前 `EMB_EXTRA_SPECS` 为空，多半无关）。
**我没有改指纹公式**：改了会让所有开 real_proto 的册 rare_candidates 一次性全过期，且它的 model_fingerprint
是整体哈希、没有「老路径」可供 fp-migrate 重算。需要总管拍板：(a) 把 spec 换成相对工作区的路径再哈希，
并接受一次过期或另写迁移；(b) 保持现状，服务器上重跑 rare_candidates。
`--explain` 会把上述分量逐项列出（★=可能随机器变）。

## 改了什么
- `products/fp_migrate.py`
  - `diff_upstream / format_diff`：对被跳过页逐键给出 记录 sha / 现算 sha / 现由哪个步产出 /
    **记录的 sha 现在对应哪个步的产物**（`_attribute`，扫全部产出该 kind 的步）/ 差异类型（sha 不同｜仅记录有｜仅现算有｜现算缺失）。
  - `migrate_book(..., explain=False)`：explain 时报告多 `detail: {页: {why, diffs}}`；不开则报告结构与以前逐位相同。
  - `--steps` 点名却无 path_params 的步 → `{"na": "无路径参数，不适用"}`；点了不在管线里的 → `"不在本管线里"`。不点名时行为不变。
  - `rare_fingerprint_parts`：分解 rare_candidates 指纹。
- `cli_v2.py`：`fp-migrate --explain`，打印上述；`--steps rare_candidates --explain` 另列指纹分量。
- 迁移判断逻辑**没改**（没发现它有错）；单测证明同名上游来源不同时不迁、不改 manifest。
- 测试：`tests/test_path_params_fp.py` +3 条（同名 cells 来源不同不被洗白且 explain 归因正确／点名无路径步不静默／仅一侧有键）。

## 服务器怎么用
```
guji fp-migrate vol03 --trust --steps glyph_match,rare_candidates,align_ref,context_decide,seed_admit --explain
guji fp-migrate vol02 --trust --steps align_ref --explain --json    # detail 里每页逐键差异
```
每个被跳过页下面 `· kind: 记录 xxxx ≠ 现算 yyyy [how；现由 <step> 产出]（记录的 sha 现对应 <step>）`。
先看差异集中在哪个 kind。

## 拿不准
- 上面 rare/ocr 可选上游的猜测与 real_proto 路径的猜测都只是读码推断；以 `--explain` 输出为准。
- 未做：改 real_proto 指纹公式（见上，等拍板）。
