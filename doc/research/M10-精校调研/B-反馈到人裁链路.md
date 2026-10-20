# 调研 B：公众反馈 → AI 处理 → 人裁事件落地 → 重跑／导出（GUJI-637 M10 精校流程梳理）

> 只读调研，洛杉矶 2026-10-20。读码基线：open-guji-cv `a00dbdb`、ai-team `f960641`、kaiyuanguji-web `1df0cc4`、guji-workspace-data 本地检出、guji-workspace `422f1d5`（浅克隆，事件文件已迁走；H-web 两批原文经 GitHub 读 `6bef1ada`）。中心库用**读令牌**只读查过（`/v1/files`、`/v1/tables/events`，main 分支）。
> 文件路径简写：`cv/`＝`cv/`，`ai/`＝`ai-team/`，`web/`＝`open-guji/kaiyuanguji-web/`，`data/`＝`guji-workspace-data/`，`wo`＝`ai/team/CV/公众意见导入/web_opinions.py`。

---

## 一、现状链路（2026-10-20 实际状态）

```
①读者在精校页点六档之一 ─POST /api/cellreview─▶ ②EdgeOne KV `cr:<rev>:<book>:<a>:<voter>`（60 天 TTL）
      ▲                                                  │
      │                                   ③每日 21:23 UTC Action「proofing-sync」opinions 段（管理读）
      │                                                  ▼
      │                         ④中心库 files 表 feedback/lists/web/<书>/<rev>.jsonl（旧快照 ∪ KV，只增不删）
      │                                                  │ guji db sync 拉到数据目录
      │                                                  ▼
      │          ⑤【手工】会话跑 wo：fetch --from-db → import → triage（规则）→ sheet（拼图）
      │                    → AI 会话肉眼看 sheet-NN.png，手写 review.tsv（ok/no）→ write
      │                    → problems／给用户.tsv 交用户（聊天／卡片，无界面）
      │                                                  ▼
      │          ⑥人裁事件 confirm（batch H-web-<册>-<日期>）经控制台 POST /api/events 写入
      │             → 路由表消费：glyphdb_admit／gold_add／crop_exclude／product_invalidate(seed_admit)
      │             → guji db sync 推中心库 events 表
      │                                                  ▼
      │          ⑦【手工】guji rerun --stale（或单页 pipeline）→ Step9 导出 → char/cord/norm
      │             → book-text PR（0.1.x，人定版本号）→ data.yml 每日发布 COS
      │          ⑧【手工】pending_list.py --ws 重出待审单（rev 人定）→ guji db sync
      │                                                  ▼
      └──────── ⑨ proofing-sync publish 段把待审单发 COS proof/；精校页读 COS，已裁格从单上消失
```

