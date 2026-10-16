# guji-page v0.2：每字带坐标的页面文本格式

> F1 道（任务卡 open-guji-core/overview#357）定 v0/v0.1，F2 道（#381）升 v0.2，2026-10-02。CV 总管派活，文本总管共同验收。
> 在《自校文本格式草案 v1.1》（overview `项目进展/古籍文本/整体设计/2026-09-自校文本格式草案.md`，
> 下称**草案**）的基础上定稿；草案 §八 CV 审定的三条全部照办。
> **状态：v0.2（2026-10-02）**——在 v0.1 上落实用户 10-02 对 #361 的三条裁定（阙文 3、未收字 7、记录先行 10），
> 变更见下方「v0.2 相对 v0.1」；规范层（norm）的方案调研另见 [`norm_layer_proposal.md`](norm_layer_proposal.md)，v0.2 的 `norm` 暂按 v0.1 不动。
> v0、v0.1 规范 `guji_page_v0.md`、`guji_page_v0.1.md` 留档；**v0、v0.1 文件照样能读**（`check()`、导出器都认，`upgrade()` 一路升到 0.2，
> 升级前后导出的 guji-markdown 逐字相同）。
>
> | 产物 | 位置 |
> |---|---|
> | JSON Schema | `formats/guji_page_v0.2.schema.json`（v0、v0.1 的 schema 保留）；册级索引 `formats/guji_layout_index_v0.1.schema.json`（不变） |
> | 格式工具（检查、坐标换算、canvas、稳定 ID、md / IIIF 注释与 canvas 导出、去 ext、升级、册级索引） | `open_guji_cv/formats/guji_page.py` |
> | CV 产物 → 本格式 | `open_guji_cv/formats/guji_page_cv.py`、`scripts/export_guji_page.py` |
> | 校验图 | `scripts/render_guji_page_overlay.py` |
> | 样张（四庫 vol03 p3、p107）＋校验图 | `doc/formats/samples/guji_page_v0.2/`（v0、v0.1 样张留在原目录） |
> | yolo_tool 互转（yolo_tool 仓不改，其格式并入本设计） | `open_guji_cv/formats/guji_page_yolo.py`（只用标准库）、`tests/test_guji_page_yolo.py` |
> | 测试 | `tests/test_guji_page_format.py`（10 条）、`tests/test_guji_page_v01.py`（13 条，改用造出的 v0.1 页）、`tests/test_guji_page_v02.py`（15 条）、`tests/test_guji_page_yolo.py`（6 条），全部自造数据 |
> | yolo_tool 的 YOLO 切分算法评估 | `doc/research/yolo_tool_segmentation_review.md` |

## 〇、一句话

**一页一个 JSON。** 文本流 `text` 是真源（原样层，字元数组）；版面按「区 → 列 → 段（正文 / 夹注右 / 夹注左 / 单行小注）」
分层，段引用文本区间、首尾相接铺满全页文本，所以阅读顺序是显式的；字框 `glyphs` 落在**IIIF canvas 的整数像素、左上原点
`[x,y,w,h]`**（canvas = IA 原叶；合扫页拆开的每块各一个 canvas），同样只引用文本区间，一框多字、一字多框都只是区间的事；
阙文在文本里是可见的「□」、页上 `lacuna` 稀疏标出；未收字 `text` 放近似字、`zi` 记原形；每个字框带各路候选字 `cand` 与放行通道 `channel`；
`canvas` 块记 canvas id、页序、尺寸，拆块页另记原叶与裁剪框（`source.selector`）；`image` 块记 CV 跑批那张图的 sha256 与
它在原叶上的区域——两者对不上时导出器已把几何搬到 canvas 上。缩放档按比例换算，不另存坐标。

## v0.2 相对 v0.1（用户 10-02 裁定，CV 总管记录于 #361 最新一条）

| # | 改了什么 | 依据 |
|---|---|---|
| 1 | **阙文**：`text` 里放可见字符「□」（U+25A1），页上稀疏记 `lacuna: [下标…]`（升序不重复）标出「这个□是阙文」；不带标记的「□」是底本真刻的□或来源站点的□，照录。`text` **不再出现空串**。导出 guji-markdown：带标记的出 `[[]]`（每位一个，不合并），不带的出「□」；有 `guess` 的真□仍出 `□{guess=X}`。**不用全角空格**——它留给空格、抬头这类版式空位 | 用户 #361·3：「能否用全角空格或方框字符」→ 用□ + 稀疏标记，真□与阙文仍分得开 |
| 2 | **Unicode 未收字分两层**：`text[i]` 放**近似的已收字**；`zi: [{"i", "ids"｜"desc", "rel"}]` 记原形（方位确定写 IDS，拿不准写描述文字，二选一）与 `rel`（近似字与原形的关系：异体／形近／部件近）。还没有近似字时 `text[i]` 放「〓」（U+3013）、`rel: null`。导出 md 仍写 `:zi[IDS或描述]`（guji-markdown §16）；网站按模式选显示哪一层 | 用户 #361·7：「第一层放近似的 Unicode 已收字，第二层放 IDS」 |
| 3 | **记录先行**：字框新增 `channel`（CV `seed_admit` 的放行通道，未放行为 null）与 `cand: {lib, ocr, rare, ref}`（库首位 / OCR 首位 / 5-b 首位 / 整理本字，有哪路记哪路）。两者不属 `ext`，入库 `strip_ext` 后仍在 | 用户 #361·10：「先确保信息记录完整，显示方式灵活，可能有阅读模式、校对模式」 |
| 4 | IIIF 注释：框里有阙文时加 `kyg:lacuna: true`（body 照 `text`，v0.2 是「□」） | 随 1 |
| 5 | 版本号 `guji-page/0.2`；v0、v0.1 照样 `check()`/导出，`upgrade()` 一路升：空串 → 「□」+ `lacuna`；v0.1 组字的 IDS/描述从 `text` 挪进 `zi[].ids/desc`、`text` 放「〓」；`channel` 从 `ext.cv.channel` 补；`cand` 旧页没有就不编。升级前后 md 逐字相同（测试钉住） | CV 总管 |
| 6 | yolo 互转：yolo 的空串字元 = 阙文 → 「□」+ `lacuna`，回写时还原空串，往返仍逐字节一致 | 随 1 |

