# doc/formats：格式文档

| 档 | 是什么 |
|---|---|
| [guji_page_v0.2.md](guji_page_v0.2.md) | 每字带坐标的页面文本格式 guji-page（现行 v0.2；v0、v0.1 留档） |
| [norm_layer_proposal.md](norm_layer_proposal.md) | 规范层（异体 → 通行字）方案调研 |
| `F*_handoff.md` | F1／F2 道交接记录 |
| `samples/` | 各版样例数据 |

标点层 `NNN.punct.json`、实体层 `NNN.entity.json` 的字段规范在 `guji-format` 仓（04 标点、05 实体）；
本仓的产出脚本是 `open_guji_cv/render/{punct_extract,entity_extract,siku_extract}.py`（CLI `scripts/siku_volume_extract.py`）。

## book-text `original` 的版本号（T67，overview#400，用户 10-05 定）

规范全文：overview `项目进展/古籍文本/整体设计/2026-10-文本版本号与仓库流程.md`（v2）。和本仓相关的要点：

- **只有 `original` 跟踪版本**：也就是本项目从书影做出来、进 book-text `<条目>/original/` 的文本。维基、Kanripo、识典的转录不跟踪。
- **三条线各自独立的 `MAJOR.MINOR.PATCH`**：

  | 线 | 文件 | 版本号记在哪 |
  |---|---|---|
  | 文本 | `NNN.lines.md`（纯字流，不放元数据） | `original/index.json` 该章的 `text_version` |
  | 标点 | `NNN.punct.json` | 顶层 `version` |
  | 实体 | `NNN.entity.json` | 顶层 `version` |

  `index.json` 的章条目同时镜像 `punct_version`、`entity_version`，三线一眼可见，网站从这里读。
  像素坐标、字框、`pages.json`、guji-page 属于 CV 产物，**不归文本线**。
- **punct、entity 产物必须带两个字段**：
  - `version`：这一层自己的内容版本。**注意**：流水线原先写的 `"version": "0.1.0"` 指格式版本，
    改按本规范作内容版本解释（格式版本看 `$schema` URL）；
  - `text_version`：这一层是对着哪一版文本做的。流水线产出时填当时 `index.json` 里该章的 `text_version`
    （还没编号的 wip 阶段可写 `0.x` 或不写）。
- **书名两层都记**（guji-format#3）：每个 `work` 实体在标点层也有一对《》，《 `pos: before` 锚书名首字、》 `pos: after` 锚末字，与实体 `anchor.start`／`anchor.end` 一致。
- **锚点校验字**：标点每条带 `anchor`（`页:列:格[子列]`）和 `pre_char`（该格的字）；实体每条带
  `anchor.start`／`anchor.end` 和 `text`（区间内的字）。坐标口径以 `siku_extract.parse_lines_md` 为准
  （空行不占列；夹注 `<甲|乙>` 甲为右列（先读）记子列 a、乙为左列记 b；超框抬头负格位、无第 0 格；`[[…]]`／`□` 记作 □）。
  文本改了以后，book-text 的校验器（overview `validate_text_format.py` 规则 F-OV-02）靠这两样逐个核对；
  改坐标口径必须同步改 overview `项目进展/古籍文本/scripts/original_version.py`。
- **major = 质量等级**（1 可用／2 出版级／3 定本），门槛从严、要用户点头；第一次并 book-text main 时三线定 `1.0.0`，
  前提是够得上第 1 级（标点抽检一致率 ≥95%、实体精确率 ≥90%）。major ≥2 时要带验收记录
  （文本线 `index.json` 章条目的 `text_review`，标点、实体顶层的 `review`，至少含 `date`、`signed_by`、`sample`）。
- **minor／patch**：一次 PR 里一册改动 ≤50 处且逐处改的算 patch；超过，或按规则成批改的（整册重跑、换模型或提示词、
  新增类型……）算 minor。升级用 overview `scripts/book-text/bump_original.py`，它同时写 `original/CHANGES.md`。
  本仓流水线**不自己升版本号**；字段由 T66（overview#397）在流水线里写。
