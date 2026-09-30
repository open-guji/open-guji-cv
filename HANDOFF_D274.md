# HANDOFF · D 道（overview#274）· 分支 `claude/D-context-guard-0930`

## 基线问题与处理（总管 09-30 指出）
我最初从**旧提交 32b9c2b（≈09-27）**拉的分支（本机 `origin/main` 引用是旧的，没先 fetch），所以先前报告里「本仓没有遮挡闸」是**错的**——闸在 09-28 已合进 main。
已修：`git fetch origin main && git merge origin/main`（merge，未 rebase；冲突 book.py / core/step.py / report/run.py / seed_admit.py 四处）。处理原则：**保留 main 上全部已有闸与字段**
（`context_verdicts`、`context_blank_gate`、`occluded_gate`、`variant_indirect_guard`、`ref_lib_variant_guard`、rare_agree、`book_deps/path_params`、`params_for` 那一串 `_with_book_*`、`collate_book` 的 `page_errors` 容错），只叠加我的护栏：
seed_admit 版本改 **1.11**（main 是 1.10）；`code_deps` 加 `context_guard`；`params_for` 末尾追加 `context_guard_pages` 注入；`collate_book` 保留 main 的 try/except 并给 `collate_page` 传 `codepoints`；
`BookSpec` 同时保留 `step6_ai`/`params` 与 `context_guard_pages`。context 通道内 elif 顺序：verdict 闸 → 整理本冲突 → **我的整页/列首护栏** → 空白格闸 → 放行。
合并后唯一需要改的既有测试：`test_seed_admit_context_verdicts.py` 里的单格列（那格就是列首）——夹具里显式 `context_head_check=False` 隔离，它测的是 verdict 闸，不是我的护栏。

## 改了什么

### 1. `context` 通道护栏（`clustering/context_guard.py` 新，`steps/seed_admit.py` 接线）
护栏同时管 `context` 与 `ref_ctx` 两条通道（后者 provenance 也是 context，整页错位时整理本对齐同样是错的）。**只在 seed_admit 一处执法**；`context_decide` 产物一字未改（它的指纹**不变**，seed_admit 版本 1.10→1.11）。

- **整页错位名单**：现成信号里没有可读的「整页错位」产物（`grep cutline/seg_defect/misalign` 命中的都是别的语义），所以做成**书级配置**
  `context_guard_pages`（`BookSpec` 字段，yaml 顶层，缺省空 = 行为不变）。`RunContext.params_for` 把它注入 `SeedAdmitParams.context_guard_pages`，
  因此**进参数指纹**：改 yaml 名单 → seed_admit 判过期。命中页：`context`/`ref_ctx` 一律不放行，疑问记 `context_guard_page`。
  显式传 `--params context_guard_pages=…` 的优先。
  **ws 的 vol03.yaml 示例（我没改 ws，请总管加）**：
  ```yaml
  context_guard_pages: [49, 107, 110]   # 整段错位页：context 通道退回待审
  ```
- **列首第 1–2 格非字护栏**：读序前 2 格要走 context/ref_ctx 放行时，须满足 **库 verdict ∈ {same, unsure}** 或 **图块墨形像字**
  （`patch_looks_like_char`：Otsu 二值后墨占比 ∈[4%,60%]、面积≥0.05% 的连通块 1~14 个、墨外接框短边 ≥ 图块短边 30%；灰度极差<32 直接否）。
  取不到图（char_patch 缓存没有）→ 视为没证据 → 退回待审，疑问 `context_head_nonchar`。开关 `context_head_check`（缺省 True）。
  **阈值只在合成数据上定**（字形/空白/细长界行/满黑块/散点噪声），没在真书上标定——见下「怎么验」。
- **p110 印章区**（重做，基于合并后的 main）：main 上已有遮挡闸（`steps/occlusion.py`、`seed_admit.occluded_gate`、`page_occluded`），
  判据是「格周围（扩半格）中等墨点密度 → 热格连通成块」，块要同时过：**≥ `occluded_min_cells`(12) 格、横跨 ≥ `occluded_min_cols`(3) 列、峰值密度 ≥ 8、块内中位 ≥ 2.5×页内其余**。
  **p110 没被盖到的原因（推断，没有 vol03 数据实测）**：p110 的印章只有 6 格，块大小硬门槛 12 就过不了——模块头自己记的「十册复核」里 vol09 p68 那方小印「12 格刚好过线」也是同一类。
  `tests/test_context_guard.py::test_small_seal_below_min_cells_is_not_flagged_by_default` 用合成密度表复现：6 格块默认漏、`min_cells=6` 抓得到、12 格大块默认就抓得到（排除别的闸在拦）。
  **没改默认值**：模块头的阈值扫描表显示密度 4 下「块 ≥6 格」在 vol03 有 9 页误报，但那张表**早于**后来加的峰值/对比两道块级闸，加了闸之后 6 格是否仍误报没人量过，我没数据量。
  **最小改法**：先用 vol03 p110 与全册跑 `occluded_cells(..., min_cells=6)`（保留 peak 8 / contrast 2.5），看全册命中页是否只多出 p110；若干净，把 `occluded_min_cells` 改 6（或在 vol03.yaml 用 `params: {seed_admit: {occluded_min_cells: 6}}` 只对本书生效）。
  在此之前 p110 靠 `context_guard_pages: [110]` 兜底（整页 context/ref_ctx 不放行，但注意：**它只拦 context 通道，不像遮挡闸那样连 match_solo 等通道一起拦、也不给「用整理本字」的默认卡**）。

