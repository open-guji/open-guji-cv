# 交单 · C 道 · overview#247 定字裁决按类别审 + 己已巳专用卡

分支 `claude/C-review-by-class-0928`（基于 main `b18e1e5`，未动 main）。

> **为什么是这份文件而不是 #247 的评论**：本会话读 / 评 `open-guji-core/overview` 被权限拒了
> （仓库不在会话范围，挂仓请求被自动模式拦下）。#247 原文也没读到，**按派单摘要做的**。
> 请值守把本文件贴到 #247，或给会话开 overview 的权限。

## 结论

- (一) 层级改好：**范围 → 类别（主导航，点了就载入，按钮带剩余张数）→ 本类细项（条数、含已裁决、
  先切线后字符、批次，默认收起）**。队列模式：提交后自动载入同一类下一批，显示「本类还剩 N」。
  一张卡只归优先级最高的一类。卡片样式与快捷键随类别变。
- (二) 己已巳专用卡：只有 己/已/巳（1/2/3）＋「都不是」（4/0）；不显示整理本、库分、次选、OCR。
  上下文前后各 20 字、跨列跨页、**取整理本对位原文**（本位遮成「？」）。通用卡上下文也默认改整理本，
  刻本读法放到「上下文用刻本读法」开关后面。
- **事件协议没变**：三选一发的行与普通卡点同一个字逐字段相同，下游 `human_chars` 读出的字不变（用例守着）。
- **康熙部首码位：整理本里 0 个**（数字见下），加了归一护栏。
- 真规模实测：四庫 vol03 首次载入 14.7 s → 10.1 s，**提交后重载 13.9 s → 1.8 s**，峰值 RSS **747 MB → 185 MB**。

## (一) 类别

正本在 `review/cards.py::REVIEW_CLASSES` / `card_class`（纯函数），表序即优先级：

| 优先级 | 键 | 名 | 命中条件 | vol03 | v006 |
|---|---|---|---|---|---|
| 1 | occluded | 印章遮挡 | `occluded` 码或证据 | 129 | 4 |
| 2 | ji_yi_si | 己已巳 | 字／整理本字／库首选任一在本族，或 `ji_yi_si` 证据、`ji_yi_si_review` 码 | 32 | 0 |
| 3 | form_open | 义定形未定 | `form_open` | 0 | 0 |
| 4 | ref_conflict | 与整理本冲突 | context_vs_ref / iron_vs_ref / signal_conflict | 76 | 0 |
| 5 | near_form | 形近字 | near_form / solo_confusable | 66 | 113 |
| 6 | lib_miss | 库里没有 | 「库里没有这个字」 | 3 | 95 |
| 7 | variant | 异体／通道 | variant_indirect / replace_form / channel_off / ref_lib_variant | 0 | 163 |
| 8 | replace_align | 对齐改字层 | replace_align | 330 | 1268 |
| 9 | other | 其余 | 库 unsure、上下文 margin 不足等 | 116 | 405 |
| | | **合计** | | **752** | **2048** |

（范围＝只看待审、先切线后字符开、跳过已裁；vol03 1–111 页、v006 1–87 页。）

为什么要另立类别、不直接用 #215 的 doubt 码：vol03 待审 804 张里 357 张同时带三条疑因，按码筛同一张卡
在三个按钮下各出现一次，裁完一类别的按钮数不动。**#215 的 `doubt=` 后端参数原样保留**（别的地方还能用），
面板上的码按钮换成了类别按钮；印章遮挡「整组确认」挪到选中「印章遮挡」类时出现。

各类卡片：
- 己已巳：专用卡（见下）。
- 印章遮挡：原样（默认整理本字、字形不入库）＋整组确认按钮。
- 库里没有：当前卡自动「查候选」（10 个）。
- 其余类：通用卡；卡片左上角一段类别色条。帮助行（快捷键说明）随类别换。

接口：`GET /api/review/cards?…&cls=*|<类别键>`。给了就每张卡带 `cls`，响应多 `class_counts`（不受 `limit`
截断）/`class_total`/`classes`；不给则与改前一致（缓存键也不变）。坏值 400。

## (二) 己已巳专用卡

- 选项 `1 己 · 2 已 · 3 巳`，`4`/`0` = 都不是 → 这张卡展开成普通卡（不发事件，人自己挑字／非字／跳过）。
  N/S 照常；T/C/D 在这张卡上不响应（卡上没有这几个按钮）。
