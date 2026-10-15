# ctx 口径只读比对（GUJI-208aq；交 Ethan 跑，任务书 GUJI-208at）

## 第一屏：怎么跑（单进程、只读）
```bash
# 1. cv 代码根：候选分支 claude/window-candidate-1014 @ 4a78280（含 cv#44/#46/#47），拿 worktree
git -C <cv克隆> fetch origin pull/44/head pull/46/head pull/47/head   # 若还没有候选分支，按 窗口当日执行手册 §一 重建
git -C <cv克隆> worktree add /tmp/win_wt <候选分支或 4a78280>

# 2. 跑（每册约几十秒～几分钟；只读 products，写只落在 --out）
PYTHONIOENCODING=utf-8 python3 项目进展/CV形近字分组/计划/scripts-Evan/ctx_caliber_compare.py \
  --code-root /tmp/win_wt \
  --products-root <含 <book>/seed_admit,glyph_match,align_ref 的产物根> \
  --books vol01 vol02 vol03 vol04 vol05 vol06 vol07 \
  --ry-table <ry-v2 答案表 json> \
  --out /tmp/ctx_compare_out
```
产物：`--out/cells.jsonl`（逐格）、`summary.json`、`summary.md`（汇总表直接贴进 `Step6b-PR2-先量结果-Evan.md`）。
小样例先跑：加 `--pages 24,25` 只看几页。

## 它读什么、不写什么
- 读：`<products-root>/<book>/{seed_admit,glyph_match,align_ref}/pNNNN.json`（用 cv 的 `ProductStore` 读）、`--ry-table`。
- **不写** products/、事件、人裁、答案表、字形库；不调模型；不起子进程。产物根建议用沙箱快照（`GUJI_PRODUCTS_DIR` 同口径）。
- **yaml sha**：脚本不读 yaml；请在 summary 旁贴各册 `book_yaml_sha256`（现场取）与所用 cv commit，复现才对得上。

## 三种 ctx 口径（逐格都过 `ctx_key`：左取最近 □ 之后、右取第一个 □ 之前，各至多 30 字）
| 名 | 序列 | 邻格取字 | 对应 |
|---|---|---|---|
| `adm` | **整页**（列号升序，剔 `excluded`） | 邻格已放行→其 `char`，否则 align 字，否则 □ | `seed_admit._clf_ctx`（现行 ry_group 用它） |
| `pre_col` | **按列分开** | 邻格 same 档字，否则 align 字，否则 □ | cv#47 `group_decide` 现码 |
| `pre_page` | **整页**（同 adm） | 邻格 same 档字，否则 align 字，否则 □ | 假想口径：只改"取字"、不改序列 |

> **新发现（写脚本时对照码发现）**：`group_decide`（cv#47）的邻格序列是**按列**的（`for col in match.columns` 里单列 `seq`），而 `seed_admit._ry_group_pass` 的序列是**整页跨列**的。所以现码除了"取字"不同，还有"序列不同"——邻字窗口在列边界处断开。208ak 的代理量只比了取字（用整页序列），没覆盖这一项，真实差异会更大。脚本里 `pre_page` 就是把这两个因素分开：`adm` vs `pre_page` 只差"取字"，`pre_page` vs `pre_col` 只差"序列"。

## 输出表（`summary.md` / `summary.json`）——三栏口径差（v2，208be）
每册 × 组（ry／jys）：目标格数，以及 ctx 哈希**不同**的格数，分三栏：
- **口径差 1（取字）**：`adm ≠ pre_page`——两边序列都是整页，只差"邻格取已放行字 / same 档字"。
- **口径差 2（序列）**：整页 vs 按列，取字固定。给两个版本互相印证：`adm ≠ adm_col`（都用放行字取字）与 `pre_page ≠ pre_col`（都用 same 档取字）。
- **两者叠加**：`adm ≠ pre_col`——即"seed_admit 现行"对"cv#47 group_decide 现码"的实际差异，PR2 要面对的就是这一栏。
三栏的 jsonl 字段：`diff1_fetch / diff2_seq_adm / diff2_seq_pre / diff_both`。
`ry_table`（给了 `--ry-table` 才有，只针对日曰 ry 组）：
- `hit_adm / hit_pre_col / hit_pre_page`：三种口径下答案表给出非空字的格数；
- `why_*`：三种口径下弃权原因分布（`ctx_mismatch / cache_miss / abstain:… / disagree / haiku_veto / ver_mismatch`）；
- `lost_pre_col / lost_pre_page`：`adm` 有字、换口径后弃权的格数；`changed_char_pre_col`：两边都有字但字不同（应为 0，非 0 要逐格看）；
- `recon_check`：**自校**——重建的 `adm` 口径结果与 seed_admit 产物里记录的 `evidence.ry_group` 对不对得上（只有未放行且当时查过表的格有记录）。`n_match / n_recorded` 应接近 1；明显偏低说明重建有偏差（产物后面的 pass 改了放行状态，或读序近似），**此时结论先别用**，把 `cells.jsonl` 里不一致的格贴给我。
- 局限：`adm` 用的是产物**终态**的放行状态，而 `ry_group` 查表发生在若干后续 pass（shadow 等）之前；对 ry_group 自己放行的格无影响（放行字＝对位字），其余以 `recon_check` 为准。

## 自测记录（我这边）
用合成产物（2 列 7 格，含日／曰）自测通过：语法、读取、三口径计算、汇总均能跑；合成数据里 `adm` 与 `pre_page` 相同、与 `pre_col` 不同，正好体现"按列断开"。没有真书数据，所以没有真书数字。