### 2. 三件小修
- **(a) yaml `#` 截断**：`core/book.py` 新 `yaml_comment_truncations()`，`load_book` 读文本时对疑似被 ` #` 截断的未加引号标量发 `UserWarning`
  （判据：值里括号未配平而「被当注释的半截」里有对应右括号，或 `#` 后紧跟数字如 `#195`；带引号的不报）。只警告不报错，不改 ws yaml。
  ⚠️ 副作用：vol03.yaml 那条 label 现在读入会出 warning，且**值仍是被截断的**——需要 ws 侧给值加引号才真正修好。
- **(b) scipy**：`pyproject.toml` 核心依赖加 `scipy>=1.10`（`utils/preclean` 顶层 import scipy.ndimage，RunContext 读页必经）；
  `preclean` 缺 scipy 时抛带安装指引的 `ImportError("缺 scipy…")`。
  局限：控制台/审查页几处 `except Exception → 404/ImageMissing(str(e))` 会把这个报错变成带文字的 404，而不是空白；我没能在仓里找到把它吞成**完全空白**的那个调用点
  （`_col_strip` 读不到图会画灰块，可能是那条），没有去改它。
- **(c) classify 读书级码位**：`report/collate.classify(char, ref, codepoints=None)`，两形按 `codepoints` 归一后相等即 `same`；
  `diff_page` / `collate_page` 加可选 `codepoints` 参数，`report/run.collate_book` 传 `load_book(book).codepoints`。缺省 None = 旧行为。
  没动 `clustering/review/collation_export.classify`（那是 SeedItem 版、另一套，也没读 codepoints；若 70 条来自它请告诉我）。

## 影响面（指纹会变一次，预期）
- `seed_admit`：版本 1.10→1.11 + 新参数字段 + code_deps 加 `context_guard` → **全书 seed_admit 判过期、重跑**。
  重跑后只有下列格会变：guard 页上的 context/ref_ctx 放行格（→待审）；列首前 2 格 context/ref_ctx 放行且库 verdict=diff/无 且图块不像字（→待审）。其它格不变。
  **没有 char_patch 缓存的环境（如刚导入的快照）列首两格 context 放行会全部退回待审**——重跑前先确认缓存在。
- `context_decide`：**不变**（产物、指纹都不动）。
- 下游 `glyphdb_admit` / 审查页会多出这批待审格，`doubts` 新增 `context_guard_page` / `context_head_nonchar`。
- 对勘报告（collate）：书有 `codepoints` 时 diff 数减少（𠮓/變 那 70 条变 same）。

## 怎么在真书上验（我没法验）
需要：vol03 工作区（含 `cache/char_patch`、seed_admit 旧产物）与最终包的 94 格「放行但错」名单。
1. vol03.yaml 加 `context_guard_pages: [49, 107, 110]`，`guji status vol03` 应显示 seed_admit 过期；`guji step seed_admit vol03 --pages 49,107,110`：这三页应无 `channel in (context, ref_ctx)`。
2. 全书重跑 seed_admit，对 94 格名单：统计其中多少现在是 admit=False；再拿人裁为真值的「放行且对」的 context 格，看误伤（新增待审里有多少其实是对的）。
3. 列首阈值标定：取全书列首前 2 格 context 放行者，按 `patch_looks_like_char` 分组，对人裁真值看 precision/recall；调 `INK_MIN/INK_MAX/MAX_COMPONENTS/MIN_EXTENT_FRAC`（都是 `context_guard.py` 顶部常量）。
4. p110 印章 6 格：确认在 guard 页名单后全退回待审。

## 拿不准
- 列首阈值是合成数据上定的，真书上可能对淡墨/残缺字过严（会多进待审，不会多放行）。
- `ref_ctx` 也一并护了（任务书只提 `context`）；若总管认为整理本对齐该保留，把 `_ctx_guard_pass` 从 ref_ctx 分支拿掉即可。
- 整页错位名单目前靠人工配置；长期该由切线闸/人裁 `seg_defect` 事件自动产出。
- 全量测试结果见下（云端 venv：`.[torch]`，deselect 了指定那条）。