| 环 | 做什么 | 谁／什么触发 | 证据 |
|---|---|---|---|
| ① 提交 | 六档 `char｜none｜unsure｜cut｜jiazhu｜main`＋`char`＋`note`(≤500)＋`shown`＋`aid`；必带 `rev` | 读者，精校页 | `web/edge-functions/api/cellreview.js:17,24,51-84`；前端 `web/nextjs/src/lib/proofing.ts:542` |
| ② 存 | KV key `cr:<rev>:<book>:<a>:<voter>`，`voter=sha256(aid|ip)[:16]`，同格同来源覆盖；`iph`（HMAC IP）**仅当配了 `CELLREVIEW_IP_KEY` 才存**；TTL 60 天；按 IP 限速 120 次／10 分钟 | 边缘函数 | `cellreview.js:10-15,27,38-40,140-148` |
| ③ 导出 | 列中心库所有待审单的 (书, rev) → 管理读 KV（`FEEDBACK_ADMIN_TOKEN`，同一把在 Worker 登记为 web 角色）→ `mergeSnapshot` 合并 → `PUT /v1/files` | GitHub Action 每天 `23 21 * * *` | `web/.github/workflows/proofing-sync.yml:31,60-68`；`web/nextjs/scripts/lib/proofing-sync-run.mjs:53-69` |
| ④ 中心库 | `files` 表一行（raw＝原文）＋`source_files`＋`changes` 逐行留痕；快照「旧 ∪ KV、同 (a,voter) 以 KV 为准、KV 过期的保留」 | Worker `/v1/files` | `data/worker/src/files.ts:1-10`；`data/worker/src/policy.ts:6-7,63-95`；`proofing-sync-plan.mjs:100-130` |
| ⑤ AI 处理 | 见下「H 道判据」 | **人在会话里手敲命令**，无定时任务 | `wo:1-40` |
| ⑥ 落事件 | `POST /api/events`（`kind=confirm, step=seed_admit, unit=cell, consume=True`）；事件 id `evt_<batch>_<seq>`；锚由写入函数按当前产物算 | wo write 或会话直接调引擎写入函数 | `wo:400-466`；`cv/open_guji_cv/console/routers/feedback.py:143-245`；`cv/open_guji_cv/feedback/events.py:162-166`；路由 `cv/open_guji_cv/feedback/routes.py:135-152` |
| ⑦ 重跑／导出 | `product_invalidate` 只标 seed_admit 失效不跑；要人跑 `guji rerun --stale`；导出、book-text PR、版本号全手工 | 整理会话 | `cv/doc/受控重跑.md:58`；`ai/team/整理/设计/文本整理三阶段流程.md:153` |
| ⑧⑨ 回显 | 待审单 rev 由人定（`pending_list.py --rev`），只列 `admit=false` 且非排除格；网站只显示「已提交」，**不回告某条意见被采纳／驳回** | 整理会话＋Action publish 段 | `ai/team/整理/GUJI-543/pending_list.py:42-58,84,111-113`；`web/nextjs/src/app/proofing/[book]/[vol]/ProofingClient.tsx:361,642` |

### H 道（AI 裁决）现在怎么判

**是「规则分流＋会话 AI 肉眼看图」两段，没有程序化的 LLM 调用，也没有置信度。**

1. **规则段（triage，纯 Python）** `wo:258-345`
   - 去重：同 (cell_id, src＝voter) 只留最后一条 `wo:185-188`；测试票按 note 前缀「【测试】」或含 `eden-test` 剔除 `wo:149-153`。
   - 版本核对：`shown` 与该 rev 快照里的显示字不一致即丢（□ 不核）`wo:284-288`。
   - **无票数门槛**（用户 10-16 定，`三阶段流程.md:203`）：一票即可成草稿。
   - 进「给用户」的条件：同格意见不一致 `wo:302-303`；选字档字不一致 `wo:308-309`；要推翻已有人裁 `wo:310-314`；「无字」推翻机器已放行字 `wo:315-316`；疑似刷票——同来源当天 ≥60 条（`FLOOD_PER_SRC`）或同格 1 小时内 ≥5 个来源（`BURST_VOTES`）`wo:71-73,318-324`。
   - 只有「看不出」：**不写，只记 skipped** `wo:297-299`。
   - 六档映射：char→confirm shape；none→not_a_char；cut→seg_defect truncated；jiazhu／main→seg_defect reason `wo:237-255`。（注：网站注释说「只有 char 与 none 会被自动落」`cellreview.js:18`，与脚本不符。）
2. **看图段（sheet → review.tsv）** `wo:368-395,410-420`：脚本拼 40 格一张的字块图＋前后 6 字上下文，**由当时的 Claude 会话打开 PNG 看**，手写 `review.tsv` 每行 `cell_id ok|no 理由`。判据就是会话的眼力；没有固定 prompt、模型、温度、版本，也不进中心库。
3. **写段**：只写 ok 的草稿；用户点名的 problems 用 `--include-problems` 放行 `wo:431-433`；同日批次已存在即拒 `wo:450-451`；在快照工作区写完后把事件文件复制回正式工作区并提示手工补跑 `fix_excl.py` `wo:456-465`。

---

## 二、事件与数据 schema

