# 发版附带 Python 执行包（方案对比；用户 2026-10-23 已点头采用方案 A）

> 起因：用户 2026-10-23 提出——每次发版建 Release 时附一个可直接安装/执行的 Python 包，执行方不必再克隆整仓（克隆太慢）；并问能否直接发到 PyPI。
> **数据边界（用户 10-23／10-24 定）**：CV 版本只管代码和逻辑，数据各有自己的版本。字体（`fonts/`）、语料不进 CV 包，走各自的版本与中心库。`models/`、`config/`、`formats/`、`precleaned/` 过渡期**先随 CV 包**（资源包），等中心库管上这几样再迁出（10-24 卡片选「过渡：三样先随 CV 包」）。
> 用户 2026-10-23 同意：采用方案 A；PATCH 也建 Release（只放附件）；新增发版 workflow；PyPI 暂不发。
> **实施时对第三节的修订**：不加 `GUJI_CV_HOME`、不动那 87 处路径引用（会让多个 Step 的 `code_hash` 变），改为让资源包**按仓库布局解到 `open_guji_cv` 的上一级目录**，`parents[2]` 照旧找得到；源码零改动，`code_hash` 不变（L0）。

## 一、先说结论

1. **推荐：每个正式版在 GitHub Release 上挂两个文件**——`open_guji_cv-X.Y.Z-py3-none-any.whl`（代码，约 2.4 MB）和 `open-guji-cv-data-X.Y.Z.tar.gz`（代码运行要读的 `models/`、`config/` 等资源，约 70 MB 量级，见第三节）。执行方 `pip install <wheel 链接>` 再解压资源包，几十秒，不用克隆 4300 个文件的整仓。
2. **PyPI 技术上能发，但现在不推荐**：wheel 只带代码，装完缺模型/配置会静默出错（第三节）；PyPI 上一个版本发出去**不能改、不能真删**，与「cv_version 钉版、tag 不改不挪」本是一个口径，但一旦资源没处理好就只能烧版本号。等资源问题解决后再议（第五节）。
3. **关键前置发现：现在的 wheel 是残的。** `pyproject.toml` 只打 `open_guji_cv*` 包，实测 `pip wheel .` 得到 2.4 MB 的 wheel，里面**只有** `open_guji_cv/`；而代码里有 87 处用 `Path(__file__).resolve().parents[N]` 找仓库根，其中 `models/`（`datastore/packs.py:297`、`pagetype_model/model.py:18`）、`config/`（`hanzi/symbols.py:12`、`clustering/ids_guard.py:54`）、`fonts/`（`clustering/match.py:89`、`glyph_selfcheck.py:94`）都是**仓库根的兄弟目录**。pip 装进 site-packages 后 `parents[2]` 就是 `site-packages/`，这些目录都不在——所以「只发 wheel」不够，必须先定资源怎么随包。

## 二、现状（实测）

| 项 | 情况 |
|---|---|
| 仓库 | `open-guji/open-guji-cv` 是**公开**仓，默认分支 dev |
| 版本 | `pyproject.toml` 0.5.8，setuptools 构建，入口 `guji`、`guji-cv` |
| Release | 只有 MINOR 才建（规矩第四节），且没有任何发布物；旧 `release.yml`（exe）已停用，`.github/` 目录现在不存在 |
| 打 tag | 云端会话 403，靠 ai-team `process/tag.py` 中转站用 API 打 annotated tag；中转站**明说不建 Release** |
| 构建 | 本机 Python 3.13 用旧 setuptools 会报 `install_layout`，要用隔离构建（`pip wheel .` / `python -m build`） |
| PyPI | `open-guji-cv` 这个名字**还没人占**（查询 404） |
| 体积 | 代码 8.7 MB；`models/` 49 MB（glyph_cnn r4+r5 各 19 MB、partition_unet_v2 11 MB）；`config/` 45 MB（groups 16、hanzi 10、gloss 8、ids 5…）；`fonts/` 194 MB（jigmo 61、kangxi 55、genmin 53、iming 25）；`corpus/` 30 MB |

## 三、资源怎么办（决定方案的关键）

执行一个册到底需要哪些资源，我没有逐步实测，下面是按代码引用做的分类，**落地前要由 A21–A24 各步骤负责人核一遍**：

| 资源 | 谁读 | 建议 |
|---|---|---|
| `models/`（r5 现役 19 MB、partition_unet 11 MB、pagetype/rr_clf/shadow_admit 共 <1 MB） | Step5-b、切分、页型、放行闸 | 随资源包；r4（上一代）可不带，省 19 MB |
| `config/`（字表、变体、IDS、gloss） | 多步 | 随资源包；其中 `config/corpus-pack` 已有中心库管道（`datastore/workcopy.py`） |
| `fonts/`（194 MB） | 生僻字候选、字形库 | **更正（A24 核查，10-23）**：原写「`guji db pull` 取」不成立，datastore 里没有取字体的逻辑；缺字体时 `groups/ids_parts.py` 静默少模板、`clustering/match.py` 读 `fonts/jigmo`。可再分发的 jigmo（CC0）、iming（IPA）、genmin（OFL）约 139 MB，`kangxi`（商业字体，55 MB）**不得**进公开 Release。建议另出一个 `open-guji-cv-fonts-X.Y.Z.tar.gz`（只含前三者；字体极少变，可只在变时更新），**待用户定** |
| `corpus/` | 对勘、语料钉版 | 同上，走中心库（`corpus: N` 钉版已是这个口径） |

