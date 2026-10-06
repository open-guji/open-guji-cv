# guji-page v0：每字带坐标的页面文本格式

> **已由 v0.1 取代**：[guji_page_v0.1.md](guji_page_v0.1.md)（2026-10-02，吸收 IIIF canvas 约定与文本口径）。v0 文件仍可读。

> F1 道（任务卡 open-guji-core/overview#357），2026-10-02。CV 总管派活，文本总管共同验收。
> 在《自校文本格式草案 v1.1》（overview `项目进展/古籍文本/整体设计/2026-09-自校文本格式草案.md`，
> 下称**草案**）的基础上定稿；草案 §八 CV 审定的三条全部照办。
> **状态：v0 草定，待「待定清单」（§12）拍板后升 v1。**
>
> | 产物 | 位置 |
> |---|---|
> | JSON Schema | `formats/guji_page_v0.schema.json` |
> | 格式工具（检查、坐标换算、稳定 ID、md / IIIF 导出） | `open_guji_cv/formats/guji_page.py` |
> | CV 产物 → 本格式 | `open_guji_cv/formats/guji_page_cv.py`、`scripts/export_guji_page.py` |
> | 校验图 | `scripts/render_guji_page_overlay.py` |
> | 样张（四庫 vol03 p3、p107）＋校验图 | `doc/formats/samples/guji_page_v0/` |
> | yolo_tool 互转（yolo_tool 仓不改，其格式并入本设计） | `open_guji_cv/formats/guji_page_yolo.py`（只用标准库）、`tests/test_guji_page_yolo.py` |
> | 测试 | `tests/test_guji_page_format.py`（自造数据，10 条）、`tests/test_guji_page_yolo.py`（6 条） |
> | yolo_tool 的 YOLO 切分算法评估 | `doc/research/yolo_tool_segmentation_review.md` |

## 〇、一句话

**一页一个 JSON。** 文本流 `text` 是真源（原样层，字元数组）；版面按「区 → 列 → 段（正文 / 夹注右 / 夹注左 / 单行小注）」
分层，段引用文本区间、首尾相接铺满全页文本，所以阅读顺序是显式的；字框 `glyphs` 落在**本页图像的整数像素、左上原点
`[x,y,w,h]`**，同样只引用文本区间，一框多字、一字多框都只是区间的事；图像块记 sha256、宽高，以及「本图 = 哪张原叶的哪块
裁切区域」，缩放档、另一版裁法都靠这一条换算，不另存坐标。

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

- **空间**：本页图像（`image` 块描述的那张图）的像素；**左上原点**，x 向右、y 向下。
- **框**：`[x, y, w, h]` 整数，与 IIIF `#xywh=x,y,w,h` 同序同义。CV 浮点框换整数时**向外取整**（左上 floor、右下 ceil），
  宁多包一点墨也不裁笔画。可选 `quad`（四角整数点）留给斜格。
- **CV 换算**：`x_tl = (W-1) - x_tr`（`core/anchor.py` 的像素中心约定），`tr_bbox_to_xywh()` 一处实现。
  **不要**拿 `bbox_page` 当左上原点用（chars.py 模块头的「鳳」字教训）。
- **派生图不存坐标**：缩放档（IIIF `300,` / `1200,` / `max`）按比例换算，`scaled_image()` + `map_box()`。

### 2.2 `image` 块：本页图是什么、从哪来

```jsonc
"image": {
  "width": 2230, "height": 3100,
  "sha256": "1822ea8f…",                  // 坐标所在那张图（CV 跑批时的 raw_page，取自 _manifest.jsonl upstream）
  "path": "data_full/zongmu/vol03/107.png", // 参考，不作身份
  "source": {"kind": "ia", "item": "06061302.cn", "leaf": 105, "width": 4198, "height": 5848, "sha256": "4a65a5fa…"},
  "region": [1945, 2743, 2230, 3100],     // 本图在 source 上的裁切区域；缺省 = 整张
  "edits": [{"op": "whiten", "note": "…"}] // 裁切之外动过的像素，只说明、不影响坐标
}
```

- `sha256` 是**坐标的身份证**：图一换（重扫、重裁、抹白），旧坐标就不能直接用。CV 导出取产物 manifest 里记的那张，
  不取工作区现在的文件——两者可以不同（见 2.3 实例）。
