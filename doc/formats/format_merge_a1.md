# A1 格式合一：guji-page × guji-format 对照表与推荐

> F3 道（任务卡 open-guji-core/overview#398，挂 #387 的 A1、A2），2026-10-05。CV 牵头，文本总管会签，网站总管关注 pages.json。
> 代码：`open_guji_cv/formats/guji_format.py`（双向转换器）、`scripts/export_guji_format.py`（A2：CV 产物 → 一章 guji-format）、
> `scripts/reconcile_lines_anchors.py`（锚点对账）、`scripts/check_pages_json_boxes.py`（抽字核框）；测试 `tests/test_guji_format.py`（8 条，自造数据）。
> 样张与核对：`doc/formats/samples/guji_format_v0.1/`。
> guji-format 规范仓（`spec/04-guji-punct.md`、`05-guji-entity.md`）**本会话挂不上**（`open-guji/guji-format` 无权限），
> punct/entity 的字段按 book-text `wip/siku-vol02`（`cc2d9d9`）里的实物与 #385 的描述来定。

## 〇、结论

**照 CV 总管的初判走，改两处、补一处：**

1. **对外存储（book-text）用 guji-format**。`NNN.lines.md` 是**文本真源**（原样层），伴生层都按锚点挂。理由：可读、git 好比对、
   前端已接上；`lines.md` 就是 Step9 9.1 的 guji-markdown，两边本来同源（vol02/vol03 快照导出的 lines.md 与用户 book-text 版
   **行数完全相同**（1,668 / 952 行）、字 98.3% / 98.0% 相同，差的是用户本地多放行了一批字）。
2. **guji-page 作 CV 内部与交换格式**：每字证据、候选、坐标在这里，由它**确定性生成** lines.md、pages.json 与 proof/norm/zi 的初值；
   反方向 guji-format → guji-page 也无损（往返测试 + 两册真数据自检都过）。
3. **锚点以 CV 格 id 为准，落在 pages.json，不写进 lines.md。** ——这是**改的第一处**：初判说「lines.md 推出来的位置只做校验」，
   对账证明它**连校验都只能做一半**：lines.md 里根本没有排除格、列中空格的痕迹，数出来的锚点在 vol02 有 3.5%、vol03 有 31% 的位
   是错的（§三），修 `build_anchor_map` 只能消掉其中一小部分。所以锚点**必须**由 CV 几何给出、随 pages.json 发布；
   lines.md 保持纯 guji-markdown（不加显式锚点，理由见 §三·3）。
4. **cand/channel 不进 pages.json，另起 `proof.json`**（**改的第二处**，初判二选一）：pages.json 是对读前端要拉的几何文件，
   proof 比它还大（vol02 4.8 MB vs 3.6 MB），只有校对模式要，分开后阅读模式不用下载。
5. **补：锚点会随 CV 重切变**（guji-page §6 早就记着）。伴生层除锚点外必须同时存 `char_offset` + `pre_char`（现在 punct 已有，
   entity 有 `span` 但值是错的，§五），重切后由 `reattach` 先按新锚点、再按偏移 + 字校验重挂，两头都对不上的报出来交人。
   更稳的做法（锚点改挂稳定字框 id `g…`）列进待定 ★2。

---

## 一、两套格式逐字段对照

### 1.1 文件与层