`norm`（规范层）v0.2 **不动**：用户要求「再仔细研究，提供方案」，调研与推荐见 `norm_layer_proposal.md`，定了再进 v0.3。

## v0.1 相对 v0

| # | 改了什么 | 依据 |
|---|---|---|
| 1 | **坐标空间从「本页图」改为「IIIF canvas」**。新增必有的 `canvas` 块：`id`、`seq`、`width`、`height`，拆块页加 `source`（原叶 id、原叶尺寸、`FragmentSelector` `xywh=` 裁剪框）。普通页 canvas = 整张原叶 = 本页图，坐标不变；CV 跑批的图与 canvas 不是同一块时（vol03 p107），导出器经原叶把全部几何搬到 canvas 上并记 `warnings` | 网站总管 #357：canvas 尺寸与坐标空间取原图像素；拆块各一个 canvas、原点在裁剪区左上角 |
| 2 | **canvas id**：`https://data.kaiyuanguji.com/iiif/<bookId>/canvas/<册2位>/<页序>`，页序 = IA leaf 号补零 4 位 + 拆块后缀 a–d（阅读顺序：右上、左上、右下、左下）。工作区页号 → 页序按整理总管的裁剪框表（`73d3b4be`）换算，`seq_for_ws_page()` | 网站总管 #357 两条评论；整理总管裁剪框表 |
| 3 | **IIIF 导出**：注释 target = `<canvas id>#xywh=`；新增 `to_iiif_canvas()` 出 canvas 骨架，拆块页带 `source.selector` | 同上 |
| 4 | **阙文**：`""` 只用于不知道原字的位；底本刻的「□」、来源站点（维基、Kanripo）的「□」都是真字照录；导出每个 `""` 一个 `[[]]`，不合并 | 文本总管 #361·3 |
| 5 | **`norm`** 只记异体→通行字，`why` 必填且只许「异体」；校勘改字（讹脱衍倒）不进 `norm`，从外部用稳定 `id` 挂 | 文本总管 #361·4 |
| 6 | **组字 `zi`**：页上稀疏记 `[{"i": 下标, "form": "ids"|"desc"}]`，`text[i]` 放 IDS 串或描述文字，导出 `:zi[…]`；方位拿不准用描述；来源站点的组字式（`[口*恒]`、`{宀兒}`、`[B18D]`）与 HT/KT 原样留在 `text`、不标 `zi`、不转 IDS | 文本总管 #361·7 |
| 7 | **册级索引** `layout/index.json`（`guji-layout-index/0.1`）：先定「页 → book-text 版本与章 NNN」映射字段 `pages[].chapters`，其余等第一批入库 | 文本总管 #361·5 |
| 8 | **去 ext**：`strip_ext()`；去掉后导出的 guji-markdown 与 IIIF 注释不变（测试钉住） | 文本总管 #361·6 |
| 9 | 版本号 `guji-page/0.1`；v0 文件 `check()`/导出照常，`upgrade()`/`read_page()` 升级 | CV 总管 |

---

## 一、与草案 v1.1 的关系（逐条）

| 草案条目 | v0 | 为什么 |
|---|---|---|
| 层级 书→册→页→版框→列→格→字（§一） | **改**：书→册→页→**区**→列→**段**→字框。版框几何并入「区」（`regions[].box`、`rules` 界行折线）；「格」不再是一层，`slot` 留作字框属性 | 版心、天头批注不在版框里，要有「区」才放得下；「格」是 CV 切分的中间量，yolo 没有格、只有框，强行一层会让 yolo 数据造假格。夹注左右要成为列下一级（大总管点名「没有列这一级」），用「段」表达 |
| 坐标 统一 `raw_page_px@top-right`（§一） | **改**：左上原点整数 `[x,y,w,h]`，图像 = 本页图（§二） | 网站/IIIF/W3C 注释、yolo、OpenCV 全是左上原点；右上原点是 CV 内部规范（`core/anchor.py`），**导出时换一次**（`tr_bbox_to_xywh`），格式里不出现。草案担心的「拿列坐标充页坐标」照旧禁止 |
| `bbox` 优先 `bbox_page` 退 `quad_page`，都缺记 null（§二，§七·2） | **照用**：`box` 取 Step4 `bbox_page`，缺则退 Step3 `quad_page` 外接框并记 `box_from: "cell_quad"`，都缺 `box: null` | 草案推荐「允许都缺、如实记」，CV 无异议 |
| `bbox_source` 三值 | 并进 `box_from`（缺省 = 字框本身）＋ `by.box`（哪个来历） | 两件事分开：几何从哪一层来 vs 哪个工具出的 |
| 字段 `id = book:page:col:slot[sub]`（§二） | **改**：`id` 是不透明稳定 ID；CV 主键另存 `cv_id` | CV 主键随重切变（§八·2「页面重切后字位 id 会变」），网站深链、校勘挂点要一个不变的 ID，见 §六 |
| `glyph_id` 与 `id` 同构（§二，§八·2） | **照 §八·2**：保留两个字段，代码不假设相等；CV 导出时**不知道就记 null**，不拿字位 id 冒充 | §八·2 原话「格式同构、值不保证相等」 |
| 书级 `edition`（§八·2 新增） | **照用**：`book.edition` | 字形库跨书键 = `edition` + `glyph_id` |
| `char` 照录字形、null = 阙文 | **改**：字形放 `text` 流，阙文 = 空串 `""`；`char` 字段取消 | 文本与坐标分开（大总管要求）；空串比 null 在字元数组里好处理 |
| 没有规范层 | **新增**：`norm`，稀疏记「与原样层不同的位」 | 网站要通行字检索、异体字展示（§四） |
| `order` 列内读序 | **改**：读序 = `text` 的顺序，不另存序号 | 序号与文本两处存必漂；`text` 本身就是按 CV `sort_by_reading` 排好的 |
| `kind`（char/blank/jiazhu_a/b/solo/punct） | 拆开：夹注 a/b/单行 → 段的 `lane`（`jz_r`/`jz_l`/`solo`）；`blank` → `marks` | blank 不是字，不该进文本流 |
| `channel` + `human_reviewed` 分开记、不合成置信数（§二） | **照用并扩展**：`method`（human / `cv:<通道>` / cv:occluded_default / cv:pending / ocr / yolo / yolo:human）、`review`（pending/auto/human/disputed）、`conf`（只在真有概率时填，CV 一律 null）、`by`（来历表键）、`ext.cv`（原样留 channel/doubts/cov） | CV 现状「有来源、没有概率式置信度」，照实转发 |
| `excluded`/`defect`/`unreadable`/`guess`（§二三分表） | **照用**：排除·非字 → `marks` kind `excluded`，不进文本；切坏/残 → 字框 `lacuna: "defect"`，字照占位；阙文 → `lacuna: "unreadable"` + 空串；`guess` 照留 | 三种「没有字」必须分开（草案、`report/slots.py` 的教训） |
| 抬头 `n_raised`、挪抬 `lead_blank`（§三） | **照用**：列上的 `raised`、`lead_blank` | 离散量，直接读 |
| 版心 `col_kind`（§三） | 升为区：`regions[].kind = "banxin"`；列 `kind` 照留 CV `line_index` 的 body/margin/edge | 版心有自己的文字（书名、卷次、页码），放区里才能挂列与字 |
| 界行（§三） | **简化**：`rules` 只存折线点列（左上原点整数） | 网站与 luatex-cn 要的是「线在哪」，不是 CV 的拟合参数 |
| 印章（§七·4「不预留」） | **改**：`marks` kind `seal`，`occludes` 列出压到的字框 | 用户这次点名要「印章遮挡」样例；印章框 CV 仍无产物，样张里是人工目测框，`by: "manual"` |
| `variant_note` 只留字段位（§七·5） | 不设。校勘挂点用稳定 `id` 从外部引用 | 字段位放了也没人填；稳定 ID 才是挂点 |
| 落点 `Book/…/layout/pNNNN.json` + `index.json`（§五） | **照用**，文件名 `pNNNN.guji-page.json`；`index.json` 待定（§12·5） | 文本总管 09-26 已定 `layout/` |
| 只对刻本竖排链启用（§八·1） | **照用** | 现代链 `to_original()` 未做 |

