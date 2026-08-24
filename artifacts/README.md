# Artifact 登记处——审查页面的 URL、快照与再生方法

本项目的人机协作靠一组发布在 claude.ai 上的交互审查页（Artifact）。
**URL 是持久资产**：用户的书签、页面里的浏览器本地状态都锚在 URL 上，
更新内容必须**重发布到同一 URL**（发布时带 `url` 参数），千万别新开。
本目录存各页的 HTML 快照（可离线看、可回滚），README 是唯一的 URL 台账。

## 活跃页面（vol01 进库工作流）

| 页面 | URL | 快照/真源 | 再生 |
|---|---|---|---|
| **种子审查页**（逐页进库人裁）| https://claude.ai/code/artifact/98d441fc-b27e-482a-a0c0-1cf1f72d170d | [vol01_seed_review.html](vol01_seed_review.html) | `scripts/export_seed_review.py output/vol01 --page <页>` |
| **字形库体检**（/glyphdb-audit）| https://claude.ai/code/artifact/a9509695-aaa5-4842-a496-a09e164b5417 | `output/glyphdb_audit/review.html`（随库提交）| `scripts/audit_glyph_db.py run` |
| **对勘复审**（我的定字 × 整理本，可改判/打印）| https://claude.ai/code/artifact/33403492-4d1c-4b32-bb2b-c66e01971684 | `output/vol01/phase9_seed/collation_review.html` | `scripts/export_collation_review.py output/vol01` |

## 切分审查（G1/G2 工作流）

| 页面 | URL | 快照/真源 | 再生 |
|---|---|---|---|
| **切分朱批·图块流**（紧裁版逐块审）| https://claude.ai/code/artifact/5406db9c-76da-46a6-a3d9-6b55e2965f81 | 数据即产物 | `scripts/build_patch_review.py --pages vol01:20-27 vol02:1-8` + 壳模板（会话脚手架）|
| 切分朱批·整页叠框（V1，看框位）| https://claude.ai/code/artifact/46681969-bd3f-46fe-915c-0ecd5a376f32 | 数据即产物 | `scripts/build_seg_review.py --pages vol01:20-39 vol02:1-20` |

标记经页内「导出」产 `GUJI-SEG-REVIEW` JSONL 回流。

## 分析报告（静态，作决策依据引用）

| 页面 | URL | 快照 | 说明 |
|---|---|---|---|
| 三信號進庫策略 | https://claude.ai/code/artifact/bbea2607-799d-4ab2-a97f-4c35fd485f87 | [signal_policy.html](signal_policy.html) | 529 条人审难例的三信号交叉标定（R1~R4 规则的依据）|
| vol01 對勘記 | https://claude.ai/code/artifact/cda67c8c-b5e9-48ac-99cb-f769652d71f4 | [vol01_duikanji.html](vol01_duikanji.html) | 三栏对照（原图/我的整理/整理本）|

## 历史页面（早期会话，无本地快照，URL 备查）

- 總目卷一（vol01）審查總覽 c82aa38f / 卷二（vol02）0bdcc21f
- vol01 · 頁型 0668c3f7 / 版面 ddab1f03 / 圖塊 fe3a22ce / 認字 1855f6f9
- vol02 · 頁型 d1bae796 / 版面 6ccd3a43 / 圖塊 ddb3e784 / 認字 19d34055
- book9 分步審查 d306fc16、錯判圖譜 ec62393b、並行作業總表 59a120cb、
  四庫總目字勘 2f1913aa（兩冊版 ec914d9a）
  （完整 URL 形如 `https://claude.ai/code/artifact/<uuid>`，uuid 见上）

## 纪律

- **同 URL 重发布**：会话内用同一文件路径重发即可；跨会话发布带
  `url` 参数指向上表 URL。发布前先读回最新存档（页面会自存用户事件），
  别覆盖没收割的裁决。
- **快照更新**：审后流程收尾时把最新导出的 HTML 拷回本目录一并提交
  （体检页与对勘页真源本就在仓库内，不必拷）。
- **事件回收**：所有审查页共用 `GUJI-SEED-EVENT` 前缀三层持久化
  （persist_js.py），从 artifact 存档提取事件行即可回收。