| 层 | guji-page（CV，`guji_page_v0.2.md`） | guji-format（#385、book-text `wip/siku-vol02`） | 合一后（book-text 一章 `NNN.*`） |
|---|---|---|---|
| 单位 | 一页一个 JSON | 一章一组文件（章可跨很多页，vol02 一章 188 页） | 一章一组；pages.json 里按页分块 |
| 原样文本 | `text` 字元数组 | `NNN.lines.md`（逐列分行 guji-markdown） | **`lines.md`**，由 `text` + `lacuna` + `zi` + 列/段导出，与 Step9 逐字同 |
| 读序 | `regions[].columns[].runs`（段引文本区间） | 行序 + 行内字序；夹注 `<右\|左>` 先右后左 | 两者一致（转换器在真数据上逐字核过）；runs 进 pages.json |
| 分页 | `page.index` | `<!-- pN -->` | 两者都有，pages.json 的 `page.index` = md 的 N |
| 抬头 / 挪抬 | 列 `raised` / `lead_blank` | 行首 `^`×级 / `.`×格 | md 照写；数值在 pages.json 列上 |
| 夹注 | 段 `lane` = `jz_r`/`jz_l`/`solo` | `<右\|左>`、`:jz[…]{type=单行}`；锚点子列 a/b | md 照写；锚点 a = 右 = `jz_r` |
| 阙文 | `text` 里「□」+ 页上 `lacuna` | `[[]]` | **md 的 `[[]]` 为准**；`:jz[…]` 里 Step9 写「□」的那几位记在 pages.json `lacuna_extra` |
| 真刻的□ / 残字 | 不带标记的「□」；字框 `guess` | 「□」；`□{guess=X}` | md 照写 |
| 未收字 | `text[i]` 近似字 + `zi[{ids｜desc, rel}]` | `:zi[IDS]` | 原形在 md `:zi[…]`；近似字与 `rel` 进 **`zi.json`**（guji-markdown 加属性后可并回 md，待定 ★5） |
| 规范层 | `norm[{i,t,by,why}]`（v0.2 不动，方案 C 待拍板） | 无 | **`norm.json`**（方案 C：共享表版本 + 逐位物化/例外） |
| 坐标 | IIIF canvas 整数 `[x,y,w,h]`；`canvas`/`image` 块 | `NNN.pages.json`（「版心条带、字格坐标」，用户本地版**未推上来**） | **`pages.json`（`guji-pages/0.1`，本文 §四）** |
| 版框 / 界行 | `regions[].box`、`rules` | 无 | pages.json `regions` |
| 非字元素 | `marks`（blank/excluded/seal…） | 无 | pages.json `marks` 原样 |
| 每字证据 | `method/review/conf/channel/cand` | 无 | **`proof.json`**（`guji-proof/0.1`） |
| 稳定 ID | `glyphs[].id`（`g…`，mint 自产物 sha，重切按 IoU 承接） | 无 | pages.json 格上 `id` |
| 标点 | 无 | `NNN.punct.json`（字间 token：mark/kind/pos/char_offset/pre_char/anchor/source） | 原样；`reattach` 按锚点重挂 |
| 实体 | 无 | `NNN.entity.json`（span：anchor.start/end、span offset、target） | 原样；`reattach` 按锚点重挂 |
| 合成稿 | `to_guji_markdown` / IIIF 注释 | `NNN.rich.md`、`NNN.md`（运行时合成） | 不变（派生物，不是真源） |
| 工具私有 | `ext` | — | 不进 book-text（入库口径 = `strip_ext`） |
| 册级索引 | `layout/index.json`（页 → 章映射） | `original/index.json`（章 → 文件、页范围） | 两者合一：章 → `lines_file/pages_file/…`、页范围（待定 ★7） |

### 1.2 字级字段（一字一格）

| guji-page `glyphs[]` | 合一后在哪 | 备注 |
|---|---|---|
| `id` | pages.json `cells[].id` | 稳定 ID |
| `text` `[s,e)` | pages.json `cells[].o`（全章字偏移，单字是整数）+ `c`（字，防漂移校验） | `o` 与 punct 的 `char_offset` 同口径 |
| `cv_id` | pages.json `cells[].a`（锚点 = cv_id 去册前缀）；顶层 `cv_book` 还原 | |
| `box`/`quad`/`box_from` | pages.json | canvas 整数像素、左上原点 |
| `col`/`slot`/`lane` | pages.json；能从锚点推出时省略，`lane` 缺省 `main` | `cell_defaults` 记缺省值 |
| `glyph_id`/`by` | pages.json（等于缺省值时省略） | |
| `lacuna`(unreadable/defect)/`guess`/`flags`/`prev` | pages.json | |
| `method`/`review`/`conf`/`channel`/`cand` | **proof.json** | 校对模式用 |
| `ext` | 丢弃 | |

### 1.3 字偏移的口径（两边必须一致的地方）

`o` / `char_offset` = 本章 lines.md 的字元序号：`[[]]`、`□{guess=…}`、`:zi[…]` 各算 1 字，夹注先右后左，`<!-- pN -->`、`^`、`.`、
空白不算。= guji-page 各页 `text` 首尾相接后的下标。**现有代码有两处没守住**：

