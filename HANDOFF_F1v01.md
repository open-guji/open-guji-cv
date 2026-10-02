# F1 交单：guji-page v0.1（吸收网站总管 IIIF 约定 + 文本总管文本口径）

> 定时任务「CV→F1 v0.1」派活（2026-10-02 09:33Z），意见原文：overview#357（网站总管两条、整理总管裁剪框表）、#361（文本总管、CV 总管汇总）
> cv 分支 `claude/F1-v01-1002`，基于 main `da166b0`（含 v0 与 yolo 扩测）。未合 main、未开 PR。

## 一、交了什么

| 产出 | 位置 |
|---|---|
| 规范 v0.1（开头有「v0.1 相对 v0」变更表；v0 规范加了「已由 v0.1 取代」） | `doc/formats/guji_page_v0.1.md` |
| JSON Schema v0.1 + 册级索引 schema（v0 schema 保留） | `formats/guji_page_v0.1.schema.json`、`formats/guji_layout_index_v0.1.schema.json` |
| 格式库：canvas、页序换算、几何搬家、IIIF canvas 导出、`zi`、`norm.why`、`strip_ext`、`upgrade`/`read_page`、`volume_index` | `open_guji_cv/formats/guji_page.py` |
| CV 导出器出 v0.1（按裁剪框表定 canvas；跑批图 ≠ canvas 时整体搬家并记 warning） | `open_guji_cv/formats/guji_page_cv.py`、`scripts/export_guji_page.py`（新参数 `--split-table`、`--index`；`--iiif` 改为开关） |
| yolo 互转出 v0.1（canvas id/seq 为 null，帧 = 渲染图） | `open_guji_cv/formats/guji_page_yolo.py` |
| 样张 v0.1（p3、p107）＋ IIIF 注释、canvas 骨架、册级索引、1200 档校验图 | `doc/formats/samples/guji_page_v0.1/` |
| 测试（全部自造数据） | 新增 `tests/test_guji_page_v01.py` 13 条；`test_guji_page_format.py` 10 条、`test_guji_page_yolo.py` 6 条照过 |

## 二、逐条对照

**网站总管（#357）**
- canvas 尺寸与坐标空间取原图像素 → 坐标空间由「本页图」改为 canvas；普通页 canvas = 原叶 = 工作区页图，坐标不变。
- 拆块各一 canvas、原点在裁剪区左上角、`source.selector` FragmentSelector `xywh=` → `canvas.source`；`to_iiif_canvas()` 照网站给的写法放在 canvas 上。裁剪框取整理总管的表（`73d3b4be`，副本 `samples/guji_page_v0.1/split_table_siku.json`）。
- canvas id `https://data.kaiyuanguji.com/iiif/<bookId>/canvas/<册2位>/<页序>`，页序 = IA leaf 4 位 + a–d → `canvas_id()`、`seq_for_ws_page()`（拆点前同号 / 拆块 a–d / 拆点后 −3）。
- 逐字注释 target `<canvas id>#xywh=` → `to_iiif_annotations()` 缺省取 `canvas.id`。
- **`image.region` ⇔ `canvas.source.selector`**：都是原叶上的 xywh。跑批图就是这一块时两者相等（导出器在 region 缺省时自动补）；跑批图是另一块时坐标经原叶换到 canvas（规范 §2.4）。

**文本总管（#361）**
- 「□」照录为真字、`""` 只给不知道原字的位、每个阙文一个 `[[]]` → 规范 §四、导出器、测试（相邻两个阙文出 `[[]][[]]`）。
- `norm` 只记异体，`why` 必填且只许「异体」→ schema 与 `check()` 双拦；校勘改字从外部用稳定 `id` 挂。
- 组字 `zi: [{"i", "form": "ids"|"desc"}]` 稀疏记在页上，导出 `:zi[…]`；来源站点组字式与 HT/KT 原样 → 规范 §四、测试。
- 册级索引预留「页 → book-text 版本与章 NNN」→ `volume_index()`、`pages[].chapters`，schema 要求 `chapter` 三位数字。
- 去掉 ext 后 md 不变 → `strip_ext()`，测试同时比 md（三种开关）与 IIIF 注释。

**CV 总管**：版本号 `guji-page/0.1`；v0 文件 `check()`、v0 schema 校验、md、IIIF（传 canvas id）照旧，`upgrade()` 升级——测试钉住。

## 三、样张实测

- 两页 v0.1 的 guji-markdown 与 v0 样张、与 Step9 `render_page` 都逐字相同；两页过 `check()` 和 v0.1 schema。
- p3：canvas `…/canvas/03/0003`（整张原叶 2361×3096），坐标与 v0 一致。
- p107：canvas `…/canvas/03/0105c`（2074×2931，selector `xywh=2101,2913,2074,2931`）。CV 产物建在 09-27 首版裁法的图上（原叶 `1945,2743,2230,3100`），导出器整体平移 (−156, −170)；22 个框碰边被裁，第 9 列版心条的「五」整块落在新块之外，`box` 置 null、写进 `warnings`。画在工作区现行 `107.png`（就是这个 canvas）上对位通过：墨占比原位 0.280，左右平移 0.193 / 0.174，上下 0.270 / 0.269。
- 顺带把待定 #9 做了：v0.1 坐标都在 canvas 上，`carry_ids` 在「同一 canvas、两边 `image.region` 都已知」（重裁）时照常按 IoU 承接 ID，重扫仍不承接。

## 四、留下的事 / 新的待定

1. **单行小注里的阙文**（新 #11）：Step9 在 `:jz[…]` label 里把阙文写成「□」（label 不能带方括号），与「□ 是真字」冲突。本格式为了与 Step9 逐字相同暂时照抄。推荐：guji-markdown 允许 label 里写成对的 `[[]]` 后，Step9 与本格式一起改。待文本总管定。
2. **`canvas.source.id`**（新 #12）：现在写 IA 的 IIIF 图像地址；网站要用站内原图 id 时，只改 `ia_image_id()` 一处。待网站总管定。
3. vol03 p105–108 仍要从 Step1 重跑（v0 交单已提）；重跑后 p107 的 `image.region` 会等于 selector，不再需要搬家。
4. ★1/★2/★7/★10 等用户点头（#361 汇总），v0.1 已按推荐做。

## 五、测试

```bash
python -m pytest tests/test_guji_page_v01.py tests/test_guji_page_format.py tests/test_guji_page_yolo.py -s -p no:cacheprovider   # 29 passed
python -m pytest tests/ -s -p no:cacheprovider                                                                                    # 全量，见下
```

全量（本容器补装 scipy/fastapi/fontTools/opencc 后）：**2582 passed、30 skipped、1 failed**。失败的是
`tests/test_cut_select.py::test_ckpt_fingerprint_empty_for_missing_file`（容器里没有 U-Net checkpoint，`ckpt_fingerprint()` 返回空串）；
在未改动的 main 上同样失败，与本分支无关。
