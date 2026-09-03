# 控制台使用手册

给**用这套东西干活的人**。架构为什么这么设计看
[console_architecture.md](console_architecture.md)，这里只讲怎么用。

---

## 0. 起步

```bash
cd D:\workspace\open-guji-cv

# 首次：建环境（仓里的 venv/ 已死，别用）
uv venv .venv --python 3.12
uv pip install -e . pytest fastapi uvicorn pydantic pyyaml opencc-python-reimplemented

# 起控制台
.venv/Scripts/python -m open_guji_cv console
# → http://127.0.0.1:8640/ ，会自动开浏览器；加 --no-browser 不开
```

控制台只监听 `127.0.0.1`。要在 iPad 上用就走 Tailscale 连到这台机器。

**四个视图**：总览、运行、产物、审查、评测。顶栏的「册 / 管线 / 页」是全局选择，
换了它下面所有视图跟着变。

---

## 1. 总览：现在跑到哪了

顶栏选册（vol01 / vol02）与页范围，按「刷新状态」。

**状态矩阵**行是步骤、列是页，每格一个字母：

| 颜色 | 含义 | 该怎么办 |
|---|---|---|
| 绿 `f` | 新鲜——产物是当前代码 + 当前参数跑出来的 | 不用管 |
| 黄 `s` | 过期——指纹失配（改了参数 / 代码 / 上游变了） | 想要最新结果就重跑 |
| 灰 `m` | 缺失——还没跑过 | 跑一遍 |
| 红 `f` | 失败——跑了但报错，鼠标悬停看错误 | 看错误再决定 |
| 斜纹 | 阻塞——上游缺产物，轮不到它 | 先补上游 |

**点任意格子** → 跳到产物视图看那一页那一步的结果。

**页范围**三种写法：`dev_set`（每册固定的 12 页分层小集，默认）、`all`（全书）、
`3-6,9`（页号表达式）。日常调参用 `dev_set`，几十秒一轮；全书跑放后台。

---

## 2. 运行：跑管线

「运行」视图填四样：

- **从 / 到步骤**：只跑一段。改了 Step2 就选 `column_warp` → `cell_shrink`，
  Step1 不用重跑。
- **页**：同上三种写法。
- **参数覆盖**：JSON，如 `{"column_gate": {"width_tol": 0.2}}`。留空用生产默认值。
- **强制重跑**：勾上则无视指纹，全部重算。平时不用勾——**跳过是特性不是偷懒**，
  没变的东西重算一遍只会浪费时间。

按「入队」。任务串行执行，日志实时流式显示。点任务行看它的日志。

**跑完看总览**：受影响的步骤应该变绿。如果某页红了，鼠标悬停看错误——引擎逐页
记录，一页失败不拖垮整轮。

### 命令行等价

```bash
# dev_set 12 页跑完整链
.venv/Scripts/python -m open_guji_cv pipeline keben_body_v2 vol01

# 只跑一段、指定页、改参数
.venv/Scripts/python -m open_guji_cv pipeline keben_body_v2 vol01 \
    --from column_warp --to row_segment --pages 24,42 \
    --params '{"column_gate": {"width_tol": 0.2}}'

# 只跑一步
.venv/Scripts/python -m open_guji_cv step border_detect vol01 --pages 24

# 看状态
.venv/Scripts/python -m open_guji_cv status vol01
```

---

## 3. 产物：看结果对不对

选步骤与页，按「查看」。左边是**叠图**（原图上画出这一步的产物），右边是**数值产物** JSON。

各步叠图画的是什么：

| 步骤 | 叠图上能看到 |
|---|---|
| `border_detect` | 红线界行、蓝线上下版框、抬头框标记 |
| `column_warp` | 逐列窗口的左右边线与列号 |
| `column_gate` | 每列过没过闸、页级 period 与 ref_w |
| `row_segment` | 绿框字格（多边形，弯页是梯形） |
| `cell_shrink` | 紧框；带 flags 的显红 |

