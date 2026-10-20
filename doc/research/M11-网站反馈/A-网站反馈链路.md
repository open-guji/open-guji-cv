# A · 网站侧反馈链路调研（kaiyuanguji-web）

> 服务于 M11「网站反馈流程梳理」（Jira GUJI-638）。范围：只看**文字**（改字、缺/多字、错位），不看标点与专名号（相关代码只在需要说明数据形状时带到）。
> 依据：`/home/user/open-guji/kaiyuanguji-web` 只读克隆，HEAD `1df0cc4`（2026-10-19）。下文路径都相对这个仓根；`文件:行号` 是事实，标「推测」的是推断。
> 阅读器组件 `book-index-ui` 是外部 npm 包（`nextjs/package.json:22`，`^0.61.1`），源码不在本仓，本地也没装 node_modules，它内部的「报告错字」右栏只能从接线代码与测试反推。

---

## 0. 一页总览

网站上现在有 **四套互不相通的「读者意见」通道**，各写各的 KV 前缀，同存一个 KV 命名空间 `FEEDBACK_KV`：

| 通道 | 用户入口 | 接口 | KV key | 定位精度 | 有状态机？ | 下游 |
|---|---|---|---|---|---|---|
| ① 通用反馈 | 顶栏「反馈」、条目页「这条有误？」、阅读页选字「报错」（非对读章／无版本时的回落）、阅读器右栏「报告错字」 | `POST /api/feedback` | `fb_<毫秒>_<4位>` | **只有** pageUrl（含章号）＋可选 `#rd-e-N`＋正文里拼的「【原文】…」≤200 字 | 有：pending／in_progress／resolved／wontfix／duplicate | **无任何导出**；只在 /admin/feedback 人工处置 |
| ② 改字／一段有问题／专名意见 | 对读章点字→浮条「改字」；拖选→「報錯」→「這段有問題」；浮条「专名有误」 | `POST /api/charfix`（kind=char／span／entity） | `cf:` `cs:` `ce:` | **格位**（`页:列:格[ab]`）＋`text_version`＋原字（取自 char.json） | 记录本身没有；另有 `fs:` 状态记录 open／adopted／rejected／discussing | 每日 Action 拉进中心库 `feedback/lists/web/<书>/fixes.jsonl`，再发 COS 公开清单 |
| ③ 讨论 | `/feedback/text` 每处意见下「同意／有不同看法／回复」 | `POST /api/thread` | `tv:` `tm:` | 挂在 ② 的「一处」上（target） | 无 | 每日进中心库 `threads.jsonl` |
| ④ 精校（待审格投票） | `/proofing/<书>/<册>`：每格候选字／另写一字／「图上没有字」「看不清」「切分错了」「这是夹注小字」 | `POST /api/cellreview` | `cr:` | 格位＋待审单 `rev` | 无（下游判） | 每日进中心库 `feedback/lists/web/<书>/<rev>.jsonl` |

另有只读与管理接口：`GET /api/fixes`（②③＋状态的公开实时读）、`POST /api/fixes`（整理组回写状态／回复，**站内没有任何页面调用**）。

**一句话结论**：② 和 ④ 已经能把「格位＋版本＋原字＋建议字」送进中心库，形状离 CV 的人裁事件很近，但到中心库就停了（网站仓里没有任何东西把它们变成 glyph_store 事件或 book-text 改动）；① 是最常被用到的入口之一，却完全不带格位与版本，也不出网站。状态回显只在 ② 有雏形，且只靠手工 curl 写。

---

## 1. 用户入口（逐个）

### 1.1 阅读页总装：`nextjs/src/app/read/[id]/ReaderClient.tsx`

阅读页把下面这些入口全挂在同一个正文容器 `textRef` 上：
- `<ProofingNotice …/>` 在阅读器上方（`ReaderClient.tsx:347`）
- `<TextReader … onReportError={onReportError} …/>`（book-index-ui，`ReaderClient.tsx:349-365`）
- `<SelectionReport containerRef={textRef} context={feedbackContext} getCtx={getCharfixCtx} />`（`:367`）
- `<CharFixEntry containerRef={textRef} getCtx={getCharfixCtx} />`（`:368`）
- `<ReaderProof …/>`（校对层，只读，`:369`）

**改字上下文 `CharFixCtx` 的来历**（②的定位信息全从这里来）：
- 只有章条目声明了 `char_file`＋`cord_file`（对读章）才会建（`ReaderClient.tsx:279-286`）；纯 .txt 章没有 `data-char-id`，没有改字入口（`CharFixEntry.tsx:41`）。
- `book = id`；`volume = String(chapterFile ?? chapterKey)`；`chapter = chapterKey`（`ReaderClient.tsx:297-299`）。
- `textVersion`：章条目 `text_version`，缺则 `char.json` 的 `version`，都不合 `^[A-Za-z0-9._-]{1,16}$` 就是空串——空串时**不收改字**（`ReaderClient.tsx:288-291`，`charfix.ts:133`）。
- `chars`：`格位 → char.json 原字` 的 Map（`ReaderClient.tsx:301`，`charfix.ts:62-73`）。old_char 一律取 char.json，不取 DOM（DOM 可能经过繁简转换）（`charfix.ts:4`）。
- `entities／entityVersion`：专名层，异步并进来（`ReaderClient.tsx:325-336`）。

**通用反馈上下文**：`{resourceId: id, label: 「书名 · 版本 · 卷N」}`（`ReaderClient.tsx:231-242`），章号不单独传，靠提交时的 `window.location.href`（`lib/feedback.ts:6-8`）。

### 1.2 选字「复制｜报错」浮条：`components/feedback/SelectionReport.tsx`

- **触发**：在正文容器内拖选文字，`selectionchange` 停 200ms 后量位置（`SelectionReport.tsx:73-93`）；桌面浮在选区上方，触屏（`pointer: coarse`）放下方（`:62-69`）；滚动／缩放即收起（`:80-86`）；输入框里的选区不弹（`:32-35`）。
- **点「报错」的分流**（`:107-116`）：
  - 有改字上下文 **且** 本章有合法 textVersion **且** 选区里至少有一个带 `data-char-id` 的字 → 开 `SpanFixDialog`（kind=span，见 1.5）；
  - 否则 → `open({context:{…context, quote}, type:'bug'})`，走通用反馈弹窗（见 1.3）。
- 选区 → 首末格位：`spanOfRange` 按文档序取选区里第一个与最后一个 `data-char-id`，同格位去重；原文按 char.json 拼，>64 字截断（`charfix.ts:215-228`）。

### 1.3 通用反馈弹窗：`components/feedback/FeedbackProvider.tsx` ＋ `FeedbackDialog.tsx` ＋ `lib/feedback.ts`

- **Provider**：全站唯一弹窗，挂在 LayoutWrapper；调用方：顶栏「反馈」（`layout/Navbar.tsx:57`）、条目页「这条有误？」（`book-index/CitationBar.tsx:57-60`）、阅读页选字回落（上节）、阅读器右栏「报告错字」（`ReaderClient.tsx:245-255`）、/feedback「写反馈」（`FeedbackPageContent.tsx:145`）。
- **表单字段**（`FeedbackDialog.tsx`）：
  - 类型页签 4 个：bug（内容有误）｜resource｜suggestion｜contact（想参与，永不公开）（`lib/feedback.ts:29-33`；后端另收 `other`）；
  - 「关于」一行（label）与引文 `quote`（可点「不带」去掉上下文，`FeedbackDialog.tsx:159-168`）；
  - 子类 subtype：只在 type=bug 且有 quote 时出现，可选 char／punct／name／version，不选不上送（`FeedbackDialog.tsx:55-56,170-184`；`lib/feedback.ts:37-43`）；
  - 正文 textarea，上限 = 2000 − 引文前缀长度（`lib/feedback.ts:95-97`）；
  - 联系方式（选填，≤200，只给站方看）（`FeedbackDialog.tsx:201-210`）。
