# HANDOFF K238 —— 路径参数出指纹 + manifest 指纹迁移

分支 `claude/K-dbpath-fp-0929`。**没读 overview#238**（会话 GitHub 范围只有 cv 仓），按任务书转述做的；
若 issue 正文有转述里没有的要求，请总管对照。

## 改了什么

`glyph_match` 的 `db_path` 留空时 `model_post_init` 填本机绝对路径，进了 `params_hash` 和 `self_hash`
→ 云端算好的包到服务器必判过期。修法：

- `core/spec.py`：`StepSpec` 新增 **`path_params`**（与 `soft_params` 并列）。路径字段**不进指纹、也不记漂移**
  （路径是机器属性，不是「库变了」）。docstring 里写了登记纪律：只有旁边已有内容指纹、或纯日志目录的才许放。
- `core/engine.py`：`params_hash(params, soft, path)` 三处调用（`self_hash`、`fingerprint`）都剔 `path_params`。
  没登记 `path_params` 的步指纹逐位不变。
- 「库变了只报漂移」口径**没动**：`db_fingerprint` 仍是软参数，`status` 漂移列照旧。

## 哪些步的路径参数被处理了

排查方法：实例化全部 Step 的 Params，扫默认值（含绝对路径 / 带目录 / 文件后缀的字符串），再扫字段名。
测试 `test_no_unregistered_path_like_defaults` 把它固化成守卫：新增路径类默认值不登记会红。

| 步 | 出指纹的字段 | 谁管内容 |
|---|---|---|
| glyph_match | `db_path` | `db_fingerprint`（软参数） |
| seed_admit | `db_path` `variants` `note_lexicon` `exclusions` | `human_fingerprint` / `variants_fingerprint` / `note_fingerprint` / `exclusions_fingerprint`（都是文件名+内容哈希，不含目录） |
| context_decide | `corpus` `general_corpus_dir` `ai_evidence` `llm_log_dir` | `corpus_fingerprint` / `ai_evidence_fingerprint`；`llm_log_dir` 只是调用日志落点 |
| align_ref | `corpus` | `corpus_fingerprint` |

注意 `context_decide.corpus`、`align_ref.corpus` 缺省是**仓内绝对路径**，跟 db_path 是同一个病（换机器就变），
也顺手修了。**故意没放**的：`context_decide.variants`（没有内容指纹，放进去等于换了异体表还报新鲜）。

## ⚠️ 升级副作用（必须迁移）

公式变了，**所有已有 manifest 里上面 4 步的指纹都对不上**（同机旧产物也一样）。上线后先跑迁移再看 `status`，
否则这 4 步及其下游全显示过期。下游不用单独迁：下游指纹只含上游**产物 sha**，产物没动它们就不变。

## 迁移脚本

`python -m open_guji_cv fp-migrate <book> [--pipeline P] [--pages all] [--steps a,b]
  --old-path glyph_match.db_path=/云端/路径 [--old-path ...] [--trust] [--apply] [--json]`

实现在 `products/fp_migrate.py`。**默认干跑**，加 `--apply` 才写；持书级跑批锁；幂等（已迁的报「本来就新」）。

- 只改 `fingerprint / params_hash / self_hash`，产物文件不动；`invalidated / recheck / soft / book / ts` 原样带过去。
- 安全判据：老条目只存哈希、没存参数，所以调用方用 `--old-path` 说出产出那台机器上的路径，脚本用「老路径 + 老公式」
  重算老指纹，**与条目逐位相等才改**——同时证明代码/版本/其余参数/册配置都没变，不会把本该过期的洗成新鲜。
  对不上就跳过并报原因。
- `--trust`：老路径说不清时用。不验老指纹，只查上游 sha 与产物文件 sha。**发现不了代码/参数变了**，默认关。
- 跳过的情形（都报数）：状态非 ok、上游缺失、上游产物变了、产物文件缺失/与记的 sha 不符、没给证据。
- 用法示例（服务器上导入云端包之后）：
  `guji fp-migrate vol03 --old-path glyph_match.db_path=/home/user/ws/output/glyph.db --old-path seed_admit.db_path=… --old-path context_decide.corpus=/home/user/open-guji-cv/corpus/x.txt --old-path align_ref.corpus=…`
  干跑看数对得上，再加 `--apply`。

## 验证

- 新测试 `tests/test_path_params_fp.py`（12 条，合成步骤 + 真步骤参数，无真书依赖）：真步骤登记、哈希对路径不敏感对其它参数/内容指纹敏感、
  守卫、迁移干跑/落盘/幂等/拒绝（不只路径变了、老路径给错、无证据、产物被动过）/`invalidated` 保留、CLI。
- 全量：云端 venv（`.[torch]`）`2452 passed, 3 skipped, 5 deselected`。

## 拿不准的地方

1. **老路径怎么获知**：云端包的路径服务器上不一定知道。`snap pack` 若能把各步路径参数写进包元数据，
   `snap watch` 导入后就能自动调 `fp-migrate`（我没接，任务书没要求、也不该在没确认打包格式时动）。
   目前要人给 `--old-path`，或退到 `--trust`。
2. **`snap watch` 的「cv 兼容」校验**：这次改动让新旧 cv 对同一份产物算出不同指纹。若 snap 兼容校验看 cv 版本/指纹公式，
   需要总管确认是否要把这次算「不兼容变更」（旧 cv 云端包 → 新 cv 服务器，导入后需 `fp-migrate`）。
3. `context_decide.variants` 没内容指纹，默认空所以没事；若哪本书显式给了绝对路径，它仍会带机器路径进指纹。
   要修得先给它加内容指纹（像 `seed_admit.variants_fingerprint`），我没顺手做。
4. `align_ref` 的多证人 `references`（书级配置里的文件路径）是否进指纹我没细查，只确认 `witness_fingerprint` 存在且按内容算。
5. 本仓 checkout 里没有 `doc/pipeline_handbook.md` 和 `cv-pipeline-ops` skill（`doc/` 不在），所以没改文档；
   规则写在 `StepSpec.path_params` 的 docstring 和 `fp_migrate.py` 模块头里，文档仓那边请总管补一句。
6. 干跑/迁移没在真书 manifest 上跑过（要求不依赖真书数据）。
