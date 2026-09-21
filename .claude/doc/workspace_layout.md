# 工作区目录约定（一本书 = 一个数据仓）

> 2026-09-15 立。**本篇是布局的人读正本**；代码正本是
> `open_guji_cv/core/workspace.py` 顶部的 docstring 与其中的 `*_REL` 常量——
> 改布局要**先改那边、再改这里**，两边不一致时以代码为准。
>
> **2026-09-20 迁仓**：各书工作区已并入 **`guji-workspace`** 一个仓（`open-guji/guji-workspace`），
> 一部书一个目录，目录名 = `<book-index id>-<书名>`，如
> `96mid1ogzk-欽定四庫全書總目武英殿刻本`。`GUJI_WORKSPACE` / `-w` 指到**书目录**那一层，
> 书目录内部结构不变。`products/`、`cache/`、`output/glyph.db` 仍不进 git（见书目录的
> `.gitignore`），换机器要重跑或另行拷贝。控制台 URL 的短 id 由书目录下的
> `workspace.yaml` 的 `id:` 决定——本仓目录名不以 `-workspace` 结尾，不写这个文件
> URL 上就是一整串中文。
>
> 四个工作区（`siku-zongmu` / `beixingrilu` / `yiwenzhi` / `beixing-guben`）已按此对齐；
> 各自当下状态与迁移记账在 overview 仓
> `项目进展/图片初步数字化/进度/总览/08-工作区目录约定.md`。

## 一、一句话

**工作区 = 一本书（或一套书）的数据仓，引擎仓不落任何一本书的数据。**

目录名不是随便起的：`core/workspace.py` 的 `*_REL` 常量按这些相对路径去找库、
产物、语料、裁决；控制台**只认有 `books/*.yaml` 的兄弟目录**，少这一样它根本
不出现在工作区列表里。

## 二、标准布局

| 路径 | 内容 | 进 git？ | 由谁写 |
|---|---|---|---|
| `books/<book>.yaml` | 册配置（版式字段、raw_dir、语料引用） | **是** | 人 |
| `workspace.yaml` | 可选。写 `id:` 覆盖控制台 URL 里的工作区 id（默认 = 目录名去掉 `-workspace`） | 是 | 人 |
| `data_full/<book>_scan/` | **原始扫描页**，永不改写 | 看体积 | `guji import-pdf` |
| `data_full/<book>/` | **逻辑页**（分页后；不分页就等于扫描页）+ `manifest.json` 记来源 | 看体积 | `guji split` |
| `source/` | 原始来源档：PDF、docx、校對本 txt 等**没进管线的东西** | 否（体积） | 人 |
| `corpus/<name>.txt` | 整理本 / 校對本语料（`align_ref` 读） | 是 | 人 |
| `output/glyph_store/` | **本书字形库真源**（PNG + JSONL），不可再生 | **是** | `admit_instance` |
| `output/glyph.db` | 库的 SQLite 索引，可从 store + 共享库重建 | **否** | 引擎 |
| `products/<book>/<step>/` | 数值产物，可重算 | 否 | 引擎 |
| `cache/<book>/<kind>/` | 派生图像 LRU 缓存 | 否 | 引擎 |
| `review/batches/` | 人裁批次登记 | 是 | 控制台 |
| `feedback/{events,consumed}/` | 人裁事件日志与消费记账 | 是 | 控制台 |
| `feedback/verdicts/<shard>/` | 裁决表（导入测试集从这里挑） | 是 | 引擎 |
| `config/crop_exclusions.jsonl` | 图块排除名单 | 是 | 人 |
| `reports/<book>/` | 对账 / 评测报告 | 是 | 脚本 |
| `scripts/` | **只放这本书专用**的一次性脚本；通用的归引擎仓 | 是 | 人 |
| `bench/` | 可选。这本书的评测台（口径正本在 overview，这里只放实现） | 是 | 人 |
| `README.md` `.gitignore` | 必备 | 是 | 人 |

两个最容易放错的：

- **`source/` 不是 `data_full/`**。管线读的原图目录只有 `data_full/`，
  两个名字只差一截，放错了引擎**静默读不到**（yiwenzhi 原来把 PDF 放在 `data/`，
  统一时改名 `source/` 就是这个原因）。
- **`scripts/` 只放本书专用的**。通用打分器、通用导出器写在这里，第二本书就得
  复制一份——那种东西归引擎仓。

## 三、字库与模型存哪（三层）

字形数据按**能不能确定性重建**和**属不属于某一本书**分三层，落三个地方。
这是 `export_store` 跳过 `kind='font'`、`models/` 进 Git 这些既有行为背后的同一条线。