- **提交体**（`lib/feedback.ts:123-134`）：`{type, content: "【原文】<quote≤200，空白压成单空格>\n\n<读者的话>", pageUrl: location.href（若有 rd-e-N 锚点换掉 #）, resourceId（合法条目 id 才留）, contact?, subtype?}`。
- **提交到** `/api/feedback`（同源，`lib/feedback.ts:137-158`）；成功把返回的 `fb_` id 记进本机 localStorage `guji.feedback.mine`（最多 100 条），用于 /feedback 上高亮「我的」（`lib/feedback.ts:161-190`）。
- **定位信息**：只有 pageUrl（`/read/<id>/<章>`）、可选 `#rd-e-N`（阅读器条目锚点，**不是格位**）、引文文字。**没有**册／页／列／格号、字偏移、文本版本、图坐标。
- 附图：无（全仓无 `type="file"`）。登录：不要。匿名：是。限速：同 IP 10 条／10 分钟（见 2.1）。

### 1.4 点字「改字」浮条与弹窗：`components/CharFixEntry.tsx` ＋ `lib/charfix.ts`

- **触发**：在对读章正文里**单击**一个字（无选区时），`cellIdOf` 取最近的 `[data-char-id]`（`CharFixEntry.tsx:54-73`，`charfix.ts:136-140`）；浮条锚在字旁，写「第 4 页 3 列 8 格「於」［改字］［专名有误］×」（`CharFixEntry.tsx:114-129`）。本章缺 textVersion 时「改字」换成提示「本章缺文本版本，暂不能改字」（`:124-126`）。
- **改字弹窗字段**（`CharFixEntry.tsx:175-228`）：建议字 `new_char`（单字或 `{{组字式}}`，与原字不同，`charfix.ts:22-28`）、依据 `basis`（选填 ≤500）。
- **提交体**（`charfix.ts:164-178`）：`{kind:'char', book_id, volume, text_version, cell_id, old_char?（取 char.json）, new_char, basis?, entity_ids（该格落在哪些专名 anchor 里）, aid}` → `POST /api/charfix`。
- 成功页文案「已收到，谢谢。我们核对后会在整理本中更正。」＋链接「看全部」到 `/feedback/text?book=&vol=`（`CharFixEntry.tsx:191`，`i18n/messages/charfix.ts:122`）。
- 附图：无；弹窗里**不显示该格书影裁图**，只有「第 N 页 N 列 N 格「原字」」。登录：不要。限速：同 IP 30 条／10 分钟（`edge-functions/api/charfix.js:50`）。

### 1.5 「这段有问题」弹窗：`components/SpanFixDialog.tsx`

- 由 1.2 的选字「报错」进入。字段：类别 `sub`（错字 wrong｜缺字 missing｜多字 extra｜次序 order｜标点 punct｜分段 para｜标题 heading｜小注 note｜专名 entity｜其他 other，默认 wrong）、「應作」`new_text`（≤64）、「說明」`note`（≤500），后两项至少一项（`SpanFixDialog.tsx:23-39,48-71`；`charfix.ts:197`）。
- **提交体**（`charfix.ts:238-252`）：`{kind:'span', book_id, volume, text_version, start, end, sub, old_text?（char.json 拼的选区原文，≤64）, new_text?, note?, aid}`。
- 对「文字」最相关的是 wrong／missing／extra／order 四类。

### 1.6 阅读器右栏「报告错字」（book-index-ui 内部，`ReaderReport`）

- 网站只接了回调 `onReportError(ctx: ReaderReportContext)`，把它转成**通用反馈**弹窗：`{resourceId: ctx.entryId||id, label, quote: ctx.selectedText, anchor: ctx.anchor}`，type=bug（`ReaderClient.tsx:243-255`）。
- 测试里 `ctx` 形如 `{bookTitle, entryId, chapterKey, selectedText, anchor:'rd-e-3'}`（`app/read/[id]/__tests__/ReaderReport.test.tsx:43-53`）。
- 也就是说：**即使在对读章，右栏「报告错字」也不带格位与文本版本**，进的是 `fb_` 而不是 `cf:`/`cs:`。

### 1.7 阅读页顶部提示条：`app/read/[id]/ProofingNotice.tsx`

- 两个互斥阶段（`ProofingNotice.tsx:20-22`）：
  - v0.x 校对中（COS 待审单总表 `proof/index.json` 里该章 n>0，或回落到章条目 `proofing:true` 且 `pending_file` 非空）→「这一章正在校对」＋「参与校对 →」去 `/proofing/<书>/<章>`（`ReaderClient.tsx:79-91,111-112`）；
  - 不在校对且章条目 `text_version` 主版本 ≥1 → 「这一章已校定，发现问题请告诉我们：选中文字即可报错」＋「读者反馈 →」去 `/feedback/text?book=&vol=`（`ReaderClient.tsx:113-115`，`ProofingNotice.tsx:39-52`）。
- 点 × 后本标签页（sessionStorage）不再出现（`ProofingNotice.tsx:7-10,57`）。
- 版本号小标签 `TextVersionChip`：书名栏里「文本 v0.1.4」，悬停列文本／标点／专名三线版本，并按主版本说「校对中／可用／出版级／定本」（`TextVersionChip.tsx:26-33,113,137`）。只有 `is_original` 版本才出（`ReaderClient.tsx:106-107`）。

### 1.8 精校页（cellreview）：`app/proofing/[book]/[vol]/ProofingClient.tsx` ＋ `lib/proofing.ts`

- **数据**：先读 COS `proof/<书>/<章>.pending.json`（中心库每日发布），没有再按 book-text 章条目的 `pending_file`（`proofing.ts:486-523`）；`rev` 是待审单版本，提交时必须原样带回（`proofing.ts:57-60`；`ProofingClient.tsx:581`）。
- **每格卡片**：原叶裁图（pending 里的 `box` 或按格位到 cord 查）、上下文、为什么要人看（`why`）、候选字按钮（前 3＋更多）、相似字格（alt）、「另写一字」输入、预选（`ProofingClient.tsx:296-356`；`proofing.ts:193-209`）。
- **按钮（客户端实际只有 5 档）**：char（选字／另写一字）＋ `OTHER_CHOICES`：none「图上没有字」｜unsure「看不清」｜cut「切分错了」｜jiazhu「这是夹注小字」（`ProofingClient.tsx:27-32`；`proofing.ts:528`）。后端白名单还有第 6 档 `main`（`edge-functions/api/cellreview.js:24`），**前端没有按钮**。
- **提交体**（`ProofingClient.tsx:580-590`，`proofing.ts:530-559`）：`{book, vol, a, rev, choice, char?, shown?（页面显示的机器读字）, aid}` → `POST /api/cellreview`。后端还收 `note`（≤500，`cellreview.js:72-77`），**前端从不发**。
- 「您已回应 x / y」进度只存本机 localStorage `kyg-cr-done:<rev>`（`proofing.ts:562-581`；`ProofingClient.tsx:584-587`）。
- 页面写明「不用登录，意见匿名收集，供整理时参考」（`ProofingClient.tsx:495`）。限速同 IP 120 条／10 分钟（`cellreview.js:38-40`）。

