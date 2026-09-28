# 权威字书异体源盘点 —— 脚本

配套文档：[`doc/variant_authoritative_sources_survey.md`](../../doc/variant_authoritative_sources_survey.md)、
[`doc/touchstone_87pairs.tsv`](../../doc/touchstone_87pairs.tsv)。
任务书：`overview` 仓 `项目进展/图片初步数字化/进度/字形库/任务书-H-权威字书异体源.md`。

**本轮只盘点＋核查，不写 `config/variants/variants.json`、不改任何库。**

## 文件

- `muse_87pairs.json`：从审查页 <https://claude.ai/artifact/QgMY2HwMiaV8qCWtifwNq6>
  （issue #18）提取的 87 对 muse 候选（71 新增＋16 弱边复核）原始数据，含 muse 给出
  的依据文本、本书刻例覆盖格数、用户已裁的 7 条判定。**这是本轮核查的输入**，页面本
  身是会话产物、不长期存在，故把提取结果落盘存证。
- `fetch_zdic.py`：按字顺序抓 zdic.net 字头页（`/hans/<字>`），提取基本解释/康熙字典/
  说文解字原文段落。zdic 条款页声明 CC0 1.0，robots.txt 未禁止字头页，可批量取，脚本
  仍按 1.5s 间隔顺序请求、不并发。抓取结果缓存到 `zdic_cache/`（**不进 git**，可重新
  生成）。用法：`python3 fetch_zdic.py muse_87pairs.json zdic_results.json`。
- `check_unihan.py`：查 Unicode 官方 `Unihan_Variants.txt` 里的
  `kSemanticVariant`/`kZVariant`/`kSpecializedSemanticVariant`/`kTraditionalVariant`/
  `kSimplifiedVariant` 等字段。需先下载解压
  `https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip` 到本目录下 `unihan/`
  （**不进 git**，UNICODE LICENSE V3 允许自由使用但没必要跟仓库一起分发这份官方数据）。
  用法：`python3 check_unihan.py`（读 `muse_87pairs.json`，写 `unihan_results.json`）。
- `build_touchstone.py`：合并上面两步的结果，出 `touchstone_87pairs.tsv`（87 对逐条：
  muse 依据、Unihan 命中、zdic 康熙/说文原文摘录、正文互现信号、用户已裁判定）。

## 复现

```bash
cd scripts/variant_authoritative_sources
mkdir -p unihan && curl -sS -o unihan/Unihan.zip \
  https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip && \
  unzip -o -q unihan/Unihan.zip -d unihan
python3 fetch_zdic.py muse_87pairs.json zdic_results.json
python3 check_unihan.py
python3 build_touchstone.py
cp touchstone_87pairs.tsv ../../doc/touchstone_87pairs.tsv
```

GlyphWiki、教育部《異體字字典》未写自动化脚本：前者的许可与取数方式沿用
`.claude/doc/unencoded_char_sources_survey.md` §2.1 既有调研（dump 自由许可但没有
逐条原文出处，只能当索引）；后者「版權所有・翻拷必究」不许可批量抓取，只能人工单条
查阅，详见盘点文档 §1.2。
