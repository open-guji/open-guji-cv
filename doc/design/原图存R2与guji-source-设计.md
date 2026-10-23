# 原图存 R2 与 `guji source pull|push`：设计稿（A20，2026-10-23）

> 状态：**设计稿，待用户定方案**。纯文档，不改代码、不写 R2、不搬数据。
> 来源：A30 需求（ai-team `domain/CV/规范/子会话启动提速与待命池策略.md` 第六节 6.2）；对齐 PR #443（产物与版本钉）与 `datastore/packs.py`、Worker `packs.ts`。
> 与现行规则的冲突：项目规则写「git 里只放原图」，本方案把**新增册**的原图改放 R2，vol01–10 与 bxgb 暂不动（见第七节）。

## 一、要解决什么

vol11 起的原图不在 guji-workspace 仓里，源是 archive.org（浙大 CADAL 扫描的 `_tif.zip`）。每个子会话都从 IA 重下、重转 PNG，慢、受 IA 限速、转出来的字节还可能不同。
**转出来的字节不同会直接改产物**：`border_detect` 的上游记了 `raw_page` 的 sha，原图页字节一变，下游指纹全变。所以原图必须有**唯一一份规范字节**，取回后逐文件核 sha。

## 二、方案总览

沿用产物包的机制（按名字只增不改、分段、逐段核 sha、Worker 令牌分级），新增一类包「原图包」。

| 项 | 方案 | 备选 |
|---|---|---|
| 桶 | 正式桶 `guji-assets`；试存、演练用 `guji-assets-exp` | 单独开 `guji-source` 桶（要新建桶与域名，不建议） |
| R2 键 | `pack/source/<ws>/<册>/<包标签>/{manifest.json, part-000.tar …}` ＋ `…/<册>/main-ptr/…` | Worker 新开 `/v1/sources`，键为 A30 提的 `source/<ws>/<册>/`（要改 Worker 并部署，经 Deploy） |
| 前缀说明 | 复用 `/v1/packs`，Worker 固定加 `pack/`，所以实际键多一层 `pack/`；**零 Worker 改动**，令牌分级、只增不改、409 防覆盖都现成 | 同左 |
| 包标签 | `src-<来源>-<UTC日期>`，如 `src-ia06061311-20261023`（ASCII，同 `LABEL_RE`） | — |
| 一册一个包 | 内容＝管线读的 `data_full/<book>/`（逻辑页 PNG ＋ `manifest.json` ＋ `_source_defects/`）。tar 不压缩（PNG 已压缩），每段 ≤64 MB | 另存 `_scan/` 扫描页（体积翻倍；IA 的 `_tif.zip` 校验和已能回源，默认不存） |
| 取 | `guji source pull <册> [--label 名] [--to 工作区] -w <ws>`：读令牌；缺省取 main 指针；逐段核 sha256 → 解到 `<工作区>/data_full/<册>/` → 逐文件核 `files.json` → 写 `.source.json`（标签、sha、时刻） | — |
| 存 | `guji source push <册> --from <目录> --ia <identifier> --ia-sha256 <zip 校验和> [--main] [--bucket exp\|main]`：打包、算 `files.json`、传、写指针 | — |
| 列 | `guji source list [<册>]`（★＝main） | — |

manifest 字段（沿用产物包，增 `kind: "source"`）：`ws, book, label, files, bytes, parts[{name,bytes,sha256}], pack_sha256, files_index_sha256` ＋ **回源信息** `origin{ia_identifier, ia_file, ia_zip_sha256, ia_url, fetched_at, convert{tool, version, args}}`。
逐文件索引 `files.json`（`{相对路径:{sha256,size}}`）与 #443 步 1 为产物包补的同形，实现时共用一个函数。

## 三、登记进中心库

- **第一期不新增表**：册配置 `books/<book>.yaml` 加一块 `source:`，随 `guji db push` 进 `books` 表：
  ```yaml
  source:
    pack: src-ia06061311-20261023     # 包标签（R2 manifest 为准）
    files_index_sha256: …
    ia_identifier: …
    ia_zip_sha256: …
  ```
  册 yaml 与包一一对应；`guji source pull` 缺省读这里的 `pack`，没写才退回 main 指针。这样**换了原图包必须改册配置、走人裁同款的版本号与 rev**，不会悄悄换。
- 第二期（#443 步 2 的三表落账后）再考虑 `snapshots` 一类的 `source_packs` 表，把 `books/*.yaml` 里的块迁过去；现在不建，避免 schema 变更与 Worker 部署。

## 四、令牌与写入