### 1.9 其他入口
- `components/book-index/FeedbackTab.tsx`：旧的条目页反馈 tab，**全仓无引用**（死代码）；localhost 下会直连正式站 `/api/feedback`（`FeedbackTab.tsx:12-14`）。`BookDetailContent.tsx:61-66` 同样把 localhost 指到正式站，交给 book-index-ui 的条目页表单（不在文字范围内，略）。
- `ReaderProof.tsx`：`?proof=1` 打开的校对层，只把 proof.json 的存疑／缺字／人校状态叠到字上，**不提交任何东西**（`ReaderProof.tsx:5-16,69-72`）。

---

## 2. 后端（edge-functions/api/）

> nextjs 下没有反馈类 API 路由（`nextjs/src/app/api/` 只有 `book-index/[...slug]`）。全部在 EdgeOne Pages 边缘函数，存储全是 **EdgeOne KV**（绑定名 `FEEDBACK_KV`），没有 D1/R2/数据库。可选 GitHub 模式（见 2.1）。

### 2.1 `/api/feedback`（`edge-functions/api/feedback.js`，1127 行）

- **三条路**（文件头 `:1-39`）：
  - `POST`（无 action）提交：公开、匿名；
  - `GET` 列表：公开读剔除 hidden／test／contact 类，去掉 `contact`／`updatedBy`／`routedIssue`／`resolvedRef`，正文脱敏（邮箱、手机、QQ／微信、身份证）（`:387-433`）；带管理 token（`Authorization: Bearer`）或成员 cookie（reviewer／editor／admin）返回全量原样（`:953-957`）；`?summary=1` 只回计数给监控（`:946-948,1004-1032`）；
  - `POST {action:'update'}` 管理改记录（token 或成员 cookie，fail-closed：没配 `FEEDBACK_ADMIN_TOKEN` 一律 503）（`:197-206,626-698`）；`PATCH /api/feedback/:id` 同等鉴权但 EdgeOne 实测不路由（`:1040-1106`）。
- **存储模式**：`FEEDBACK_MODE=kv`（默认）｜`github`；github 模式把反馈开成 `open-guji/book-index-draft` 的 issue（label 反馈-错误／反馈-资源），列表从 issue 读（`:171-179,500-554`）。现行是 kv（推测：架构文档只写 KV，`docs/architecture.html:306`）。
- **记录 schema**（`kvPost` `:357-380` ＋ `kvPatch` `:579-615`）——逐字段：

| 字段 | 写入方 | 说明 |
|---|---|---|
| `id` | 提交 | `fb_<13位毫秒>_<4位随机>`（`:60-64`），也是 KV key |
| `type` | 提交／管理改 | bug｜resource｜suggestion｜contact｜other（`:68`） |
| `content` | 提交 | trim 后 ≤2000（`:733-737`）；阅读页带引文时开头是「【原文】…\n\n」 |
| `pageUrl` | 提交 | ≤500（`:299-305`），阅读页即 `/read/<id>/<章>[#rd-e-N]` |
| `resourceId` | 提交 | ≤500，条目 id |
| `createdAt` | 提交 | ISO |
| `status` | 提交=pending／管理改 | pending｜in_progress｜resolved｜wontfix｜duplicate（`:69`） |
| `reply` | 管理 | 站方回复，**公开显示** |
| `category` | 提交时规则分类／管理改 | typo｜entry｜site｜join｜other（`feedback-classify.js:5,41-59`）；/read/ 下 bug→typo |
| `subtype` | 提交（可选）／管理改 | char｜punct｜name｜version｜unspecified（`feedback-classify.js:7`） |
| `contact` | 提交（可选） | ≤200，仅站方可见（`:710`） |
| `test` | 提交（Origin=localhost 或 body.test）／管理改 | 测试数据，公开读不出（`:711-715`） |
| `visibility` | 管理 | public｜hidden；contact 类强制 hidden（`:376,609`） |
| `duplicateOf` | 管理 | 指向另一条 `fb_`，须存在（`:681-688`） |
| `assignee` | 管理 | 认领「块」：catalog｜web｜text｜cv｜collate｜layout｜owner（`feedback-classify.js:10`） |
| `claimedAt` | 服务端 | 首次认领时写（`:598-606`） |
| `routedIssue` | 管理 | `owner/repo#n`（`:557`），**admin 页面没有输入框**（`FeedbackView.tsx:37-41` 的 Patch 不含它） |
| `resolvedRef` | 管理 | `owner/repo@sha` 或 `owner/repo#n`（`:559`），内部凭据 |
| `updatedAt` / `updatedBy` | 服务端 | updatedBy＝'token' 或成员邮箱 |

- **状态机**：只有白名单，没有转移约束——任何状态可直接改成任何状态（`:644-648,582`）。admin 的「标记已改」要求写公开回复、已改须带 resolvedRef（前端校验，`FeedbackView.tsx:156-162`，后端不强制）。
- **去重**：无自动去重；靠管理员手工标 duplicate（`FeedbackView.tsx:384-402`）。
- **限速**：同 IP（取 `request.eo.clientIp` 的 sha256，取不到就**不限**）10 条／10 分钟固定窗口，KV 出错放行（`:307-353`）。
- **新反馈通知**：推到 `HEALTH_NOTIFY_WEBHOOK`（飞书／钉钉／Slack／PushPlus 个人微信），5 分钟最多 1 条、其余合并计数，测试数据不推（`:109-169,766-773`）。**只通知站方，不通知反馈者**。
- **列表性能**：每次读都把所有 `fb_` key 列一遍再倒序取值，按 resourceId 过滤最坏读遍全部值（`:449-496`，注释自认「到上千条再建索引」）；公开读 30 秒新鲜／10 分钟过期缓存＋8 秒 KV 预算（`:25-36,789-937`）。
- **硬删除**：没有；「删除」＝ `test=true`＋`visibility=hidden`（`ops/feedback-hide.mjs:4-6`，手动 Action `.github/workflows/feedback-hide.yml`）。

### 2.2 `/api/charfix`（`edge-functions/api/charfix.js`，261 行）

- **POST 公开**，kind=char（缺省）｜entity｜span；**GET 只开管理读**（token 或成员 cookie），按前缀导出（`charfix.js:1-17,207-247`）。
- **key**（`:12-16,191-196`）：
  - 改字 `cf:<book>:<volume>:<text_version>:<cell_id>:<voter>`
  - 一段 `cs:<book>:<volume>:<text_version>:<start>-<end>:<sub>:<voter>`
  - 专名 `ce:<book>:<volume>:<entity_id>:<voter>`
  - `voter = sha256(aid|ip)` 前 16 位；值里不存 aid、不存 IP（`:17,189-190`）。
- **值**：`{v:1, ...校验后的字段（去掉 aid）, voter, ts}`，`expirationTtl` 180 天（`:27,196`）。字段见第 8 节原文。
- **校验**（`validateFix` `:73-169`）：book `^[0-9a-z]{4,24}$`；volume／text_version `^[A-Za-z0-9._-]{1,16}$`；cell `^\d{1,6}:\d{1,4}:-?\d{1,4}[ab]?$`（含抬头字 -1 格）；new_char 单字或 `{{组字式}}`；old_char ≤32 码点且不得等于 new_char；span 的 new_text／note 至少一项。
- **服务端不核 old_char 是否等于该格原字**（拿不到 char.json，`:10`）。
- **同来源同处覆盖**：同一 voter 对同一格（或同 start-end-sub）再提就覆盖（`:5`）。
- **限速**：同 IP 30 条／10 分钟，独立前缀 `ratelimit:cf:`（`:50`）。
- **KV 平台口径**（作者 GUJI-590 核对的注释）：list 每页 ≤256；最终一致、边缘缓存 ≤60 秒；key ≤512B、value ≤25MB、每账户 1GB；文档说 key 只许数字字母下划线，而本仓 key 都带 `:`／`.`，待 staging 实测（`:28-31`）。
- 设计意图（注释）：「网站不改正文：记录由下游落成 GUJI-541 对照表的 A 类行（`change=A｜cell_id｜old_char｜new_char`），合入走 PR」（`:9`）。

