# HANDOFF F4：导出器出 book-text 新形态 char.json ＋ cord.json ＋ norm.json

任务卡 open-guji-core/overview#419（来由：book-text#20、guji-format#4）。分支 `claude/F4-char-cord-1006`，基于 cv main `a985daa`。不合 main、不开 PR。2026-10-06。

## 改了什么

| 文件 | 内容 |
|---|---|
| `open_guji_cv/formats/guji_char_cord.py`（新） | `guji-pages/0.1` → char／cord／norm：`from_pages_json()`。char → 分行稿：`char_to_lines_md()`，记法与 Step9 9.1／`to_guji_markdown` 逐字相同。另有两边一致性核对 `check()`、schema 校验 `validate()`、与 book-text 同口径的 `lines_slots()`，以及按格一行排版的 `dumps()`／`write_files()` |
| `formats/guji_char_v0.1.schema.json`、`formats/guji_cord_v0.1.schema.json`（新） | 从 guji-format `7ad86dc` 原样照抄。测试只读本仓 |
| `scripts/export_guji_format.py` | 新增 `--format char-cord`，带 `--keys cv\|lines` 和 `--text-version`。缺省 `--format legacy` 还是原来那组文件，旧形态没删、没改 |
| `scripts/convert_pages_to_char_cord.py`（新） | **纯转换入口**：旧 pages.json 直接转成 char、cord、norm，不读产物。给了 `--lines-md` 就核往返 |
| `tests/test_guji_char_cord.py`（新，14 条） | 全部用自造数据，见下 |

**没动任何 Step 模块，也没动 `code_deps`。** 动手前 `grep -rn code_deps open_guji_cv/steps/` 核过：所有 code_deps 都在 `utils.*`、`clustering.*` 下，`formats.*` 不在其中。所以各书产物不会被判过期。

## 往返核对（验收第 3 条）

输入用 book-text `wip/siku` 的 `a5b26b4`，也就是 T68 换形态之前的那个提交。其中 vol02 的 `002.pages.json` 和 `002.lines.md` 与 `1c4e7996`（终稿三）没有差别（`git diff` 为空）。命令照下文「本地怎么用」，结果如下：

| | vol02 | vol03 |
|---|---|---|
| 页／格（全部有框） | 188 页／30,480 格 | 110 页／17,366 格 |
| 阙文（`lacuna: true`） | 0 | 6 |
| char schema／cord schema | 过／过 | 过／过 |
| cord 的 `a` 都在 char 里，页号、列号两边一致 | 过 | 过 |
| **char 生成的分行稿与原 `lines.md` 逐字节相同** | 1,856 行，**相同** | 1,061 行，**相同** |
| 列数：cv 口径／lines 口径 | 1,674／1,668 | 972／951 |
| 两种口径 key 不同的格 | 841 | 4,000 |
| cord 里没写的（版框 box 为空） | region 2 个（p1、p2） | region 2 个 |

两种格位口径（`--keys cv`、`--keys lines`）各跑了一遍，四项检查全过。另外：

- `--keys lines` 转出的 `002.char.json`、`003.char.json`，与 T68 推到 wip/siku 的文件**逐字节相同**。
- cord 的 `cells[]` 也和 T68 的相同。差别只在 `marks`：lines 口径下我不写 slot，列号用的是新列号。
- 输入文件的 sha256 前 12 位：002.pages `a91a79ca82d1`、003.pages `c57fd13ed35f`、002.lines `be7eaa49d537`、003.lines `6a38355fc8b1`。

## 要拍板的（已写在 #419）

1. **格位 key 用哪套口径。**
   - `cv`（缺省）：照 spec 02 §二，key 就是 CV 锚点。空列占列号；格用 Step3 slot，行首的排除格、留白格也占号。
   - `lines`：照 book-text `original_version.lines_slots` 去数分行稿。wip/siku 上现有的 char、punct、entity 用的都是这一套。
   - 选 `cv` 的话，wip/siku 上的 punct、entity 要按新 key 重挂。选 `lines` 的话，与 spec 02「空列也占列号」不一致；cord 的留白、排除记号也只能留列号，留不了 slot。
