# -*- coding: utf-8 -*-
"""快照自动导入（K 道，2026-09-27；overview `进度/总览/任务书-K-快照自动导入.md`）。

**云端算、git 运、服务器定时器自动收，不经过 Claude 会话。**

    云端  guji snap pack <book> …   → 推 guji-workspace 孤儿分支 snap/<ws>/<book>/<ts>
    服务器 guji-snap-watch.timer（15 分钟）→ guji snap watch
          → ls-remote snap/* → 逐包 guji snap import 的同一套逻辑 → 导入记录推 overview

包格式 v1（`FORMAT`）——**一包一条孤儿分支，不设 index 分支**：

- 分支名 `snap/<ws短id>/<book>/<yyyymmddThhmm>`（UTC）。`git ls-remote 'refs/heads/snap/*'`
  本身就是索引；不设 `snap/index` 是因为索引是**多写者共享的可变状态**——两个云端会话同时
  打包就要在 index 分支上抢 rebase，丢一次更新就等于丢一个包。作废靠新包 manifest 的
  `supersedes` 声明，不靠改旧分支。
- 分支内容是**明文文件树**，不是压缩包：`manifest.json` + `products/<book>/<step>/…` +
  `attach/<cv|ws>/<相对路径>`。git 按内容去重——同一本书重打包，没变的页一个字节都不重传，
  仓库不会因为反复打包线性膨胀（旧孤儿分支里的 `.tar.zst` 每次全量 11 MB）；服务器也不用
  装 zstd，`git archive` 读出来直接是 tar。
- 单文件 > `CHUNK_BYTES`（45 MB，GitHub 单文件 50 MB 起警告、100 MB 硬拒）按块切
  `…part000/001…`，导入时拼回并校验整文件 sha256；再大的放 Release/对象存储，manifest
  写 `url` + sha256（`attachments[].url`），导入时下载校验。

- 大模板索引（rare emb / 字体 HOG，几十 MB 一张、多本书共用）**不进包**：一张表一条
  `idx/<kind>/<key>` 孤儿分支，manifest `indexes` 只写引用，打包与导入都按 key 去重
  （2026-09-28，overview#246，见 `indexes` 模块头）。

模块：`manifest`（格式、分支名、标记文件）、`gitio`（可注入的 git 调用）、`pack`、
`importer`、`watch`、`indexes`。
"""