### 2.3 `/api/thread`（`edge-functions/api/thread.js`）

- POST 公开：对「一处意见」表态 agree／disagree（同来源覆盖），或回复 reply（必留称呼 ≤20、正文 ≤500）（`thread.js:1-13,47-62`）。
- target：`<kind>~<首格>~<末格>~<类别>`（`:7-8,31`）。
- key：表态 `tv:<book>:<volume>:<target>:<voter>`，回复 `tm:<book>:<volume>:<target>:<ts36>-<voter>`，TTL 180 天（`:10-13,22,83-85`）。
- 限速 30／10 分钟（`:34`）。GET 只开管理读（`:93-130`）。

### 2.4 `/api/fixes`（`edge-functions/api/fixes.js`）

- **GET 公开**：`?book=&volume=` 直读 KV 六个前缀 `cf/cs/ce/tv/tm/fs`，拼成与 COS 公开清单同形的 `{book, volumes:{<册>:[条目]}, threads:{<册>:{<target>:{agree,disagree,replies,status?}}}}`（`fixes.js:1-8,104-127`）。voter 只给 6 位、正文脱敏（`:42-50`）。每类每册最多读 1000 个 key，超了静默截断（`:18,85-102`）。**不应用中心库的隐藏单 hidden.txt**（`:9`）。
- **POST 只限管理**（整理组回写）：`{book_id, volume, target, state?, version?, reason?, reply?}`（`:129-145`）。
  - state ∈ `open｜adopted｜rejected｜discussing`（`:19`），写 `fs:<book>:<volume>:<target>`，**无 TTL**；`open` 用来撤回（`:164-168`）；
  - reply 写 `tm:…:<ts36>-team`，`name:'整理组', team:true`，TTL 180 天（`:169-173`）。
- 这是②唯一的「状态机」：open → adopted(可带 version「已进文本 vX」)｜rejected(可带理由)｜discussing，可随时改回 open。**没有任何前端页面调用这个 POST**（全仓 grep `/api/fixes` 只有 GET 调用与单测）。

### 2.5 `/api/cellreview`（`edge-functions/api/cellreview.js`）

- POST 公开：`{book, vol, a, rev, choice, char?, note?, shown?, aid}`（`cellreview.js:51-84`）；choice 六档 `char|none|unsure|cut|jiazhu|main`，char 档必须恰好一个字（`:24,61-70`）。
- key `cr:<rev>:<book>:<a>:<voter>`，TTL 60 天（`:10-15,27,143`）。另存 `iph`＝HMAC(CELLREVIEW_IP_KEY, ip) 前 16 位，用于统计时识别同 IP 换 aid 刷票；没配密钥就不存（`:109-121,144-147`）。
- 注释：「只有 char 与 none 会被下游自动落裁决，其余进异常清单。不给公众 damaged。」（`:17-18`）
- 限速 120／10 分钟（`:38-40`）。GET 只开管理读，按 `rev`（可加 book）前缀（`:156-194`）。

### 2.6 鉴权与 KV 共享小结
- 所有写接口提交侧都**不需要登录**；读者身份只有 localStorage 随机 `aid`（`kyg-cr-aid`，`lib/aid.ts:1-24`）＋IP。
- 管理侧：`FEEDBACK_ADMIN_TOKEN`（Bearer）或成员 cookie（JWT＋AUTH_KV 成员表＋tokenVersion，角色 reviewer／editor／admin）（`feedback.js:197-290`）。charfix／thread／cellreview／fixes 都复用这套（`charfix.js:19-22`）。
- 全部前缀共用一个 `FEEDBACK_KV`：`fb_`、`cf:`、`cs:`、`ce:`、`tv:`、`tm:`、`fs:`、`cr:`、`ratelimit:*`、`notify:feedback`。

---

## 3. 展示与讨论

### 3.1 `/feedback`（`app/feedback/FeedbackPageContent.tsx`）
- 只读 `/api/feedback?limit=50`（**只有 `fb_`**，不含改字意见；**没有翻页**，第 51 条以后看不到）（`:107-121`）。
- 每条显示：类型、「我的」（本机记过的 id）、相关条目链接（先查条目还在不在）、日期、状态、已认领块（未结时）、正文、站方回复（`:172-199`）。
- 默认只列未结（pending／in_progress），勾「显示已处理」才列 resolved／wontfix／duplicate（`:41-42,129-132`）。
- **不能讨论、不能投票、不能追问**；反馈者看结果只能回来翻这页（或找自己的「我的」高亮）。
- 页面上**没有通往 /feedback/text 的入口**（全仓只有阅读页提示条与改字弹窗的「看全部」链到 /feedback/text，见 `grep fixesPageHref`）。

### 3.2 `/feedback/text?book=&vol=`（`app/feedback/text/TextFixesContent.tsx`）
- 先读 `/api/fixes`（实时 KV），取不到退回 COS `proof/fixes/<书>.json`（每日发布）（`lib/fixes.ts:1-4,183-185`）。
- 按「同类＋同起止＋同类别」并组，组按格位排（`lib/fixes.ts:128-148`）；页签 全部／改字／一段／专名（`TextFixesContent.tsx:16,178-184`）。
- 每组显示：类别、位置（链接 `/read/<书>/<册>#<格位>`）、状态（已采纳＋「已进文本 vX」／未采纳＋理由／讨论中）、原文与各条建议、各条说明、提的人数（按 6 位 who 去重）、涉及的文本版本、最近日期（`TextFixesContent.tsx:89-127`）。
- **讨论**：同意／有不同看法（匿名、一人一票可改）、回复（留称呼，存 localStorage `kyg-th-name`），回复先在本页显示「待汇总」（`TextFixesContent.tsx:29-86`）；整理组回复带「整理组」标（`:68`）。
- 反馈者能看到处理结果：**只有当有人用 `POST /api/fixes` 写了 `fs:` 状态时**才看得到，且只在实时读里有（COS 兜底清单不含状态，见 6.2）。

### 3.3 `/admin/feedback`（`app/admin/feedback/FeedbackView.tsx`）
- 只管 `fb_`：读 `GET /api/feedback`（成员 cookie）翻页取全（每页 100，最多 50 页）（`:97-112`，`admin/fetchAll.ts`）。
- 能做：改类型、改状态、改分类、认领块、标重复、隐藏／恢复公开、写／改回复、「标记已改」（已改／不采纳＋公开回复＋处理凭据）（`:313-443`）；SLA 统计（近 30 天认领数、超 24h 未认领、认领耗时中位数）（`:224-228`，`lib/feedbackTriage.ts:35-79`）；筛选 状态／类型／分类／认领／公开／测试（`:245-297`）。
- **不能做**：看或处置改字意见（cf/cs/ce）、精校票（cr）、讨论（tv/tm）；写 `fs:` 状态；填 routedIssue；把一条 `fb_` 转成改字记录或导出。
- 截断提示文案写的是「只取到了前 N 条（最旧的一批）」（`FeedbackView.tsx:218-221`），但后端已改成从新到旧取（`feedback.js:449-465`）——文案过时，实际截掉的是**最旧**的。

---

## 4. 下游：网站侧的导出与回流

