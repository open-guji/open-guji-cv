# 古籍图片全流程：源件 → 页图 → 管线与 IIIF（设计稿，A20，2026-10-23）

> 状态：**已定案并实施（2026-10-23）**。用户 10-23 05:34 定：直接写正式桶，其余六条按推荐。实施记录与和设计稿的出入见文末「十一」。
> 起因：A30 要「原图存 R2、子会话一条命令取」（ai-team `domain/CV/规范/子会话启动提速与待命池策略.md` 6.2）；用户 10-23 要求把**网站书影（COS 上的 IIIF）**一并纳入，统一设计下载、存储、拆页、修正和取用。
> 读过的现状：cv `scripts/ia_download_zongmu.py`、`utils/page_split.py`、`utils/preclean.py`、`core/step.py::raw_page`、`core/engine.py::_upstream_sha`；
> kaiyuanguji-web `ops/iiif/siku_zongmu_iiif.py`、`siku-zongmu-splits.json`、`check_cord_vs_splits.py`、`nextjs/src/lib/facsimile.ts`；guji-workspace-data Worker `packs.ts`、`policy.ts`；cv PR #443。

## 一、现状的问题

| 环节 | 现在怎么做 | 问题 |
|---|---|---|
| 管线原图 | vol01–10 在 guji-workspace git `data_full/`；vol11 起每个线程自己从 IA 下 `_tif.zip`、自己转 PNG | 慢、受 IA 限速；各线程转出的字节可能不同，而原图 sha 进 `border_detect` 的上游指纹（`raw_page`），字节一变整册过期 |
| 网站书影 | web 仓 GitHub Action 再从 IA 下一遍 `_tif.zip`，按自己的裁剪框表拆合扫页，切三档 WebP 传 COS `iiif/`（已上线 01–35 册） | 与管线**各下各切**；合扫拆页裁剪框有三份（web `siku-zongmu-splits.json`、cv `doc/formats/samples/guji_page_v0.2/split_table_siku.json`、overview 的 json），靠 `check_cord_vs_splits` 事后对账 |
| 修图 | 合扫页先拆好再放进 `data_full/`，原合扫页挪到 `_source_defects/`；反色带等在 Step0 `preclean` | 「拆好再覆盖」没有记录，换了哪页、从哪来、谁改的查不到；覆盖后旧字节没了，旧产物无法复现 |

## 二、三层模型（一句话：**页图是唯一真源，管线和网站都从它派生**）

```
 L0 源件（原样、永不改）           L1 页图（规范页，唯一真源）              L2 派生
 IA _tif.zip / 网站图片链接  ──build──▶  每页一张无损 PNG + 页表  ──pull──▶  管线 data_full/<册>/0001.png（本机）
        │                         ▲   (R2 按 sha 存，页表进中心库)  ──iiif──▶  COS iiif/<书>/<册>/<页序>/…webp + manifest
        └─ R2 存档                 └─ 拆页/旋转/人工换页 = 页表出新版本（旧字节不删）
```

原则：
1. **源件原样存一份**（用户要求保留原格式），带来源地址与校验和，R2 丢了也能回源。
2. **页图只在一处生成**，管线和网站都读它，不再各自下载、各自拆页。
3. **修正＝页表出新版本**，不物理覆盖：新字节按 sha 新存，旧字节保留，页表记谁、何时、为什么改。「覆盖」体现为页表指向新 sha。
4. **按内容寻址**：页图键就是 sha256，与刻例图同一套 R2 布局、CDN 与本地缓存，天然去重、天然可核。

## 三、ID 与路径

| 东西 | ID | 例 |
|---|---|---|
| 书 | book-index id | `96mid1ogzk` |
| 册 | 两位册号；cv 里的册名照旧 | IIIF `11`，cv `vol11` |
| 源件 | `<来源>:<标识>/<文件名>` | `ia:06061310.cn/06061310.cn_tif.zip`；其它网站 `url:<域名>/<路径>` |
| **页序 seq（全链路唯一页 id）** | **沿用 IIIF 已在用的口径**：源件内叶号补零 4 位，合扫拆页加 a–d | `0003`、`0105a` |
| 管线页号 | cv 照旧用连续整数（`p0105`），页表给出与 seq 的对照 | vol03：ws 页 105–108 ↔ `0105a–d`（现行即如此） |