**顶部那行灰字**是这份产物的身份证：单位键、指纹、状态、耗时、代码版本。
两次结果不一样时先比指纹——指纹相同而结果不同，说明有不确定性，那是 bug。

### 存储：数值长期，图像即算

产物目录 `products/` 里**只有 JSON**（两册各 12 页约 2 MB）。列图、字块这些派生图像
在 `cache/`（同样规模约 34 MB），可以随时删，下次要用时自动重算。

```bash
.venv/Scripts/python -m open_guji_cv cache usage          # 看占用
.venv/Scripts/python -m open_guji_cv cache prune --limit-gb 5   # 压到 5 GB
```

---

## 4. 审查：人裁与反馈

### 4.1 批次是人裁的调度单位

一批卡片、一个 URL 或一个控制台页面、一份裁决。批次表取代了手写的
`artifacts/README.md` 台账。

```bash
# 建批次
.venv/Scripts/python -m open_guji_cv batch new border-cols-r2 \
    --title "界行切分裁决台 第二轮" --step border_detect \
    --transport artifact --url https://claude.ai/code/artifact/12a167f9 \
    --shard border-detection/column-split --n-cards 63

.venv/Scripts/python -m open_guji_cv batch list        # 看所有批次
.venv/Scripts/python -m open_guji_cv batch list --md   # 出台账 markdown
```

**两种传输**：

- `artifact`：卡片发布成 claude.ai 页面，你在手机上点。**复审必须重发到同一 URL**，
  用户书签和页面本地状态都锚在上面。
- `server`：页面直接跑在控制台，裁决实时回传，断网进本地队列、重连补发。

### 4.2 收割：把裁决收回来

artifact 模式裁完之后，用 `Artifact action:"read"` 读回 HTML，粘进控制台
「收割」框，选批次，按「收割」。

**四种旧格式都认**，自动识别：审查页 HTML、裁决 JSONL、种子事件日志、朱批 JSON。

```bash
.venv/Scripts/python -m open_guji_cv events harvest border-cols-r2 --file 读回的.html
.venv/Scripts/python -m open_guji_cv events list border-cols-r2
```

⚠️ **发布前必须先收割**。不先读回就重发，会盖掉线上还没收割的裁决。批次登记里有这道闸。

### 4.3 路由：裁决自动变成金标

按「试算（不落库）」先看会写什么，确认后按「按路由表消费」。

路由表在 `feedback/routes.yaml`（缺省用内置的），规则形如「`verdict` 类事件 +
`border_detect` 步骤 → 落进 `border-detection/column-split` 分片」。

**消费是幂等的**：同一批消费两次，第二次什么也不做。

```bash
.venv/Scripts/python -m open_guji_cv events route border-cols-r2 --dry-run
.venv/Scripts/python -m open_guji_cv events route border-cols-r2
```

### 4.4 金标分片

审查视图下半部分是 35 个金标分片表：载体、条数、状态分布、抽样分层。

- **载体 `items`** 是已迁到统一信封的（34 个已迁完）；其余显示旧载体名，可点「迁移」。
  迁移**不删旧文件**，两边并存。
- **「漂移检查」**按图像指纹比对：图没变的金标照旧成立，图变了的要回去重看。
  这是产物重生之后必做的一步——**先查漂移，再谈数字**。

```bash
.venv/Scripts/python -m open_guji_cv gold shards
.venv/Scripts/python -m open_guji_cv gold migrate <分片>          # 单个迁
.venv/Scripts/python -m open_guji_cv gold drift <分片> --apply    # 漂移检查并标 stale
PYTHONPATH=. .venv/Scripts/python scripts/verify_gold_migration.py --all   # 校验迁移无损
```

---

## 5. 评测：算法改动有没有变好