### 4.1 唯一的导出：每日 `proofing-sync` Action
- 工作流 `.github/workflows/proofing-sync.yml`：每天 21:23 UTC（`:31`），先跑单测，再两步：
  - **opinions**（`nextjs/scripts/proofing-sync.mjs:142,144`）：
    - 精校票：从中心库 `feedback/lists/proofing/<书>/<章>.pending.json` 得出所有 (书, rev) → `GET /api/cellreview?rev=&book=` 翻页 → 合并写回中心库 `feedback/lists/web/<书>/<rev>.jsonl`（`scripts/lib/proofing-sync-run.mjs:53-76`，`proofing-sync-plan.mjs:6-7,31-35,65-71`）；
    - 改字／一段／专名：对 `FIX_BOOKS` 里每本书 `GET /api/charfix?book=&kind=char|span|entity` → 合并写回中心库 `feedback/lists/web/<书>/fixes.jsonl`（旧快照 ∪ KV，同 id 以 KV 为准，KV 过期的旧条保留）（`proofing-sync-run.mjs:110-124`，`fixes-sync.mjs:98-125`）；
    - 讨论：`GET /api/thread?kind=vote|reply` → `threads.jsonl`（`proofing-sync-run.mjs:126-139`）。
  - **publish**：中心库待审单 → COS `proof/index.json`、`proof/<书>/<章>.pending.json`；`fixes.jsonl`＋`threads.jsonl`－`hidden.txt` → COS `proof/fixes/<书>.json`（`proofing-sync-run.mjs:147-174`，`fixes-sync.mjs:139-160`）。
- 中心库写入走 Worker `https://data.open-guji.com/v1/files?ws=&src_path=`（PUT 带 base_sha 乐观锁），令牌复用网站管理令牌 `FEEDBACK_ADMIN_TOKEN`（在中心库登记为 web 角色）（`proofing-sync.mjs:64-75`，`proofing-sync.yml:9,67`）。
- **范围限制**：`PROOF_WS` 默认 `siku-zongmu`；`FIX_BOOKS` 默认只有 `96mid1ogzk`，所有书的改字快照都写进第一个工作区（`proofing-sync.mjs:16-19,28-29,144`；`proofing-sync.yml:45-46`）。仓库变量里实际配了什么在本仓看不到。
- **中心库里的格式**：`fixes.jsonl` 每行就是 KV 原值（键排序后序列化），即第 8 节的 cf/cs/ce 记录；`<rev>.jsonl` 每行是 `normalizeRecord` 固定键序 `v, book, vol, a, rev, choice, char, note, shown, voter, iph, ts`（`proofing-sync-plan.mjs:64-71`）。

### 4.2 没有导出的
- `fb_` 通用反馈：**没有任何脚本／cron／Action 读它往外送**（监控只数条数，`monitor.yml` B2；feedback-hide 只改标记）。github 模式能开 issue，但开在 `book-index-draft`，与 book-text／CV 无关（`feedback.js:500-525`）。
- `fs:` 状态（采纳／未采纳）：没有管理 GET、不进中心库、不进 COS 清单（`fixes-sync.mjs:139-160` 只拼 fixes 与 threads）。
- 网站仓里**没有任何代码**把中心库的 `fixes.jsonl`／`<rev>.jsonl` 转成 CV 的 `feedback/events/`、glyph_store 裁决或 book-text 的改动；这一段在仓外（charfix 注释说由下游落成 GUJI-541 对照表 A 类行、合入走 PR，`charfix.js:9`；cellreview 注释说只有 char/none 下游自动落裁决，`cellreview.js:17-18`）。

### 4.3 文本版本号在网站上怎么用
- `text_version`（章条目，缺则 char.json `version`）：
  - 决定改字入口开不开（缺就不收改字，`charfix.ts:133`）；
  - 写进 cf/cs 的 key 与值（`charfix.js:191-195`），也显示在 /feedback/text 每组的「文本版本」（`TextFixesContent.tsx:92,121`）；
  - 主版本 ≥1 且不在校对 → 阅读页出「已校定，发现问题请告诉我们」（`ReaderClient.tsx:113-115`）；
  - `TextVersionChip` 显示与分级（`TextVersionChip.tsx:15-33`；注意它要求 `x.y.z`，而改字接口只要 `^[A-Za-z0-9._-]{1,16}$`）。
- `proofing: true`／`pending_file`（章条目）：COS 总表取不到或没列这章时的回落判据（`ReaderClient.tsx:79-91`，`proofing.ts:385-397`）；精校页同样先 COS 后 book-text（`proofing.ts:486-523`）。
- `rev`（待审单版本）：精校票的 key 前缀与导出单位；不带合法 rev 的待审单不让提交（`ProofingClient.tsx:581`）。
- `fs:` 状态里的 `version`：整理组手工写「已进文本 vX」（`fixes.js:137-138`，`i18n/messages/charfix.ts:176`）。

---

## 5. docs/ 里关于反馈的描述

- `docs/architecture.html:300-316`「七、后台接口」只列了 `/api/feedback`（「读者反馈。公开列表不含联系方式；管理接口需要管理令牌；新反馈推送到站长微信」，存 `FEEDBACK_KV`）、`/api/track-error`、`/api/auth/*` 等；**`/api/charfix`、`/api/thread`、`/api/fixes`、`/api/cellreview` 均未登记**，也没有 proofing-sync。
- `docs/architecture.html:152,208,314,366`：正式站／测试站各一套独立 KV；e2e 写操作必须 mock，不能提交到 www。
  - 与之矛盾：`nextjs/src/lib/feedback.ts:136` 注释写「正式站与测试站共用 KV」（推测是旧注释没更新）。
- `docs/architecture.html:421`：「公开写接口有限流：反馈接口取不到客户端 IP 时跳过限流并记警告」。
- `docs/architecture.html:406`：反馈表单组件在 `book-index-ui`（源码在 `open-guji/book-index-manager` 的 `ui/`）。
- `docs/runbook.md:188`：每小时私有监控有「B2 反馈量」。
- `docs/cutover.md:45,93,165`：切换检查项「`/api/feedback` 200，否则回滚」。
- `docs/reader-performance.md:92,110`：分批渲染时 `SelectionReport`／`CharFixEntry` 依赖 DOM 完整，改造分页会影响改字与报错浮条。
- 设计规格都在仓外：ai-team 仓 `team/网站/GUJI-561-charfix-接口规格.md`（`charfix.ts:3`）、`team/整理/设计/文本整理三阶段流程.md §6.2`（`cellreview.js:1`）、`team/整理/设计/待审单与公众意见走中心库.md`（`proofing-sync.mjs:3`）；GUJI-597 反馈设计（`thread.js:1`）。

---

## 6. 断点与问题（带证据）

### 6.1 数据不通