seq 已经是 cord 的 canvas id（`…/iiif/<书>/canvas/<册>/<seq>`）和网站取图的依据，不改；管线不改页号口径，免得所有册重跑。

| 层 | 存哪 | 键／路径 | 公开？ |
|---|---|---|---|
| L0 源件 | R2 正式桶 `guji-assets` | `pack/source/orig/<书id>/<册>/<源件文件名>`（经 `/v1/packs`，>95 MB 自动分段＋manifest；零 Worker 改动） | 否，读令牌取 |
| L1 页图 | R2 正式桶 | `sha256/<前2位>/<sha>.png`（与刻例图同一套） | 是，`blob.open-guji.com` 按哈希公开（与网站书影同一内容，本就公开） |
| 页表 | 中心库 `files` 表 | `config/pages/<册>.json`（随 `guji db pull/sync`，带 rev、写前比版本） | 同中心库 |
| L2 管线原图 | 本机 | `<工作区>/data_full/<册>/<页号:04d>.png`（从缓存硬链接）＋ `_pages.json` | — |
| L2 网站书影 | 腾讯云 COS | 现有路径不变：`iiif/<书id>/<册>/<seq>/full/<宽>,/0/default.webp`、`iiif/<书id>/<册>/manifest.json` | 是 |

## 四、页表（`guji-pages/1`）

```json
{
  "schema": "guji-pages/1", "book_id": "96mid1ogzk", "ws": "siku-zongmu", "book": "vol11", "vol": "11",
  "rev": "r2", "status": "final",
  "sources": [{"key": "s1", "kind": "ia", "id": "06061310.cn", "file": "06061310.cn_tif.zip",
               "url": "https://archive.org/download/06061310.cn/06061310.cn_tif.zip",
               "source_md5": "…", "sha256": "…", "bytes": 51234567,
               "r2": "pack/source/orig/96mid1ogzk/11/06061310.cn_tif.zip", "fetched_at": "…"}],
  "build": {"tool": "guji source build", "cv": "0.6.x", "pillow": "12.3.0"},
  "pages": [
    {"seq": "0001", "page": 1, "role": "spine", "src": "s1:06061310.cn_0001.tif", "ops": [],
     "sha256": "…", "w": 4198, "h": 5848, "mode": "1"},
    {"seq": "0105a", "page": 105, "src": "s1:06061310.cn_0105.tif",
     "ops": [{"crop": [2096, 0, 2102, 2913]}], "sha256": "…", "w": 2102, "h": 2913, "mode": "1"},
    {"seq": "0140", "page": 143, "src": "s1:06061310.cn_0140.tif",
     "ops": [{"manual": "原图歪斜，人工转正"}], "sha256": "…", "by": "A30", "at": "…"}
  ],
  "history": [{"rev": "r1", "at": "…", "by": "…", "why": "首次生成"},
              {"rev": "r2", "at": "…", "by": "…", "why": "0105 合扫拆四页", "changed": ["0105a", "0105b", "0105c", "0105d"]}]
}
```

- `ops`：`crop`（xywh，原图坐标）、`rotate`（90/180/270）可由 build 从源件**确定性复现**；`manual` 是人工处理后上传的整张图，不能复现，但字节永存 R2，页表记说明与人。
- 三份裁剪框表并成页表的 `ops`，`check_cord_vs_splits` 改为核 cord ↔ 页表。
- 一册一张页表，`rev` 只增；`status: draft|final`。

## 五、流程与命令（cv 新增 `guji source …`）