---

## 二、坐标

### 2.1 口径

- **空间**：**IIIF canvas** 的像素（`canvas` 块，§2.4）；**左上原点**，x 向右、y 向下。canvas = IA 原叶（原扫像素），
  拆块页 canvas = 裁剪框、原点在裁剪框左上角。三档 WebP 只是这个 canvas 上的不同图片资源，坐标不绑任何一档。
- **框**：`[x, y, w, h]` 整数，与 IIIF `#xywh=x,y,w,h` 同序同义。CV 浮点框换整数时**向外取整**（左上 floor、右下 ceil），
  宁多包一点墨也不裁笔画。可选 `quad`（四角整数点）留给斜格。
- **CV 换算**：`x_tl = (W-1) - x_tr`（`core/anchor.py` 的像素中心约定），`tr_bbox_to_xywh()` 一处实现。
  **不要**拿 `bbox_page` 当左上原点用（chars.py 模块头的「鳳」字教训）。
- **派生图不存坐标**：缩放档（IIIF `300,` / `1200,` / `max`）按比例换算，`scaled_image()` + `map_box()`。

### 2.2 `image` 块：本页图是什么、从哪来

```jsonc
"image": {
  "width": 2230, "height": 3100,
  "sha256": "1822ea8f…",                  // 坐标测量时那张图（CV 跑批的 raw_page，取自 _manifest.jsonl upstream）
  "path": "data_full/zongmu/vol03/107.png", // 参考，不作身份
  "source": {"kind": "ia", "item": "06061302.cn", "leaf": 105, "width": 4198, "height": 5848, "sha256": "4a65a5fa…"},
  "region": [1945, 2743, 2230, 3100],     // 本图在 source 上的裁切区域；缺省 = 整张
  "edits": [{"op": "whiten", "note": "…"}] // 裁切之外动过的像素，只说明、不影响坐标
}
```

- `sha256` 是**坐标的身份证**：图一换（重扫、重裁、抹白），旧坐标就不能直接用。CV 导出取产物 manifest 里记的那张，
  不取工作区现在的文件——两者可以不同（见 2.3 实例）。
- 合扫页拆分（vol03/04/07/09）：`source` + `region` 表达「CV 跑批那张图 = 某原叶的某个裁切区域」。它若与 canvas 的裁剪框
  不同（**同一原叶的另一版裁法**），导出器经原叶把几何换到 canvas 上（`remap_geometry`），不必重跑 CV；
  整块落到 canvas 外的字框 `box` 置 null 并记进 `warnings`。
- yolo_tool 的 PDF 渲染图没有文件：`sha256: null`，`render: {"from":"pdf","zoom":2,"pdf_sha256":…}`，`source` 记扫描原图宽高，
  换算回原图同样走 `map_box`（region 缺省 = 整张 → 纯缩放）。

### 2.3 实例：vol03 p107 的图已经换过一次

CV 快照 `snap/96mid1ogzk/vol03/20260928T1708-full` 的 p107 产物建在 sha `1822ea8f…`、2230×3100 的图上；工作区现行
`107.png` 是 sha `fbdc696a…`、2074×2931——09-27 21:25Z 整理总管修了裁法（`cap_top`）之后重裁的。两张都是 IA leaf105
（4198×5848 双联叶）的右下块：模板匹配得旧图 region `[1945,2743,2230,3100]`、新图 `[2101,2913,2074,2931]`（均逐像素一致）。
**按产物记的 sha 去对现行文件会对不上；按 region 经原叶换算则全对**（校验图 §十一）。这正是本格式要记 sha + region 的理由，
也说明 vol03 p105–108 的 CV 产物相对现行图是过期的（尺寸都变了），该从 Step1 重跑——已写进交单。