1. **通用反馈 `fb_` 是死胡同**：不导出、不进中心库、不进 CV／book-text；只能在 /admin/feedback 人工读、写一句回复。而阅读页选字回落、阅读器右栏「报告错字」、顶栏「反馈」都走它（`ReaderClient.tsx:245-255`，`SelectionReport.tsx:115`，`feedback.js:357-380`；全仓无读取 `fb_` 往外送的代码）。
2. **同一件事两条通道**：对读章里，拖选→「報錯」进 `cs:`（带格位），右栏「报告错字」进 `fb_`（不带格位）（`SelectionReport.tsx:112-115` vs `ReaderClient.tsx:243-255`）。两边互不认识，无法合并去重。
3. **`fs:` 采纳状态只活在 KV**：没有管理 GET、不进中心库、不进 COS 公开清单（`fixes.js:147-179`，`fixes-sync.mjs:139-160`）。实时接口一挂，/feedback/text 退回 COS 清单就看不到「已采纳／未采纳」。也就是说「处理结果」没有真源备份（`fs:` 无 TTL，但也没备份）。
4. **写状态没有界面**：`POST /api/fixes` 全仓无调用（grep 结果只有单测 `fixes-live.test.ts:88`），整理组要回写只能 curl。
5. **FIX_BOOKS 白名单**：改字／讨论只同步 `FIX_BOOKS`（默认仅 `96mid1ogzk`），其他书的 cf/cs/ce/tv/tm 在 KV 里 180 天后过期即永久丢失（`proofing-sync.mjs:19,29`，`charfix.js:27`，`thread.js:22`）。快照还一律写进 `PROOF_WS` 第一个工作区（`proofing-sync.mjs:144`），书与工作区不对应时会放错地方（推测）。
6. **精校票按「当前待审单的 rev」拉**：opinions 段只对中心库里现存 pending 的 (书, rev) 拉票（`proofing-sync-run.mjs:53-76`）。若某章待审单在一次同步之间换了 rev，旧 rev 在上次同步后新增的票不会再被拉，60 天后过期（`cellreview.js:27`）（推测，取决于中心库换 rev 的时机）。
7. **hidden.txt 只管 COS 清单**：`/api/fixes` 实时读不应用隐藏单，站方隐藏的条目在实时页上照样出现，只能去 KV 里删（`fixes.js:9`）。
8. **网站侧到 CV 的最后一跳不存在**：中心库快照（`fixes.jsonl`、`<rev>.jsonl`）之后由谁、以什么格式落成 CV 的 `feedback/events/` 或 glyph_store 裁决、或 book-text 的 PR，本仓无代码（`charfix.js:9` 仅注释提到 GUJI-541 对照表 A 类行）。

### 6.2 缺失字段／定位失效

9. **`fb_` 没有格位、没有文本版本、没有册**：只有 pageUrl＋`#rd-e-N`＋压成单行、截到 200 字的引文（`lib/feedback.ts:80-84,118-133`）。同一段文字在一章里出现多次时无法确定是哪一处；文本改版后引文可能对不上。
10. **改字没有字形实例 id**：cf 只有 `cell_id`（`页:列:格[ab]`）＋`old_char`（char.json），没有 CV 的字框稳定 id、像素 box、字形库实例 id、cord 版本（`charfix.ts:164-178`）。`lib/proof.ts:4-5` 明说格位 `a` 与字框稳定 `id` 是两回事。若 CV 重切分导致格位重排，旧 cell_id 就指错（推测）。
11. **跨版本没有迁移**：cf/cs key 带 text_version，但公开并组不看版本（`lib/fixes.ts:131` 的 key 不含 tv），/feedback/text 的位置链接 `/read/<书>/<册>#<格位>` 总是打开**当前**文本（`TextFixesContent.tsx:97`）。版本升级后旧意见既不会自动失效，也不会标「已过时」；读者对新版同一格再提会生成新 key（不覆盖旧的），人数会重复计（推测）。
12. **服务端不核 old_char**：old_char 与该格实际原字是否一致只能下游核（`charfix.js:10`）；new_char 若读者在**简体模式**下输入，存的就是简体字，接口不做任何归一（推测；`charfix.ts:4` 只保证 old_char 取 char.json）。
13. **volume 取值口径不一**：改字用 `String(chapterFile ?? chapterKey)` 原样（`ReaderClient.tsx:298`），提示条和精校用去掉扩展名的 stem（`ReaderClient.tsx:80,114`）。若章条目 `file` 带扩展名，同一章会有两种 volume，/feedback/text 链接与 KV 前缀对不上（推测，取决于数据里 file 的写法）。
14. **没有图坐标与附图**：所有入口都不能附截图，也不带书影 box（全仓无文件上传）；改字弹窗里也看不到该格裁图（`CharFixEntry.tsx:193-195`），只有精校页有裁图（`ProofingClient.tsx:315`）。
15. **精校前端少字段**：后端收 `note` 与第 6 档 `main`，前端都不发／没按钮（`cellreview.js:24,72-77` vs `ProofingClient.tsx:27-32,582`，`proofing.ts:528`）。

### 6.3 UX 痛点

16. **改字步骤多、要会打字**：点字 → 浮条「改字」→ 手输一个字（或 `{{组字式}}`）→ 提交（`CharFixEntry.tsx:124-125,197-206`）。生僻字基本打不出来；精校页有候选与相似字，改字没有（对比 `ProofingClient.tsx:330-345`）。
17. **手机上选区难控**：选区浮条靠 `selectionchange`＋200ms，滚动即收起（`SelectionReport.tsx:73-86`）；改字靠单击，与系统长按选字在触屏上互相干扰（推测；代码里只做了「触屏放下方」的规避，`SelectionReport.tsx:62-63`，`CharFixEntry.tsx:64-65`）。
18. **入口语义分裂**：选字「报错」在对读章是「这段有问题」，在非对读章是通用反馈；右栏「报告错字」永远是通用反馈。读者看不出提交去了哪里，也看不出在哪儿看进展（`SelectionReport.tsx:112-115`）。
19. **看不到进度**：
    - `fb_`：只能回 /feedback 翻（只列 50 条、无翻页，`FeedbackPageContent.tsx:109`），自己的反馈靠本机 localStorage 高亮，换设备就丢（`lib/feedback.ts:161-190`）；
    - cf/cs：结果只在 /feedback/text 的状态行，而状态没人写（问题 4）；
    - 精校：「您已回应」只存本机（`proofing.ts:562-581`），提交后读者不知道最后定成什么。
20. **/feedback 与 /feedback/text 互不相通**：/feedback 页没有入口到整册意见页；整册意见页只能从阅读页提示条或改字成功页进（`grep fixesPageHref`）。也没有「所有书的改字意见」总览。
21. **回复「待汇总」文案过时**：/api/fixes 已是实时读，但回复后仍显示「待汇总」，组件注释还写「新提交的次日汇总后才进清单」（`TextFixesContent.tsx:29,69`，`i18n/messages/charfix.ts:206`）。

### 6.4 重复提交与刷量

22. **`fb_` 完全不去重**：同一人重复点提交会生成多条，只能管理员手工标 duplicate（`feedback.js:357-380`，`FeedbackView.tsx:384-402`）。
23. **voter 不稳定**：`voter = sha256(aid|ip)`，换网络（手机常见）或清 localStorage 就是新 voter，「几个人提的」与同意数都会虚高（`charfix.js:189-190`，`thread.js:79-81`，`fixes.js:66-71`）；只有 cellreview 在配了 `CELLREVIEW_IP_KEY` 时存 `iph` 便于事后去重（`cellreview.js:144-147`）。
24. **取不到 IP 就不限速**（`feedback.js:330-336`，`cellreview.js:90`）。

### 6.5 无 AI 预判、无闭环通知

25. **没有 AI 预判**：唯一的「分类」是按 type＋路径＋有没有引文的规则（`feedback-classify.js:37-59`）；`suggestAssignee` 写了但没人调用（`feedback-classify.js:69-72`，全仓 grep 无引用）。charfix／cellreview 进来后没有任何自动判断（例如拿字形库比对、拿 OCR 候选比对）。
26. **没有闭环通知**：新反馈只推给站方 webhook（`feedback.js:144-169`）；charfix／thread／cellreview 连站方通知都没有；反馈者留了联系方式也没有任何回信代码（`contact` 只存不用，`feedback.js:372`）。

### 6.6 运维与规模