| # | 做什么 | 命令 | 谁 |
|---|---|---|---|
| 1 | 登记来源（书单里 IA 链接或其它网站图片链接） | `guji source add <册> --ia <id>` 或 `--url …` | 整理线程 |
| 2 | 下载存档：断点续传、核 IA 的 md5、算 sha256、存 L0（已存在跳过） | `guji source fetch <册>` | 有写权限者（见第七节） |
| 3 | 生成页图：解 L0，逐叶确定性编码成 PNG（保留源位深和分辨率），按 `ops` 拆／转，上传 L1，写页表 `r1 draft` | `guji source build <册>` | 同上 |
| 4 | 查与修：自动标宽高比异常页（疑似合扫）出缩略图清单；拆页写 `ops` 后重建（只传变了的页）；人工修的图直接换 | `guji source check <册>`、`guji source replace <册> <seq> <png> --note …` | 整理线程看，写权限者落 |
| 5 | 定稿 | `guji source final <册>` | 人点头 |
| 6 | 管线取图：读页表 → 从 CDN 并发取 → 核 sha → 落 `data_full/<册>/` | `guji source pull <册>` | 任何云会话（读令牌） |
| 7 | 出网站书影：从页表＋页图切三档 WebP 传 COS、生成 manifest；只重切变了的页并清 CDN | web 仓 IIIF 脚本改读页表 | A41（经协调者） |

**云会话快速取图**：页表已随 `guji db pull` 到本机；页图走 `blob.open-guji.com` CDN，不经 Worker、不计 Worker 次数；本机缓存按 sha 去重（`GUJI_DATA_CACHE`），同一线程内续用零下载。一册约 170 页、40–60 MB，16 路并发预计十秒级（待实测，对比 IA 基线）。`data_full/<册>/` 里已有且 sha 对得上的页跳过。

**修正与指纹**：
- 页数和顺序不变、只换某页字节（转正、人工修）：只有那几页 `raw_page` sha 变，引擎只让这几页过期、只重跑这几页。
- 页数变（定稿后才发现合扫要拆）：之后页号整体后移，整册从 Step1 起过期（L3），**要用户点头**。所以第 4 步的合扫检查必须在定稿和跑 Step1 之前做完；`guji pipeline` 遇到 `draft` 页表给警告。
- 修图界线：**给读者看的修正**（拆页、旋转、换页）进页表，网站同步更新；**只为识别的修图**（反色带等）留在 Step0 `preclean`，网站不受影响。

## 六、与现有东西的关系

- **guji-workspace `data_full/`**：vol01–10、bxgb 把现有 PNG **原样登记**成页表 `r1`（不重编码，sha 不变，产物不过期）。登记后 git 里的图可删可留，删要用户点头。新册不再进 git。项目规则「git 里只放原图」改为「原图走页表＋R2」，改规则要用户点头。
- **`ia_download_zongmu.py`** 并入 `guji source fetch`。
- **web 仓 IIIF**：已上线 01–35 册不必重切（来源和裁剪相同、路径与 canvas id 不变）；之后新册、改过的页改从页表出。页表 rev 写进 IIIF manifest 的 metadata，便于对账。
- **PR #443（产物只存 R2 包）**：页图的 sha 已经进产物指纹，产物包 manifest 的 `versions` 加记页表 rev 即可串起「哪版原图 → 哪版产物」。
- **上一版方案（每册一个 tar 包）作废**：逐页按 sha 存，改一页只传一页，和指纹、IIIF 都对齐，取图走现成 CDN 和缓存。

## 七、权限

- 读：页表随中心库读令牌；页图公开 CDN；源件读令牌。
- 写 R2 正式桶：Worker 规定只有正式令牌（`main` 角色）能写，正式令牌只在服务器；云会话的实验令牌只能写实验桶。可选：
  - **A（推荐）**：fetch／build／replace 的正式写入在服务器跑（经 Ops），云会话先在实验桶演练、核对；
  - B：Worker 加一个只能写 `sha256/` 与 `pack/source/` 的新令牌角色，发给整理线程（要改 Worker、经 Deploy，扩权要用户点头）。
- 页表写：随 `guji db sync`，与人裁同一权限。

## 八、影响判级