- `build_anchor_map` 与 `punct_extract.tokenize` 在 `<…>` 里面不再切单元，夹注里的 `[[]]` 被数成 4 字（vol02 实测 11 位、vol03 13 位
  因此错位；用户 vol02 lines.md 按它数是 30,422 字，按口径是 30,401 字）；`:zi[…]` 也被逐符号数成字（目前 CV 导出没有组字，还没咬到）。
- 修法：`guji_format.parse_lines_md` 是按口径的解析器，`derive_anchors` 用它；`punct_extract.tokenize` 建议改调它（待定 ★4，
  文本总管的代码，本道没动）。

---

## 二、每层归哪套、谁产、谁是真源

| 文件 | 真源 | 初值谁产 | 之后谁改 | CV 重跑后 |
|---|---|---|---|---|
| `NNN.lines.md` | ✔（原样层） | CV：guji-page → `to_guji_markdown` | 人审定字（整理总管 A3）；**只改字，不改行结构** | 重新导出；字变了的位进差异报告（待定 ★3：人改过的字谁优先） |
| `NNN.pages.json` | 几何与锚点的真源 | CV：`export_guji_format.py` | 只由 CV 重导出 | 整份重导出 |
| `NNN.proof.json` | 证据快照 | CV | 只由 CV 重导出 | 整份重导出 |
| `NNN.norm.json` | 规范层（方案 C） | CV 出空表 + 共享表物化（待定 ★6） | 文本侧 | 按锚点重挂 |
| `NNN.zi.json` | 近似字与关系 | CV（目前 CV 不产组字，空） | 文本侧 / 人 | 按锚点重挂 |
| `NNN.punct.json` | ✔ | 文本侧（LLM + 规则） | 文本侧 | `reattach` |
| `NNN.entity.json` | ✔ | 文本侧（NER + book-index） | 文本侧 | `reattach` |
| `NNN.rich.md`、`NNN.md` | 派生 | 合成 | 不手改 | 重合成 |

---

## 三、锚点：怎么对上、对账结果、修法

### 3.1 口径

锚点 = `<页>:<列>:<格>[a|b]`，就是 CV 格 id `book:page:col:slot[sub]` 去掉册前缀：

- **页** = 工作区页号（拆页册 vol03/04/07/09 里 ≠ IA leaf；canvas 页序在 pages.json `canvas.seq`）；
- **列** = Step3 物理列号（从右数、1 起，**列里没字也占号**）；
- **格** = Step3 slot：正文 1 起，**抬头格为负、没有 0**（`^` 一级 = −1，`^^` = −2、−1），排除格、留白格**都占号**；
- **子列** a = 右（先读，`jz_r`）、b = 左（`jz_l`）；单行小注不带子列。

两边记法完全同构，所以「对上」只是去掉册前缀；难处在于 lines.md 数不出这个号。

### 3.2 对账（`scripts/reconcile_lines_anchors.py`，快照 vol02 `20260929T1023`+`T1024`+`20260930T0339`、vol03 `20260928T1708-full`+`20260930T0457`）

CV 产物 → guji-page → lines.md，再分别用 `build_anchor_map` 原样（legacy）与修正版 `derive_anchors`（fixed）数锚点，与 CV 格 id 逐位比。
对不上的位按**列内第一处错位的成因**归类（一列一旦错位，后面的字都跟着错，归到引起它的那一处）。报告 `samples/guji_format_v0.1/check/anchor_reconcile_vol0{2,3}.json`。

| | vol02（188 页 30,402 字） | | vol03（110 页 17,376 字） | |
|---|---|---|---|---|
| 成因 | legacy | fixed | legacy | fixed |
| **行首排除格/留白**（列首几格是排除格或留白、没折进 `lead_blank`，md 不留痕） | 532 | 532 | 3,725 | 3,725 |
| **抬头**（legacy 从 −r 数到 0；fixed 剩下的是抬头格本身是排除格、md 照写 `^`） | 209 | 144 | 1,629 | 1,571 |
| **列中排除格**（列中间的墨污格，md 不留痕） | 343 | 343 | 0 | 0 |
| **列中空格**（列中间的版式空位） | 19 | 19 | 19 | 19 |
| **夹注**（单边夹注、夹注前有排除格） | 45 | 13 | 69 | 0 |
| **记号误数**（夹注里的 `[[]]` 被数成 4 字） | 11 | 0 | 13 | 0 |
| **Step3/7 不同步**（产物过期：Step3 有格 Step7 无记录，导出时已报 warning） | 20 | 20 | 144 | 144 |
| 空列、拆页、组字 | 0 | 0 | 0 | 0 |
| **合计** | **1,179（3.9%）** | **1,071（3.5%）** | **5,599（32.2%）** | **5,459（31.4%）** |