27. **`fb_` 列表是 O(全部 key)**：每次读都全列 key，resourceId 过滤最坏读遍所有值（`feedback.js:449-496`）；admin 翻页每页都重新全列（`admin/fetchAll.ts` × `kvGet`）。
28. **`/api/fixes` 每类每册 1000 key 上限**，超了静默截断（`fixes.js:18,99`）。
29. **KV key 字符**：平台文档说 key 只许字母数字下划线，本仓所有 key 都带 `:`／`.`，作者标了「以 staging 实测为准」（`charfix.js:28-31`）。
30. **admin 截断提示说反了**（问题见 3.3，`FeedbackView.tsx:218-221` vs `feedback.js:449-465`）。
31. **文档缺登记**：architecture.html 后台接口表只有 `/api/feedback`，缺 charfix／thread／fixes／cellreview 与 proofing-sync（`docs/architecture.html:300-316`）。
32. **死代码**：`components/book-index/FeedbackTab.tsx` 无引用，且 localhost 下直写正式站（`FeedbackTab.tsx:12-14`）。

---

## 7. 测试覆盖概况

### 7.1 单测（Jest，`nextjs/src/**/__tests__`；边缘函数在 Jest 里直接 import 测）
| 文件 | 用例数 | 覆盖 |
|---|---|---|
| `lib/__tests__/feedback-abuse.test.ts` | 10 | 限速、输入约束 |
| `lib/__tests__/feedback-auth.test.ts` | 10 | 管理鉴权 fail-closed、成员 cookie |
| `lib/__tests__/feedback-batch2.test.ts` | 11 | 新类型／状态、标重复、推送 |
| `lib/__tests__/feedback-cache.test.ts` | 11 | 公开读缓存／预算／503 |
| `lib/__tests__/feedback-classify.test.ts` | 15 | 规则分类、QUOTE_MARK 对表 |
| `lib/__tests__/feedback-client.test.ts` | 26 | 提交体拼装、引文、锚点、我的 |
| `lib/__tests__/feedback-desensitize.test.ts` | 13 | 脱敏 |
| `lib/__tests__/feedback-listing.test.ts` | 14 | 倒序取、游标、resourceId 过滤 |
| `lib/__tests__/feedback-triage(-ui).test.ts` | 14＋8 | 分流字段校验、SLA |
| `lib/__tests__/charfix.test.ts` | 17 | 校验、同来源覆盖、管理读前缀、公开读拒、限速、专名 |
| `lib/__tests__/cellreview.test.ts` | 20 | 枚举、char 必填、rev、覆盖、限速 |
| `lib/__tests__/fixes-live.test.ts` | 8 | /api/fixes 实时读、整理组回写 |
| `lib/__tests__/thread.test.ts` | 5 | 表态覆盖、回复追加、target 形状 |
| `lib/__tests__/proof.test.ts`／`proofing.test.ts` | 11／38 | 校对层与待审单解析 |
| `components/feedback/__tests__/feedback.test.tsx` | 25 | 弹窗、选字浮条（含 span 走 /api/charfix，`:381`） |
| `components/__tests__/CharFixEntry.test.tsx` | 17 | 点字浮条、改字／专名提交体 |
| `app/feedback/__tests__/FeedbackPageContent.test.tsx` | 10 | /feedback 列表 |
| `app/feedback/text/__tests__/TextFixesContent.test.tsx` | 9 | 实时→COS 兜底、讨论提交 |
| `app/admin/feedback/__tests__/FeedbackView.test.tsx` | 14 | 管理处置 |
| `app/read/[id]/__tests__/ProofingNotice／ReaderProof／ReaderReport` | 4／5／1 | 提示条、校对层、右栏报告错字接线 |
| `app/proofing/[book]/[vol]/__tests__/ProofingClient.test.tsx` | 22 | 精校页 |
| `scripts/lib/fixes-sync.test.mjs`／`proofing-sync.test.mjs` | 11／15 | 中心库合并、公开清单（node --test） |
| `ops/tests/feedback-hide.test.mjs` | 7 | 隐藏脚本 |

### 7.2 e2e（Playwright，`e2e/`）
- `e2e/ui/feedback.spec.ts`：只测**通用反馈** `/api/feedback`（route mock，不真写）：首页顶栏、Esc、条目页「这条有误？」、阅读页选字报错（引文拼正文、章号随 pageUrl）、阅读器右栏「报告错字」、/feedback 写反馈、手机 390 宽（`:31,62-191`）。
- `e2e/contract/fullstack.spec.ts:659-660`：`/api/feedback` GET 可读（只读）。
- **没有** e2e 覆盖：点字改字、拖选「这段有问题」、/feedback/text、/api/thread、/api/fixes、精校页 /proofing 与 /api/cellreview、proofing-sync 端到端（仅单测）。
- 已知缺口：没有跨通道的一致性测试（同一格既有 fb_ 又有 cf 的情形），没有文本版本切换后的定位测试。

---

## 8. 关键数据结构原文摘录

### 8.1 通用反馈 `fb_` 写入（`edge-functions/api/feedback.js:357-380`）
```js
async function kvPost(kv, type, content, pageUrl, resourceId, contact, test, subtype) {
  const id = generateId();
  const record = {
    id,
    type,
    content: content.trim(),
    pageUrl: pageUrl || '',
    resourceId: resourceId || '',
    createdAt: new Date().toISOString(),
    status: 'pending',
    reply: '',
  };
  // 分块 A：入口分类（只写 category，不写 assignee——认领是站方的动作）
  record.category = classifyFeedback({ type, pageUrl, content: record.content });
  if (subtype) record.subtype = subtype; // 已在入口校验过；不传则不写，读时按 unspecified
  if (contact) record.contact = contact;
  if (test) record.test = true;
  if (type === 'contact') record.visibility = 'hidden';
  await kv.put(id, JSON.stringify(record));
  invalidateListCache();
  return { id };
}
```
白名单（`feedback.js:68-69`）：
```js
const ALLOWED_TYPES = ['bug', 'resource', 'suggestion', 'contact', 'other'];
const ALLOWED_STATUSES = ['pending', 'in_progress', 'resolved', 'wontfix', 'duplicate'];
```
分流字段（`feedback-classify.js:5-10`）：
```js
export const CATEGORIES = ['typo', 'entry', 'site', 'join', 'other'];
export const SUBTYPES = ['char', 'punct', 'name', 'version', 'unspecified'];
export const ASSIGNEES = ['catalog', 'web', 'text', 'cv', 'collate', 'layout', 'owner'];
```
前端提交体（`nextjs/src/lib/feedback.ts:123-134`）：
```ts
export function buildFeedbackBody({ type, text, contact, context, pageUrl, subtype }: FeedbackInput): FeedbackBody {
    const body: FeedbackBody = {
        type,
        content: quotePrefix(context?.quote) + text.trim(),
        pageUrl: withAnchor(pageUrl, context?.anchor),
        resourceId: normalizeResourceId(context?.resourceId),
    };
    const c = contact?.trim().slice(0, CONTACT_MAX);
    if (c) body.contact = c;
    if (subtype) body.subtype = subtype;
    return body;
}
```

