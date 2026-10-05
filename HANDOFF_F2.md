# F2 交单：guji-page v0.2 ＋ 规范层（norm）方案调研

> 任务卡 open-guji-core/overview#381（CV 总管派活，文本总管共同验收），依据 #361 用户 10-02 裁定（CV 总管记录在最新一条）。
> cv 分支 `claude/F2-guji-page-v02-1002`，基于 main `10bd9be`（v0.1 已合）。**未合 main、未开 PR。**

## 一、交了什么

| 产出 | 位置 |
|---|---|
| **任务一**：规范层方案调研（参照 TEI / CBETA / 识典 / 汉典 / IVS / 教育部异体字字典 / 通用规范汉字表；两档口径与共表；来源与上下文；校勘层结构草案；四方案对比与推荐；待拍板 10 条） | `doc/formats/norm_layer_proposal.md` |
| 规范层演示脚本（共享归一表 + 逐位条目 → 原样 / 繁体通行 / 简体 三档） | `scripts/demo_norm_layer.py` |
| 演示数据与输出（vol03 p3、p53、p78、p107 真实产物；表草样、逐位条目、每页三档 md、运行记录） | `doc/formats/samples/norm_demo/` |
| **任务二**：规范 v0.2（开头「v0.2 相对 v0.1」变更表；v0.1 规范加了「已由 v0.2 取代」） | `doc/formats/guji_page_v0.2.md` |
| JSON Schema v0.2（v0、v0.1 schema 保留） | `formats/guji_page_v0.2.schema.json` |
| 格式库：`lacuna`、两层 `zi`、`cand`/`channel` 检查；`lacuna_set()`/`zi_at()` 按版本读；md / IIIF 导出；`upgrade()` v0 → v0.1 → v0.2 | `open_guji_cv/formats/guji_page.py` |
| CV 导出器出 v0.2：阙文「□」+ `lacuna`；从 glyph_match / ocr_candidates / rare_candidates / align_ref 填 `cand`，从 seed_admit 填 `channel`，缺件留空 | `open_guji_cv/formats/guji_page_cv.py`、`scripts/export_guji_page.py` |
| yolo 互转出 v0.2：yolo 空串字元 ↔ 阙文，往返仍逐字节一致 | `open_guji_cv/formats/guji_page_yolo.py` |
| 样张 v0.2（p3、p107）＋ IIIF 注释、canvas、册级索引；校验图沿用 v0.1（几何不变） | `doc/formats/samples/guji_page_v0.2/` |
| 测试（全部自造数据） | 新增 `tests/test_guji_page_v02.py` 15 条；`test_guji_page_v01.py` 改用造出的 v0.1 页（13 条照过）；`test_guji_page_format.py` 改一处期望（阙文 `""` → `□` + `lacuna`） |
| CLAUDE.md 文档表指向 v0.2 | `.claude/CLAUDE.md` |

## 二、任务二逐条对照（用户裁定 → 落实）

- **#3 阙文**：`text` 放「□」（U+25A1），页上 `lacuna: [下标…]`（升序不重复）；不带标记的「□」是真刻的□。md：带标记的 `[[]]`（每位一个），不带的「□」，真□带 `guess` 出 `□{guess=X}`。不用全角空格。`text` 不再有空串（check 拦）；字框 `lacuna: "unreadable"` 必须与页上 `lacuna` 一致（check 拦）。IIIF 注释框里有阙文时加 `kyg:lacuna: true`。
- **#7 未收字两层**：`text[i]` 放近似的已收字；`zi: [{"i", "ids"|"desc", "rel"}]`，`rel` ∈ 异体／形近／部件近；还没近似字时 `text[i]="〓"`、`rel: null`。md 写 `:zi[ids|desc]`（§16）。check 拦：ids/desc 并存或都缺、rel 越界、IDS 写进 text、指向阙文。
- **#10 记录先行**：字框 `channel`（seed_admit 原始通道，未放行 null）与 `cand: {lib, ocr, rare, ref}`（库首位：same 档取认定字、否则候选首位；OCR topk 首位；5-b 首位；整理本：过闸对齐字优先、否则坐标对位字，整理本空格不算）。缺件留空；不在 `ext` 里，`strip_ext` 后还在。
- **版本**：`guji-page/0.2`；v0、v0.1 照样 `check()`/schema/导出；`upgrade()` 一路升（空串 → □+lacuna；v0.1 组字原形挪进 `zi`，text 放「〓」；`channel` 从 `ext.cv.channel` 补）。**升级前后 md 逐字相同**（测试钉住，样张实测：`upgrade(v0.1 样张)` 的 text/lacuna 与 v0.2 样张逐字相同）。去 ext 后 md 不变的测试保留并新增 v0.2 版。

## 三、样张实测

