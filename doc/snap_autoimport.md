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
- 附带 R 道预建的 rare 模板索引：`--attach models/glyph_cnn_r5/emb_<key>.npz=cv:models/glyph_cnn_r5/emb_<key>.npz`
  （float32，几十 MB 会自动切块）。

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