- 上下文：`/api/review/around/batch` 前后各 20，一批卡一次请求（不是一卡一请求）；每格新增
  `ref`（整理本对位字）、`text`（显示用：有整理本字用它，否则退回刻本定字）、`text_src`；
  响应多 `ref_text`。原来的 `char`/`text` 不变。项里带 `sub` 时按 (slot, sub) 取本位、返回键 `p:c:s<sub>`
  （夹注 a/b 以前会取到同一格）。读序改用 `sort_by_reading`（无夹注的列与原排序完全相同）。
- 本位遮成「？」：不让整理本在这一格的字替人答（四庫整理本自己也把「而已」印成「而巳」）。
- **事件协议**：裁决 → 事件行抽成 `reviewClass.ts::verdictRow`，所有卡型共用；三选一走与普通卡改字同一个
  `pickVerdict`。结果 = `{id, v:'confirm', shape:<选的字>, no_glyph_lib, client_ts, dwell_ms}`，与改前一模一样。
  字形按现有规则（己已巳在库里样本封顶，`seed_admit` 对本族取事件的字）。
  用例：`tests/test_review_by_class.py` 里 node 跑 `reviewClass.ts` 断言三选一行 == 普通卡行、各档行形状与改前
  submit 逐字段相同；再把这些行按 `/api/events` 的同一句 payload 规则写进 EventLog，断言 `human_chars` 读出
  已/巳/己（`seg_defect` 带字也算）。

## 康熙部首核查

扫描 U+2F00–U+2FDF（康熙部首）与 U+2E80–U+2EFF（部首补充）：

