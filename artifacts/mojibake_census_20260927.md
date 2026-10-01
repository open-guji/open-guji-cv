# 人裁事件乱码普查（2026-09-27，H 道）

依据 [P cross 1717](https://github.com/open-guji-core/overview/blob/main/项目进展/图片初步数字化/进度/inbox/P-对勘未放行口径/20260927-1717-cross-vol01人裁事件乱码致对勘全书跑批中止.md)：
`vol01-p1-30-confirm-20260916.jsonl` 一批 confirm 事件的 `shape`/`reading` 在写盘前
已被 UTF-8 误按 cp1252/latin-1 解码再存盘（`"内"` → `"å†…"`），原样流进
`feedback.lookup.human_chars()` 后把「一个字位=一个字符」的假设打破，
`report/collate.py::diff_page` 逐位对齐时下标越界崩溃，vol01 7 页（p24/26/33/42/47/137/141）
`guji collate` 全部拿不到结果。

## 普查范围与方法

- 扫描 `guji-workspace` 仓两本已建 `feedback/` 的书：
  - `96mid1ogzk-欽定四庫全書總目武英殿刻本`（含 vol01/vol02/vol03 全部事件，104 个 `.jsonl` 文件）
  - `988g7gsqhd-北行日錄清乾隆道光間長塘鮑氏刊知不足齋叢書之一`（bxgb，18 个 `.jsonl` 文件）
  - 合计 13,561 条事件行。
- 脚本：`scripts/mojibake_census.py`（cv 分支 `claude/H-mojibake-fix-0927`）。
  对每条事件的 `payload.shape` / `payload.reading` / `payload.char` 三个字段，
  凡长度 ≠ 1 且不是**合法多码位形态**（IDS 拆分串、PUA+变体选择符）的都记一条；
  对命中的记录尝试 `s.encode('cp1252').decode('utf-8')` 机械还原，能还原成单个
  合法字符的记为 `recoverable`，还原不了或还原结果仍不合法的记为 `needs_human`。
- 判据实现在 `open_guji_cv/feedback/mojibake.py`（`is_legal_shape` / `unmojibake` /
  `classify_shape_field`），与写入口/读取处共用同一份逻辑（见下）。

## 结果

| 书 | 扫描文件数 | 命中字段·条数 | 涉及事件文件 |
|---|---|---|---|
| 四庫（vol01/02/03） | 104 | 112（`shape`=56、`reading`=56） | 仅 `vol01-p1-30-confirm-20260916.jsonl` |
| 北行日錄（bxgb） | 18 | 0 | — |
| **合计** | 122 | **112** | **1 个文件** |

- **可还原 recoverable：112 / 112（100%）**，**需人判 needs_human：0**。
- 112 条命中记录去重后对应 **56 条乱码 confirm 事件**（`shape`/`reading` 成对乱码，
  同一条事件两个字段都坏），再按 `target.key`（书:页:列:格）去重后是 **28 个不同字位**
  （同一格在这批里被改判过 1~2 次，都是乱码）。
- 逐格核对「最终生效的那条事件是不是乱码」（按 `(ts, batch, seq)` 重放，取每个
  key 最后一条）：**28 个 key 全部命中**——没有更晚的合法事件已经覆盖过它们，
  说明这批乱码从写入那天起一直是"生效值"，从未被自愈。
- 命中的 28 个字位分布在 8 页：**24 / 26 / 33 / 42 / 47 / 60 / 137 / 141**（前 7 页
  正是 P cross 报告崩溃的那 7 页；60 页额外命中但不在崩溃清单里——大概率是那一位
  在这 8 页的对勘序列里刚好没有被判到会导致越界的位置，不代表它不是坏数据）。

## 20 条看图抽检（machine 还原 vs 原图）

从 28 个字位里随机抽 20 个，materialize 字块图核对还原字对不对（用 vol01 Step1-7
快照 `products-snap/vol01-20260927-54d08d3` + 原图 `data_full/zongmu/vol01/`）：

**20/20 全部匹配**，机械还原（cp1252/latin-1 → UTF-8 的确定性字节级逆运算）与
图上刻的字完全一致，包括一个生僻字 `𫝑`（U+2B751）与一个变体字头 `㸃`（點的异形）。
唯一需要放大核对的一条（`vol01:47:7:15`）初看像「丙」，放大后确认是相邻字笔画
渗入裁片边缘，核心字形仍是「内」。

明细见 `mojibake_census_final.jsonl`（本次会话 scratchpad，未入仓——纯诊断中间产物）。

## 字形库检查（任务书 §4）

直接扫 `glyph_store/`（真源，随 ws 仓提交）里两本书的 `glyphs.jsonl`（2,595 条，
四庫）与 `admissions.jsonl`（17,193 条四庫 + 4,851 条 bxgb，含内嵌 `evidence.shape`/
`evidence.reading`）：**`char`/`shape`/`reading` 字段长度 ≠ 1 的记录：0 条**。

交叉核实：`consumed/glyphdb_admit.jsonl` 里那批 56 条乱码事件的 id **确实被消费过**
（60 条同批次消费记录，含另外几条非乱码的），但因为 `glyphdb_admit` 自 `b162e64`
起已有「长度≠1 或非 CJK 就拒收」的闸（先于本次改动就存在），这批乱码从未真正
写进 `glyphs`/`admissions` 表——**字形库本身没有被污染**，问题完全在文本层
（`feedback.lookup.human_chars()`）。

**建议命令（先 dry-run，写进值守工单）**：对服务器真 `glyph.db` 跑一遍等价 SQL
核实与本地 jsonl 扫描结果一致（见下方值守工单草稿）。预期结果：0 条命中
（除非服务器库比这次 git 快照更新、且期间有新的乱码事件被别的路径直接写库——
可能性极低，但值守工单仍给出核实步骤，不假设）。