### 2.4 `canvas` 块与 IIIF 约定（v0.1）

```jsonc
"canvas": {
  "id": "https://data.kaiyuanguji.com/iiif/96mid1ogzk/canvas/03/0105c",
  "seq": "0105c",                        // IA leaf 4 位 + 拆块后缀 a–d；普通页无后缀，如 "0003"
  "width": 2074, "height": 2931,         // 普通页 = 原叶尺寸；拆块页 = 裁剪框尺寸
  "source": {                            // 只拆块页有
    "id": "https://iiif.archive.org/image/iiif/3/06061302.cn%2F06061302.cn_tif.zip%2F06061302.cn_tif%2F06061302.cn_0105.tif",
    "width": 4198, "height": 5848,
    "selector": {"type": "FragmentSelector", "value": "xywh=2101,2913,2074,2931"}
  }
}
```

- **页序**：工作区页号 n、拆点 P（裁剪框表里该册最小的 ws 页号）：n < P → n；P ≤ n ≤ P+3 → 表里那一块（`0105a`–`0105d`）；
  n > P+3 → n−3。只有 vol03/04/07/09 受影响，其余各册 ws 页号 = IA leaf 号。人裁事件、products 的字位 key 仍是 ws 页号
  （`cv_id`、`page.index`、`page_id` 照旧），canvas 只在 `canvas` 块与 IIIF 导出里出现。
- **`image.region` ⇔ `canvas.source.selector`（一一对应）**：两者都是「原叶上的 xywh」。
  - CV 跑批的图就是这一块（拆页修好后重跑的正常情况）：`image.region` = selector 的 xywh，`image` 宽高 = canvas 宽高，坐标原样；
    导出器在 `image.region` 缺省时自动补成 selector。
  - CV 跑批的图是同一原叶的另一块（vol03 p107：产物建在 09-27 首版裁法 `1945,2743,2230,3100` 上，canvas 是 09-29 重切的
    `2101,2913,2074,2931`）：坐标 = 原叶坐标 − selector 的 (x, y)，即 canvas 坐标 = 跑批图坐标 + (region.x − selector.x,
    region.y − selector.y)，导出器已做完并记 warning。
  - 普通页没有 selector、`image.region` 也缺省：canvas = 原叶 = 本页图。
  - 换回原叶像素：canvas 坐标 + selector 的 (x, y)（`map_box(box, coord_frame(page), {原叶宽高})`）。
- **`canvas.source.id`** 缺省写 IA 的 IIIF 图像地址（R12 实测可用的写法）；网站若改用自己的原图 id，只改这一处。
- 网站侧的 manifest、图片资源由网站按图源（COS/R2/Commons/IA）另挂；本格式只保证 canvas id、尺寸、selector 与坐标一致。

---

## 三、文件结构

```jsonc
{
  "schema": "guji-page/0.2",
  "page_id": "96mid1ogzk/3/107",       // <bookId>/<册>/<页>，与影像路径 images/{bookId}/{volume}/{page} 同构
  "book":   {"id": "96mid1ogzk", "edition": "siku-zongmu", "title": "…"},
  "volume": {"index": 3, "cv_book": "vol03", "label": "…", "juan_range": "4-5"},
  "page":   {"index": 107, "label": null, "page_type": "body"},
  "image":  { … §2.2 … },
  "canvas": { … §2.4 … },
  "producers": {"cv": {"tool": "open-guji-cv", "rev": "1332c01734", "pipeline": "keben_body_v2",
                       "steps": {…}, "products_sha": {…}, "snapshot": "…"},
                "manual": {"tool": "manual", "who": "…"}},
  "text":    ["旋", "爲", "□", …],      // §四：阙文位是可见的「□」
  "lacuna":  [2],                       // v0.2：哪些「□」是阙文（其余「□」是真刻的□）
  "norm":    [{"i": 12, "t": "内", "why": "异体"}],
  "zi":      [{"i": 40, "ids": "⿰句員", "rel": "部件近"}],  // text[40] = "員"（近似的已收字）
  "regions": [ {"id": "r1", "kind": "body", "box": [...], "rules": [[[x,y],…],…],
                "columns": [ {"id": "c4", "n": 4, "kind": "body", "box": [...], "raised": 1, "lead_blank": 0,
                              "runs": [{"lane": "main", "text": [16, 22]},
                                       {"lane": "jz_r", "text": [22, 26]},
                                       {"lane": "jz_l", "text": [26, 29]}]} ]} ],
  "glyphs":  [ … §五 … ],
  "marks":   [ … §七 … ],
  "warnings": ["…"],                   // 可缺：导出时发现的问题（如 Step3/Step7 对不上）
  "ext": {}                            // 工具私有，格式不解释
}
```

### 3.1 CV 自己不知道、要调用方给的（`--meta`）

Book ID、IIIF 册号、IA item（`volume.ia_item`）、`page.label`（书上叶次）、`page_type`、IA 原叶号、CV 跑批那张图的 region、
人工标的印章/版心框。canvas 由 `--split-table`（整理总管裁剪框表）按工作区页号推出，也可在 `meta.canvas` 里显式给。
格式见 `samples/guji_page_v0.1/meta.json`。**册号 `volume.index` 取 IIIF 路径那一级**（四庫 vol03 → 3），`cv_book` 只作对照。

---

## 四、文本：原样层与规范层

- `text`：**原样层**，阅读顺序的字元数组。一个元素 = 一个字元：通常一个码位；也可以是带异体选择符的序列、PUA、
  来源站点的组字式。**下标按元素数，不按 UTF-16 / 码位数**——生僻字大量在 Ext-B 以后，JS 的 `string.length` 会数错，
  字元数组从结构上绕开这个坑。v0.2 起**元素不得为空串**。
