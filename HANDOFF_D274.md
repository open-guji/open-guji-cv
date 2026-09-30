# HANDOFF · D 道（overview#274）· 分支 `claude/D-context-guard-0930`

## 改了什么

### 1. `context` 通道护栏（`clustering/context_guard.py` 新，`steps/seed_admit.py` 接线）
护栏同时管 `context` 与 `ref_ctx` 两条通道（后者 provenance 也是 context，整页错位时整理本对齐同样是错的）。**只在 seed_admit 一处执法**；`context_decide` 产物一字未改（它的指纹**不变**，seed_admit 版本 1.7→1.8）。

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
- **p110 印章区**：**本仓里根本没有「印章遮挡闸 / `occluded_gate`」**（`grep -ri occlu|遮挡|occluded_gate` 在 `open_guji_cv/ scripts/ tests/ doc/` 与全部 git 历史里零命中；
  唯一带「印章」字样的是 `gates/column_gate.py` 的 `stamp_noise`，它只挡**整列散布的背景印章噪点**、且只是 flag、不进 reject，不看单格）。
  所以不是「闸没盖到 p110」，而是 cv 里没有这道闸；总管说的闸可能在别的仓/别的分支。
  **最小改法**：p110 直接进 `context_guard_pages`（整页退回待审）就能盖住这 6 格；要通用的单格印章闸，需要一个「格内红墨/大块深色块占比」判据，
  需要真书印章样本标定，云端做不了。

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
- `seed_admit`：版本 1.7→1.8 + 新参数字段 + code_deps 加 `context_guard` → **全书 seed_admit 判过期、重跑**。
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