- 代码只落 `datastore/`、`cli_*.py`，不进任何 Step 的 `code_deps`：17 步 `code_hash` 不变，实现 PR 附对照。
- vol01–10、bxgb 原样登记：**L0**。
- vol11–20：先拿 A30 各线程本地的 PNG 与 `build` 结果逐页比 sha。一致 → L0；不一致而某册已跑过 → 二选一：登记 A30 那份为 `r1`（不重跑），或用 build 那份（干净，但该册 Step1 起过期，**L3**）。
- 网站：路径、canvas id 不变，cord 不受影响。

## 九、实现顺序

| # | 内容 | 验收 |
|---|---|---|
| 1 | 页表格式＋`guji source pull`；拿 vol01–10 现有 PNG 在实验分支／实验桶登记演练 | 新容器 pull 后 `data_full/` 逐字节等于 git 里的图；产物不过期 |
| 2 | `fetch`／`build`／`check`／`replace`／`final` | vol11 build 结果与 IA tif 逐像素一致；拆页 ops 复现 vol03 的四页 |
| 3 | vol11–20 走全流程，正式桶写入（**要用户点头**） | 十册页表 final；A30 线程改用 `guji source pull` 并记耗时 |
| 4 | web 仓 IIIF 改读页表（A41） | 新册书影上线；`check_cord_vs_splits` 改核页表 |
| 5 | 收掉旧裁剪框表、`ia_download_zongmu.py`；guji-workspace 原图去留（要用户点头） | — |

## 十、用户的决定（2026-10-23）

1. 页图按 sha 存正式桶、公开读：**同意**。
2. 页 id 用 IIIF 的页序，管线页号不改：**同意**。
3. 正式桶写入：**直接写正式桶**（出错覆盖即可），不先在实验桶演练；由 A20 用正式令牌执行。
4. 网站书影改读页表：**同意**（A20 出 web PR，A41 接手合并与重出）。
5. 修图界线：**同意**。
6. 已跑过的册字节不一致时保留已跑的：**同意**（实测没有不一致，见下）。

## 十一、实施记录（2026-10-23，A20）

**代码**：`open_guji_cv/datastore/sources.py`、`open_guji_cv/cli_source.py`（`guji source pull|show|list|check|ia|register|replace`），测试 `tests/datastore/test_sources.py`。不进任何 Step 的 `code_deps`，17 步 `code_hash` 不变。

**与设计稿的出入**（实现时改的，理由都是少改别处）：
- **页表放 R2，不放中心库 `files` 表**：`pack/source/pages/<书id>/<册>/r<NNN>.json`，每版一份、只增不改（同名再存 Worker 回 409，即两人同时改时后到的被拒）。原因：Worker 的 `/v1/files` 只开 `feedback/lists/`，写 `config/` 要直连 Postgres；网站的 web 令牌也读不了中心库的 `config/`。放 R2 不改 Worker、不改表，任何令牌都能读。
- **cv 册与书的对应**：`pack/source/by-ws/<工作区>/<册名>.json` 指针（只写一次），`guji source pull vol11 -w <ws>` 靠它找页表。
- **R2 正式桶整桶按键公开**：实测 `blob.open-guji.com/<任意键>` 都能取（包括 `pack/` 下的产物包、源件），只是不能列目录。所以「源件不公开」实际是「按键公开、键不可列」，与产物包现状相同。网站就是靠这一点不要令牌读页表（从 r001 往上探到 404 取最新版）。
- **页图编码**：`Image.convert("RGB")` 后 Pillow 缺省参数存 PNG（不是灰度）。殿本 vol11–20 线上产物用的原图就是这么转的，逐字节核过。

**殿本 vol01–20 已上正式桶**（页表都是 r001，`guji source list 96mid1ogzk`）：

