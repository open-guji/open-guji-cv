# -*- coding: utf-8 -*-
"""（拆分 P4 第六批，2026-11-04：本包的 cache_verify, cache_warm, central_glyph, corpus_pack, emb_pack_build, exclusion_rebind, exp_record, glyph_release_gate, glyph_snapshot, pack_purity, page_kinds_report, prep, products_diff, rare_index_build, rerun_stale 已搬去 guji-manager `guji_manager.ops`。）

发布与部署（K 道，2026-09-26）。

- `release_check`：`guji release check`，云端跑，给总管发版用——候选提交跟上一个
  `cv-*` tag 比，列出「指纹变了的步」＋全量测试回归＋出 `RELEASES.md` 草稿。
- `deploy_check`：`guji deploy check`，服务器定时跑——`production` 分支有更新就
  拉模式自动部署，健康检查失败自动回滚。

见 overview `进度/图片初步数字化/进度/总览/16-三机分工与发布流程.md` §三、
`总览/任务书-K-发布与部署.md`。
"""