- 合扫页拆分（vol03/04/07/09）：`source` + `region` 表达「本页 = 某原叶的某个裁切区域」。网站切片用的图若与 CV 跑批的图
  是同一原叶的**另一版裁法**，`map_box(box, page.image, canvas_image)` 经原叶换算即可，不必重跑 CV。
- yolo_tool 的 PDF 渲染图没有文件：`sha256: null`，`render: {"from":"pdf","zoom":2,"pdf_sha256":…}`，`source` 记扫描原图宽高，
  换算回原图同样走 `map_box`（region 缺省 = 整张 → 纯缩放）。

### 2.3 实例：vol03 p107 的图已经换过一次

CV 快照 `snap/96mid1ogzk/vol03/20260928T1708-full` 的 p107 产物建在 sha `1822ea8f…`、2230×3100 的图上；工作区现行
`107.png` 是 sha `fbdc696a…`、2074×2931——09-27 21:25Z 整理总管修了裁法（`cap_top`）之后重裁的。两张都是 IA leaf105
（4198×5848 双联叶）的右下块：模板匹配得旧图 region `[1945,2743,2230,3100]`、新图 `[2101,2913,2074,2931]`（均逐像素一致）。
**按产物记的 sha 去对现行文件会对不上；按 region 经原叶换算则全对**（校验图 §十一）。这正是本格式要记 sha + region 的理由，
也说明 vol03 p105–108 的 CV 产物相对现行图是过期的（尺寸都变了），该从 Step1 重跑——已写进交单。

---

## 三、文件结构

```jsonc
{
  "schema": "guji-page/0",
  "page_id": "96mid1ogzk/3/107",       // <bookId>/<册>/<页>，与影像路径 images/{bookId}/{volume}/{page} 同构
  "book":   {"id": "96mid1ogzk", "edition": "siku-zongmu", "title": "…"},
  "volume": {"index": 3, "cv_book": "vol03", "label": "…", "juan_range": "4-5"},
  "page":   {"index": 107, "label": null, "page_type": "body"},
  "image":  { … §二 … },
  "producers": {"cv": {"tool": "open-guji-cv", "rev": "1332c01734", "pipeline": "keben_body_v2",
                       "steps": {…}, "products_sha": {…}, "snapshot": "…"},
                "manual": {"tool": "manual", "who": "…"}},
  "text":    ["旋", "爲", …],           // §四
  "norm":    [{"i": 12, "t": "内", "why": "异体"}],
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

Book ID、IIIF 册号、`page.label`（书上叶次）、`page_type`、IA 原叶号、拆页 region、人工标的印章/版心框、网站 Canvas 用哪张图。
格式见 `samples/guji_page_v0/meta.json`。**册号 `volume.index` 取 IIIF 路径那一级**（四庫 vol03 → 3），`cv_book` 只作对照。

---

## 四、文本：原样层与规范层

- `text`：**原样层**，阅读顺序的字元数组。一个元素 = 一个字元：通常一个码位；也可以是带异体选择符的序列、
  IDS 串（未收字，写法待定 §12·7）、PUA。**下标按元素数，不按 UTF-16 / 码位数**——生僻字大量在 Ext-B 以后，
  JS 的 `string.length` 会数错，字元数组从结构上绕开这个坑。
- 阙文 = `""`（空串）。残字的原刻占位 `□` 是一个真字元，配字框上的 `guess`。
- **字形照录**：CV 2026-09-26 起全流程只存字形（`seed_admit` 的 `char`），原样层就是它。
- `norm`：**规范层**，只列与原样层不同的位 `{"i": 下标, "t": 通行字, "by": 来历键, "why": 原因}`；`t` 可以多字或空串。
  CV 不产规范层（没有「读法」了），样张里为空；由文本一侧（整理本对齐、异体字表）填。导出器 `layer="norm"` 时用它覆盖。

---

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
  `prev` 记下压到的旧 ID，留给人裁/校勘挂点去搬家；图换了一律不承接（先 `map_box` 换到同一坐标，再按 sha 改口径——v0 不自动做）。
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
5. `norm[].i` 不越界。

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
  **丢掉**：抬头级数、行首留白、阙文与「框里还没字」之别（yolo 里都是空串）、印章/留白/排除标记、来历通道、稳定 ID。
  这些要回到本格式里看，yolo 只当校对界面用。

---

## 十、导出

### 10.1 guji-markdown（`to_guji_markdown`）

一列一行；`^`×抬头级数 + `.`×行首留白；正文直出；`<右|左>` 双行夹注；`:jz[…]{type=单行}` 单行小注；`[[]]` 阙文；
`□{guess=X}` 残字；页首 `<!-- pN -->`（book-text 规范 F-MD-04）。**与 Step9 `render/guji_markdown.render_page` 逐字相同**：
测试钉住（自造页），样张两页实测也相同。`layer="norm"` 出规范层。

### 10.2 IIIF / W3C Web Annotation（`to_iiif_annotations`）

每字框一条 `Annotation`，`motivation: supplementing`，body `TextualBody`（字，`language: zh-Hant`），
target `<canvas>#xywh=…`；Canvas 对应的图不是本页图时传 `canvas_image`，按 `map_box` 换算（样张 p107 就是这样指到工作区现行
`107.png`）。审核状态放扩展属性 `kyg:review`。整页一个 `AnnotationPage`，可挂到 manifest Canvas 的 `annotations`。