- 两页 v0.2 的 md 与 v0.1 样张逐字相同（也即与 Step9 `render_page` 相同）；两页过 `check()` 与 v0.2 schema。
- 阙文：p3 8 位、p107 21 位。`cand`：lib/rare 全覆盖，ref p3 124/124、p107 170/184；**OCR 一路全缺**（快照没跑 Step5-c，不补跑）。
- 各路一致 / 分歧：p3 81 / 43（卷端大字行库首位全错）、p107 157 / 27（阙文位多是形近对：乾/軋、西/酉、禮/禎、權/榷/𣙜）——正是校对模式要看的。
- `channel`：p3 未放行 101、context 17、match_solo 6；p107 match_ref 154、未放行 21、context 8、match_solo 1。
- 体积：缩进 JSON +14% / +19%。

## 四、任务一要点（详见 `norm_layer_proposal.md`）

推荐 **方案 C**：规范层只存「繁体通行」一档，简体由 `t2cn` 派生不存（云/雲、后/後、余/餘 在繁→简方向是多对一，不用判）；无条件字形异体走**与网站 #350 共用的 bim 归一表**（页上物化，`by: table:<版本>`，可整批重算）；上下文才定的（証→證）与例外逐位记在页上；校勘另起 `collation.jsonl`，按稳定字框 id 锚定、按校勘三式导出。

参照调研（§二，全部附打开过的出处）：TEI 与 CBETA 都把「异体规范化」与「校改」分成两套（orig/reg vs sic/corr；CBETA 通用字 vs `<app>`）；
识典是「底本原字 / 大陆标准繁体 / 简体」三档、后两档机器转；IVS 只管同一字的字形、装不了异体映射；教育部《異體字字典》用「部分異體」标上下文相关，
**但它不在教育部 CC BY-ND 开放名单里**（bim 表以它为主依据，只宜引编号与判断，不宜搬运字形资料——请 bim 维护者确认）。

两条实测结论值得单列：
1. **`variants.json` 不能直接填 norm**：vol03 四页若照其有向边填，会提 44/87/85/74 位，真该归一的只 2/6/5/1 位（欽→撳、全→痊、士→土、傳→傅 全是噪声）。本书用字账也有错条（卞→其、籕→抽）。
2. **这批页上整理本对齐一路没有信号**：维基整理本照录刻本字形，`cand.ref` 与原样没有一位不同；规范层在这批书上只能靠表与人裁。

## 五、待定清单（每条附推荐）

**v0.2 格式**（规范 §十二）
1. 单行小注 label 里的阙文（旧 #11）：v0.2 下「□」在 md 里与真□分不开更明显。推荐 guji-markdown 允许 label 写成对的 `[[]]` 后 Step9 与本格式一起改。待文本总管。
2. `canvas.source.id`（旧 #12）：不变，待网站总管。
3. 未收字的近似字进不了 md（新 #13）：§16 `:zi` 无属性。推荐 guji-markdown 给 `zi` 加可选 `{near=X rel=…}`，旧写法照样合法。待文本总管。
4. 没有近似字的占位（新 #14）：推荐「〓」（U+3013）+ `rel: null`，如现实现。
5. `cand` 只记首位（新 #15）：推荐照用户原话只记首位，分数与 top-k 留 `ext.cv`；要 top-3 再加 `cand_k`。
6. 阙文位的 `guess`/候选不进 md（新 #16）：推荐不改，保持与 Step9 逐字相同。
7. OCR 一路样张全缺（新 #17）：不补跑，等 OCR 产物。

**规范层**（方案 §七，10 条）：方案 C；繁体通行口径以 bim 表为准；`why: "保留"` 记例外；`by: table:<表>@<版本>`；简体逐位覆盖先靠 `t2cn` 词组表；刻本补充字进 bim 白名单只维护一处；`cond: true` 条目只出候选；进表逐对裁决并入 #372 muse；校勘先定结构后落 schema；表的那部分现在就可由 CV 导出器物化。

## 六、测试

```bash
python -m pytest tests/test_guji_page_v02.py tests/test_guji_page_v01.py tests/test_guji_page_format.py tests/test_guji_page_yolo.py tests/test_render_guji_markdown.py -s -p no:cacheprovider
python -m pytest tests/ -s -p no:cacheprovider
```

- 格式相关 5 个文件：53 passed。
- 全量（本容器补装 cv2 依赖、httpx 后）：**2598 passed、30 skipped、1 failed**。失败的是 `tests/test_cut_select.py::test_ckpt_fingerprint_empty_for_missing_file`
  （容器里没有 U-Net checkpoint）——F1 交单记过，在未改动的 main 上同样失败，与本分支无关。

## 七、边界自查

- 没改 CV 管线现有产物、没碰工作区正式 products（快照只在 /tmp 解出来只读）；guji-workspace、overview、guji-markdown 只读。
- 测试只用自造数据。提交只 add 具体文件；没开 PR、没写 GitHub 评论。
