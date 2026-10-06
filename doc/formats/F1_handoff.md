# F1 交单：每字带坐标的页面文本格式 v0（guji-page/0）

> 任务卡 open-guji-core/overview#357｜CV 总管派活，文本总管共同验收｜2026-10-02
> cv 分支 `claude/F1-char-coord-1002`（未合 main、未开 PR）

## 一、交了什么

| # | 产出 | 位置 | 状态 |
|---|---|---|---|
| 1 | 规范 v0 | `doc/formats/guji_page_v0.md` | ✅ 含与草案 v1.1 逐条对照（§一）、yolo project.json 实况（§九） |
| 1 | JSON Schema | `formats/guji_page_v0.schema.json` | ✅ 两张样张、yolo 转出的 6 页都过 |
| 1 | overview 副本 + 草案 v1 文件头「已由 v0 取代」 | — | ❌ **没做**：overview 只拿到只读权限（push 被权限分类器拒），见 §三 |
| 2 | 样张 2 页 | `doc/formats/samples/guji_page_v0/`（vol03 p3、p107） | ✅ 夹注、抬头、印章遮挡都在 p3；p107 是拆过合扫页的一页 |
| 2 | 校验图 | 同上 `check/`（1200 px 档 3 张） | ✅ 原图分辨率的另有 3 张，太大没进仓（4 MB/1.3 MB/1.1 MB），可重生成 |
| 3 | CV 产物 → 新格式 | `open_guji_cv/formats/guji_page_cv.py` + `scripts/export_guji_page.py` | ✅ 独立脚本，没挂进 Step9，现有导出零改动 |
| 3 | 格式工具 + md / IIIF 导出器 | `open_guji_cv/formats/guji_page.py` | ✅ md 与 Step9 `render_page` 逐字相同（测试钉住 + 两页实测） |
| 3 | yolo_tool ↔ 新格式 + 往返测试 | `open_guji_cv/formats/guji_page_yolo.py`、`tests/test_guji_page_yolo.py` | ✅ 6/6。**用户 10-02 定：yolo_tool 仓不改**，它的格式并进本设计，互转放 cv 仓 |
| — | yolo_tool 的 YOLO 切分算法评估（用户追加） | `doc/yolo_tool_segmentation_review.md`、`research/yolo_tool_probe/` | ✅ 读代码＋两页实测 |
| 4 | 待定清单 | 本文 §四 | ✅ 10 条 |
| — | 测试 | `tests/test_guji_page_format.py` | ✅ 10/10；`test_suite_hygiene` 照过（只用自造数据） |

跑法：

```bash
python -m pytest tests/test_guji_page_format.py -s -p no:cacheprovider          # cv：10 passed
python -m pytest tests/test_guji_page_yolo.py -s -p no:cacheprovider            # yolo 互转：6 passed
```

## 二、要点（详见规范）

- **坐标**：本页图像整数像素、左上原点、`[x,y,w,h]`，与 IIIF `#xywh` 同序；CV 的右上原点只在导出时换一次，向外取整。
- **图的身份**：`image.sha256`（取产物 manifest 里 CV 跑批时那张，不取工作区现在的文件）+ `source`（IA item/leaf）+ `region`（本页在原叶上的裁切区域）。缩放档、另一版裁法一律 `map_box` 换算，不另存坐标。
- **分层**：区 → 列 → 段（main / jz_r / jz_l / solo）→ 字框。`text` 字元数组是真源与读序；段引用区间且首尾相接铺满；字框也引区间（一框多字、一字多框、空框）。
- **两层文本**：`text` 原样（照录字形，阙文 = `""`），`norm` 稀疏规范层。
- **字级来历**：`method`（human / cv:<通道> / cv:occluded_default / cv:pending / ocr / yolo / yolo:human）、`review`（pending/auto/human/disputed）、`conf`（只在真有概率时填，CV 一律 null）、`by` → `producers`（cv 各步 code_rev 与产物 sha）。
- **稳定 ID**：不透明、可复现（page_id + cv_id + Step3 产物 sha）；重切后按 CV `feedback/bindings.py` 同一组 IoU 门槛承接（`carry_ids`），切开/合并给新 ID 并记 `prev`。`cv_id`、`glyph_id` 另存，`glyph_id` 不知道就 null（§八·2「不保证相等」）。

## 三、做的过程中发现的事（给 CV 总管 / 整理总管）