### 2.1 公众意见（KV → 中心库快照，一行一票）
`{v:1, book, vol, a:"页:列:格[ab]", rev, choice, char?, note, shown, voter, iph?, ts(毫秒)}`（字段白名单 `proofing-sync-plan.mjs:64`）。
- 没有意见 id（导入时合成 `book:vol:a:voter`，`wo:144`）；没有处理状态字段（「已处理／已落／已驳」不在任何地方）。
- `vol` 网站上同时出现 `"001"` 与 `"vol01"` 两种写法（中心库快照实证）；`wo:184` 默认 `int(o['vol'])` 遇到 `vol01` 会崩，只能靠 `--book-map` 兜。

### 2.2 意见落成的人裁事件（中心库 events 表）
实例（H-web-vol01-2026-10-18 第 1 条，`6bef1ada` 原文）：
```
{actor:"user", batch:"H-web-vol01-2026-10-18", id:"evt_H-web-vol01-2026-10-18_000001", kind:"confirm", seq:1,
 payload:{v:"confirm", shape:"臼", note:"", request_id:…,
          source:"网站公众意见 2026-10-18（001-r2；意见 96mid1ogzk:001:9:7:17:dd04f7895bf5d5d8）；E 道（M8 公众回路）逐条看图后写，本机快照工作区，未经服务器（GUJI-589）"},
 reviewer:"claude-E-GUJI589", source_format:"server",
 target:{step:"seed_admit", unit:"cell", key:"vol01:9:7:17", book, page, col, slot,
         anchor:{bbox, quad, content_sha, ctx, evidence{fp,…,row_segment sha}, product_key{fingerprint,…}, space:"raw_page_px@top-right"}},
 ts:"2026-10-18T06:07:55Z"}
```
- 信封定义 `cv/open_guji_cv/feedback/events.py:124-152`；`actor` 只有 `user｜model｜align` `events.py:100`；缺省 `user` `events.py:141`。
- 中心库表 `events (ws, src_path, id)` 主键，列 `batch/kind/actor/reviewer/ts/payload/target/raw/rev` `data/schema/schema.sql:131-152`；Worker 追加按 (ws,id) 幂等、内容不同 409 `data/README.md` 事件追加节、`data/worker/src/events.ts:6-7,124-142`。
- **意见 → 事件的对应只写在 `payload.source` 自由文本里**；AI 的看图理由、规则分流结果、给用户的清单都**不是事件**。
- 「是不是人裁」的判定 `counts_as_human` 只排除 `kind=vision_check` 或 `payload.source="vision"` `events.py:105-121`。**H-web 事件 `actor=user`，与用户亲裁同级**：进字形库（`provenance="human"`，`cv/open_guji_cv/feedback/consumers.py:457`）、算已裁、进绑定表、进金标。
- 已有「模型判断不算人裁」的先例：`vision_check`（`actor="model"`，存 `feedback/vision/`，判 wrong 只送回待审）`events.py:94-98`。

### 2.3 副作用表
| 消费者 | 动作 | 可逆性 |
|---|---|---|
| glyphdb_admit | v=confirm → 刻例入字形库，provenance=human；后来改判不同字会撤旧再进 | 改判可覆盖 `consumers.py:425-460` |
| crop_exclude | not_a_char／damaged → 排除名单 | **只追加不删除** `consumers.py:536-548`；名单按格位、无锚（设计 15 的 P4 未做 `cv/doc/design/15-人裁锚定与重切后重绑定.md:7,80,99`）；名单一改全册 seed_admit 过期（`三阶段流程.md:153`） |
| gold_add | seg_defect → instances 金标 | 追加 |
| product_invalidate | 该页 seed_admit 标失效，不跑 | — |

### 2.4 归档与审计位置
- import 的原样存档写 `<正式工作区>/feedback/web/<日期>.jsonl` `wo:191-197`；但 `scope.classify` 对 `feedback/web/**` 返回 None（`cv/open_guji_cv/datastore/scope.py:124-141`），**这两份存档没进中心库**，只躺在已冻结的 guji-workspace git 里（`guji-workspace/96mid1ogzk-…/feedback/web/2026-10-18*.jsonl`，README 说其余数据已全部迁走）。
- triage／sheet／review.tsv／给用户.tsv 全在 `--out` 临时目录；只有空跑那次留在 `ai/team/CV/公众意见导入/589-dryrun/`。

