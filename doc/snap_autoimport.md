# 快照自动导入：云端算、git 运、服务器定时器自动收（2026-09-27，K 道）

> 代码 `open_guji_cv/snap/`（模块头是正本）；任务书 overview `进度/总览/任务书-K-快照自动导入.md`。
> 取代此前每次手抄的「clone 孤儿分支 → zstd 解压 → cp 进 products」导入命令。

## 一圈怎么走

```bash
# 云端（产物在 GUJI_WORKSPACE 的 products/ 里，或用 --from-products 指到旧快照目录）
guji snap pack vol03 -w ~/guji-workspace/96mid1ogzk-… [--pages 1-50] [--steps a,b] \
     [--mode display-only] [--supersedes snap/…] [--param seed_admit.use_context=false] \
     [--attach models/r5/emb_x.npz=cv:models/r5/emb_x.npz] [--note …]
#   → 推 guji-workspace 孤儿分支 snap/<ws短id>/<book>/<UTC yyyymmddThhmm>
#   加 --dry-run 只打印计划（分支名、页数、文件数、字节数），不建提交、不推。
#   ⚠️ 2026-09-28 之前的 cv 里 pack 不认 --dry-run、照样真推（Z21/Z22/Z23 踩过，#174）

# 服务器：guji-snap-watch.timer 每 15 分钟
guji snap watch --ws-repo ~/guji-workspace --ws-root ~/guji-workspace --overview ~/overview
#   → 导入记录 overview 进度/图片初步数字化/进度/inbox/导入/<UTC>-import.md

guji snap list   --ws-repo ~/guji-workspace          # 各包状态
guji snap import snap/… --ws-repo … [--dry-run] [--force]   # 手动导一个
```

## 打包惯例（CV 总管 09-27 定）

- **Step1–4 一包、Step5–7 另一包**，别混打。Step5–7 的指纹含字形库，云端重建的库与服务器现役库指纹不同，导到
  服务器上必然判过期；防降级闸一看「新鲜页数变少」就**整包**换回——混在一个包里，本来能变新鲜的 Step1–4 也跟着导不进去。
  ```bash
  guji snap pack vol03 -w … --steps border_detect,border_detect_gate,column_warp,column_gate,row_segment,row_segment_gate,cell_shrink
  guji snap pack vol03 -w … --steps glyph_match,rare_candidates,align_ref,context_decide,seed_admit   # 只在服务器没有更好的那份时才会导进去
  ```
- 只给人看、不许服务器重算的（全唐文这类借库/关 context 的试跑）用 `--mode display-only`；包里没带的步不受标记保护，
  要么一起带上，要么接受服务器按夜间队列去算。
- 重打的包用 `--supersedes <旧分支>` 作废旧包，别去改旧分支。
- 防降级闸**留着**：无人值守宁可不换，也不把新鲜的换成过期的。真要换用 `guji snap import … --force`（先问 CV 总管）。
- **纯附件包**（只发 rare 预建索引之类、本地没有 products）：`guji snap pack rare-index -w <ws> --mode attach-only
  --attach …=cv:models/glyph_cnn_r5/emb_<key>.npz`。导入只校验 sha、落位附件（被换掉的留 `runs/snap_backup/`），不碰 products。
  ⚠️ 2026-09-27 实测：emb 索引 key 里带字体档 mtime（`font_set_fingerprint`），跨机器 key 对不上，云端预建的索引在服务器
  命中不了——等 R 道把 key 改成按内容算再发（见 overview#51）。
- ~~附带 R 道预建的 rare 模板索引：`--attach models/glyph_cnn_r5/emb_<key>.npz=cv:…`~~ ——
  2026-09-28 起改用下一节的 `--rare-index` / `--font-index`（按 key 去重，大文件不进包）。

## 大模板索引分发（2026-09-28，overview#246，用户定方案 1）

大模板索引（Step5-b CNN embedding 表 `models/<ckpt>/emb_<key>.npz`、控制台 HOG 字体表
`<ws>/cache/font_index/<key>.npz`）**一律云端预建、随快照分发，服务器控制台只读盘、不现建**
（控制台一侧 cv e3fcfdf）。代码 `open_guji_cv/snap/indexes.py`（模块头是正本）。

```bash
# 云端：先建表（单进程单核，base ≈3 万字 / escalate ≈4.3 万字，耗时与峰值见 overview#246 交单）
guji cache build-rare-index --book bxgb -w <工作区>
guji cache build-font-index [--book bxgb] -w <工作区>     # 不带 --book = 控制台启动预热用的默认语料
# 再打包：纯索引包用 attach-only；产物包也能顺手带
guji snap pack bxgb -w <工作区> --mode attach-only --rare-index            # base+escalate
guji snap pack v007 -w <工作区> --mode attach-only --rare-index escalate   # 只带一档
guji snap pack … --font-index [book|default]
#   书 id 要写在 --rare-index/--font-index 前面（两者值可省，省了会吞掉后面的位置参数）
```

- **一张表一条孤儿分支 `idx/<kind>/<key>`**（`kind` = `rare_emb` / `font_hog`）：`index.json` + 45 MB 一块的
  `data.partNNN`。大文件只在这里，**不进任何主干历史，也不进 `snap/…` 包本身**——包的 manifest 只多一栏
  `indexes: [{kind, key, root, dest, sha256, size, branch, label}]`，写明 key 与落位。