| 文件 | 康熙部首 | 部首补充 |
|---|---|---|
| 四庫 corpus 5 份（含 siku_daizhige.txt、zongmu_wenyuange_wikisource.txt） | 0 | 0 |
| 四庫 corpus/daizhige/*.jsonl（戴震閣原始） | 0 | 8（全是 ⺊ U+2E8A） |
| 北行日錄校對本 | 0 | 0 |
| 全唐文維基逐卷本 16 份（qtw_wikisource_*，取自 products-snap 分支） | 0 | 0 |
| 全唐文 Kanripo 本 + repairs/notes 表（z8/qtw-draft 分支） | 0 | 12（⺡⻏⺨⻖，在注释表格里） |
| 仓内 corpus/ 6 份 | 0 | 0 |
| vol03 / v006 align_ref 产物 | 0 | 0 |

**没有需要归一的**。发现一个隐患顺手记下：`steps/align_ref._corpus_text` 只留 U+4E00–U+9FFF，部首码位会被
**整个删掉**（整理本少一个字、对位从那里起错一格）。眼下 0 个所以没后果；没改 `align_ref`（改了会让全部书的
align_ref 产物按代码指纹过期重跑）。加的是护栏：`utils/radicals.py::fold_radicals`（只做 NFKC 给得出的映射，
康熙部首 214 个全有，补充区只有 ⺟→母、⻳→龟），卡片「整理本」一栏与上下文的整理本字都过它。
**建议**下次 align_ref 本来就要升版时把它接进 `_corpus_text`。⺊ 这类没有兼容分解的不动。

## 真规模实测（耗时与 RSS）

路由级（FastAPI TestClient，每行一个新进程 = 控制台冷启动后的一串操作），工作区 = guji-workspace 浅克隆
＋快照分支 `snap/96mid1ogzk/vol03/20260928T1708-full`、`snap/qtw-draft/v006/20260928T1725` 的产物，
列图缓存预先热过；OLD = origin/main `b18e1e5` 的面板请求序列，NEW = 本分支。

**四庫 vol03（1–111 页，待审 752）**

| 操作 | OLD | NEW |
|---|---|---|
| 首次载入（OLD `doubt=*` / NEW `cls=*`） | 14.68 s | 10.09 s |
| 点类别（`cls=ji_yi_si`） | — | 1.95 s |
| 上下文 around/batch（OLD 10/10，NEW 20/20，30 卡一次） | 0.02 s | 0.30 s |
| 提交 1 条 | 0.14 s | 0.16 s |
| **提交后重载（队列：同类下一批）** | **13.92 s** | **1.79 s** |
| 峰值 RSS | **747 MB** | **185 MB** |

**全唐文 v006（1–87 页，待审 2048）**

| 操作 | OLD | NEW |
|---|---|---|
| 首次载入 | 3.04 s | 2.38 s |
| 点类别 | — | 2.33 s |
| 上下文 around/batch 20/20 | 0.01 s | 0.01 s |
| 提交后重载 | 2.94 s | 2.30 s |
| 峰值 RSS | 149 MB | 143 MB |

提速／降内存从哪来：
1. 卡片「整理本」一栏改读 `align_ref` 产物（就是 seed_admit 准入用的那份对位），不再绕
   `gold.v2_align.align_book`。那条路只要有一页缺产物（vol03 p111）就现建 34 万字的 8-gram 索引：
   6.4 s、约 600 MB。`align_book` 本身也改成惰性建索引（产物都新鲜时一次不建，结果逐字节不变），
   jiazhu_cards 与 eval 也受益。
2. 顺序闸（先切线后字符）取切线用例要把页范围里每一列的列图读一遍求投影：vol03 1788 列、8.8 s。
   它只看切分产物与列图、与事件无关，加了进程内记忆（键 = 切分段产物 manifest＋逐页文件 stat＋列图缓存根
   ＋两个取用例函数本身；识别段的步不进键，因为人裁一条 confirm 就会把那页 seed_admit 标失效）。
   **只记完整成功的**：有列取不到列图时不记，冷缓存兜底的语义不变。
3. v006 在沙箱里提速不明显，原因在沙箱：工作区仓里没有原图，738 列列图做不出来，顺序闸每次都走保守兜底、
   记忆按设计不记。服务器上有原图，行为应同 vol03，**但没在服务器上量过**。
4. NEW 的首次载入仍要 10 s（冷进程第一次读列图）；控制台是常驻进程，之后同书同页范围都走记忆。

UI 用 headless Chromium 在真 vol03 上点过：类别栏计数、己已巳卡（1/2/3 选字跳下一张、4 展开成普通卡）、
通用卡上下文整理本/刻本切换（例：整理本「鄉」vs 刻本「嫏」）、细项折叠。

## 测试

- `.venv/bin/python -m pytest tests/ -s -q -p no:cacheprovider`：**2340 passed, 27 skipped, 1 failed**（下面那条预先就红的）。
- 新增 `tests/test_review_by_class.py` 13 条（归类优先级、计数不截断、无 cls 时无新字段、整理本读产物＋部首归一、
  路由与缓存键、上下文整理本优先与 sub、node 跑 TS 守事件协议、human_chars 下游、切线用例记忆的失效条件）。
- 前端：`tsc -b` 过；`npm run build` 重出 `static/dist`。
- **预先就红的一条**：`tests/test_cut_select.py::test_ckpt_fingerprint_empty_for_missing_file`，在未改动的
  origin/main worktree 里同样失败（本环境 U-Net 权重是 LFS 指针文件，`ckpt_fingerprint()` 返回空串），与本单无关。

## 拿不准、按保守做法走的（请裁）

1. **类别表与优先级是我定的**（摘要只说「按原因升为主导航」「只归最高优先级」）。依据：先挑卡片形态不同的，
   再按「人该看什么」排。改表只动 `REVIEW_CLASSES`／`card_class` 一处。
2. 己已巳判定用「字／整理本字／库首选任一在本族」——宽。宽的代价是偶尔把别的字端进三选一卡，有「都不是」兜；
   窄了会把真己已巳漏到通用卡。
3. 「都不是」不发任何事件，只把卡展开成普通卡。
4. 己已巳卡没显示 `ji_yi_si.resolve` 的规则建议字（摘要要求隐藏整理本/库分/次选/OCR，规则建议部分依赖整理本）。
5. 卡片 `ref` 来源从 `align_book` 换成 `align_ref` 产物：两者只在「产物缺页或语料指纹过期」时不同
   （vol03 只有 p111 一页：旧路现算锚上了，新路没有整理本字）。卡片缓存版本 `CARDS_CACHE_VERSION` 1→2。
6. 「含已裁决」开着时提交后**不**自动翻下一批（复核模式，翻了就看不到刚裁的）。

## 改动清单

- `open_guji_cv/review/cards.py`：`REVIEW_CLASSES`/`card_class`/`parse_class_filter`、`cards(cls=)`、
  `_align_ref_maps`、切线用例记忆 `_cutline_cases`。
- `open_guji_cv/console/routers/review.py`：路由 `cls` 参数；上下文每格整理本字、`sub`、`ref_text`。
- `open_guji_cv/gold/v2_align.py`：索引惰性建。
- `open_guji_cv/utils/radicals.py`（新）。
- 前端：`reviewClass.ts`（新，纯函数）、`ReviewPanel.tsx`、`ReviewCardView.tsx`、`review.css`、`types/review.ts`、
  `api/review.ts`；`static/dist` 重出。
- `tests/test_review_by_class.py`（新）。