---

## 三、实际运行数字

| 项 | 数 | 来源 |
|---|---|---|
| 公众回路真实批次 | **2 批 5 条事件**：H-web-vol01-2026-10-18（2：9:7:17 confirm 臼；10:7:10 seg_defect truncated）；-18b（3：10:7:16 法、90:1:3a 日、90:1:17a 大） | 中心库 events 按 `reviewer=claude-E-GUJI589` 查得 5 行；GUJI-589 评论 13900、13934 |
| 测试批次 | P0-5 自造 5 条 → 4 落、1 给用户（H-web-vol01-2026-10-17，一次性工作区 t552，测完删） | GUJI-552 评论 13193 |
| 中心库 001-r2 快照 | 11 行＝7 个格位；2 条【测试】；3 个 voter：`dd04f789…`（5 票）、`827b7158…`（4 票，10-18 17:32Z，**两批写完之后才到**）、两个测试 voter | `feedback/lists/web/96mid1ogzk/001-r2.jsonl`（rev 1472） |
| 真实「公众」 | **0**。第二批卡上写明「用户本人在审校页投了剩下 3 格，并说以他的判断为准」；第一批与第二批同一个 voter `dd04f789…`；`827b7158…` 投的 4 格与已落裁决完全一致，极可能也是团队自己换设备／换 IP | GUJI-589 13934；快照 |
| 走过 wo write 的正式写入 | **0**。两批都是 E 线程「本机按快照重建＋引擎写入函数」写，再走 guji-workspace PR #3、#4 | GUJI-589 13900 |
| 给用户的存疑单 | 0 条（两批都没触发） | 同上 |
| 是否修正过 CV | 1/5 改字有实义（9:7:17 曰→臼）；10:7:10 与用户 10-16 已裁的 seg_defect truncated **完全重复**（中心库查：用户事件 2026-10-16T17:57:54Z, quality=truncated）；其余 3 格本就是用户自己的判断 | 中心库 events |
| 网站现挂的待审格（未来负载） | 001：0 格；**004–010 共 1,983 格**（280/271/231/203/197/489/312），cv_version 均为 `0.4.6.dev`；这些 rev 目前**还没有任何意见快照** | 中心库 `feedback/lists/proofing/96mid1ogzk/*.pending.json` |
| GUJI-589（真实导入前补验：读回／去重／限速／管理读） | **仍是待办**，四项一项没验 | Jira |

结论：公众→AI→人裁这条链在 vol01 上「跑通」的只是骨架；AI 段从没在真实、多来源、有冲突的意见上判过一次，vol01 的 1.0.0 实际靠用户本人裁定。

---

## 四、问题清单

严重度：**高**＝会静默写错正式文本／污染字形库，或挡住规模化；**中**＝审计缺口、手工瓶颈；**低**＝体验／整洁。