- 空列 0 位：两册快照里没有夹在中间的空列（空列都在页尾），但这是运气不是口径——别的书会有，lines.md 不出空行就数错。
- vol03 行首排除格多：Step7 人裁把许多列首的版框残墨格判成 `human:not_a_char`（例：p3 列 2 第 1 格），字从第 2 格起，
  md 里看不出来。**这类恰恰是人裁越细、数出来越错**，说明修 `build_anchor_map` 这条路走不通。
- 拆页：vol03 p105–108 的产物建在旧裁法的图上（guji_page §2.3），锚点不受影响（锚点是 Step3 号，不是像素），但 p106 有 3 个框出 canvas，
  `check()` 报错，照 v0.2 交单要从 Step1 重跑。

**用户 book-text 现有锚点**（vol02 `002.punct.json`/`002.entity.json`，拿快照几何核）：

| | 落在 CV 同一格且字相同 | 那格在快照里是阙文 | 同页有这个字但锚点数错了 | 同页没有这个字 |
|---|---|---|---|---|
| punct 362 条 | **305（84%）** | 10 | 42 | 5 |
| entity 起点 230 | 6 | 4 | 214 | 6 |
| entity 终点 230 | 8 | 7 | 204 | 11 |

punct 锚点数错的 42 条：p3 26 条（经部总敘那页：抬头格是排除格 + 每列首两格排除）、p12 10 条、p4 4 条、p11 2 条，与上表成因一致。entity 几乎全错不是锚点口径问题，
见 §五·1。

### 3.3 修法：选「pages.json 带锚点」，不选「lines.md 加显式锚点」，`build_anchor_map` 只修三处 bug

| 做法 | 能修的 | 代价 | 取舍 |
|---|---|---|---|
| A 改 `build_anchor_map`（已做成 `derive_anchors`）：抬头跳 0、`:zi` 一字、夹注内单元照切 | 记号误数、legacy 抬头数法、部分夹注：vol02 1,179→1,071、vol03 5,599→5,459 | 无 | **做了，但只做校验** |
| B lines.md 加显式锚点（如行首 `{@3:4:3}`，或排除格写占位符） | 全部 | md 不再是纯 guji-markdown，book-text 规范、reflow、前端都要认新记号；人审改字时要小心别动它；排除格占位会把「不是字」的东西放进文本流——正是 `report/slots.py` 头上记的 09-11 教训 | **不推荐** |
| C pages.json 逐格带锚点 `a` + 字偏移 `o` + 字 `c`；lines.md 不动 | 全部（锚点就是 CV 格 id） | pages.json 必须与 lines.md 同版发布（转换器读回时字数、逐格字核对不上就报错，不静默兜底） | **推荐，已实现** |

C 下伴生层的挂法：`anchor` 用 pages.json 的锚点（`anchor_index()`）；生成伴生层的工具（`test_vol02_extract.py`）应改为从 pages.json 取
「偏移 → 锚点」，不再自己数（待定 ★4）。`derive_anchors` 留作没有 pages.json 时（手抄本、外来文本）的退路与一致性校验。

---

## 四、A2：`NNN.pages.json`（`guji-pages/0.1`）

用户 vol02 版 pages.json **没推到** book-text `wip/siku-vol02`（分支里只有 lines/punct/entity/rich/md），对读前端 kaiyuanguji-web
`wip/duidu` 也**还没推**，所以 schema 先按 #385 的描述（版心条带、字格坐标）+ guji-page 现成几何定，**待对齐**（待定 ★1）。