- **阙文（v0.2）= `text` 里的「□」（U+25A1）+ 页上 `lacuna` 标记。** `lacuna` 是阙文位下标的升序数组，只用于不知道原字的位。
  不带标记的「□」是真字：底本上刻着的「□」（原刻残的配字框上可带 `guess`）、book-text 里维基/Kanripo 来的「□」
  （SKchar、补字码查不到的来源站点占位）都照录「□」、不标 `lacuna`。
  - 为什么不直接只用「□」：真刻的□与阙文都长「□」，不标就分不开（文本总管 #361·3 关心的就是这一点）。
  - 为什么不用全角空格（U+3000）：它留给空格、抬头这类版式空位，混用会分不清。
  - 导出 guji-markdown 时**每个阙文位出一个 `[[]]`**（guji-markdown §13），不合并成 `[[凡三字]]`，每个阙文位仍各自对得上字框；
    不带标记的「□」出「□」，带 `guess` 的出 `□{guess=X}`（§14）。
  - 字框上的 `lacuna: "unreadable"` 与页上 `lacuna` 必须一致（检查规则 §八·8）；`lacuna: "defect"`（字在、图块切坏）的字若认出了，
    `text` 放那个字、不进页上 `lacuna`。
- **Unicode 未收字（v0.2）分两层**：
  - `text[i]` 放**近似的已收字**——阅读、检索、繁简转换都只碰这一层，不用认 IDS；
  - 页上稀疏记 `zi: [{"i": i, "ids": "⿰句員", "rel": "部件近"}]`：`ids`（方位确定，guji-markdown §16）与 `desc`（方位拿不准的描述文字，
    如 `左句右員`，不要猜）**二选一**；`rel` 是近似字与原形的关系，只许 **异体**（同字异形，如刻本俗写）、**形近**（不同字，只是长得像）、
    **部件近**（共享主要部件，如取声旁）；
  - 还没有近似字（v0.1 升上来的组字、实在找不到）时 `text[i]` 放「〓」（U+3013 GETA MARK）、`rel: null`；
  - 导出 md 写 `:zi[ids 或 desc]`；网站阅读模式可显示近似字（`rel=异体` 时最安全）或合成字形，校对模式显示原形与关系——显示哪层由网站定；
  - 标记放页上不放字框上——从整理本补进来的字没有字框。来源站点原有的组字式（`[口*恒]`、`{宀兒}`、`[B18D]`）与医书 HT/KT
    **原样保留**在 `text`，不标 `zi`、不转 IDS。
- **字形照录**：CV 2026-09-26 起全流程只存字形（`seed_admit` 的 `char`），原样层就是它。
- `norm`：**规范层**，v0.2 照 v0.1：只记**异体字 → 通行字**且与原样层不同的位 `{"i": 下标, "t": 通行字, "by": 来历键, "why": "异体"}`；
  `why` 必填，只许「异体」。**校勘改字（讹、脱、衍、倒）不进 `norm`**。CV 不产规范层，样张里为空。导出器 `layer="norm"` 时用它覆盖。
  怎么填、通行字以什么为准、一字多义怎么办、校勘层挂在哪，见 [`norm_layer_proposal.md`](norm_layer_proposal.md)（F2 调研，待拍板）。

## 五、字框 `glyphs`

| 字段 | 必有 | 含义 |
|---|---|---|
| `id` | ✓ | 稳定 ID（§六），不透明字符串 |
| `text` | ✓ | `[start, end)`，引用 `text`。长度 1 = 一框一字；>1 = 一框多字（合文、yolo 连框）；几个框引同一区间 = 一字多框（切坏）；空区间 = 框还没对上字 |
| `box` | ✓ | `[x,y,w,h]` 或 null |
| `quad` | | 四角点（斜格用，v0 导出器未填） |
| `box_from` | | box 不是字框本身时注明，如 `cell_quad` |
| `col`、`lane`、`slot` | | 所在列 id、段类别、CV 格号（便于回查） |
| `cv_id` | | CV 字位主键 `book:page:col:slot[a|b]`，随重切变 |
| `glyph_id` | | 字形库刻例 id；不知道就 null |
| `by` | | `{"box": 来历键, "text": 来历键}`，引 `producers` |
| `channel` | | v0.2：放行通道，CV `seed_admit` 的 `channel` 原样（`human` / `match_ref` / `match_solo` / `context` / `iron` …）；未放行 null。与 `method` 的差别：`method` 是归一过的「怎么定的字」，`channel` 是原始通道名，校对模式按它分组 |
| `cand` | | v0.2：候选字，各路证据的**首位**：`lib`（Step5-a 库匹配：same 档取认定字，否则候选首位）、`ocr`（Step5-c OCR topk 首位）、`rare`（Step5-b 生僻字候选首位）、`ref`（Step5-d 整理本：过闸对齐的字，没有则坐标对位的字，整理本是空格不算）。缺哪步的产物就没有那个键；全缺则不写 `cand`。分数留在 `ext.cv`，不进这里（`conf` 只给真概率） |
| `method` | | 定字方式：`human`、`cv:<通道>`（match_ref / match_solo / context / iron …）、`cv:occluded_default`（印章压字，取整理本坐标对位的默认字）、`cv:pending`（未放行）、`ocr`、`yolo`、`yolo:human`、`manual` |
| `review` | ✓ | `pending`（没人看过）/ `auto`（过了自动放行闸）/ `human`（人裁过）/ `disputed` |
| `conf` | | **只在有真概率时填**（OCR 分数）；CV 一律 null |
| `lacuna` | | `unreadable`（阙文）/ `defect`（字在、图块切坏或原刻残） |
| `guess` | | 阙文/残字「最像哪个字」 |
| `flags` | | 如 `occluded`（被印章/污损压住）、`orphan`（yolo 孤框） |
| `prev` | | 重切未承接时压到的旧 ID |
| `ext` | | 工具私有：`ext.cv`（channel/doubts/cov）、`ext.yolo`（原数组，保证往返逐字节一致） |