| # | 问题 | 严重度 | 证据 |
|---|---|---|---|
| P1 | **AI 段不是程序，是会话肉眼**：sheet 出拼图、Claude 会话看 PNG 手写 review.tsv；无 prompt／模型版本／温度记录，无法复现、无法批量，1,983 格一来就扛不住 | 高 | `wo:9,24,368-395`；GUJI-552 13193「AI 逐张看图」 |
| P2 | **整条链没有定时任务**：只有 ③ 每日自动；⑤ 导入分流、⑥ 写入、⑦ 重跑导出、⑧ 重出待审单全靠人在会话里敲，F4「意见池清零」靠人只读核 | 高 | `三阶段流程.md:203`「每日导入」从未实现；GUJI-597 13978 F4「只读核过」 |
| P3 | **AI 落的裁决与用户亲裁不可区分**：`actor="user"`，只有 `reviewer="claude-E-GUJI589"` 与 `payload.source` 文本能看出；`counts_as_human` 照单全收 → 进字形库（provenance=human）、进金标、当「铁证」压过一切自动证据，还会经借库影响别的册 | 高 | 2.2 节实例；`events.py:105-121`；`consumers.py:457`；`cv/doc/datastore.md` 借库段 |
| P4 | **wo 在中心库迁移后路径已失效**：triage 的 `latest_human` 读 `<ws>/feedback/events/`（`wo:212-215`），write 往 `<正式工作区>/feedback/events/` 复制（`wo:456-460`），import 存档写 `<ws>/feedback/web/`（`wo:191-197`）；迁过的工作区数据在 `$GUJI_DATA_HOME/<分支>/<ws>/`，结果是「推翻已有人裁」检查**静默失效**（读到空目录），写入落到冻结的 git 树里不进库 | 高 | `cv/doc/datastore.md` 第六节布局；guji-workspace README；`decision_build.py` 同样读 guji-workspace 事件（`ai/team/整理/GUJI-588/decision_build.py:3-4`） |
| P5 | **快照工作区看不到正式库的最新裁决**：triage 在 rev 快照工作区查人裁，快照之后用户写的裁决看不见 → 10:7:10 照样出草稿、重复写了一条与用户相同的 seg_defect；若用户当时裁的是别的值就会被覆盖（「后到覆盖」） | 高 | GUJI-589 13896（Eliot 指出快照里没有 10-16 那条）；中心库 events 实查 |
| P6 | **排除名单只追加不删、按格位无锚**：公众「无字」一旦被 AI 落成 not_a_char 进名单，后来改判也删不掉；重切后仍按格位挡新切结果（GUJI-623 同根，vol01 75 格 □ 靠用户手工逐格补回）；名单一动全册 seed_admit 过期 | 高 | `consumers.py:536-548`；设计 15 P4 未做；GUJI-623；GUJI-597 13939 |
| P7 | **一票定案、无冲突仲裁策略**：不设票数门槛（用户 10-16 定）；冲突一律丢给用户，但没有「几票对几票、谁的票更可信」的模型；voter＝aid+IP，换设备／换网络就是新人（001-r2 的 `827b…` 与 `dd04…` 几乎可确定同一人） | 中 | `三阶段流程.md:203`；`cellreview.js:142`；快照 |
| P8 | **防刷弱**：`iph`（同 IP 换 aid 识别）要配 `CELLREVIEW_IP_KEY`，现快照无 `iph` 字段＝没配；wo 也不读 `iph`；刷票门槛 60 条／天、5 来源／小时是拍的，没校准；限速只按 IP；无 captcha／登录信誉 | 中 | `cellreview.js:109-121,144-147`；快照字段；`wo:71-73` |
| P9 | **「看不出」不写事件，没有审计痕迹**：unsure 票只进 skipped；decision_build 把「在 pending、没有用户定字」一律算 ①看不出，分不清「有人看过说看不出」与「没人看过」；F1「至少过一遍人」无法用数据证明 | 中 | `wo:297-299`；`decision_build.py:11-12`；GUJI-597 13862「看不出不写事件，需审阅页留审阅记录」 |
| P10 | **意见处理状态无处可查**：意见没有 id、没有「已落／已驳／待用户」状态；快照是并集，不知道哪些行处理过；`827b…` 的 4 票在两批之后到达，没人处理也没记录 | 中 | 2.1 节；快照时间戳 |
| P11 | **审计痕迹断在中心库外**：import 存档 `feedback/web/**` 不在 `scope.classify` 范围；review.tsv、给用户.tsv、AI 理由只在临时目录；意见→事件只靠 source 文本 | 中 | `scope.py:124-141`；`wo:191-197,410-430` |
| P12 | **存疑交用户没有渠道和界面**：给用户.tsv 靠会话贴聊天／卡片；用户回话后再由会话 `--include-problems` 代写；无页面、无记录、无超时缺省 | 中 | `wo:410-433`；`三阶段流程.md:203` |
| P13 | **AI 判错怎么回滚没定义**：没有通用撤销事件；只能再写一条覆盖；字形库可被改判撤回，排除名单不行（P6）；不知道一批里哪几条该撤（无结构化 opinion→event 映射） | 中 | `events.py` Kind 无撤销类；`consumers.py:546` |
| P14 | **重切后裁决绑定与格号换号**：H-web 事件带锚（好），但 seg_defect 绑定 rebound 会让「原格号」与「绑定后格号」对不上（90:2:1/90:2:2 实例）；待审单、decision 用哪个口径没定 | 中 | GUJI-589 13872；`cv/open_guji_cv/feedback/bindings.py:340-385` |
| P15 | **幂等只靠批次名＋同日拒写**：批次 `H-web-<册>-<日期>`，同日第二批手工加 `b`；事件 id `evt_<batch>_<seq>` 不含意见 id，换个批次名重跑同一批意见会写出重复事件，Worker 的 (ws,id) 幂等挡不住 | 中 | `wo:441,450-451`；`events.py:165` |
| P16 | **写入者与角色脱节**：规矩是「人裁只由 H 道写」，两批实际由「E 道（M8 公众回路）」会话写，经 guji-workspace PR，绕过服务器控制台 | 低-中 | `ai/process/子会话须知.md:29`；事件 source 文本 |
| P17 | **版本号、rev 全手工**：pending rev（001-r2 在 63→4→0 格间没变）、book-text 版本（0.1.1→0.1.3→0.1.6→1.0.0）都靠会话定；rev 不变而格变，网站和意见快照对不上版本只能靠 `shown` 粗核 | 低-中 | `pending_list.py:84,111-113`；中心库 001.pending.json `rev:001-r2, cells:[]`；GUJI-597 |
| P18 | **网站与脚本口径不一致、字段不规整**：`cellreview.js:18` 说只 char/none 自动落，脚本 cut/jiazhu/main 也自动落；`vol` 两种写法；`wo:184` 遇 `vol01` 崩 | 低 | 见左 |
| P19 | **读者看不到结果**：提交后只显示「已提交」，格从单上消失时不说明是否采纳；无「我的意见」页 | 低 | `ProofingClient.tsx:361,642` |
| P20 | **规模信号**：004–010 已挂 1,983 待审格，pending 的 cv_version 是 `0.4.6.dev`（非冻结版本），与「整书固定一个 CV 版本」（`三阶段流程.md:0 节`）相冲；意见一来，rev 快照工作区要能按 `0.4.6.dev` 某个 commit 复原 | 中 | 中心库 pending 文件 |
| P21 | **GUJI-589 四项补验一直未做**（读回、去重覆盖、限速、管理读），GUJI-610 国内通道未做 | 中 | Jira 状态 |