- **打包按 key 去重**：远端已有 `idx/<kind>/<key>` 就直接引用（sha 取远端那份），不重推；一个包里重复的 key
  只留一条。全唐文 v007–v009 共用一张 escalate、四庫 vol09/vol10 共用一张 escalate，都只推一次。
- **导入按 key 去重**：目标文件已在就跳过、连 idx 分支都不拉（导入记录写「模板索引已在」）；不在才浅拉那条
  分支、拼块、校 sha256、原子落位（「模板索引落位」）。同一 key 不同机器建出来的字节可能不逐位相同
  （浮点累加顺序），内容等价，所以「已在」只看文件在不在。
- 索引先于产物落位、不拿书锁（按内容 key 的缓存，放上去不会让任何产物变旧）；拉不到/校验不过记 `fetch_failed`
  （可重试），产物一点不动。
- ⚠️ **服务器 cv 要先部署到认 `indexes` 的版本再推这种包**：旧版 `validate` 不认识纯索引的 attach-only 包
  （「至少要有一个附件」），会记成 `bad_manifest` 终态，同一提交不再重试——真撞上了就重打一个包（新提交）。
- key 与产线同一个函数算（`emb_index_key` / `font_candidates._index_key`），2026-09-28 起都按内容算，
  换机器照样命中；打包端表没建会直接报错提示先建，不替人现建。
- **idx 分支挂哪个仓**：缺省 guji-workspace（与包同仓）；`--index-repo cv` 挂 open-guji-cv 的 origin，manifest
  条目写 `repo: cv`，导入端到 `--cv-repo` 的 origin 去拉。本地没建过、但远端已有同 key 的 idx 分支也能打包
  （只引用、不要求本地有文件）——建表的会话和打包的会话可以不是同一个。
- **值守手动落一张表、不经包**：`guji snap import-index idx/<kind>/<key> --index-repo cv|ws [--cv-repo …]
  [--ws-repo …] [-w <工作区>（font_hog 才要）] [--dry-run]`——读分支自己的 `index.json`，同样校 sha、已在就跳过。

## 包格式 v1

- **一包一条孤儿分支，不设 index 分支**：`ls-remote 'refs/heads/snap/*'` 就是索引；index 分支是多写者
  共享可变状态，并发打包会抢 rebase。作废靠新包 `supersedes`。
- **明文文件树**：`manifest.json` + `products/<book>/<step>/…` + `attach/<cv|ws>/…`。git 按内容去重，
  重打包只传变了的页；服务器不用 zstd。`_prev/` 不进包。
- 单文件 > 45 MB 切块（GitHub 50 MB 警告 / 100 MB 硬拒；guji-workspace 仓 .git 已 700 MB，推荐上限 5 GB），
  再大的走 Release/对象存储、manifest 写 `url`+sha256。
- manifest：书、页、步、`page_scope`（full=整目录替换 / subset=合并页）、`mode`（replace-steps /
  display-only）、`supersedes`、cv 提交与 `compatible_with`、各步 `params_hash` 与参数覆盖、
  字形库指纹、书 yaml sha256、生成时间/会话、每文件 sha256、附件、`workspace.create`、`allow_downgrade`。

## 导入判据（顺序）

拉包 → 逐文件 sha256（多/少/错都拒，终态）→ 书级跑批锁（占着就 `locked`，下轮再试）→ cv 兼容
（包的提交或 `compatible_with` 之一是服务器 HEAD 的祖先，否则 `incompatible`，部署跟上后自动通过）→
持锁备份（`products/<book>/.snap_backup/`，留 2 份）+ 原子换目录 → **防降级**（任一步新鲜页数变少就
整包换回、`downgrade` 终态；display-only 不查）→ display-only 标记 `.snap_marks.json`、流水
`.snap_imports.jsonl`。部署器的过期步队列（`deploy_check.collect_stale_summary`）跳过 display-only 步。

## 踩过的坑

- 对完整 clone `git fetch --depth 1` 会把整个仓变浅仓（写 `.git/shallow`）——只在本来就浅时带 depth。
- **反过来，浅仓做不带 depth 的 fetch 会拉整个仓的历史**（09-28 服务器 cv 仓，约 4.7 GB、临时 pack 13 GB，
  部署与 snap-watch 卡了近 7 小时，overview #236）。现在部署与快照的所有 fetch 都走 `ops/git_fetch.py`：
  浅仓带 `--depth`（部署 50、拉包 1、补拉 cv 提交 50）、开跑前查盘（`GUJI_FETCH_MIN_FREE_GB`，缺省 10）、
  超时整组杀并删半截 `tmp_pack_*`（`GUJI_FETCH_TIMEOUT`，缺省 600 秒）。`check_cv` 在浅仓里先
  `fetch --deepen=200` 把 HEAD 往下接再判祖先——否则落在浅边界下的老 cv 提交会被误判成不兼容。
- `resolve_pages("all")` 按原图目录数页：原图不在时新鲜度量出 0 页。导入记录只量包里的页。
- 部分页的包不能整目录替换（会删掉别的页），走合并：复制现目录 → 覆盖包内页 → `_manifest.jsonl` 追加。
