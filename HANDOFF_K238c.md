# HANDOFF K#238c（分支 claude/K-fpmigrate3-0929）

## 改了什么
1. **`ocr_candidates` 受书级开关管**（指纹 + 读取）
   - `core/spec.py`：`optional_consumes_when` 的开关名支持 `@book.<字段>`，读 `BookSpec` 同名字段；`live_optional_consumes(spec, params, book=None)` 多一个 `book` 形参。
   - `core/engine.py`：两处调用（`upstream_shas`、`_live_upstream`）传 `self.book`。
   - `align_ref` / `context_decide` / `seed_admit`：加 `("ocr_candidates", "@book.ocr_candidates")`；`run_page` 里 `ocr` 只在 `ctx.book.ocr_candidates` 为真时才读，否则 None。
   - 选这个办法的理由：开关本来就在书级、Engine 也读 `book.ocr_candidates`，一处真源；不往三步 params 里再造字段（会与书级开关打架，且要改 `params_hash` 的 dump 规则）。改动只落在 spec 一个函数 + 三步各两行。
   - Engine「关闭时跳过该步」的行为未动，pipeline 拓扑未动。
2. **rare_candidates 指纹可移植**
   - `clustering/cnn_candidates.py`：`real_proto_fingerprint` 进哈希前 `store:<绝对路径>` → `store:<相对工作区根>`（`_portable_store_label`；没设工作区则相对引擎仓根；不在根下则原样）。文件内容指纹本来就跨机器一致。
   - 外部模板 stamp 的「空输入 sha1」：**不是 bug**。`EMB_EXTRA_SPECS` 自 2026-09-08 起为空元组，所以恒为空输入 sha1（`da39a3ee…` 前 16 位），两台机器相同。`--explain` 里原来把它标成 machine=True，已改标 False 并写明原因；将来填了 spec 才会随机器数据变。
3. **`fp-migrate --trust` 支持 rare_candidates**：`fp_migrate.WHOLE_HASH_STEPS={"rare_candidates"}`。这类步没有 path_params/老公式，只能 `--trust`：要求上游 sha 等于现值、产物文件 sha 与条目一致；不 trust 一律不动；不接 `--old-path`（报 na）。align_ref/context_decide/seed_admit 接线后照原逻辑迁（云端记录没有 ocr 键、现算也不再有 → 上游相等）。
4. 单测 `tests/test_book_gate_fp.py`（5 条）：开关关时遗留文件不读、不进指纹、删了指纹不变；开关开照旧；关时遗留产物变了不致过期；整体哈希迁移（dry 不动、trust 迁、真过期不洗、不接 old-path）；real_proto 不同根同内容指纹相同、内容变则变。

## 影响面 / 迁移办法
- **所有书**的 `align_ref`/`context_decide`/`seed_admit`：开关关着的书指纹变一次（ocr 键不再进）；有遗留 ocr 产物的（服务器 vol02 188 页/vol03 40 页）不再读它——**结果可能与旧产物不同，属预期**（09-11 口径）。开关开的书指纹不变。
- **开了 real_proto 的书**的 `rare_candidates`：指纹变一次（路径改相对）。没开的书不变。
- 迁移：先 `guji fp-migrate <book> --steps rare_candidates,align_ref,context_decide,seed_admit --trust --explain`（干跑）看无 skip，再加 `--apply`。align_ref 等旧记录若含 `ocr_candidates` 键会报「上游产物变了」且不迁——这是对的（那是真变化，要重跑）。注意 `--trust` 不能发现代码/参数变化，只在确认无变化时用。
- 全书 Step5-d～7 对服务器那两本仍要重算（本来就过期）。

## 拿不准
- 服务器遗留的 ocr 产物没清理；建议总管确认后手工清或保留（开关关着后无害）。
- `_portable_store_label` 的根用 `workspace_root()`；若服务器上 real_proto store 在工作区之外，仍会带绝对路径。
- 全量测试：见提交说明中的结果。