---

## 五、改进方向

### 5.1 AI 裁决器的形状（把 ⑤ 做成程序）

**输入（每格一个 case）**
- 意见组：该格全部票（choice、char、note、voter、iph、ts）＋来源画像（该 voter 历史采纳率、当天量、与机器一致率）。
- 卡片上下文：字块图（当前切图＋上下文条）、前后各 6 字、待审原因 `why/cls`、`lib_top`、`ctx`、整理本字 `ref`、`occ`、相似字 `alt`（pending 0.2 字段已有，见 004 实例）。
- 证据：本书同字已放行刻例（≤5）、字形库同候选的最近邻分数、异体族、是否被现有人裁覆盖（**读正式库最新，不读快照**）、绑定表状态。
- 版本：rev、cv_commit、产物指纹（锚）。

**输出（结构化，一格一条）**
`{cell, rev, decision: adopt|escalate|reject|abstain, verdict:{v, shape?, quality?, reason?}, tier: A|B|C, confidence, rationale, evidence_refs, opinion_ids[], model, prompt_ver}`
- adopt→落事件；escalate→进用户复审队列；reject→驳回（记理由，意见标已处理）；abstain＝「看不出」也记一条。

**判定分层（建议）**
| 档 | 条件（示例，要用金标校准） | 处理 |
|---|---|---|
| A 自动落 | 意见与 ≥2 路独立证据一致（如整理本字＋库 top1、或库 top1 margin 大），无已有人裁冲突，非「无字」，非结构类 | 直接落，`tier=A` |
| B AI 落＋抽检 | 意见只有 1 路证据支持、或单票、或改了已放行字以外的待审格 | 落，按 ≥20% 抽进用户复审，抽检错率超阈值整档降级 |
| C 必须用户 | 推翻任何人裁／放行字；none→not_a_char（不可逆进名单）；cut/jiazhu/main 结构类；冲突票；刷票嫌疑；模型低置信 | 不落，进复审页 |