- 读令牌 `GUJI_DATA_TOKEN_READ`：pull、list（云会话环境已有）。
- 写正式桶要正式令牌 `GUJI_DATA_TOKEN_PROD`，**只在服务器**；云会话没有。所以 vol11–20 首次搬运分两步：①有 A30 本地 PNG 的会话用**实验令牌**先 push 到 `guji-assets-exp`，在新容器 `source pull` 核 `files.json`，演练通过；②**用户点头后**由持正式令牌的一方（服务器 / Ops）做正式桶 push，或把实验桶对象复制到正式桶（同名同字节）。
- 正式桶 `pack/` 经公开域名 `blob.open-guji.com` 是否可读要确认：现行「按哈希公开」只对 `sha256/` 键成立；若 `pack/source/` 也被公开，原图（IA 公版扫描）可直接下载，需用户确认可接受，否则让 Worker 继续走令牌读。

## 五、对 code_hash／指纹的影响判级

- 代码只落在 `datastore/` 与 `cli_*.py`，不进任何 Step 的 `code_deps`：17 步 `code_hash` 不变，PR 里附改前改后对照。
- **指纹口径不变，但有一个硬前提**：原图页字节必须与 IA 转出的规范字节逐字节相同（`border_detect.upstream.raw_page` 记 sha）。已用 guji-workspace 内 vol01–10 的 PNG 验证不了 vol11+，所以：
  1. vol11–20 以 **A30 已转好的 PNG 为规范字节**，push 后不再重转；
  2. A30 各线程本地已有的 PNG 与规范字节不一致时，以 R2 为准，**已按旧字节跑出的产物要查 `raw_page` sha，不一致的册该册 Step1 起全过期（L3）**；一致则 L0；
  3. 在 push 前先让 A30 各线程各报一页 sha，确认他们转的是同一份（抽 5 页对）。
- 综合：**代码改动 L0**；**数据搬运的影响取决于第 2 条，须先核对**。

## 六、与 guji-workspace、#443 的关系

- 与 guji-workspace：新册原图**不再进 git**；vol01–10（1,713 张、388 MB）与 bxgb 留在 `data_full/`，`guji source pull` 发现 `data_full/<册>/` 已有且 `files.json` 对得上就跳过。是否把老册也搬到 R2、让仓只剩 `workspace.yaml`，是下一步，**不在本期**。
- 与 #443：同用「包＋manifest＋`files.json`＋main 指针」的格式，`guji source` 与 `guji products pack` 共用一套底层（`push_file`／`fetch_file`／分段），只有键前缀与 `kind` 不同；#443 步 1 的 `files.json` 先落，本方案紧随其后，或同一个 PR 系列。
- 项目规则「git 里只放原图」要改写成「新增册原图放 R2 原图包，老册原图暂留 git」，**改规则要用户点头**，本 PR 不动。

## 七、实现顺序与验收

| # | 内容 | 验收 |
|---|---|---|
| 1 | `datastore/sources.py`＋`guji source pull\|push\|list`（共用 packs 底层）；单元测试用假 Worker | 往返逐文件 sha 一致；篡改一段被拒；已存在 409 |
| 2 | 册 yaml `source:` 块读写与校验 | `db push` 后 `books` 表有块；`pull` 读它 |
| 3 | 实验桶演练：A30 的 vol11 本地 PNG → exp push → 新容器 pull | 核 `files.json`；抽页 sha 与 A30 一致 |
| 4 | 正式桶 push vol11–20（**要用户点头**＋正式令牌） | `source list` 十册均有 main；册 yaml 已登记 |
| 5 | A30 启动脚本改用 `guji source pull`；记下 pull 耗时对比 IA 基线 | 十册各一次，耗时进经验 |

## 八、需要用户定的

1. **前缀**：接受 `pack/source/<ws>/<册>/`（零 Worker 改动，推荐），还是要 A30 说的裸 `source/…`（要改 Worker 并部署）？
2. **包内容**：只存逻辑页 `data_full/<册>/`（推荐），还是连扫描页一并存？
3. **公开读**：原图包是否允许走 `blob.open-guji.com` 公开读（推荐不公开，走令牌）？
4. **正式桶写入**：演练通过后，由谁用正式令牌做 vol11–20 的首次 push（服务器 Ops 还是用户本人）？
5. 同意后改写项目规则「git 里只放原图」的措辞。

## 九、通知（经协调者）

存储位置变化：A21–A24、A30（A30 是需求方，已同意方向）；Ops/Deploy 仅在选了 `/v1/sources` 或需要服务器代推正式桶时。