资源包不能再靠 `parents[2]` 猜位置。**需要一处小改动**：加一个环境变量（暂名 `GUJI_CV_HOME`，缺省仍为仓库根），所有 `parents[N] / "models|config|fonts"` 收口到一个 `core/paths.py` 的函数里。这是触碰 87 处引用中约十几处的重构，**不改任何 Step 的输入输出，但 `code_deps` 若包含这些文件则 `code_hash` 会变**——按冻结基线分级，初判 L1（改路径解析、产物逐字节不变），实施 PR 里要合前实算 `code_hash` 并写明。

## 四、方案对比

| 方案 | 做法 | 执行方怎么用 | 优点 | 缺点 |
|---|---|---|---|---|
| **A. wheel ＋ 资源包挂 Release（推荐）** | 发版时构建 wheel，打资源 tar，传到该版 GitHub Release | `pip install <wheel URL>`；`curl … \| tar -x -C $GUJI_CV_HOME` | 与现有 tag/版本钉一致；公开仓无需令牌；wheel 小；资源版本与代码版本同号 | 要先做路径收口；PATCH 现在不建 Release（见第六节） |
| B. zipapp / pex / shiv 单文件 | 把代码和依赖打成一个可执行 `.pyz` | `python guji.pyz step …` | 一个文件即用 | 依赖含 numpy、opencv、scipy，按平台/Python 版本分别打，体积大几十到上百 MB；torch/paddle 本就是 extra，无法打进去；资源仍要另给 |
| C. 只发 wheel，资源靠 `guji db pull` | wheel 小，模型/配置从中心库取 | 一条 pip ＋ 一条 pull | 最省 Release 空间 | 模型是「不可重建的真源」（models/README），现在在 Git 里；搬去中心库是架构变化，要先通知 A21–A24、A30，不是本题范围 |
| D. 发 PyPI | `python -m build` ＋ `twine upload`（或 Trusted Publishing） | `pip install open-guji-cv==X.Y.Z` | 体验最好、版本钉最方便 | 公开且不可撤；资源同样要另给；要 PyPI 账号/令牌/Trusted Publisher 配置；wheel 装完缺资源会静默出错（有的路径缺了闸会「静默关死」，见 models/README） |
| E. 现状：克隆整仓 | `git clone --depth 1` | — | 零改动 | 4319 个文件，浅克隆实测工作区 431 MB ＋ .git 250 MB，慢 |

## 五、PyPI 专项回答（用户问「是不是已经可以放进 Python 官方仓库」）

- **能不能**：技术上现在就能打出合格的 wheel/sdist，名字 `open-guji-cv` 也空着。**但还不该发**，原因：(1) 资源问题没解，装上的包跑不全；(2) 仓库公开，PyPI 是公开分发，任何人能装能看，且**不可撤回**（可 yank，文件仍在）；(3) 依赖里有 `paddlepaddle`／`torch` 这类要按环境选轮子的包，已正确放在 extras，但 PyPI 页面上的「开箱即用」承诺会比实际强。
- **公开 vs 私有**：想私有就不是官方 PyPI——可选 GitHub Packages 不支持 Python；私有索引需要自建（如 devpi／云厂商 artifact registry），要钱要运维，不建议。仓库本就公开，Release 附件已经是公开分发，PyPI 只是更方便。
- **凭据**：首选 PyPI **Trusted Publishing**（GitHub Actions OIDC，不存长期令牌），需要用户在 PyPI 注册账号、建项目并添加受信发布者；不要把 API 令牌放进仓库 secrets 之外的任何地方。这些都是用户本人操作，不是我能代办的。
- **建议顺序**：先做 A（含路径收口）→ 跑两三个版本确认执行方（A21–A24、A30 的会话和服务器）都能用 → 再决定是否同一份 wheel 发 PyPI（那时只多一个 workflow 步骤）。

## 六、需要用户点头的事

1. **采用方案 A 吗？**（推荐）；PyPI 先不发。
2. **PATCH 也要建 Release 吗？** 规矩第四节规定 PATCH 不建 Release，但「每发一版就挂执行包」要求每版都有 Release 页放附件。建议：PATCH 建 Release 但**只放附件和一行说明**（可标 `--latest=false`），正文仍只在 MINOR 写完整 release note；这是改规矩第四节，需用户同意。
3. **谁建 Release、怎么触发？** 建议发版 workflow 在 `on: push: tags: ['v*']` 时触发（中转站用 API 打 tag，令牌不是 `GITHUB_TOKEN`，会触发；实施时先用一个 rc tag 验证），构建 wheel ＋ 资源包并 `gh release upload`。`.github/workflows/` 现在是空的，新增 workflow 需要仓库开 Actions 写 contents 权限，**是改仓库设置，等用户点头**；中转站「不建 Release」不变，由 workflow 建。
4. **资源包的内容清单**（第三节表）请 A21–A24 核实后定稿。
5. 若采用，**实施 PR 的步骤**：① `core/paths.py` 收口 `GUJI_CV_HOME`（L1，写明 `code_hash` 影响）；② `scripts/build_release_assets.py` 本地可跑，产出 wheel ＋ 资源包 ＋ sha256；③ `release.yml`（新，替换停用的旧文件）；④ 更新版本号规矩第一、四节和 README 的安装说明；⑤ 用一个 rc tag 空跑验证。

## 七、会影响别人的地方

- 执行方取包方式变化（`pip install` wheel ＋ 资源包代替克隆）**会影响 A21–A24、A30 的会话和服务器**，实施前需经协调者通知；本文档合并本身不改任何东西。
- 资源路径收口若改动 `code_deps` 里的文件，会触发「`code_hash` 变化必须登记」，见第三节。