**实现要点**
- 程序跑在固定地点（服务器或 Action 后的会话），每日 proofing-sync 之后自动触发；用 LLM 多模态看图＋规则特征，prompt 与模型版本入库。
- **事件身份**：新增 `actor="model"`＋`payload.source="web_ai"`＋`payload.tier`＋`payload.opinion_ids[]`＋`payload.ai_ref`（指向判定记录）；`counts_as_human` 改三档：用户亲裁＝human；AI tier A/B＝`ai_adjudicated`（**进文本、不进字形库种子、不进金标**，用户抽检通过后才升 human）；vision＝model。
- **事件 id 带意见指纹**（如 `evt_web_<sha(opinion_ids+verdict)>`），重跑天然幂等，不靠批次名。
- **读写都走数据目录／中心库**（修 P4），冲突检查读正式库最新事件＋绑定表；锚仍按 rev 快照算（§5.2 原则保留），写前对比「快照后正式库是否有新裁决」。
- 「看不出」写成事件（如 `kind=cell_review verdict=unsure` 或新 `abstain`，路由不配消费者），F1 才可证。
- not_a_char 走 C 档，或先实现排除名单可撤销＋带锚（GUJI-623／设计 15 P4）再放开。

### 5.2 用户复审页面
- 复用 `review-artifact` 型卡片页或控制台格级审阅页：每格显示图、上下文、全部票、AI 结论与理由、候选；按钮＝同意 AI／改判（六档）／驳回意见。
- 两个队列：C 档必审；B 档抽检。点完自动写事件（用户亲裁，`reviewer` 为用户），并回写判定记录状态。
- 缺省规则：C 档 N 天未审保持待审（不落），B 档抽检未做不阻塞但计入指标。

### 5.3 意见状态与审计
- 中心库加「意见处理台账」（`feedback/lists/web/<书>/<rev>.state.jsonl` 或新表）：一票一行 `{opinion_id, status: adopted|rejected|escalated|abstained|superseded, event_id?, ai_ref, at}`；F4 改成查台账「未处理=0」。
- 把 AI 判定记录（含理由）也入库（`feedback/lists/web/<书>/<rev>.ai.jsonl`），scope 已认 `feedback/lists/**`，不改 cv。
- 废掉 `feedback/web/<日期>.jsonl` 存档（中心库快照＋changes 已足）。

### 5.4 回滚
- 新增撤销语义：`kind=confirm, v=revoke`（或 `return_resolve` 同类），绑定表取最新时视同「无裁决」；排除名单消费者支持撤销。
- 判定记录带 `batch_ai_run`，可以「整次 AI 运行回滚」：列出该运行落的事件 → 批量写撤销。

### 5.5 指标与金标
- **AI 判对率**：分档报 precision（落了的有多少对）、escalate 率、用户推翻率。
- **金标来源**：①用户复审／抽检结果（B 档抽样即标注）；②回放：拿已有**用户亲裁**格（vol01 139 条、vol02–04 大量）造合成意见（含故意错票、冲突、刷票），隐去用户答案让 AI 判，对答案；③vision_check 结论与多证人对勘（Step8 collate）作为弱金标；④后续 CV 升级追上的格。
- 读数口径：按 cls（near_form、seg_defect、ref_conflict、ji_yi_si…）分开报，正文与非正文分开报（cv CLAUDE.md 要求）。
- 刷票门槛用真实分布校准（先在 004–010 上积累一个月）。

### 5.6 自动化串起来
proofing-sync（每日）→ AI 裁决器（每日，读中心库快照＋正式库）→ 落 A/B 档事件、出 C 档队列（`guji db sync`）→ `guji rerun --stale`（每日或累积 N 条）→ 重出待审单（rev 自动加一，待审单记 `based_on_db_rev`）→ proofing-sync publish。文本版本（book-text PR）仍可人点头，但「改了哪些格、来自哪些意见」自动成 CHANGES 片段。

---

