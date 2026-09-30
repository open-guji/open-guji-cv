# HANDOFF · H 道：印章遮挡格不入字形库（2026-09-30）

分支 `claude/H-seal-nolib-0930`（从 main 223de1a 拉），**未合 main**。云端没有工作区数据，
所有对真库的写操作都由值守在服务器上执行；下面是完整命令。

## 交付了什么

1. **代码堵漏**
   - `steps/occlusion.py::page_occluded(ctx, page, p)` —— 遮挡判据**唯一入口**（seed_admit `_occluded` 已改为调它，逻辑逐字不变）。
   - `feedback/consumers.py::glyphdb_admit`：格落在遮挡块里 → **无论事件 `no_glyph_lib` 是什么一律不入库**，计入
     `res.no_lib` 与新字段 `res.occluded`（`to_dict()` 里有 `occluded`）。判据经 `_occluded_lookup(book, page)`（读该书 cells 产物 + 原图，
     参数取该书 `seed_admit` 解析结果，与 `occluded_gate` 同源）；按 (书,页) 记忆化；可注入 `occluded_of=` 供测试。
   - 前端：遮挡卡提交时 `no_glyph_lib` 恒为 true（`verdictRow` 新增 `occluded` 参数，`gridRows/screenRows/groupRows` 都传）；遮挡卡上「字形不入库」复选框恒显示勾选。
     `tsc -b` 通过，`static/dist` 已重建（旧 `index-CRnj3Knp.js` → `index-CatGJqxd.js`）。原来 `occludedDefault` 只在「卡上还没裁决」时才缺省为真，
     已裁决/走别的入口（网格、簇、整屏提交）的路径带 false，这是 8 格漏进库的路径。
2. **撤库脚本** `scripts/experiments/seal_nolib/find_and_evict.py`（干跑缺省，`--apply` 才写，`--expect N` 条数闸）。
   走 `audit.evict_instance(reason=…)` → 写 `evictions` 审计（`glyph_store_sync` 删除护栏认它），在 `feedback_write_lock` 内，**不改事件**（文本层照出字）。
   撤的是遮挡格里 `v2:<book>:p:c:s` 与同格机器副本 `<book>:p:c:s`（v1 来源同名 id 不动）。幂等。
3. **即/卽、歷/厯重键**：**已有命令** `scripts/glyph_codepoint_unify.py`（H 码位裁定落地，读书级 `codepoints`）。
   发现它漏掉这 4 条的原因：v1 重键后没对上现格的刻例叫 `v1:<book>:p:c:idx`，`_belongs_to_book` 把 `v1:` 前缀当「不属于任何书」。
   已修（认 `v1:<book>:…`），`scan` 输出新增 `library.v1_prefixed` 列表。**不撤，只改 label/semantic/unicode_cp、合并字头、改 admissions.char、
   并对当前 human_chars 解到旧码位的位置追加改判事件。**

## 值守怎么做

前置：服务器 `git fetch && git checkout claude/H-seal-nolib-0930`（或总管验收合并后用 main）；`export GUJI_WORKSPACE=<四庫 ws>`；
跑批相关脚本按惯例 `guji-batch` 包一层（这些都是轻量单进程，可不包）。先备份库：`cp output/glyph.db output/glyph.db.bak-0930`。

