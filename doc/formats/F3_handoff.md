# HANDOFF F3：guji-page × guji-format 合一（A1）＋ pages.json 生成（A2）

任务卡 open-guji-core/overview#398（挂 #387）。分支 `claude/F3-format-merge-1005`，不合 main、不开 PR。2026-10-05。

## 交了什么

| 项 | 位置 | 状态 |
|---|---|---|
| 1 对照表与推荐 | `doc/formats/format_merge_a1.md` | 完成。结论：照 CV 总管初判，改两处（锚点只放 pages.json、lines.md 不加显式锚点；cand/channel 另起 proof.json）、补一处（伴生层同时存偏移+字，重切后 `reattach`） |
| 2 锚点对账 | `scripts/reconcile_lines_anchors.py`；报告 `doc/formats/samples/guji_format_v0.1/check/anchor_reconcile_vol0{2,3}.json`；结论在对照表 §三 | 完成。数出来的锚点错位：vol02 **1,179/30,402**（修 bug 后 1,071），vol03 **5,599/17,376**（修后 5,459）。主因是行首/列中排除格与留白、抬头格是排除格——lines.md 里不留痕，改 `build_anchor_map` 修不掉 → 锚点由 pages.json 给 |
| 3 双向转换器 + 测试 | `open_guji_cv/formats/guji_format.py`；`tests/test_guji_format.py`（8 条，自造数据） | 完成。guji-page ↔ lines.md + pages/proof/norm/zi.json，punct/entity 按锚点重挂、原样带回；往返 = `strip_ext(原页)`，format→page→format 逐字节同；两册真数据整章自检也过 |
| 4 A2 pages.json 生成 | `scripts/export_guji_format.py`（新脚本，不改任何现有导出）；样张 `doc/formats/samples/guji_format_v0.1/vol0{2,3}/`；核对 `check/check_vol0{2,3}.png/.json`、`scripts/check_pages_json_boxes.py` | 完成。vol02 整章 188 页 30,402 格、vol03 整章 110 页 17,376 格云端跑过；抽 40 字画回原图**目测 40/40 对**，图 sha 40/40 对上 |

## 怎么复现

```bash
# 快照（guji-workspace 孤儿分支，叠加顺序照任务卡）
for b in vol02/20260929T1023 vol02/20260929T1024 vol02/20260930T0339; do git -C <ws> archive origin/snap/96mid1ogzk/$b products | tar -x -C <S>/vol02; done
for b in vol03/20260928T1708-full vol03/20260930T0457; do …同上… -C <S>/vol03; done
# meta 见 doc/formats/samples/guji_format_v0.1/meta_vol0{2,3}.json
python scripts/export_guji_format.py --products <S>/vol02/products --book vol02 --chapter 002 --meta meta_vol02.json --out out/
python scripts/export_guji_format.py --products <S>/vol03/products --book vol03 --chapter 003 --meta meta_vol03.json \
    --split-table doc/formats/samples/guji_page_v0.2/split_table_siku.json --out out/
python scripts/reconcile_lines_anchors.py --products <S>/vol02/products --book vol02 --meta meta_vol02.json --out rep.json
python scripts/check_pages_json_boxes.py --pages-json out/002.pages.json --images 4.png=4 42.png=42 … --n 20 --out check.png
python -m pytest tests/test_guji_format.py -s -p no:cacheprovider
```

## 挂不上 / 没推上来的（照任务卡写明）

- **`open-guji/guji-format` 挂不上**（add_repo：无权限）。punct/entity 字段按 book-text `wip/siku-vol02`（`cc2d9d9`）实物 + #385 描述来定，
  没读到 `spec/04-guji-punct.md`、`05-guji-entity.md` 与两份 schema。
- **book-text `wip/siku-vol02` 已推**，但里面**没有 `002.pages.json`**（只有 lines/punct/entity/rich/md、003 的 lines/punct/md）→ pages.json
  schema **待对齐用户 vol02 版**（对照表待定 ★1）。
- **kaiyuanguji-web `wip/duidu` 没推**（ls-remote 无此分支）→ WarpCanvas 读什么字段**待查**，同 ★1。
- book-text 只读，没往里推；工作区 products 没碰（快照解在 scratchpad）。

## 发现（交文本侧）

1. `002.entity.json` 230 条里 216 条 `span` 偏移取出来的字 ≠ `text`，锚点跟着错（起点只 6/230 落在对的格）——`test_vol02_extract.py`
   第 5 步没走对齐表。修法见对照表 §五·1。
2. `build_anchor_map` / `punct_extract.tokenize` 把夹注里的 `[[]]` 数成 4 字（`002.punct.json` 有一条 `pre_char` 是「]」）；
   抬头格数到 0。`guji_format.derive_anchors` 是修正版（只做校验）。
3. vol02 现有 362 条标点里 305 条锚点与 CV 格对上，42 条锚点数错（p3 一页 26 条）。
4. `003.punct.json` 没有 `anchor` 字段。

## 已知问题

- vol03 p106（拆页）`check()` 报 3 个框出 canvas：v0.2 交单已记的老问题（p105–108 产物建在旧裁法的图上），该从 Step1 重跑。
  导出照出、报错不吞。
- 全量测试 2606 过 / 1 败：`tests/test_cut_select.py::test_ckpt_fingerprint_empty_for_missing_file`，本机缺模型检查点，与本道无关
  （本道没碰相关代码）。云端 venv 是现装的（`uv pip install -e . pytest pyyaml pydantic jsonschema pillow scipy fontTools …`）。
- `check_pages_json_boxes.py` 的逐字判据（原位墨占比 > 四个半框平移）太严，只 9/20、10/20 成立——上下平移常压到邻字；验收看目测 + 均值。
- 单边夹注 `<…>`（只有 jz_r 或只有 jz_l）md 里分不出左右，`parse_lines_md` 一律记 jz_r；往返不受影响（lane 在 pages.json 里），
  只影响 `derive_anchors` 的子列。

## 待定清单（详见对照表 §六，每条附推荐）

★1 pages.json schema 等用户版/前端对齐 · ★2 锚点挂格号（推荐）还是稳定 id · ★3 人改 lines.md 与 CV 重导出谁优先（推荐人优先） ·
★4 文本侧工具改从 pages.json 取锚点（推荐改） · ★5 未收字近似字先放 zi.json · ★6 norm.json 初值按方案 C 由 CV 物化 ·
★7 book-text `index.json` 加四个文件键 · ★8 proof.json 进 book-text（推荐进） · ★9 行首排除格不折进 lead_blank
