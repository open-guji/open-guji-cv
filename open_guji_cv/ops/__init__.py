# -*- coding: utf-8 -*-
"""发布与部署（K 道，2026-09-26）。

- `release_check`：`guji release check`，云端跑，给总管发版用——候选提交跟上一个
  `cv-*` tag 比，列出「指纹变了的步」＋全量测试回归＋出 `RELEASES.md` 草稿。
- `deploy_check`：`guji deploy check`，服务器定时跑——`production` 分支有更新就
  拉模式自动部署，健康检查失败自动回滚。

见 overview `进度/图片初步数字化/进度/总览/16-三机分工与发布流程.md` §三、
`总览/任务书-K-发布与部署.md`。
"""