1. **vol03 p105–108 的 CV 产物相对现行图已过期。** 快照 `vol03/20260928T1708-full` 的 p107 建在 sha `1822ea8f…`、2230×3100 的图上；工作区现行 `107.png` 是 `fbdc696a…`、2074×2931（09-27 21:25Z 修裁法后重裁）。两者都是 IA leaf105 右下块，region 分别 `[1945,2743,2230,3100]`、`[2101,2913,2074,2931]`（模板匹配、逐像素一致）。p105/106/108 同理（尺寸都变了）。**应从 Step1 重跑 105–108**；在那之前，新格式靠 region 换算仍能把 p107 的框准确画到现行图上（校验图为证）。
2. **p107 第 4 列是两列正文被并成一列**（Step1 漏一条界行，Step3 再当双行夹注切开）。可能与旧裁法有关，重跑后再看。
3. **yolo_tool 的框第 10 位是「列内序号」不是「栏号」**（任务卡写的是栏号）；栏是每次按交集面积现算的。另：9 位长度的框数组会让 `from_dict` 崩；`ear` 类在推理时被并成 `text`，模型分得出鱼尾但工程文件里留不下。
4. **guji-workspace 的 `zongmu_manifest.json` 还写着 `n_items: 199`**，R12 已查明 IA 是 99 册（四庫总目影像存储方案 §一），一并改。
5. 印章：CV 仍没有印章产物。p3 那方印 CV 用「坐标对位密度」把 136 格标了 `occluded`，比画框粗；样张里的印章框是 F1 目测的。

## 四、待定清单（每条：选项 → 推荐）

| # | 问题 | 选项 | 推荐 | 谁定 |
|---|---|---|---|---|
| 1 | 坐标原点 | A 左上原点 `[x,y,w,h]`（IIIF/W3C/yolo/OpenCV 同）；B 沿用 CV 右上原点 | **A**。右上原点是 CV 内部约定，对外每个消费者都要再翻一次，`bbox_page` 被当左上用已经栽过（chars.py「鳳」字） | CV 总管＋网站总管 |
| 2 | 坐标落在哪张图 | A CV 跑批的那张（产物 manifest 的 raw_page sha）；B 网站切片那张（工作区现行图） | **A，并要求网站 Canvas 记自己图的 region**，用 `map_box` 换。B 要在每次重裁后重写全部坐标，且与 CV 产物脱钩无法核对 | 网站总管 |
| 3 | 阙文表示 | A 空串 `""`；B 专用字元（如 `〓`）；C `null` | **A**。字元数组里空串最省事、不与真字冲突；残字的 `□` 是真字元另配 `guess` | 文本总管 |
| 4 | 规范层 | A 稀疏 `norm` 放页文件；B 另立整页规范文本文件，靠下标对齐 | **A**。只记不同的位，原样/规范天然对齐；谁填（整理本对齐？异体字表？）请文本总管定 | 文本总管 |
| 5 | 册级 `layout/index.json` | A 要：册内页表、各页 sha、格式版本、CV 快照；B 不要，靠目录列举 | **A，但等第一批入库时再定字段**（草案 §七·6 文本总管已裁「等第一批真实数据」） | 文本总管 |
| 6 | `ext.cv` / `ext.yolo` 入不入 book-text | A 入；B 工作区留全量、book-text 入库时剥掉 ext | **B**。ext 占 16–21%，只对工具回查有用；book-text 只要格式本体 | 文本总管 |
| 7 | 未收字（IDS）在 `text` 里怎么写 | A 直接放 IDS 串（`⿰木⿱…`）；B PUA＋旁注；C `{ids=…}` 属性写在 glyph 上、text 放占位 | **A＋glyph `flags:["ids"]`**，与字统网「未收字以 IDS 当身份」同口径；需与 guji-markdown `{ids=}` 属性对齐 | 文本总管 |
| 8 | 印章框谁来标 | A CV 加一步印章检测；B 人工在审查页标；C 先不标，只用字框的 `occluded` flag | **C 先行、B 补样本**：v0 已支持 `marks.seal`，等人工标出几十个再评估要不要 A | CV 总管 |
| 9 | 跨图（重扫/重裁）稳定 ID 是否自动承接 | A 自动：经 region 换到同一坐标后按 IoU 承接；B 不承接，记 `prev` 交人裁 | **A 但只对 `region` 已知的裁切变化**（vol03 p107 这类）；重扫一律 B | CV 总管 |
| 10 | `review=auto` 能否对外当「已定」 | A 能（网站正常显示）；B 网站上加「机器认定」标记 | **B**，与 CV 不合成置信数同理，让读者知道哪些字没人看过 | 网站总管＋文本总管 |

## 五、边界自查

- 没改 CV 管线任何产物格式、没碰工作区正式 products；样张产物取自快照分支解到沙箱。没跑整册（只读两页现成产物）。
- cv 测试只用自造数据，外加一份冻结的 yolo_tool 真实工程文件第 0 页（`tests/fixtures/yolo_tool/`，51 KB）。yolo_tool 仓零改动。
- 提交只 add 具体文件。
- overview 只读：overview 副本与草案文件头那一行，**需要有写权限的会话或用户代办**：
  - overview：把 `doc/formats/guji_page_v0.md` 复制为 `项目进展/古籍文本/整体设计/2026-10-每字坐标格式-v0.md`，
    并在 `2026-09-自校文本格式草案.md` 第 1 行下加一行「> **已由 v0 取代**：[2026-10-每字坐标格式-v0.md](2026-10-每字坐标格式-v0.md)（F1 道，2026-10-02）」