CV 导出的取字规则**不另写**，直接用 `report/slots.page_slots`（Step9 9.1 排版、9.3 对勘共用的那一份）：未放行位
`char` 一律不进文本（进 `guess`），印章压字照出整理本默认字，`ref_blank` 的印章假格当非字。

---

## 六、稳定 ID 与重切

- **生成**：`mint_id("g", page_id, cv_id, row_segment 产物 sha)` 取 sha1 的 base32 前 10 位，加前缀 `g`（标记 `m`）。
  同一份产物恒得同一 ID（可重导出），且**字面不含列号格号**，免得被当成位置用。
- **重切后承接**（`carry_ids(old, new)`）：与 CV `feedback/bindings.py` 同一组门槛——同一张图（`image.sha256` 相同）上
  IoU ≥ 0.85 视为同一块像素、必是同一个字，沿用旧 ID；0.6–0.85 且双方一对一也沿用；切开、合并、部分重合给新 ID，
  `prev` 记下压到的旧 ID，留给人裁/校勘挂点去搬家。图换了：v0.1 若是同一 canvas、两边 `image.region` 都已知（重裁），
  坐标本来就都在 canvas 上，照常承接；重扫或裁剪区不明一律不承接（待定 #9）。
- 外部引用（网站深链、校勘、人裁）**一律引 `id`**，不引 `cv_id` 或下标。

---

## 七、非字元素 `marks`

| kind | 来源 | 说明 |
|---|---|---|
| `blank` | CV Step3 `kind=blank` | 版式留白格（行首挪抬、列末空格）；行首几格同时折进列的 `lead_blank` |
| `excluded` | CV 排除名单·非字 | 墨污、切坏图块；`cv_id` 留着回查 |
| `seal` | 人工（CV 无产物） | `occludes` = 与印章框相交的字框 id；`text` 可记印文 |
| `banxin` / `fishtail` / `page_number` | 人工或 yolo（midText / ear） | 版心整块走「区」，单个鱼尾、页码走 mark |
| `head_raise` / `stain` / `other` | 预留 | |

抬头不是 mark，是列的 `raised`（级数）；挪抬是列的 `lead_blank`。

---

## 八、检查规则（Schema 之外，`guji_page.check()`）

1. 所有列的 `runs` 按出现顺序首尾相接，恰好铺满 `[0, len(text))`——**每个字元恰属一段，读序因此是全序**。
2. 字框区间在 `[0, len(text)]` 内；非空区间的字都在字框所称的列与段里。
3. 字框不出图。
4. 区、列、字框、标记的 `id` 全页唯一。
5. `norm[].i` 不越界；v0.1：`norm[].why` 只许「异体」。
6. v0.1：有 `canvas`；`seq` 是 4 位 + 可选 a–z；`id` 以 `/canvas/<册2位>/<seq>` 结尾；拆块页 canvas 宽高 = selector 的 w、h。
7. v0.1：`zi[].i` 不越界、不重复、不指向阙文位，`form` 只许 ids / desc。
8. v0.2：`text` 无空串；`lacuna` 升序不重复、不越界、所指的 `text` 都是「□」；`lacuna: "unreadable"` 的单字字框其字必在 `lacuna` 里。
9. v0.2：`zi[]` 有且只有 `ids`、`desc` 之一且非空；`rel` ∈ 异体／形近／部件近（`text[i]` 为「〓」时 `rel` 必须为 null）；不指向阙文位；
   `text[i]` 必须是近似字，不许把 IDS（含 ⿰–⿻ 描述符）或描述文字写进 `text`。
10. v0.2：`cand` 只认 `lib` / `ocr` / `rare` / `ref` 四个键。

字框出界按 canvas 宽高判（v0 按 `image`）。

`unboxed_tokens()` 列出没有字框的字元（yolo「待框」溢出、整理本补字）——合法，但值得报。

---

## 九、yolo_tool `<名>_project.json`：实况与对照

### 9.1 实际结构（读 `ui/main_window.py`、`ui/components.py`、`core/workers.py` 得出）

顶层 `{"<页下标，0 起>": 页}`；页 = `{"type": [...], "slide": [...], "sort_mode"?: {...}, "source_text"?: [...]}`。

| 下标 | 字段 | 含义 / 注意 |
|---|---|---|
| 0–3 | x, y, w, h | **渲染图**像素、左上原点、浮点。PDF 按 `fitz.Matrix(2,2)` 渲染（PDF 点 ×2）；图片则是原像素 |
| 4 | cls_name | type：text / subText（双行夹注）/ midText（版心）/ subText2（夹注次列）/ midSubText（版心夹注）。**ear 在推理时被并成 text**（`'text' not in cls → 'text'`）；slide 恒 text |
| 5 | conf | YOLO 检测置信度（手画框 1.0） |
| 6 | box_type | type / slide（层） |
| 7 | id_num | type：列序；slide：**全页**读序号，1 起 |
| 8 | ocr_text | 框里的字 |
| 9 | ocr_conf | PP-OCRv5 分数；**2.0 是哨兵 = 人工填/改过** |
| 10 | local_id | type = id_num；slide：**列内**序号——任务卡里写的「栏号」不对，栏是靠交集面积现算的 |
| 11 | rec_text | 「OCR 校验比对」缓存 |

**版本靠长度区分**：8（推理刚出）、10（`flow_update_text` 给旧框补位补出来的）、11、12。`from_dict` 只认 8/10/≥11，
**9 位会崩**。`sort_mode`、`source_text` 都可缺；`source_text` 是**字元数组**（与本格式 `text` 同构），插缺页时写
`["缺","頁"]` 并把后面页键整体 +1（PDF 本身也改了）。

### 9.2 大总管点的七个问题，本格式怎么接