「评测」视图列出 27 个评测器。可跑的有「跑」按钮，跑不了的显示原因
（需要 OCR 引擎、重活、需要语料、需要中间产物）。

「跑全部轻量的」批量跑 17 个可跑的，几分钟。

**三种状态**：

| 状态 | 含义 |
|---|---|
| `ok` | 跑通了，指标见表 |
| `regressed` | 跑通了，但**回归门判定不合格**——这是有效结论，不是跑挂 |
| `failed` | 没跑起来（缺产物 / 报错） |

分清 `regressed` 和 `failed` 很重要：前者是门拦住了东西（该去看算法），
后者是门本身坏了（该去修评测）。

**报告里必看三样**：

- **分母**：比值要连着分母读。精确率从 0.71 掉到 0.52 可能不是退步，是缺陷基数变小了。
- **过期金标数**：非零就说明这些数字可能挂在已失效的键上，要先做漂移检查。
- **跳过的 uncertain 数**：人工也判不准的样本不进指标。

```bash
.venv/Scripts/python -m open_guji_cv eval list             # 看有哪些、能不能跑
.venv/Scripts/python -m open_guji_cv eval run              # 跑全部轻量的
.venv/Scripts/python -m open_guji_cv eval run normalize layout
```

---

## 6. 典型工作流

### 改了 Step2 的参数，想知道好没好

1. 运行视图：从 `column_warp` 到 `cell_shrink`，页选 `dev_set`，参数覆盖填 JSON，入队；
2. 总览：确认这四步变绿，Step1 应该纹丝不动；
3. 产物：挑一两页看叠图，肉眼确认没跑偏；
4. 评测：跑 `column_warp`、`instance_quality`，看指标与之前比；
5. 觉得对了，再对全书跑。

### 收一轮人裁

1. 建批次（记下 URL）；
2. 裁完，`Artifact read` 读回 HTML；
3. 审查视图粘贴、收割；
4. 试算 → 消费，裁决进金标；
5. 跑相关评测，看金标扩充后指标怎么变。

### 上游重跑之后

1. 总览确认下游全变黄（过期是对的）；
2. 审查视图对相关分片按「漂移检查」；
3. 有 recheck 的说明图变了，那些金标要回去重看，**别直接信旧数字**；
4. 重跑产物，再跑评测。

---

## 7. 排错

| 现象 | 多半是 |
|---|---|
| 某步整列斜纹（阻塞） | 上游没跑或失败了，先看上游 |
| 跑完还是黄的 | 参数覆盖没生效？指纹含参数，改了就该变绿 |
| 产物页图裂了 | 缓存被清了，刷新页面会自动重算 |
| 评测 `failed` 说「缺产物」 | 那个评测要 `output/<book>/` 下的东西，先跑管线 |
| 评测数字很怪 | 先看报告里的过期金标数；非零就先做漂移检查 |
| 收割回来 0 条 | 读的是不是审查页本身？截图和摘要里没有裁决数据 |

**日志**在 `runs/<任务号>.log`，任务记录在 `runs/<任务号>.json`，控制台重启不丢。

---

## 8. 目录速查

| 路径 | 是什么 | 进 git 吗 |
|---|---|---|
| `products/<册>/<步>/pNNNN.json` | 数值产物（几何、类别、参数） | 否，可重算 |
| `cache/<册>/<种类>/<键>.png` | 派生图像（列图、字块） | 否，缺了现算 |
| `runs/` | 任务日志与记录 | 否 |
| `open_guji_cv/books/*.yaml` | 每册的图源、dev_set、版式常量 | 是 |
| `open_guji_cv/pipelines/*.yaml` | 管线定义（步骤顺序） | 是 |
| `../open-guji-dataset/<分片>/items.jsonl` | 统一金标 | 是 |
| `../open-guji-dataset/feedback/events/` | 人裁事件 | 是 |
| `review/batches/*.json` | 批次登记 | 否（真源随数据集仓） |