| 层 | 是什么 | 落点 | 进 Git | 判据 |
|---|---|---|---|---|
| **A 通用源料** | 字体档（Jigmo / I.Ming…）、字表、CNN / U-Net 权重 | **引擎仓** `fonts/` `models/` `config/fonts/manifest.json` | 是 | 与书无关，所有书共用；字体档是真源、字形图可由它确定性重生成 |
| **B 共享字形库** | 字体渲染出来的 `kind='font'` 字形；将来若有跨书通用的刻例库也在此 | **引擎仓的 A 层 + 各工作区本地重建**（现状）；见 §3.2 待办 | 图不进（可再生） | 可由 A 层 + 字表确定性重建，几万张 PNG 进 Git 只会撑爆仓库 |
| **C 本书字形** | 这本书的刻例 / 印例，人裁确认过的那些 | **工作区** `output/glyph_store/` | **是** | 不可再生的人工产出；且只属于这一本书 |

三层在 SQLite 索引 `output/glyph.db` 里**汇合**，按 `sources.kind` /
`edition_tag` 分域（`font:iming` / `modern:bxrl` / 刻本 `edition_tag`），
检索时 `GlyphDB.query(editions=[...], kinds=[...])` 可以只挑其中一两个域比对，
命中结果自带 `edition_tag`/`kind`，说明字形出自哪个库。**索引本身永远不是真源**，
`glyph.db` 一律不进 Git，clone 之后重建：

```bash
# C 层：从工作区真源重建
python -m open_guji_cv glyph-db rebuild   # 带 book 的命令用 -w <workspace>（2026-09-20 起必填，见下）
# B 层：从引擎仓字体档重新渲染（四核约 15 分钟）
python -m open_guji_cv glyph-db import-font
```

### 3.1 一本书的字形什么时候「入库」

用户定的次序是**先落工作区、整理完才正式入库**，对应到现有机制：

1. **在工作区里长**：跑管线、播种、人裁，`admit_instance` 往这本书的
   `output/glyph_store/` 写。此时它是 `edition_tag = <本书>` 的一个域，
   只有这本书在用——错了、重跑了、推翻了，代价只在这个工作区内。
2. **整理完**（这本书的字形审过、撤库重放做完、`glyphdb-audit` 体检过）
   才谈得上「升格成跨书可用」。**这一步现在还没有机制**——见下。

### 3.2 待办：B 层还没有「共享刻例库」这个东西

现状是 B 层只有字体渲染字形。**跨书共享的刻例库尚不存在**：`siku-zongmu` 的
16,557 条刻例只在它自己的工作区里，第二本刻本书用不到。要做需要三件事，都还没做：

- 一个**独立的共享库仓**（如 `open-guji-glyphlib`），装升格后的 `glyph_store/`；
- 一条**升格命令**（工作区 store → 共享库，带来源书、审过的证据、不可反悔的记账）；
- `glyph_db_path()` 解析时**挂载多个 store**（现在只挂工作区那一个）。

在这条路修通之前，跨书复用只能靠「把另一本书的 store 手工指过去」，
而 `GUJI_GLYPH_STORE` 只接受一个路径——**别指望它能同时挂两个**。

### 3.3 例外：库在 db 里、没有 store 的书

北行日錄的库是**字体模板 + 播种**长出来的，`patch_png` 直接内嵌在
`output/glyph.db` 里、**没有独立的 `glyph_store/`**——对那本书 db 事实上就是真源，
而它不进 Git。这是一个**已知缺口**：db 可以重跑播种重建（上一次 25 分钟起步），
但**人裁回流的改判不在重建路径里**，丢了就是丢了。处置见 overview 那篇 §四.2。

新书不要走这条路：**播种进库之后就 `glyph-db export` 出 store**，
让真源是文本 + PNG，db 退回成可重建的索引。

## 四、纪律

- **字形库是不可再生的人工产出。** 改判走「撤库 + 重放」，不要直接覆盖——
  `admit_instance` 的幂等闸是防重复入库的，不是改判入口（这个坑咬过三次）。
- **同步真源用 `scripts/snapshot_glyph_store.py --force`**，别直接调
  `glyph-db export`（那条路径会建空库、读到 0 行、把 store 里的 PNG 全当孤儿删掉）。
- **字形与释读分开存**：`shape` 进字形索引，`reading` 进释读列，
  整理本字永远不覆盖 `char`。
- **库路径变了产物就该过期**——`glyph_match` / `seed_admit` 的指纹带库指纹，
  换库等于换了上游。这是对的，不是 bug。
- **`open-guji-dataset`（测试集仓）不在这张图里**：运行时不读不写，
  只放显式导入的标注。人裁先落工作区 `feedback/`，显式导入才进测试集。

## 五、开新书

```bash
mkdir <book>-workspace && cd <book>-workspace
mkdir -p books corpus source data_full output products cache \
         review/batches feedback/{events,consumed,verdicts} config reports scripts
# README.md / .gitignore 照抄 guji-workspace 里已有的书那份，删掉它专有的行
git init
```