### 8.2 改字／一段／专名（`edge-functions/api/charfix.js`）
key（`:191-196`）：
```js
const key = rest.kind === 'char'
  ? `cf:${rest.book_id}:${rest.volume}:${rest.text_version}:${rest.cell_id}:${voter}`
  : rest.kind === 'span'
    ? `cs:${rest.book_id}:${rest.volume}:${rest.text_version}:${rest.start}-${rest.end}:${rest.sub}:${voter}`
    : `ce:${rest.book_id}:${rest.volume}:${rest.entity_id}:${voter}`;
await kv.put(key, JSON.stringify({ v: 1, ...rest, voter, ts: Date.now() }), { expirationTtl: TTL_SECONDS });
```
规整后的值（`:105-110`、`:128-133`、`:162-168`）：
```js
// kind=char
{ kind, book_id: book, volume, text_version: tv, cell_id: cell, old_char: old, new_char: newChar,
  basis: basis.value, entity_ids: entityIds, aid: body.aid }
// kind=span
{ kind, book_id: book, volume, text_version: tv, start, end, sub,
  old_text: oldText.value, new_text: newText.value, note: note.value, aid: body.aid }
// kind=entity
{ kind, book_id: book, volume, chapter, entity_id: eid, entity_version: ev,
  anchor: { start: anchor.start, end: anchor.end }, text: body.text.trim(), note: note.value,
  ...(target ? { target } : {}), aid: body.aid }
```
（`aid` 在写入前被剥掉，换成 `voter`、`ts`、`v:1`。）
格位与类别（`:37,42`）：
```js
export const SPAN_SUBS = ['wrong', 'missing', 'extra', 'order', 'punct', 'para', 'heading', 'note', 'entity', 'other'];
const RE_CELL = /^\d{1,6}:\d{1,4}:-?\d{1,4}[ab]?$/; // 与 cellreview／lib/proof.ts 同一坐标；另收抬头字的 -1 格（框外上方）
```
前端提交（`nextjs/src/lib/charfix.ts:164-178`）：
```ts
export async function submitCharFix(ctx: CharFixCtx, d: CharFixDraft, fetchImpl: typeof fetch = fetch, t: SiteT = HANT): Promise<string | null> {
    const oldChar = ctx.chars.get(d.cell);
    return post({
        kind: 'char',
        book_id: ctx.book,
        volume: ctx.volume,
        text_version: ctx.textVersion,
        cell_id: d.cell,
        ...(oldChar ? { old_char: oldChar } : {}),
        new_char: d.newChar,
        ...(d.basis ? { basis: d.basis } : {}),
        entity_ids: entityIdsAt(d.cell, ctx.entities),
        aid: getAid(),
    }, fetchImpl, t);
}
```
CharFixCtx（`charfix.ts:40-57`）：`{ book, volume, chapter, textVersion, chars: Map<格位,原字>, entities, entityVersion }`。

### 8.3 讨论与状态（`thread.js`、`fixes.js`）
```js
// thread.js:31-32
export const RE_TARGET = new RegExp(String.raw`^(char|span|entity)~${CELL}~(${CELL})?~(${SUBS})?$`);
export const STANCES = ['agree', 'disagree', 'reply'];
// thread.js:84-85
const key = rest.stance === 'reply' ? `tm:${base}:${ts.toString(36)}-${voter}` : `tv:${base}:${voter}`;
await kv.put(key, JSON.stringify({ v: 1, ...rest, voter, ts }), { expirationTtl: TTL_SECONDS });
```
```js
// fixes.js:19
export const STATES = ['open', 'adopted', 'rejected', 'discussing'];
// fixes.js:164-173（整理组回写）
if (state !== undefined) {
  const key = `fs:${book_id}:${volume}:${target}`;
  await kv.put(key, JSON.stringify({ v: 1, book_id, volume, target, state, ...(version ? { version } : {}), ...(reason ? { reason } : {}), ts }));
}
if (reply) {
  await kv.put(`tm:${book_id}:${volume}:${target}:${ts.toString(36)}-team`,
    JSON.stringify({ v: 1, book_id, volume, target, stance: 'reply', name: TEAM_NAME, text: reply, team: true, voter: 'team', ts }),
    { expirationTtl: 180 * 24 * 60 * 60 });
}
```
公开条目形（`fixes.js:43-50` ＝ `scripts/lib/fixes-sync.mjs:130-137`）：
```js
export function toPublicFix(r) {
  const o = { kind: r.kind, at: fixAt(r), who: String(r.voter).slice(0, 6), ts: typeof r.ts === 'number' ? r.ts : undefined };
  if (r.kind === 'char') Object.assign(o, { tv: r.text_version, old: r.old_char || undefined, new: r.new_char, note: clean(r.basis) });
  else if (r.kind === 'span') Object.assign(o, { tv: r.text_version, end: r.end, sub: r.sub, old: r.old_text || undefined, new: r.new_text || undefined, note: clean(r.note) });
  else Object.assign(o, { end: r.anchor && r.anchor.end, ev: r.entity_version, eid: r.entity_id, old: r.text, note: clean(r.note) });
  for (const k of Object.keys(o)) if (o[k] === undefined || o[k] === '') delete o[k];
  return o;
}
```
公开清单整体：`{ book, volumes: {<册>: [toPublicFix…]}, threads?: {<册>: {<target>: {agree, disagree, replies:[{name,text,ts,team?}], status?:{state,version?,reason?,ts}}}} }`（`fixes.js:4,60-83`；COS 版不含 status，`fixes-sync.mjs:139-160`）。

### 8.4 精校票（`edge-functions/api/cellreview.js`）
```js
export const CHOICES = ['char', 'none', 'unsure', 'cut', 'jiazhu', 'main'];   // :24
// :83  validateReview 返回值
return { value: { book, vol, a, rev, choice, ...(char ? { char } : {}), note, shown, aid: body.aid } };
// :143-148
const key = `cr:${rest.rev}:${rest.book}:${rest.a}:${voter}`;
const iph = ip ? await ipHash(context, ip) : '';
const record = { v: 1, ...rest, voter, ...(iph ? { iph } : {}), ts: Date.now() };
await kv.put(key, JSON.stringify(record), { expirationTtl: TTL_SECONDS });
```
中心库快照行的固定键序（`nextjs/scripts/lib/proofing-sync-plan.mjs:64-65`）：
```js
const RECORD_KEYS = ['v', 'book', 'vol', 'a', 'rev', 'choice', 'char', 'note', 'shown', 'voter', 'iph', 'ts'];
```

### 8.5 中心库路径（网站 Action 写入，`fixes-sync.mjs:17-31`、`proofing-sync-plan.mjs:6-13`）
```
feedback/lists/proofing/<书>/<章>.pending.json   待审单（整理导出写入，网站只读）
feedback/lists/web/<书>/<rev>.jsonl              精校票快照（proofing-sync 写）
feedback/lists/web/<书>/fixes.jsonl              改字／一段／专名快照（proofing-sync 写）
feedback/lists/web/<书>/threads.jsonl            讨论快照（proofing-sync 写）
feedback/lists/web/<书>/hidden.txt               站方隐藏单（人工维护，一行一个 fixId／threadId）
COS: proof/index.json, proof/<书>/<章>.pending.json, proof/fixes/<书>.json
```
fixId／threadId（`fixes-sync.mjs:43-57`）：
```js
if (r.kind === 'char' && typeof r.cell_id === 'string') return `cf|${r.volume}|${r.text_version}|${r.cell_id}|${r.voter}`;
if (r.kind === 'span' && typeof r.start === 'string' && typeof r.end === 'string') return `cs|${r.volume}|${r.text_version}|${r.start}-${r.end}|${r.sub}|${r.voter}`;
if (r.kind === 'entity' && typeof r.entity_id === 'string') return `ce|${r.volume}|${r.entity_id}|${r.voter}`;
// thread
if (r.stance === 'agree' || r.stance === 'disagree') return `tv|${r.volume}|${r.target}|${r.voter}`;
if (r.stance === 'reply' && typeof r.ts === 'number') return `tm|${r.volume}|${r.target}|${r.ts}|${r.voter}`;
```
