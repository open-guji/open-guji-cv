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

`.claude/doc/charset_and_lm.md` 有「字体只取 cmap，不取字形」的纪律，那条
针对的是**商业字体**——字形外框受版权保护。这里两套都是明确允许再分发的
自由字体，随附完整授权文本：

| 目录 | 字体 | 版本 | 授权 | 来源 |
|---|---|---|---|---|
| `jigmo/` | Jigmo 字雲（3 档） | 20230816 | **CC0 1.0**（公有领域奉献） | https://kamichikoichi.github.io/jigmo/ |
| `iming/` | 一点明朝体 I.Ming | 8.10 | **IPA Font License v1.0** | https://github.com/ichitenfont/I.Ming |

IPA License 允许再分发，条件是随附授权全文（见 `iming/LICENSE.md`）且不改名
分发衍生字体——本仓库原样收录，未做任何修改。

Jigmo 三档按 Unicode 区段分工，对本项目字表的独家贡献分别是 28,057 /
61,494 / 9,131 字，缺一不可。

字形匹配力实测见 `.claude/doc/glyph_db_expansion_research.md` §6。
