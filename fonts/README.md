# 字体档（字形库的可再生真源）

字形库里 `kind='font'` 的来源不把字形图提交进 Git——15.5 万张 canonical
PNG 无损打包也要 ~420MB、15.5 万个文件，会显著拖垮仓库。改为提交**字体档
本身**（86MB），任何一份克隆都能确定性重建出完全相同的字形。

```bash
python -m open_guji_cv glyph-db import-font           # 重建全部字体来源
python -m open_guji_cv glyph-db import-font --edition font:iming
```

不设 `GUJI_FONT_DIR` 时清单默认就指向本目录。四核约 15 分钟。

## 为什么这两套字体可以进仓库

`doc/design/charset_and_lm.md` 有「字体只取 cmap，不取字形」的纪律，那条
针对的是**商业字体**——字形外框受版权保护。这里两套都是明确允许再分发的
自由字体，随附完整授权文本：

| 目录 | 字体 | 版本 | 授权 | 来源 |
|---|---|---|---|---|
| `jigmo/` | Jigmo 字雲（3 档） | 20230816 | **CC0 1.0**（公有领域奉献） | https://kamichikoichi.github.io/jigmo/ |
| `iming/` | 一点明朝体 I.Ming | 8.10 | **IPA Font License v1.0** | https://github.com/ichitenfont/I.Ming |
| `genmin/` | 源流／源雲／源樣明體 TC（GenRyuMin2 / GenWanMin2 / GenYoMin2） | 2.100 | **SIL OFL 1.1**（`genmin/LICENSE.txt`） | https://github.com/ButTaiwan/genryu-font 、genwan-font 、genyo-font |
| `kangxi/` | TypeLand 康熙字典体 | — | **商业字体**，进可分发产物前须确认授权 | 字语 TypeLand |

`genmin/` 与 `kangxi/` 只做 5-b 生僻字候选的 embedding / HOG 模板（`font_candidates.FONT_ORDER`），
**不在** `config/fonts/manifest.json` 里、不导入字形库当字体域。genmin 三套 2026-09-21 才接进
`FONT_ORDER`（此前在仓里零引用），接进时没量过效果，见该常量的文档串。

IPA License 允许再分发，条件是随附授权全文（见 `iming/LICENSE.md`）且不改名
分发衍生字体——本仓库原样收录，未做任何修改。

Jigmo 三档按 Unicode 区段分工，对本项目字表的独家贡献分别是 28,057 /
61,494 / 9,131 字，缺一不可。

字形匹配力实测见 `doc/research/glyph_db_expansion_research.md` §6。

## 进 R2、按 sha 取回（2026-11-04 起）

三系统设计（字形／语料／模型从 cv 剥离）的字形第三步：cv 带一张字体表 `config/font-registry.json`（路径 → sha256），
字体文件按 sha 存在 R2（键 `sha256/xx/<sha>.txt`）。`guji font fetch` 把本机缺的取回到 `fonts/<路径>`，
`guji pipeline` 起跑前、`install_release.py` 装完都会自动补；读字体的代码与指纹不变。
换字体或加字体后跑 `guji font registry` 重写表、`guji font upload --execute` 上传。

**`kangxi/`（商业字体）不进表、不上 R2**（R2 公开只读），仍随仓走。以后从 git 删字体文件时它要留下或另找私有存放。
