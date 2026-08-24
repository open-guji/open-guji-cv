# 字形库扩展调研：外部开源字形/异体字数据怎么用

> 2026-08-24 调研记录。背景：字形库现在只有 26 字 / 94 样本（全部来自 book9all 人工
> 审阅），逐字审阅几万字形不现实。本文回答三个问题：①zi.tools 及其上游有哪些能批量
> 拿的开源数据；②业界有没有「拿现成字形免人工建库」的先例、他们怎么做的；③结合本
> 项目现有管线，扩库的可行路线是什么。

## 0. 一句话结论

**不要把字体渲染字形直接当「精确字形模板」入库**——公开文献里没有这么做成功的先例，
且本库 `verify_pair` 的 same 阈值（F1≥0.80）按 open-guji-fonts 实测（跨字体真匹配可低至
0.69）会把命中几乎全滤掉。可行路线是**分层**：

- **精确字形层**（现有 glyph_store，`same` 判定、glyph_knn 权重 3.0）：只进真实刻本字形。
  扩它靠「聚类 + 簇级确认」摊薄人工（本来就是现有设计），以及引入现成的
  **真实刻本标注数据集**（TKH/MTH 等）作为新 edition。
- **语义候选层**（新增，降权、只出候选不出定论）：字体渲染字形（Jigmo/全字庫/一点明朝
  体）+ 康熙字典扫描字形，单独 edition_tag 域 + 单独阈值档，配合**异体字关系表**
  （Unihan + cjkvi-variants + yitizi）做「同一语义字的多写法」展开。

## 1. zi.tools（字統网）调研结论