2. **T68 的 cord 带了 char 里没有的列号**：vol02 p38 列 5–9、p76 列 9，vol03 p57、p58 列 1–9、p110 列 7–9，都是页尾的空列。原因是 cord 的 `columns[]` 还在用 CV 列号。有字的列号没有错位。用本道的 `--keys lines` 重转就没有这个问题。
3. **norm.json 的形状**：guji-format 还没有 norm 的 schema。先出 `{schema: "guji-norm/0.2", book_id, volume, table, items: [{a, c, t, by?, why?}]}`，按格位 key 记，不带字偏移。两册现在都是空表。
4. **`lacuna: "defect"` 怎么记**：这类格是字还在、图块切坏了，vol02 有 134 格。char 里不标阙文，也不标 `guess`。只有 `"unreadable"` 才记成 `lacuna: true`，`c` 写「□」。

## 其余取舍

- 列：`raised`、`lead_blank` 不为 0 才写；没有字的列记 `kind: "blank"`，有字的版心列记 `banxin`，正文列不写 kind。char 也写空列（cv 口径），这样两边列号集合相同。
- 格：`lane` 只在推不出来时写。`solo` 总写；夹注只在 key 的后缀与左右对不上时写。lines 口径下单边夹注 `<…>` 一律记 `a`，所以左半边要靠 `lane: jz_l` 区分。
- 残字：字框有 `guess` 且字是「□」时，`c` 写推测的字，并带 `guess: true`；分行稿出 `□{guess=X}`。
- 组字：要给同章的 zi.json，`c` 取近似字（没有近似字时写「〓」），`zi` 写 IDS 或描述。zi.json 里的 `rel` 在 char 里没有对应字段，丢掉了。
- cord 去掉字和 CV 内部字段（`by`、`cv_id`、`o`、`runs`、字框上的 `lacuna`）。`box` 为空的版框、列、格、记号不写；类别不在 schema 枚举里的 region 或 mark 也不写，脚本会报数。印章的 `occludes` 无论原来写的是字框 id 还是 CV 格 id，都换成格位 key。
- `lines_slots()` 比 book-text 那份多做了一件事：把 `:zi[…]` 算作一格。book-text 那份会把 `:zi[⿰扌安]` 拆成好几格，现有两册没有组字，暂时不受影响。
- 纯转换做不了的情形会直接报错，不会悄悄兜底：pages.json 的格没盖满 `n_chars`（有字没框，那些字只在 lines.md 里）；lines 口径下遇到一格多字；格没有锚点。
- 导出器 `--format char-cord` 不处理 `--punct`、`--entity` 的重挂：旧的重挂按字偏移，新形态的伴生层按格位，等口径定了再接。

## 测试

- `tests/test_guji_char_cord.py` 14 条，全部用自造数据。CV 来路沿用 `test_guji_format` 的两页，再手造一份 pages.json，凑齐版心列、空列、单边夹注、残字、defect、一格两字、版框为空、印章压字、`lacuna_extra` 这些情形。钉住的有：两份文件过 schema；cord 不带字；格位、页号、列号一致；两种口径下分行稿都逐字相同；lines 口径数出的 key 等于 `lines_slots`；`check` 能报出不一致；两个入口脚本跑通，往返对不上时返回 1。
- 全量（`python -m pytest tests/ -q -s -p no:cacheprovider`，云端 Python 3.12 venv，装 `.[console,dev]`，没装 torch）：**2596 过、30 跳过、1 败**。败的是 `tests/test_cut_select.py::test_ckpt_fingerprint_empty_for_missing_file`，原因是本机缺模型检查点。在 main `a985daa` 上同样失败，与本道无关；F3 交单也记过这一条。

## 本地怎么用

```bash
# 纯转换（旧 pages.json → 新形态），顺带核往返
python scripts/convert_pages_to_char_cord.py --pages-json 002.pages.json --norm 002.norm.json \
    --lines-md 002.lines.md --keys cv --out out/
# 从产物直接出新形态（先在内存里出 pages.json，再转；写出前核 schema、一致性、往返）
python scripts/export_guji_format.py --products <products 根> --book vol02 --chapter 002 \
    --meta meta_vol02.json --out out/ --format char-cord [--keys cv|lines] [--text-version 0.1.0]
# 测试
python -m pytest tests/test_guji_char_cord.py -q -s -p no:cacheprovider
```

重导 vol02、vol03（#419「之后」一节）时，`--keys` 按拍板的结果给。缺省是 `cv`。要和 wip/siku 现有的 punct、entity 锚点兼容，就给 `lines`。
