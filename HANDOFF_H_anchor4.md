# HANDOFF H：vol03 四条 shadow 人裁补锚 + 新 seed_admit 包（2026-09-30）

分支 `claude/H-anchor4-0930`（cv，基于 main `75f1a90`），**没合 main、没改 cv 代码**。只放本文件。

## 1. 补锚（ws main `03c4ee25`，只动 `feedback/anchors/vol03.jsonl`，+4 行，446→450）

| 事件 | key | 人裁字 | 格框 bbox（raw_page_px@top-right） |
|---|---|---|---|
| evt_vol03-shadow-review-0929_000032 | vol03:53:7:18 | 㫖 | 1428.14,2283.44,1599.26,2399.42 |
| evt_vol03-shadow-review-0929_000005 | vol03:65:9:14 | 彞 | 1805.72,1829.84,1976.48,1946.87 |
| evt_vol03-shadow-review-0929_000010 | vol03:97:6:3 | 卽 | 1255.53,569.2,1429.78,697.49 |
| evt_vol03-shadow-review-0929_000024 | vol03:103:3:15 | 𠮓 | 715.55,1985.82,886.83,2104.82 |

- 格式照现有行：`source: backfill:s266_remap`、quad 顺序＝Step3 `quad_page`（右上、左上、左下、右下）、bbox＝quad 外接。
  quad 直接取 snap `20260929T0450` 的 `row_segment` 的 `quad_page`（不是重新算）。
- **依据**：① 4 格在 0450 与 `20260928T1708-full`（现有 28 条 shadow 补锚用的那版）里 quad **逐位相同**，所以人裁当时看到的就是这一格；
  ② 用原图 `data_full/zongmu/vol03/<页>.png` 按 quad（x 自右缘量起）裁出 4 格目视：框内各是一个完整单字，
  字形与人裁一致（㫖＝旨形上部带「上」、彞、卽、𠮓＝變形异体）；无跨格、无切歪，没有拿不准的。
  这 4 条 glyph_store 里没有当时图块（值守已查），所以没法做指纹比对，只能靠“格框同版 + 目视”。
- 补锚脚本不适用（`scripts/backfill_anchors.py` 靠 glyph_store 图块做模板匹配，这 4 格没有图块），手工按现有格式追加，evidence 里写了 `note`。

## 2. 沙箱重算（同 HANDOFF_S_seed 的做法）

- 环境：cv main `75f1a90`、venv `.[torch]`；沙箱＝ws 书目录整份拷贝（含新补锚）+ `GUJI_WORKSPACE` 指过去，正式 products 没动。
- `glyph-db rebuild` → `snap import` 0450、0451（沙箱、`--no-push`）→ `fp-migrate --trust --apply --pages all --steps glyph_match,rare_candidates,align_ref,context_decide`
  → 在 products 副本上 `step cell_shrink --pages all --force`（char_patch 缓存 110 页 1.6 min）→ `step seed_admit --pages all`（110/110 ok）。
- 结果与 S 的 0338 逐格比对（17171 格，字段全比）：**只有这 4 格变**，全部 `channel: human`、`evidence.human: true`：

| 格 | 0338 | 新包 |
|---|---|---|
| 53:7:18 | 旨 match_solo | **㫖** human |
| 65:9:14 | 彝 ref_lib | **彞** human |
| 97:6:3 | 即 match_replace | **卽** human |
| 103:3:15 | 𠮓 match_replace（字已对） | 𠮓 **human** |

- 汇总不变：放行 **17054** / 待审 **316** / 排除 **52**（这 4 格原本就是放行，只是通道/字变）。
- 其余（p3 撤库 8 格、整页护栏 12 格、108:7:4 釆 等）与 0338 完全一致。

## 3. 新包

cv 分支 `snaptmp/96mid1ogzk/vol03/20260930T0457`（提交 `77f9614`，110 页/111 文件/4.1 MB）。
manifest：`replace-steps`、steps `[seed_admit]`、cv `75f1a906…`、**supersedes `snap/96mid1ogzk/vol03/20260930T0338`**、`allow_downgrade false`、`compatible_with []`。
真 pack 用空 git 库 `--no-push`，再 fetch 成 snaptmp 推上来（同 S）。转 ws 时分支名改回 `snap/96mid1ogzk/vol03/20260930T0457`，提交原样。

## 4. 注意

- ws main 在我推之前已前进到 `aa486dee`（H-evict8，撤 p3 印章 8 例刻例）；沙箱库是按 `a8e15142` 重建的，未含它。p3 那 8 格在 0338/新包里本来就已是待审，影响不到本包。
- seed_admit 指纹含 `human_fingerprint`/`ledger_fingerprint`，服务器现役库若与沙箱库不同，导入后可能仍显示过期，须值守 `status` 核对（同 S 的风险 1）。
- 补锚只让 `bindings` 能把这 4 条 shadow 人裁绑到现行格；`103:3:15` 的 `evidence.no_glyph_lib: true` 是 human 通道的固有标记（同 p3 的 human 格），不是新问题。
