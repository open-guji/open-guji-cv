# 整理本缺字（〓）按源文本取字＋私用码一码一字（A24 2026-11-03）

r2 的 425 格「整理本缺字」里，新图源（siku-qiefen-v2）每页 `text.jsonl.gz` 在缺字位有真 Unicode 字（40 格试点里 13 格），
或一个固定私用码 U+F1xxx（同码＝同字）。两条路都做成 `ctx_ruling` 事件（group=O、prompt_ver=src-1、subclass=PUA），
由 seed_admit 的 `vis_rulings` 通道放行（通道名 `vis_ruling`，`evidence.vis_ruling.route`＝text_layer｜code_table）。

- `extract_cells.py`：取各册 ★main 包，按列表里的格抽「源文本该位字、对齐锚点、库候选、前后各 20 字窗口」。
- `scan_codes.py`：全册扫出所有私用码格（含已放行），供建码表。
- `code_table.json`：码→字。只收人裁（channel=human）完全一致的码，加 4 个人裁分叉码按已定取字（F1015㸃、F1001垂、F1004勅、F1007瓠）；不在表里的码留空。
- `build_events.py`：生成 events.jsonl（文本层取字要求锚点≥3、页对齐≥0.85；码表要求锚点≥3）。
- `replay_pass.py`：拿真实产物页回放 `_vis_ruling_pass`。r2 回放：256 格有字（文本层 137、码表 119），256 格全部命中窗口键，放出的字与裁定一致。
- 抽样看图 30 格没发现明确错；6 格字体缺字无法比对，交人核（标注页）。

不进事件的格：源文本字是私用码但码不在表里、源文本是〓/□/？/缅甸字母、对齐锚点不足。图形字（篆文、古文）按图片格规则，不走这里。
推库（`guji db sync`）等标注核对后再做。

## 降审：已放行但与码表不一致的 25 格（A31 11-03 定）
`build_demote_events.py`：对 `extract_cells.py`（`CELLS=` 清单）的输出，码表字≠现放行字的格出 `route=code_conflict`、`admit_ok=False` 的 src-1 裁定；`seed_admit` 的 vis_rulings 遍把**非人裁**的已放行格降回待审（doubt `src_code_conflict`，`demoted_from.by=src_code_conflict`）。
回放（`replay_pass-conflict.tsv`）：25 格里 16 格降审，9 格是人裁（provenance human）不碰——人裁与码表冲突要人来改，已单列报 A31。seed_admit 版本 1.32。