- 作者是 GitHub 用户 [yi-bai](https://github.com/yi-bai)，个人项目，网站本身不开源，
  **无使用条款页、无 API 文档、无数据下载入口**。
- 技术上有无鉴权 JSON 接口：`https://zi.tools/api/zi/<字>` 返回单字全量数据（实测 ~400KB），
  含异体字关系图（`yi.nodes/edges`，节点按字典出处编码：GKX=康熙、GHZR=汉语大字典等）、
  base64 内嵌扫描字形图（康熙/简牍/传抄古文/各地标准形）、康熙与漢語多功能字庫释文全文。
- **但不建议当数据源批量抓**：无授权条款是灰色地带，且它聚合的上游（汉语大字典、
  漢語多功能字庫、教育部異體字字典网站内容）本身有版权，抓了也不能再分发。
- 它真正的价值：**(a)** 人工查证/抽样交叉验证的参照系（异体字图谱自称 14.4 万字/6.9 万组，
  全网最好用）；**(b)** 作者把两块核心数据开源了，可直接用：
  - [yi-bai/ids](https://github.com/yi-bai/ids)（**MIT**）— zi.tools 同款 IDS 拆字表，三档
    粒度（lv0 笔画级 / lv2 UCV 认同级）；
  - [yi-bai/iwds](https://github.com/yi-bai/iwds) — UCV 认同规则 + 字形图（未标 LICENSE）。

## 2. 可批量获取的开源数据地图

### 2.1 关系层：字 → 异体字集合（全部可下载、可再分发）

| 数据 | 许可 | 说明 |
|---|---|---|
| Unihan `kSemanticVariant`/`kZVariant`/`kTraditionalVariant` | Unicode License | 最「干净」的基线，覆盖偏少。[Unihan.zip](https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip) |
| [cjkvi/cjkvi-variants](https://github.com/cjkvi/cjkvi-variants) | 无 LICENSE 文件；按「事实数据」用并注明出处 | 22 个文件共 ~10.9 万行 `字,类型,字`。核心：`twedu-variants.txt`（台湾教育部異體字字典抽取版，该字典关系数据唯一机器可读版）、`hydzd-variants.txt`（汉语大字典）、`dypytz-variants.txt`（第一批异体字整理表） |
| [nk2028/yitizi](https://github.com/nk2028/yitizi) | MIT | 现成聚合（OpenCC+韻典+手工表）成 `yitizi.json`，pip/npm 可装，工程上最省事 |
| [yi-bai/ids](https://github.com/yi-bai/ids) 或 [cjkvi-ids](https://github.com/cjkvi/cjkvi-ids) | MIT / GPLv2 | IDS 结构拆解，可按部件替换规则程序化生成「结构异体」候选 |
| OpenCC 词表 | Apache-2.0 | 简繁/异体第一层归一化 |

### 2.2 字形层：字 → 图像/矢量（合成）

| 来源 | 许可 | 定位 |
|---|---|---|
| **GlyphWiki** [dump.tar.gz](https://glyphwiki.org/dump.tar.gz)（116MB，每日更新）+ [kage-engine](https://github.com/kamichikoichi/kage-engine)(MIT) 离线渲染 | GlyphWiki License（自由使用/修改/做字体，无需署名） | **唯一能拿到「同一字多种写法」矢量的开源来源**（`-itaiji-`/`-var-`/各地区标准形 u5263-j/-g/-t/-k…）。注意站点对云 IP 有 403，走 dump 别爬页面 |
| **Jigmo（字雲）** | **CC0** | HanaMin 官方后继，覆盖 Unicode 15.1 全部汉字，仍在更新。批量渲染兜底首选（花園明朝体已 2017 停更，可不用） |
| **全字庫 TW-Sung/TW-Kai/明體**（CNS11643，[data.gov.tw #5961](https://data.gov.tw/dataset/5961)） | OGDL-1.0 / OFL 1.1 | 台湾官方 10 万+ 字，宋体形态与刻本正字最接近，附部首/部件属性表 |
| **一点明朝体 I.Ming**（[ichitenfont/I.Ming](https://github.com/ichitenfont/I.Ming)） | IPA Font License v1.0 | **传承字形（旧字形）**，用字习惯与刻本最吻合，渲染时优先于任何「新字形」字体 |
| 天珩全字库 | ⚠️ 不要用 | 字形拼凑自商业字体，法律不干净 |

许可提醒：`charset_and_lm.md` 已有约定——字体渲染模板**不入库不 commit**，由本地字体
现场生成（CC0 的 Jigmo 理论上可入库，但保持统一纪律更简单）。

### 2.3 真实刻本/写本字形（标注数据集，科研申请、禁商用）

| 数据集 | 规模 | 备注 |
|---|---|---|
| [TKH/MTH v2](https://github.com/HCIILAB/MTHv2_Datasets_Release)（华南理工） | 3,199 页、**108 万字符框、6,733 类**，高丽藏+诸大藏经**刻本** | 逐字 bbox+类别，**最适合直接当新 edition 导入字形库** |
| [HisDoc1B](https://github.com/SCUT-DLVCLab/HisDoc1B) | 4 万本书、**10 亿字符、30,615 类** | 伪标签（管线自动标注），补长尾类别用，精度需自评 |
| [CASIA-AHCDB](https://nlpr.ia.ac.cn/pal/CASIA-AHCDB.html) | 220 万单字、10,350 类 | **写本**（四库抄本+佛经），风格与刻本不同，优先级低 |
| [HNG 漢字字体規範史](https://www.hng-data.org/)（[GitLab](https://gitlab.hng-data.org/HNG/hng-basic-data)） | 数十种有纪年写本/刊本逐字字形卡 | 含宋刊本；量小但字形学价值高 |
| [kangxizidian.com](https://www.kangxizidian.com/) | 康熙字典扫描（同文书局本）按字定位 | **CC BY-SA 3.0**，开放渠道里唯一可批量的「真实雕版字形 per 字头」；但每字仅 1 例、需自己切分净化 |

教育部異體字字典网站有《字彙》《正字通》等明清字书的逐异体扫描图（正是我们最想要的
形态），但**无开放授权**，只能人工参照；关系数据用 `twedu-variants.txt` 代替。

## 3. 业界先例：他们怎么免人工建库

- **阿里「汉典重光」**（2021，20 万页，最终 97.5%）：与本项目同构度最高。第一阶段
  **单字检测 + 无监督聚类，只对聚类中心做专家标注**（≈ 我们的 phase5 + review 流程）；
  第二阶段对样本不足的字类用**字体迁移合成**补到每字 ~10 样本，训练小样本分类器 +
  主动学习迭代。首轮 70% → 两轮 91%。[技术细节](https://www.qbitai.com/2021/05/24032.html)
- **MegaHan97K**（SCUT，PR 2025，97,455 类）：319 个古籍风格 TTF 渲染 + FontDiffuser
  字体生成模型补缺失类。[arXiv](https://arxiv.org/abs/2506.04807)
- **AGTGAN**（ACM MM 2022）等：标准字形 → 真实载体风格的 GAN 迁移，专治小样本类别。
- **关键负面信号**：公开文献里**几乎没有**「现成字体渲染图直接做模板匹配识别刻本」并
  成功的工作——合成字形一律是喂分类器，或先过退化/风格迁移。退化工具现成的有
  [ocrodeg](https://github.com/TalibDaryabi/ocrodeg)、DocCreator；本仓库 `synth.py` 的
  `degrade()` 已实现一部分（腐蚀/膨胀/断笔/噪声）。

## 4. 对接本项目：现状与坑（代码层）

现有管线（详见 char_clustering_design.md）：原始灰度图为真源 → `normalize_patch()`
（Sauvola → 去边缘残条 → 外接框缩放+质心居中 → **3px 笔宽归一**）→ HOG 粗排 +
`verify_pair` 配准精验两级匹配；`GlyphKnnSource` 只采纳 `verdict=="same"`，权重 3.0。

批量导入外部字形时：

1. **不用改代码的入库路径**：往 `glyph_store/` 写 4 个 JSONL + `patches/*.png`
   （**canonical 统一格式**，200×200 灰度、质心居中，规范见
   glyph_canonical_format.md，2026-08-24 起），`glyph-db rebuild` 会自动重算
   norm/skeleton/feat。
2. `synth.py:render_char()` 是现成的字体渲染函数，但它整画布 resize、没走统一
   归一。正确做法：渲染 ≤152px 字面并留足白边，`to_canonical(clean=False)`
   转 canonical 后入库（详见 glyph_canonical_format.md §4）。
3. **笔画粗细不是问题**（`stroke_normalize` 已抹平），真正的差异在骨架形状/部件写法。
4. **阈值是拦路虎**：字体 vs 刻本真匹配相似度可低至 0.69 < THETA_HIGH 0.80。字体来源
   必须单开 verdict/阈值档，且按 §19.4 约定「异 edition 命中只作语义候选」降权——
   `GlyphKnnSource` 目前不区分 hit 的 edition_tag，要一起补。
5. `edition_tag` 另开域（如 `font:jigmo`、`font:iming`、`kangxi-scan`、`mth:tripitaka`），
   `(edition_tag, char)` 唯一键天然隔离，不污染 `wuyingdian-siku-zongmu` 的同版高置信。
6. 字体模板每字 1 例 → `sparse` 标志，下游目前无人消费，需接降权。
7. 已知 bug：`run_update()`（feedback.py:264）还在用旧 `GlyphLibrary` 读新 schema 的
   `glyphs.jsonl`，会 TypeError（待修）。~~`export_store` 不清 patches 孤儿 PNG~~
   已修（2026-08-24，导出时清理 + 迁移脚本已删存量 53 个）。
8. **纪律：先建测试集再动手**（handbook §3 P1）。用 `synth.py` 造「字体模板 vs 刻本」
   配对 + char-ocr 1404 实例金标，重点量字表外字的召回，不看整体 top1。

## 5. 建议路线（按性价比排序）

1. **P0 关系层先行（零风险，纯数据）**：引入 Unihan variants + cjkvi-variants + yitizi，
   建「语义字 → 异体形集合」映射表。立刻能用在两处：候选融合时把 OCR/VLM 报的异体
   归一到正字；为字形库检索做「同义展开」。

   > **已实现（2026-08-24）**：`scripts/build_variants.py` 下载并合并三源
   > （Unihan_Variants 六属性 + cjkvi 的 twedu/hydzd/dypytz/cjkvi-simplified +
   > yitizi@0.1.3，注意 yitizi 的 npm 包里 `dist/yitizi.json` 是 404，数据内嵌
   > 在 `index.js` 里），产物 `config/variants/variants.json`（无向边 + 来源
   > 标签，确定性输出，1.6MB）+ `config/variants/report.json`。规模：**47,724
   > 字 / 44,266 对关系**（twedu 24,615 / hydzd 28,784 / yitizi 8,688 /
   > unihan:kSemanticVariant 2,177 / 简繁各 6,562 / spoofing 181——spoofing
   > 单独打标签，默认不当异体用）。查询模块 `open_guji_cv/variants.py`：
   > `variants_of` / `are_variants` / `variant_group`（默认只走 unihan 非
   > spoofing + twedu + yitizi 的高置信边；全来源展开时最大连通分量 7,869
   > 字——多义桥接的实证，千万别拿连通分量当等价类）。单测
   > `tests/variants/`，不依赖网络。
2. **P1 字体渲染 → 语义候选层**：Jigmo(CC0) + 全字庫宋体 + I.Ming 传承字形三套渲染
   全字表（89,109 字），走 `normalize_patch`，独立 edition_tag + 独立阈值档 +
   GlyphKnnSource 降权通道。先建测试集标定阈值。GlyphWiki dump 补 `-itaiji-` 异体写法
   （一字多形，这是字体给不了的）。
3. **P2 真实刻本数据集当新 edition**：申请 TKH/MTH（6,733 类、108 万刻本字形），按
   book 导入流程进库——这是「精确字形层」不靠人工的唯一扩源。
4. **P3 康熙字典扫描**（CC BY-SA 可批量）：每字 1 例、需切分净化，当雕版风格的语义
   候选补充，`script_style` 标清楚。
5. **远期**：若模板匹配对长尾字仍不够，参考汉典重光/FontDiffuser 路线，用本书已确认
   字形做风格参考，把字体字形迁移成「本书风格」再入候选层。