```jsonc
{
 "schema": "guji-pages/0.1",
 "book": {...}, "volume": {"index": 2, "cv_book": "vol02"}, "chapter": "002", "lines_file": "002.lines.md",
 "page_schema": "guji-page/0.2", "cv_book": "vol02",
 "n_chars": 30402,                         // 与 lines.md 字元数相等，读回时核
 "cell_defaults": {"lane": "main", "glyph_id": null, "by": {"box": "cv", "text": "cv"}},
 "pages": [{
   "page_id": "96mid1ogzk/2/4", "page": {"index": 4},
   "image": {"width": 2345, "height": 3122, "sha256": "…"},          // 坐标量在哪张图上（guji-page §2.2）
   "canvas": {"id": "…/canvas/02/0004", "seq": "0004", "width": 2345, "height": 3122},
   "producers": {...}, "warnings": [...],
   "o": [150, 362],                         // 本页在全章字偏移里的区间
   "regions": [{"id": "r1", "kind": "body", "box": [x,y,w,h], "rules": [[[x,y],…],…], "columns": ["c1",…]}],
   "columns": [{"id": "c1", "n": 1, "kind": "body", "box": [x,y,w,h], "raised": 0, "lead_blank": 2,
                "runs": [{"lane": "main", "o": [150, 169]}]}],          // 列条带 + 读序
   "cells": [{"id": "g2c2vyyhsr3", "a": "4:1:3", "o": 150, "c": "洛", "box": [1846,571,114,109]}, …],
   "marks": [...],                          // 留白、排除格、印章（guji-page §7 原样）
   "lacuna_extra": [...]                    // md 表达不了的阙文位（`:jz[…]` 里的），通常没有
 }]
}
```

- **字格坐标**：`cells[].box`，IIIF canvas 整数像素、左上原点（guji-page §2.1）。前端点字高亮：lines.md 字偏移 → `o` → `box`。
- **列条带**：`columns[].box` + `regions[].rules`（界行折线）。**版心条带**：CV 目前**没有版心产物**（每张图是半叶，版心在图外侧），
  `regions` 里只有 `body`；若用户版里的「版心条带」指版心那一条，要等 Step1 出版心或人工标，`regions[].kind = "banxin"` 位置已留（待定 ★1）。
- 一格一行写（`guji_format.dumps`），git 按格比对；vol02 整章 3.6 MB（gzip 1.0 MB）、vol03 2.0 MB；proof.json 4.8 / 2.7 MB 另发。
- 生成：`python scripts/export_guji_format.py --products <根> --book vol02 --chapter 002 --meta meta.json --out <dir> [--only pages]`。
  只读产物，不改现有导出；每次导出自带往返自检（读回的 guji-page 必须等于 `strip_ext(原页)`）。vol03 整册由整理总管本地出。

**样张与核对**（`samples/guji_format_v0.1/`）：vol02 p3–5、vol03 p3/p51 各一组全套文件；整章 pages.json 两册都在云端跑过
（vol02 188 页 30,402 格全有框；vol03 110 页 17,376 格、有框 17,309，缺框的是拆页 p105–108 搬 canvas 时落到外面的）。
抽字核对 `check/check_vol0{2,3}.png`：每册 4/3 页里随机抽 20 字，把 pages.json 的框画回工作区现行原图（图 sha 与 `image.sha256` **40/40 对上**）：

- **目测 40/40 框落在标注的那个字上**（含夹注 a/b、阙文位、p3 印章压字区）；
- 墨占比均值：原位 0.286 / 0.270，左右平移半框 0.175–0.191，上下平移 0.240–0.274——原位最大。
  逐字「原位必须大于四个平移」只有 9/20、10/20 成立：上下平移半格常压到邻字的墨，这个逐字判据太严，只看均值。

---

## 五、规范层、阙文、未收字、cand/channel 放哪

| 东西 | 放哪个文件 | 记法 | 理由 |
|---|---|---|---|
| 阙文 | `lines.md` | 每位一个 `[[]]`（不合并）；`:jz[…]` 里的那几位在 pages.json `lacuna_extra` | guji-markdown §13 现成；`[[]]` ↔ `text` 里「□」+ `lacuna`，一一对应 |
| 真刻的□、残字猜测 | `lines.md` | 「□」、`□{guess=X}` | 同上 §14 |
| 未收字原形 | `lines.md` | `:zi[IDS或描述]` | §16 现成，阅读稿就该带原形 |
| 未收字近似字 + 关系 | `zi.json`（`{a, o, near, ids｜desc, rel}`） | | guji-markdown 的 `:zi` 没有属性；加了 `{near= rel=}` 后可并回 md、删掉 zi.json（★5） |
| 规范层 | `norm.json`（`{table, items:[{a, o, c, t, by, why}]}`） | 方案 C：`table` 记共享归一表版本，`items` 是物化与逐位例外 | 不进 md 原文（会污染原样层）；网站规范层模式按它覆盖 |
| cand / channel / method / review | `proof.json`（`{cells:[{id, a, method, review, channel, cand}]}`） | | 只给校对模式；与几何分开发 |
| 校勘（讹脱衍倒） | 另起一层（norm_layer_proposal §五），按字框 `id`/锚点挂 | | 不归本卡 |