| 问题 | 接法 |
|---|---|
| 坐标绑在渲染像素上、不记原图尺寸与哈希 | `image.render`（zoom、pdf_sha256）+ `image.source`（扫描原图宽高）+ `map_box` 换算；`sha256` 渲染图无文件时为 null |
| 位置数组、靠长度区分版本 | 具名字段；原数组只作 `ext.yolo.raw` 保往返 |
| 没有「列」这一级 | type 框 → 列（`regions[].columns`），cls → 段 lane（subText→`jz_r`、subText2→`jz_l`、midText/midSubText→版心区） |
| 一框只能对一字 | 区间引用（一框多字、一字多框、空框） |
| 原字形与通行字混在一个字段 | `text`（原样）与 `norm`（规范）分开；yolo 的异体字替换算改原样层，由人决定 |
| 没有来源和审核状态 | `method` / `review` / `conf` / `by`：ocr_conf==2.0 → `yolo:human`/`human`；有字 → `ocr`、`conf`=分数；无字 → `yolo` |
| 不挂 Book / 册 / 页 ID | `page_id`、`book.id`、`volume.index`、`page.index`（yolo 页键 + 1） |

### 9.3 互转与损失（本仓 `open_guji_cv/formats/guji_page_yolo.py`；yolo_tool 仓不改）

- **yolo → guji → yolo 逐字节一致**（真实工程 yolo_tool `pdfs_demo/diff/001_project.json` 的第 0 页，冻结在 `tests/fixtures/yolo_tool/`；自造 8/10/11/12 位混排、手动序、
  待框溢出、空框、孤框、缺页）：每框原数组留在 `ext.yolo.raw`，回写时只把格式里真改过的字段（框挪了、字改了）盖上去。
- 读序复刻 `_page_slide_order_arrays`（列按 type id；单字框按交集面积归列；列内手动看 id、自动看中心 y）。
- 有 `source_text` 时它是文本真源：第 k 个框对第 k 个字；字多出来 = 待框（无框字元，挂末列），框多出来 = 空区间。
- **CV 页 → yolo → guji**：文本、字框、读序、夹注左右全保住（每段一条版面框，`sort_mode.slide=manual` 锁读序）。
  **丢掉**：抬头级数、行首留白、阙文与「框里还没字」之别（yolo 里都是空串）、印章/留白/排除标记、来历通道、候选字、组字原形、稳定 ID。
  v0.2：yolo 的空串字元转进来一律当阙文（「□」+ `lacuna`），回写时还原成空串。
  这些要回到本格式里看，yolo 只当校对界面用。

---

## 十、导出

### 10.1 guji-markdown（`to_guji_markdown`）

一列一行；`^`×抬头级数 + `.`×行首留白；正文直出；`<右|左>` 双行夹注；`:jz[…]{type=单行}` 单行小注；
`[[]]` 阙文（**每个 `lacuna` 位一个，不合并**；v0/v0.1 文件按空串）；不带标记的「□」照出「□」；`□{guess=X}` 残字；
`:zi[…]` 组字（v0.2 取 `zi[].ids/desc`，`text` 里的近似字不进 md）；
页首 `<!-- pN -->`（book-text 规范 F-MD-04）。**与 Step9 `render/guji_markdown.render_page` 逐字相同**：
测试钉住（自造页），样张两页 v0、v0.1、v0.2 实测都相同。`layer="norm"` 出规范层。
**`strip_ext()` 去掉 ext 后导出不变**（测试钉住），入 book-text 前先 `check()` 再 `strip_ext()`。

已知例外（沿用 Step9）：单行小注 `:jz[…]` 指令的 label 里不能有方括号，那里的阙文写成「□」——与「□ 是真字」的口径冲突，
记入待定 §12·11。

### 10.2 IIIF / W3C Web Annotation（`to_iiif_annotations`）

每字框一条 `Annotation`，`motivation: supplementing`，body `TextualBody`（字，`language: zh-Hant`），
**target `<canvas.id>#xywh=x,y,w,h`**（整数、canvas 像素，网站总管约定）。审核状态放扩展属性 `kyg:review`；v0.2 框里有阙文时加
`kyg:lacuna: true`（body 是「□」）；候选字、通道不进注释（网站校对模式直接读本格式）。整页一个
`AnnotationPage`，id `<canvas id>/annotations/guji-page`。

`to_iiif_canvas()` 出 canvas 骨架：`id`、`type: Canvas`、`label`（页序）、`width`/`height`、拆块页的
`"source": {"id": <原叶>, "type": "Image", "selector": {"type": "FragmentSelector", "value": "xywh=…"}}`
（照网站总管给的写法放在 canvas 上），以及指向上面 AnnotationPage 的 `annotations`。图片资源（三档 WebP）由网站挂。
v0 文件导出时照旧传 `canvas_id` / `canvas_image`。

### 10.4 册级索引 `layout/index.json`（`volume_index`，schema `guji-layout-index/0.1`）

```jsonc
{"schema": "guji-layout-index/0.1", "book": {…}, "volume": {…}, "page_schema": "guji-page/0.1",
 "book_text": {"version": null},                     // 对齐的 book-text 版本；换版本整张映射跟着换
 "pages": [{"page": 107, "canvas_seq": "0105c", "canvas_id": "…", "file": "p0107.guji-page.json",
            "sha256": "…", "image_sha256": "…",
            "chapters": [{"version": "…", "chapter": "005", "text": null}]}]}   // 页 → 章 NNN；text = 本页属于该章的区间，null = 整页
```

文本总管 #361·5：其余字段等第一批入库再定，先定「页 → book-text 版本与章」。CV 导出时 `chapters` 留空，由文本一侧对齐时填。

### 10.3 luatex-cn 输入（只给映射，v0 不写导出器）

luatex-cn（webtex-cn）要的三层几何都在：版框/界行 → `regions[].box`、`rules`；列与抬头 → `columns[].box/raised/lead_blank`；
逐字定位与夹注左右 → `runs` + `glyphs[].box`。展示格式方案已定「先手工试点，不急写通用转换器」，故不实现。

---

## 十一、样张与校验（`samples/guji_page_v0.2/`；v0、v0.1 时的数字见各自规范）

