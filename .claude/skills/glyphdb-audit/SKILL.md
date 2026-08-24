---
name: glyphdb-audit
description: 刻本字形库体检——找出同字不相像的刻例（可能选错字）与形似他字/OCR 异议的刻例，出交互审查页供人裁决，回收裁决撤库或入白名单。用户说「检查/体检字形库」「查一下有没有选错的字」时用。
---

# 字形库体检（glyphdb-audit）

进库的每个字形都是后续匹配的证据，错一个毒一片。本 skill 定期体检
`output/glyph.db`，判据与实现在 `open_guji_cv/clustering/audit.py`
（模块注释是单一事实源），脚本是 `scripts/audit_glyph_db.py`。

## 流程（照单执行）

1. **扫库出报告**：

   ```bash
   PYTHONIOENCODING=utf-8 venv/bin/python scripts/audit_glyph_db.py run \
       --db output/glyph.db --out output/glyphdb_audit
   ```

   三路怀疑信号（互相独立，都只是怀疑）：
   - `outlier` 同字离群：留一法同字最优 cov < 0.90；
   - `rival` 形似他字：异字 cov ≥ 0.90 且反超同字——标错字的典型形态；
   - `ocr` OCR 异议：RapidOCR top1（s2t+语义归一）≠ 库内字且 prob ≥ 0.80。
     OCR 单独只算弱信号（校准不可靠），与前两路叠加才要紧。
   耗时约 2~3 分钟（形状 ~2500 例留一验证 + 全量 OCR）；`--no-ocr`
   可省一半时间做快扫。

2. **发布审查页**：把 `output/glyphdb_audit/review.html` 发布为
   Artifact（**固定复用体检页的既有 URL**，别新开；本页与种子审查页
   是两个不同 Artifact）。排序已按怀疑等级：rival+ocr > rival >
   outlier+ocr > outlier > ocr。页尾单例字（全库唯一刻例，无同字参照）
   只有 OCR 信号，单独列出仅供扫一眼。

3. **回收裁决**：用户在页上按 X（撤库重审）/ O（没问题）后，从
   artifact 最新存档提取 `GUJI-SEED-EVENT` 行（op 是 evict/ok，
   与种子事件同前缀不同 op 空间，seed-ingest 会自动忽略它们）：

   ```bash
   PYTHONIOENCODING=utf-8 venv/bin/python scripts/audit_glyph_db.py apply \
       --db output/glyph.db --events <events.txt>
   ```

   - `evict`：删库（admissions/exemplars/derived/instances + 空壳
     glyph），队列行退回 `pending_review`（note=audit_evict）——
     下次导出该页时字位重新出卡，走正常审查流重新定字；
   - `ok`：进 `output/glyphdb_audit/audit_ok.json` 白名单，下轮体检
     不再骚扰。白名单按 instance_id 记，随仓库提交。

4. **收尾**：撤库过的页要重新导出审查（进库审查页 artifact），用户
   重新裁决后照常 seed-ingest；`output/glyph.db`、`audit_ok.json`、
   `report.json` 随 open-guji-cv 提交推送（分支 + 主干同步）。

## 什么时候跑

- 每累计新进库几百条之后（逐页审进行中大约每 3~5 页一次）；
- 改过归一化/verify/匹配参数之后（形状判据变了，旧准入要复检）；
- 用户说「我可能选错了」的任何时候。

## 判读要点（给跑体检的会话）

- **rival 双向对**（惟↔淮 这类互为竞争）多半是真形近而非错标——
  两边 OCR 都认同库内字时基本可 `ok`；
- 真错标的形态：rival + OCR 也倒向竞争字（首轮实锤 15:8:15
  「紛」形似「給」且 OCR 读「粉」）；
- 单例 OCR 异议里 恒/恆、兹/茲 这类**异体对**是 vmap 语义没覆盖的
  噪声，`ok` 掉即可（顺手把缺的异体关系报给 variants 维护方更好）；
- **参照图也可能才是坏的**（划痕/残余混进库当了范例）：每张参照图
  下有「撤此参照」，撤的是参照实例自己、不影响本例的裁决；撤完本例
  照常 X/O。
- 用户要**作废一轮已做的操作重来**：`run --tag <新盐>` 重新生成
  （批次号变，页面上的旧事件与本地计数全部作废），`force` 重发布同一
  Artifact URL；只要还没跑 `apply`，库没有被动过。
- 阈值（TH_OUTLIER/TH_RIVAL/TH_OCR）在 audit.py 顶部，动之前先看
  报告分布，别拍脑袋。