| 册 | 怎么登记 | 核对 |
|---|---|---|
| vol11–20（1,797 页） | `guji source ia`：从 IA `_tif.zip` 生成 | 与各册最新产物包 `_raw_index.json` **逐页逐字节相同**，产物不过期 |
| vol01–10（1,707 页） | `guji source register`：guji-workspace `data_full/` 现有原图原样登记 | 与 IA 逐像素相同；第 1 叶书脊页是缩小存档（957×1359，ops 记 manual）；vol03/04/07/09 合扫拆页按 web 仓裁剪框表裁出，与现有图逐像素相同；与产物包 `_raw_index.json` 逐字节相同，只有册配置 `preclean:` 登记的 10 页不比（产物记的是修好那张的 sha） |

20 个源件（IA `_tif.zip` 原样，`pack/source/orig/96mid1ogzk/<册>/…`）都已存档。

**实测**：新目录 `guji source pull` 取 vol11（110 页、22 MB）2.9 秒，vol20（285 页）6 秒，逐字节对上；落到册配置的 `raw_dir` 也试过。

**网站**：kaiyuanguji-web PR #577 给书影脚本加 `--source pages`（缺省仍是 ia）。vol11 抽 5 叶、vol03 含拆页，两种来源的三档 WebP 与 info.json `diff -r` 完全相同；只有 vol01–10 第 1 叶书脊页会变小，这 10 册已上线，不必重出。

**`guji source check` 的已知误报**：每册第 2 叶是横扫的题签页（宽高比约 1.4），会被报疑似合扫，属正常。

**别的书（2026-10-23 晚，用户「旧项目同样整理、书影都放上去」）**：

| 书 | 页表 | 怎么登记 | 核对 |
|---|---|---|---|
| 北行日錄（`988g7gsqhd`，ws `beixing-guben`，册 `bxgb`） | `988g7gsqhd/01` r001，56 页 | `register --src-file`：guji-workspace `data_full/bxgb_scan` 原样；两份国图 PDF 存 `source/orig/988g7gsqhd/01/` | 取回与原图逐字节相同 |
| 全唐文 v006–v010（ws `qtw-draft`） | `995ejelvk0/06`–`10` r001，520 页 | 原图在已删分支 `raw-snap/qtw-v006-v010-png`（9b5ff87，GitHub 按 sha 还能取），sha1 与其 MANIFEST 全对后原样登记 | 取回 v006、v010 逐字节相同 |

- `register` 加 `--src-file <路径>=<网址>`（可多次）登记非 IA 源件；R2 键只收 ASCII，中文文件名截成 ASCII 部分（`NLC403-…-15647.pdf`），原名记在 `name`。
- **全唐文书 id 借 `995ejelvk0`**（book-index「欽定全唐文清嘉慶二十一年揚州刻本內府本」，条目里的扫描是国图本）：CADAL 清華本在 book-index 没有单独条目，按「Book＝版本」同版归这条，册号用 CADAL 件号（第 6 件＝`06`）。日后若要登记同版国图本，得另立 book-index 条目，免得册号撞。
- **全唐文源件 DjVu 没存 R2**：Commons 对会话出口限流（API 与 upload 都 429），页表 `sources` 只记了文件名与链接；换个出口下到 `CADAL0102280N.djvu` 后 `register` 出 r002 补上。
- **书影**：kaiyuanguji-web PR #577 加 `ops/iiif/pages_iiif.py`（别的书只有本站图源），书名、卷次登记在 `ops/iiif/pages-books.json`，workflow `iiif-siku-zongmu.yml` 加 `book` 输入。北行日錄、全唐文五件已上 COS（`iiif/988g7gsqhd/01/`、`iiif/995ejelvk0/06–10/`）。
- **旧原图**：用户同意删。guji-workspace PR #42 删 main 上的 1,763 张（删前逐张核 sha 全在 R2）；`data/zongmu-vol11|16-17|20-raw-scans` 三分支 741 张也核过全在 R2，待删分支。

**还没做的**：
- 全唐文 DjVu 源件补存（见上）。
- 项目规则「git 里只放原图」的改写。
- `scripts/ia_download_zongmu.py` 与 web 仓裁剪框表暂留，新册不再用；等 vol21 起全走页表后再删。