| 页 | canvas | 选它的理由 | 字元 / 字框（有框） / 标记 | 阙文（`lacuna`） | 原样 guji-md 与 Step9 渲染 |
|---|---|---|---|---|---|
| vol03 **p3**（卷四卷端） | `…/canvas/03/0003`，整张原叶 2361×3096 | 抬头（列 3/4/5 各一级）、双行夹注「兩江總督｜採進本」、**印章压字**（136 格 occluded；人工印章框压到 5 个字框） | 124 / 124（124） / 72 | 8 | 相同（与 v0、v0.1 也相同） |
| vol03 **p107**（拆页） | `…/canvas/03/0105c`，2074×2931，selector `xywh=2101,2913,2074,2931` | IA leaf105 双联叶的右下块；双行夹注；产物建在 09-27 首版裁法的图上，导出时经原叶整体搬到 canvas（§2.4） | 184 / 184（183） / 23 | 21 | 相同（与 v0、v0.1 也相同） |

**v0.2 新字段实测**（快照 `snap/96mid1ogzk/vol03/20260928T1708-full` 里没有 Step5-c OCR 产物，`cand.ocr` 一路全缺，如实留空）：

| 页 | `cand.lib` | `cand.rare` | `cand.ref` | 各路一致 / 有分歧 | `channel` |
|---|---|---|---|---|---|
| p3 | 124 | 124 | 124 | 81 / 43 | 未放行 101、context 17、match_solo 6 |
| p107 | 184 | 184 | 170 | 157 / 27 | match_ref 154、未放行 21、context 8、match_solo 1 |

分歧正是校对模式要看的：p107 的 21 个阙文位里多数是「库首位 vs 5-b 与整理本」的形近对（乾/軋、西/酉、禮/禎、容/客、權/榷/𣙜），
p3 卷端大字行（「欽定四庫全書總目」）库首位全错、整理本与 5-b 对上。`upgrade(v0.1 样张)` 得到的 `text`/`lacuna` 与 v0.2 样张逐字相同，
只少 `cand`（旧页没有，不编）。

p107 搬到 canvas 时有 22 个框碰到 canvas 边被裁、1 个字框整块落在 canvas 外（第 9 列版心条里的「五」，09-29 按版心中线重切后
版心这一侧不在本块里），`box` 置 null、记进 `warnings`。

校验图（`check/`，1200 px 档；对位量法 = 字框里的墨占比，原位 vs 整体平移半个字框，框对准时原位最大）：

| 画在哪 | 原位 | 右移 / 左移 | 下移 / 上移 |
|---|---|---|---|
| p3 canvas 0003（= 工作区 3.png）1200 档 | 0.250 | 0.152 / 0.149 | 0.225 / 0.240 |
| p107 canvas 0105c（= 工作区现行 107.png）1200 档 | 0.280 | 0.193 / 0.174 | 0.270 / 0.269 |
| p107 IA 原叶 105（经 selector 换回原叶）1200 档 | 0.272 | 0.189 / 0.176 | 0.266 / 0.264 |

（p3 只量了不被印章压的 31 个字框。几何与 v0.1 完全相同，校验图沿用 v0.1 的三张。）IIIF 注释的 target 与 canvas 骨架见 `p0107.iiif-annotations.json`、`p0107.iiif-canvas.json`；
册级索引样例 `index.json`。

**体积**：v0.1 紧凑 JSON 52 KB / 60 KB，gzip 后 8.5 KB / 9.5 KB；其中 `ext.cv` 约占 16–21%（入库时 `strip_ext` 去掉）。
v0.2 的 `cand` + `channel` 让缩进版 JSON 增大约 14% / 19%（83→95 KB、96→114 KB）。

---

## 十二、待定清单（v0.2 时的状态）

v0.1 的 ★1/★2/★7/★10 用户 10-02 已裁定（#361 最新一条）：1、2 照推荐；3、7、10 改动已做进 v0.2；4 交 F2 调研（`norm_layer_proposal.md`）。

| # | 事 | 状态 / 推荐 |
|---|---|---|
| 8 | 印章框谁来标 | 不变：先只用字框遮挡标记，人工标几十个样本再评估检测 |
| 11 | 单行小注 `:jz[…]` label 里的阙文 | Step9 在 label 里把阙文写成「□」，v0.2 下与「不带标记的□是真字」冲突更明显（md 里分不开）。**推荐**：guji-markdown 允许 label 里写成对的 `[[]]` 后，Step9 与本格式一起改。待文本总管 |
| 12 | `canvas.source.id` | 现写 IA 的 IIIF 图像地址；网站要换站内原图 id 时只改 `ia_image_id()`。待网站总管 |
| 13（新） | 未收字的近似字在 md 里丢失 | guji-markdown §16 的 `:zi[…]` 没有属性，导出 md 只能带原形，`text` 里的近似字与 `rel` 进不去 md（JSON 里都在）。**推荐**：guji-markdown 给 `zi` 加可选属性 `{near=X rel=形近}`（`:zi[⿰句員]{near=員 rel=部件近}`），旧写法照样合法；定了以后导出器跟着出。待文本总管 |
| 14（新） | 没有近似字时的占位 | v0.2 用「〓」（U+3013 GETA MARK，日本排版传统的「缺字记号」）+ `rel: null`。**推荐**照此；备选是另设 `near: null` 字段、`text` 放「□」——不推荐，会和阙文/真□混 |
| 15（新） | `cand` 只记首位 | 用户原话是「库首位、OCR 首位、5-b 首位、整理本字」，v0.2 照做，分数与 top-k 留在 `ext.cv`（入库时去掉）。**推荐**：校对模式若要 top-3，再加 `cand_k`，不改 `cand` 的形状 |
| 16（新） | 阙文位要不要也带 `guess` 到 md | 现状照 Step9：阙文位一律出 `[[]]`，字框上的 `guess` 与 `cand` 只在 JSON。guji-markdown §13 的 `[[…]]` label 是说明文字、不是猜字，§14 的 `□{guess=}` 是「有字认不出」。**推荐**不改，保持与 Step9 逐字相同 |
| 17（新） | OCR 一路样张里全缺 | vol03 快照没跑 Step5-c。不补跑（边界：不改产物），字段已就位，等 OCR 产物有了自然填上 |