### 五·1 顺带查出的问题（文本侧）

1. **`002.entity.json` 的偏移是坏的**：230 条里 216 条 `span.start_offset:end_offset` 取出来的字 ≠ `text`（例「欽定四庫全書總目」取出来是「欽定四庫全總目」，
   「王柏」取出来是 `[]`）。`test_vol02_extract.py` 第 5 步用「LLM 输出去掉标点后的前缀长度」当底本偏移，没走第 3 步的对齐表；
   锚点跟着偏移一起错（起点只 6/230 落在对的格）。**修法**：实体起止也走 `annot_to_base`，锚点从 pages.json 取。重挂时 `reattach`
   会把这 224 条报成「对不上」，不猜。
2. `002.punct.json` 有一条 `pre_char` 是「]」（锚点 `4:3:7a`）——就是夹注里 `[[]]` 被数成字的那一型。
3. `003.punct.json` 没有 `anchor` 字段（只有 `char_offset`），重挂只能走偏移。

---

## 六、待定清单（要拍板的，每条附推荐）

| # | 事 | 推荐 | 备选 / 代价 |
|---|---|---|---|
| ★1 | pages.json 的 schema 以谁为准 | 先用本文 `guji-pages/0.1`；用户把 vol02 本地版推到 book-text `wip/siku-vol02`、前端 `wip/duidu` 推上来后，**按前端 WarpCanvas 实际读的字段对齐**，本道这边改 `to_guji_format` 一处。「版心条带」若指版心那一条，要 Step1 出版心或人工标 | 等用户版定了再出（拖 A2） |
| ★2 | 伴生层锚点挂 CV 格号还是稳定字框 id | **现在挂格号**（`页:列:格[子列]`，人看得懂、与 #385 一致），同时存 `char_offset`+`pre_char`；CV 重切后由导出器按 `carry_ids`（IoU 承接）把旧格号映到新格号再 `reattach` | 改挂 `g…` 稳定 id：重切不怕，但人读不懂、与 #385 不一致 |
| ★3 | lines.md 被人改了字，CV 重导出时谁优先 | **人改的优先**：CV 重导出前先读现行 lines.md，按锚点把人改过的字回写成 guji-page 的 `human` 字框（再出新 lines.md），差异列报告 | CV 覆盖：简单但会冲掉人审 |
| ★4 | 伴生层生成工具（`test_vol02_extract.py`、`punct_extract.tokenize`）改为从 pages.json 取锚点、用 `parse_lines_md` 的字偏移口径 | **改**（文本总管的代码，本道没动；改动小：`build_anchor_map` 换成 `gf.anchor_index`） | 不改：继续出错锚点（vol02 现有 362 条标点里 42 条锚点数错，p3 一页 26 条） |
| ★5 | 未收字的近似字放 md 还是 zi.json | 先放 `zi.json`；guji-markdown 给 `:zi` 加可选 `{near=X rel=Y}` 后并回 md（guji_page v0.2 待定 13 同一件事） | 现在就加属性：要 guji-markdown 改规范 |
| ★6 | norm.json 初值谁填 | 方案 C 拍板后由 CV 导出器按共享表物化一份初值（`by` 指表版本），逐位例外文本侧填 | 留空等文本侧 |
| ★7 | 册级索引合一 | book-text `original/index.json` 每章加 `pages_file`/`proof_file`/`norm_file`/`zi_file` 四个键；guji-page 的 `layout/index.json` 不再单独入库 | 两份并存 |
| ★8 | proof.json 进不进 book-text | **进**（校对模式要读，且是「记录先行」的落点），但不进阅读稿的 manifest | 只留在 CV 工作区：网站校对模式读不到 |
| ★9 | 行首排除格要不要折进 `lead_blank` | 不折：排除格是「这里有墨但不是字」，lead_blank 是版式留白，混了会让 md 多出 `.`、reflow 判段出错。锚点靠 pages.json 就够 | 折进去：数出来的锚点能对上更多，但语义错 |