然后写 `books/<book>.yaml`（字段见 `core/book.py` 的 `BookSpec`；
现代印刷链的新字段见 `modern_print_pipeline.md` §二），
`guji import-pdf` 把 PDF 抽成 `data_full/<book>_scan/`，
需要分页再 `guji split <book>`。控制台起来后该工作区就会出现在列表里。

### 抽原图的两个坑（`import-pdf` 已内建拦截，但要看它的告警）

1. **页框 pt 数 ≠ 内嵌图像素数**时，按页框渲染会**静默降分辨率**。
   北行日錄刻本那两个 PDF 页框 672×562 pt、内嵌图 2801×2343 px，
   旧实现抽出来只有 1/4.17，字身 71px → 17px。
   现在默认 `--mode embedded`（直接取内嵌像素）；显式 `--mode render` 时若
   渲染结果小 >1.2 倍会告警并算出该用的 `--dpi`。**矢量/文字 PDF 才该用 render。**
2. **JPEG2000 末 tile 残缺 → MuPDF 给一张全白图并且 exit 0**（静默坏页）。
   现在内嵌路径解不开会自动截断末 SOT 补 EOC 抢救，并提示务必目视核对。

抽完**一定要看它的逐页体检**：近乎全白/全黑的页、全目录尺寸不一致都会报出来。
**全白页 exit 0 是最难发现的一类坏数据**——它会一路往下跑，到 Step3 才莫名其妙零列。

### 筒子页（一整版两个半叶）不必先分页

`beixing-guben`（北行日錄知不足齋叢書刻本）实测：**整版直接跑就行**，
Step2 一行没改，19/20 列过闸。因为 `page_column_windows` 把列定义成**相邻两条
`verticals` 之间**，版心两侧的书口栏线在它眼里就是普通界行；上下版框虽名义上
左右半叶各一条，实测两半**几乎共线**（版心处 y 差 0.1~8.9px，远小于
`column_bounds` 已在处理的 14.5px 锚点漂移），一条 `HLine` 够用。

代价是**版心占掉一个列位**（该书 `expected_cols: 20` = 10 + 版心 + 10），
下游必须把它排除在正文之外。**判法只能用位置**（跨版框中点的那一列，8 页全中、
离中点 −8~+5px）；「列内最长空白段」「列内墨占比」两个统计判据**是负结果**——
卷题页/卷末页的短正文列比版心更空，8 页里 3 页认错。

**已落地**（2026-09-15）：刻本链补了列类型概念，照现代链
`products/kinds/line_index.py` 的 `LineRec.kind` 那套——

- 册配置写 `leaf_layout: folio`（见 `BookSpec.leaf_layout`）；
- Step1 `border_detect` 也产 `line_index`，逐列标 `body | margin | edge`
  （判据与两条负结果见 `utils/column_types.py` 的 docstring）；
- Step2 闸新增 **L0c 列级**拒因，把版心/页边拒在正文外，并剔出页级
  period/ref_w 共识。拒因写「版式如此」而不是「列宽偏离」。

一页一个半叶的书（`leaf_layout: single`，默认）只会标出 `edge`，其余全 `body`
——zongmu vol01 实测 9/9 全 body、过闸 9/9、period 114/116 不变。

北行日錄刻本全书 54 页：54/54 页恰好标出 1 个版心，过闸中位 18/20，
页级 period 中位 71.0（版式真值 70.6）。

## CLI 的工作区参数（2026-09-20 起）

凡带 `book` 位置参数的命令（pipeline / step / status / preclean / binarize / split / …）
**必填 `-w/--workspace <仓根>`**，不再读 `GUJI_WORKSPACE` 环境变量兜底：

```
python -m open_guji_cv pipeline keben_body_v2 bxgb --from row_segment --pages all -w "D:/workspace/guji-workspace/988g7gsqhd-北行日錄清乾隆道光間長塘鮑氏刊知不足齋叢書之一"
# 2026-09-20 晚迁入 guji-workspace；路径别手抄：-w "$(python scripts/ws.py path 988g7gsqhd)"
```

不给报参数错；给了先校验 `<仓根>/books/<book>.yaml` 存在，再把解析结果写进 `GUJI_WORKSPACE`
供下游用。环境变量若已设且指向别处，以 `-w` 为准并提示。为什么：环境变量漏设时册定义找
不到（好歹会炸），设错时产物**静默写到别的工作区**——2026-09-19 一天里两次栽在这上面
（一次后台起跑时变量没带上，一次指着上一本书）。控制台的跑批工单本来就记着工作区，
`JobSpec.argv()` 会把它作为 `--workspace` 传给子进程。

不带 book 的命令（console / cache / runs / gold …）和 `scripts/` 下的离线台子仍走
`GUJI_WORKSPACE`。