### A. 撤 vol03 p3 的遮挡格
```bash
PY=.venv/bin/python
# 干跑：只读
PYTHONPATH=. $PY scripts/experiments/seal_nolib/find_and_evict.py --book vol03 --page 3 --out /tmp/seal_nolib.json
```
核对：`occluded_cells` 应为 126 左右（模块头标定 p3 印章区 126 格）；`cells_in_lib` 应 = 8；`rows[*].events` 是当年裁的事件 id，`instances` 是要撤的库例 id。
`instances_to_evict` 可能 >8（同格机器副本也算）——以干跑输出为准，**把它填进 --expect**。
若 stderr 出现「遮挡检测返回空集」= 读不到 p3 的 cells 产物/原图（先 `guji status vol03`），**此时不要 apply**。
```bash
PYTHONPATH=. $PY scripts/experiments/seal_nolib/find_and_evict.py --book vol03 --page 3 --apply --expect <instances_to_evict>
```
验：
```bash
sqlite3 output/glyph.db "select instance_id,char,reason from evictions where reason like 'H-seal%';"   # 条数 = evicted
PYTHONPATH=. $PY scripts/experiments/seal_nolib/find_and_evict.py --book vol03 --page 3                # 再干跑：instances_to_evict 应为 0
```
之后 store 由 `guji-glyph-store-sync.timer` 下一轮导出（或手跑 `scripts/glyph_store_sync.py --no-push` 看删除护栏放行）。

### B. 四庫即/卽、歷/厯重键（书级 yaml 已配 codepoints，ws a16c65d7）
```bash
PYTHONPATH=. $PY scripts/glyph_codepoint_unify.py --book <四庫册id> --out /tmp/unify_scan.json    # 干跑（缺省）
```
核对 `pairs["即→卽"].library.v1_prefixed` / `["歷→厯"]` 里就是那 4 条（`v1:<册>:148:5:17`、`…:148:6:10`、`…:148:5:7`、`…:5:7:6` 之类），
`library.n` 里其他条数是否合理。册 id 我在云端看不到（4 条页号 148/5，册别请值守按 `sqlite3 … "select instance_id from instances where instance_id like 'v1:%148:5:17'"` 确认）。
```bash
PYTHONPATH=. $PY scripts/glyph_codepoint_unify.py --book <册id> --apply
```
验：再干跑，各对 `library.n / admissions.n / human_chars.n` 应全为 0（幂等）。

### C. 部署
控制台重启用 `runs/restart_console.sh`（新 dist 与 consumer 闸生效；**不要 nohup 再起一个**）。

## 拿不准（保守处理）

- 册 `occluded_gate: false`（书 yaml `params.seed_admit`）时入库闸也跟着关——「同一来源」按字面办；若用户要遮挡闸对所有书无条件生效，删 `_occluded_lookup` 里那两行即可。
- 读不到 cells 产物/原图时闸**放行**（fail-open，返回空集）——否则云端/无产物环境下人裁入库全停。代价：产物缺失的服务器上闸不起作用；`--apply` 前那条 stderr 警告就是为此。
- 遮挡判据用**当前**产物的字格编号；若 p3 重切过、slot 编号变了，干跑列出的格与当年事件可能对不上——以库里实际 id 为准，`events` 只是参考。
- 撤库范围含同格机器副本；若只想撤人裁那 8 例，干跑输出里删掉对应 `instances` 项不方便，请告诉我加 `--human-only`。
- 重键脚本我只修了 `v1:` 前缀识别；4 条具体 id/册别云端看不到，未在真数据上验证。
- 前端 dist 是我在云端 node22 上重建的；未在浏览器里点过（无控制台环境），仅 `tsc -b` + vite build 通过。

## 测试
新增 `tests/test_seal_nolib.py`（同源判据、入库闸 4 条、find/evict 干跑/expect 闸/审计/幂等）、
`test_glyph_codepoint_unify.py::test_v1_prefixed_instances_of_the_book_are_unified`。
定向 29/29 通过；全量结果见下：

全量（云端 venv 装 .[torch]，deselect rare_coldstart 那条）：**2471 passed, 3 skipped, 6 deselected, 0 failed**。

⚠️ 发现：冻结样页 `tests/fixtures`（keben，低分辨率）被遮挡检测判成 **65 格遮挡**（最高密度 11.7）——
检测阈值是按 vol03/四庫高分辨率扫描标定的，低分辨率页会过触发。这不影响真书（标定时十册复核零误报），
但说明检测对分辨率敏感；`test_glyphdb_admit.py` 因此加了 autouse 夹具关掉遮挡查询（该文件测的是别的行为）。
