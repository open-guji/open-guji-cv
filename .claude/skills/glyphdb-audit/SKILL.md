---
name: glyphdb-audit
description: 刻本字形库体检——找出同字不相像的刻例（可能选错字）与形似他字/字体异议的刻例，在控制台字形库页「体检」tab 供人裁决，裁决撤库、改字或入白名单。用户说「检查/体检字形库」「查一下有没有选错的字」时用。
---

# 字形库体检（glyphdb-audit）

进库的每个字形都是后续匹配的证据，错一个毒一片。本 skill 定期体检一本书的字形库。
判据与实现在 `open_guji_cv/clustering/glyph_selfcheck.py`（模块注释是单一事实源），
裁决的消费者在 `open_guji_cv/feedback/glyph_audit.py`。

**数据在哪（2026-10-19 写入切换后）**：字形真源在**中心库**，本机副本在数据目录
`$GUJI_DATA_HOME/<分支>/<工作区 id>/output/glyph_store/`（缺省 `~/.guji-data`）；
工作区里的 `output/glyph.db` 是从它重建的 SQLite 索引。字形库**不再进 git**，
不要 `glyph-db export` 后提交，也不要往 open-guji-cv 仓里提交库或结果。见 `doc/datastore.md` 第六节。

## 流程（照单执行）

1. **先拉最新库**：

   ```bash
   guji db sync -w <工作区>
   ```

2. **体检**（落 `<工作区>/output/glyph_selfcheck/findings.jsonl`、`summary.json`）：

   ```bash
   PYTHONIOENCODING=utf-8 .venv/bin/guji glyph-db selfcheck -w <工作区>
   #   --no-others：只在本书内比，不拿兄弟工作区的库当参照
   ```

   四路怀疑信号（都只是怀疑，裁决归人）：
   - `outlier` 同字离群：本书同字留一最优 cov < 0.90；
   - `rival` 形似本书他字：异字 cov ≥ 0.90 且反超同字——标错字的典型形态；
   - `rival_xbook` 形似他书他字：兄弟工作区的库作第二意见；
   - `font_rival` 更像另一个字的字体：弱信号，要拉开 `FONT_MARGIN` 才标。

   另有人裁 × 人裁冲突、`context` 放行两项只加权排序。北行约 15 分钟、四庫约 1 小时（两核）。

3. **在控制台裁**：字形库页「体检」tab，一张卡一个可疑刻例；裁决（没问题 / 形近·异体 /
   撤库 / 改字 / 一致程度）走 `glyph_audit` 事件，立即消费，账记在
   `output/glyph_selfcheck/decisions.jsonl`（同一张卡下轮体检不再出）。

   **结果带库指纹**（GUJI-710）：selfcheck 把开跑时的库指纹记进 `summary.json` 的 `db_fp`，
   每张卡记本例与本书对手的图块 sha。控制台出卡前核对——结果没带指纹（旧版算的），或卡上刻例
   的图与体检时对不上（刻例重排编号之类），整页提示「体检结果已过期（库已变），请重跑
   guji glyph-db selfcheck」，一张卡也不出，照提示重跑第 2 步。只是撤了、改了字的刻例，
   那几张卡不出，其余照常（在体检页上撤库不会让剩下的卡失效）。

4. **收尾**：撤库、改字改的是 glyph.db，裁完

   ```bash
   guji db sync -w <工作区>
   ```

   push 前见 glyph.db 指纹变了会自动先导出成字形库账本再推上中心库。撤库的格下次跑到那一页会重新出卡，
   走正常审查流重新定字。

5. **回流匹配基准**（可选）：本轮 rival × 白名单的新案例是匹配算法的排序金标——
   `scripts/build_match_triplets_shard.py --dataset ../open-guji-dataset` 重建 `glyph-match/triplets`，
   `scripts/eval_match_triplets.py` 重报基线并更新分片 README/results。

## 什么时候跑

- 每累计新进库几百条之后；
- 改过归一化 / verify / 匹配参数之后（形状判据变了，旧准入要复检）；
- 刻例重排编号、从中心库拉到大批新字形之后（控制台会提示旧结果过期）；
- 用户说「我可能选错了」的任何时候。

## 判读要点（给跑体检的会话）

- **rival 双向对**（惟↔淮 这类互为竞争）多半是真形近而非错标，可裁「形近·异体」；
- 真错标的形态：rival 且对手是人裁、本例是机器放行（尤其 `context`），或字体也倒向竞争字；
- 恒/恆、兹/茲 这类**异体对**是 vmap 语义没覆盖的噪声，「没问题」即可（顺手把缺的异体关系报给 variants 维护方更好）；
- **参照图也可能才是坏的**（划痕 / 残余混进库当了范例）：撤库可以撤对手那一例，不影响本例的裁决；
- 阈值（`TH_OUTLIER`/`TH_RIVAL`/`FONT_TH`/`FONT_MARGIN`）在 `glyph_selfcheck.py` 顶部，动之前先看
  `summary.json` 的分布，别拍脑袋。

## 旧工具（只读参考）

`scripts/audit_glyph_db.py`（`clustering/audit.py`，形离群＋竞争字＋OCR 异议，出 Artifact 审查页、
`apply` 回收）是 09 月控制台体检 tab 之前的做法，结果不带库指纹、白名单 `audit_ok.json` 不进中心库。
新体检一律走上面的流程；确要用旧脚本，跑 `PYTHONIOENCODING=utf-8 .venv/bin/python scripts/audit_glyph_db.py run --db <工作区>/output/glyph.db --out <工作区>/output/glyphdb_audit`，
撤库后同样 `guji db sync`，不提交进 git。