### 10.3 luatex-cn 输入（只给映射，v0 不写导出器）

luatex-cn（webtex-cn）要的三层几何都在：版框/界行 → `regions[].box`、`rules`；列与抬头 → `columns[].box/raised/lead_blank`；
逐字定位与夹注左右 → `runs` + `glyphs[].box`。展示格式方案已定「先手工试点，不急写通用转换器」，故不实现。

---

## 十一、样张与校验（`samples/guji_page_v0/`）

| 页 | 选它的理由 | 字元 / 字框 / 标记 | 原样 guji-md 与 Step9 渲染 |
|---|---|---|---|
| vol03 **p3**（卷四卷端） | 抬头（列 3/4/5 各一级）、双行夹注「兩江總督｜採進本」、**印章压字**（136 格 occluded；人工印章框压到 5 个字框） | 124 / 124 / 72 | 相同 |
| vol03 **p107**（拆页） | IA leaf105 双联叶的右下块；双行夹注；产物建在旧裁法的图上（§2.3） | 184 / 184 / 23 | 相同 |

校验图（`check/`，1200 px 档）：p3 画在本页图；p107 画在 **IA 原叶 105**（经 region）和**工作区现行 107.png**（经两次 region 换算）。
对位量法：字框里的墨占比，原位 vs 整体平移半个字框——框对准时原位最大：

| 画在哪 | 原位 | 右移 / 左移 | 下移 / 上移 |
|---|---|---|---|
| p3 本页图 2361 宽 | 0.259 | 0.159 / 0.156 | 0.227 / 0.242 |
| p3 1200 档 | 0.250 | 0.152 / 0.149 | 0.225 / 0.240 |
| p107 原叶 4198 宽 | 0.287 | 0.202 / 0.175 | 0.270 / 0.272 |
| p107 原叶 1200 档 | 0.271 | 0.194 / 0.170 | 0.264 / 0.264 |
| p107 现行 107.png 2074 宽 | 0.288 | 0.202 / 0.177 | 0.273 / 0.272 |
| p107 现行 107.png 1200 档 | 0.280 | 0.198 / 0.174 | 0.270 / 0.269 |

（p3 只量了不被印章压的 31 个字框；印章区里框内全是印泥散点。目视放大图见交单。）

**体积**：紧凑 JSON 52 KB / 60 KB，gzip 后 8.5 KB / 9.5 KB；其中 `ext.cv` 约占 16–21%。按每页约 190 格算，一册 200 页约 2 MB gzip。

---

## 十二、待定清单（需拍板的，附推荐）

见 cv 仓根 `HANDOFF_F1.md` §四（同一份，那里有选项与推荐），此处只列题目：

1. 坐标原点：左上（推荐）还是沿用 CV 的右上
2. 坐标所在的「本页图」：CV 跑批那张（推荐）还是网站切片那张
3. 阙文表示：空串 `""`（推荐）还是专用字元
4. 规范层谁填、存哪：稀疏 `norm` 放页文件（推荐）还是另立文件
5. 册级 `index.json` 要不要、放什么
6. `ext.cv` / `ext.yolo` 是否入库（推荐入工作区、不进 book-text）
7. 未收字（IDS）在 `text` 里的写法
8. 印章框谁来标
9. 稳定 ID 跨图（重扫/重裁）是否自动承接
10. `review` 的 `auto` 能否当「已定」对外展示