## 六、建议的领域输入·输出·验收标准（供 GUJI-637 拆块）

### 块 B1：意见台账与 AI 判定记录（中心库口径）
- 输入：现有快照 `feedback/lists/web/<书>/<rev>.jsonl`；cellreview 字段。
- 输出：意见 id 规则（`book:rev:a:voter:ts`）；`<rev>.state.jsonl`、`<rev>.ai.jsonl` 格式说明（放 cv `doc/formats/` 或 guji-format）；F4 改成查台账。
- 验收：vol01 001-r2 的 11 行回填完：5 条 adopted（对上 5 个事件 id）、2 条测试剔除、4 条（`827b…`）superseded/agree；F4 查台账得 0 未处理。

### 块 B2：AI 裁决器 v1（程序化，替代 wo 的 sheet/review.tsv 手工段）
- 输入：B1 台账；pending 0.2 字段；字块图（cache）；正式库事件＋绑定表；固定 prompt＋模型。
- 输出：每格结构化判定（5.1 节格式）；A/B/C 分档；落事件（`actor=model, source=web_ai, tier, opinion_ids`，id 含意见指纹）；C 档队列文件。
- 验收：①回放金标：用 vol01–vol04 已有用户亲裁抽 ≥300 格造合成意见（含 ≥20% 错票、冲突、刷票），A 档 precision ≥99%、A+B ≥97%、所有「推翻人裁／无字／结构类」100% 进 C；②同一输入跑两次事件 0 新增（幂等）；③数据目录路径（迁过的工作区）下跑通，`latest_human` 能读到快照后的新裁决（以 10:7:10 场景造例）。

### 块 B3：事件身份三档与消费者
- 输入：`events.py::counts_as_human`、glyphdb_admit、crop_exclude、bindings。
- 输出：`ai_adjudicated` 档：进 seed_admit 定字（文本生效）、**不进字形库种子／金标**；用户抽检通过升 human；排除名单可撤销＋带锚（与 GUJI-623、设计 15 P4 合做）。
- 验收：单测：AI 事件不进 glyph.db human 通道、不改 `human_verdicts_fingerprint`；revoke 后绑定表视同无裁决、名单条目撤掉；17 步 code_hash 变化按版本规矩出正式版本。

### 块 B4：用户复审页
- 输入：C 档队列＋B 档抽样。
- 输出：卡片页（手机可点、自存）；点完写用户亲裁事件并回写台账。
- 验收：用户在页上裁 20 格，事件逐条带锚进中心库、台账状态全变、`guji audit count` 无漏审无无锚。

### 块 B5：每日自动串联与回显
- 输入：proofing-sync；B2；`guji rerun --stale`；pending_list.py。
- 输出：定时任务（Action 后接服务器 job 或计划任务）：拉→判→落→重跑→重出待审单（rev 自动递增、带 `based_on_db_rev`）→发 COS；卡上自动记一行「收到／自动落／抽检／给用户／驳回」；网站可选显示「已采纳／已处理」。
- 验收：在 004 上连续 3 天无人值守运行，每天摘要数字与台账一致；人为注入 1 条错票、1 条冲突、1 组刷票，分别进 C 档；网站次日对应格状态正确。

### 块 B6：GUJI-589 补验与防刷
- 输入：cellreview.js、KV、管理令牌（用户发）。
- 输出：读回、同格覆盖、限速、管理读四项结论；配 `CELLREVIEW_IP_KEY`，wo／B2 用 `iph` 合并来源；刷票阈值用 004–010 真实分布校准。
- 验收：四项各有实测记录；同 IP 换 aid 的两票在 B2 里被识别为同来源。

### 不在本领域、但要对口的
- GUJI-623（重切后旧切坏裁决不作废）与设计 15 P4：B3 依赖。
- GUJI-610 国内通道：意见入口若改转发中心库，B1 的台账写入口要同口径。
- M11 网站持续反馈（`fixes.jsonl`、`threads.jsonl` 已由 proofing-sync 写进中心库，`proofing-sync-run.mjs:107-136`）：目前同样**没有消费者**，可复用 B1/B2 的形状。
