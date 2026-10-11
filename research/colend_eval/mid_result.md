# 列端评测:B 批 231 端 × 现行 Step2 规则(数据 /home/user/open-guji-dataset/char-segmentation/column-end-class/items.jsonl)

fp_match 全真: True;stratum_weight 缺省按 1(样本是分层超采样,**下列比例不是全书率**)。

## 1 四类混淆矩阵(规则结论按档位映射:a/d/e→trim;多层或 i→double;b→glued;c→none)

| 人判＼规则 | trim | double | glued | none | 合计 |
|---|---|---|---|---|---|
| **trim** | 114 | 28 | 0 | 11 | 153 |
| **double** | 7 | 49 | 0 | 1 | 57 |
| **glued** | 2 | 14 | 2 | 0 | 18 |
| **none** | 3 | 0 | 0 | 0 | 3 |
| 合计 | 126 | 91 | 2 | 12 | 231 |

## 2 轴一:内框有无(人判 double=有内框 [含模糊]);规则=多层(层数≥2)或 i 档

- 全部(n=231):TP=49 FN=8 FP=42 TN=132;召回 49/57=86% (95%CI 75%–93%);精确 49/91=54% (CI 44%–64%)
- 下端(n=136):TP=48 FN=5 FP=36 TN=47;召回 48/53=91% (95%CI 80%–96%);精确 48/84=57% (CI 46%–67%)
- 上端(n=95):TP=1 FN=3 FP=6 TN=85;召回 1/4=25% (95%CI 5%–70%);精确 1/7=14% (CI 3%–51%)

## 3 轴二:整段能否削(trim vs double,只看人判 trim/double 的端)

n=210;规则对这些端的结论分布:

| 人判＼规则 | trim | double | glued | none | 合计 |
|---|---|---|---|---|---|
| **trim** | 114 | 28 | 0 | 11 | 153 |
| **double** | 7 | 49 | 0 | 1 | 57 |
| 合计 | 121 | 77 | 0 | 12 | 210 |

- 规则认为"能整段削"(trim/double 结论): 198/210 = 94%;漏削(规则结论 glued/none): 12 端

## 4 分档错误表(按规则档位字母)

| 档 | n | 人判 trim | double | glued | none | 与规则结论一致 |
|---|---|---|---|---|---|---|
| a | 100 | 83 | 15 | 1 | 1 | 84/100=84% |
| b | 8 | 0 | 0 | 8 | 0 | 2/8=25% |
| c | 16 | 11 | 1 | 4 | 0 | 0/16=0% |
| d | 89 | 55 | 32 | 2 | 0 | 67/89=75% |
| e | 18 | 4 | 9 | 3 | 2 | 12/18=67% |

## 4b 按完整档位(含层数/i)

| 档位 | n | trim | double | glued | none |
|---|---|---|---|---|---|
| a | 76 | 72 | 3 | 0 | 1 |
| ai | 3 | 1 | 2 | 0 | 0 |
| a2 | 14 | 10 | 4 | 0 | 0 |
| a3 | 5 | 0 | 5 | 0 | 0 |
| a3i | 2 | 0 | 1 | 1 | 0 |
| b | 2 | 0 | 0 | 2 | 0 |
| bi | 6 | 0 | 0 | 6 | 0 |
| c | 12 | 11 | 1 | 0 | 0 |
| ci | 4 | 0 | 0 | 4 | 0 |
| d | 41 | 38 | 3 | 0 | 0 |
| di | 3 | 0 | 3 | 0 | 0 |
| d2 | 26 | 11 | 15 | 0 | 0 |
| d3 | 19 | 6 | 11 | 2 | 0 |
| e | 9 | 4 | 1 | 2 | 2 |
| ei | 3 | 0 | 2 | 1 | 0 |
| e2 | 6 | 0 | 6 | 0 | 0 |

## 5 错例清单(规则结论≠人判);glued/none 只列清单不报精度

类型 | id | 端 | 档位 | 削行数 | triage end_class | 人判 | 规则结论
---|---|---|---|---|---|---|---
★漏判粘字(会伤字) | vol02:113:8:bot | bot | a3i | 53 | none | glued | double
★漏判粘字(会伤字) | vol02:105:4:bot | bot | bi | 53 | clean | glued | double
★漏判粘字(会伤字) | vol02:114:7:bot | bot | bi | 52 | none | glued | double
★漏判粘字(会伤字) | vol02:134:1:bot | bot | bi | 53 | clean | glued | double
★漏判粘字(会伤字) | vol02:137:2:bot | bot | bi | 54 | clean | glued | double
★漏判粘字(会伤字) | vol02:137:3:bot | bot | bi | 53 | clean | glued | double
★漏判粘字(会伤字) | vol02:137:5:bot | bot | bi | 52 | clean | glued | double
★漏判粘字(会伤字) | vol02:131:2:bot | bot | ci | 52 | none | glued | double
★漏判粘字(会伤字) | vol02:133:1:bot | bot | ci | 46 | none | glued | double
★漏判粘字(会伤字) | vol02:134:2:bot | bot | ci | 52 | none | glued | double
★漏判粘字(会伤字) | vol02:138:8:bot | bot | ci | 52 | none | glued | double
★漏判粘字(会伤字) | vol02:109:2:bot | bot | d3 | 58 | clean | glued | double
★漏判粘字(会伤字) | vol02:123:3:bot | bot | d3 | 62 | none | glued | double
★漏判粘字(会伤字) | vol02:136:4:top | top | e | 5 | clean | glued | trim
★漏判粘字(会伤字) | vol02:138:3:bot | bot | e | 54 | clean | glued | trim
★漏判粘字(会伤字) | vol02:114:6:bot | bot | ei | 53 | none | glued | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:133:2:bot | bot | a2 | 58 | none | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:133:3:bot | bot | a2 | 56 | none | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:133:4:bot | bot | a2 | 54 | none | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:133:8:bot | bot | a2 | 55 | none | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:149:3:top | top | a2 | 22 | none | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:163:4:top | top | a2 | 32 | clean | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:184:6:top | top | a2 | 35 | clean | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:65:2:top | top | a2 | 18 | clean | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:65:4:top | top | a2 | 19 | none | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:81:9:top | top | a2 | 21 | clean | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:125:3:bot | bot | ai | 55 | none | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:108:3:bot | bot | d2 | 54 | none | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:135:7:bot | bot | d2 | 65 | idk | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:136:1:bot | bot | d2 | 52 | clean | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:137:7:bot | bot | d2 | 55 | none | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:138:1:bot | bot | d2 | 54 | none | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:141:3:bot | bot | d2 | 53 | clean | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:17:1:bot | bot | d2 | 28 | none | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:188:2:bot | bot | d2 | 72 | clean | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:39:8:bot | bot | d2 | 31 | idk | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:70:8:bot | bot | d2 | 82 | idk | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:71:8:bot | bot | d2 | 31 | idk | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:108:7:bot | bot | d3 | 68 | clean | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:117:2:bot | bot | d3 | 52 | none | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:118:2:bot | bot | d3 | 62 | clean | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:131:8:bot | bot | d3 | 52 | none | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:140:1:bot | bot | d3 | 53 | none | trim | double
多削内框(trim↔double 边界,人眼也可能难分) | vol02:185:9:bot | bot | d3 | 66 | idk | trim | double
无框被当有框 | vol02:15:7:top | top | a | 3 | none | none | trim
无框被当有框 | vol02:3:2:top | top | e | 2 | clean | none | trim
无框被当有框 | vol02:3:7:top | top | e | 3 | clean | none | trim
漏内框(少削一道) | vol02:141:6:top | top | a | 4 | clean | double | trim
漏内框(少削一道) | vol02:65:8:top | top | a | 3 | clean | double | trim
漏内框(少削一道) | vol02:99:1:top | top | a | 5 | clean | double | trim
漏内框(少削一道) | vol02:122:9:bot | bot | d | 32 | clean | double | trim
漏内框(少削一道) | vol02:154:4:bot | bot | d | 16 | none | double | trim
漏内框(少削一道) | vol02:43:6:bot | bot | d | 19 | none | double | trim
漏内框(少削一道) | vol02:102:3:bot | bot | e | 67 | none | double | trim
漏削(残框) | vol02:155:7:bot | bot | c | 0 | none | trim | none
漏削(残框) | vol02:164:2:bot | bot | c | 0 | none | trim | none
漏削(残框) | vol02:166:8:bot | bot | c | 0 | none | trim | none
漏削(残框) | vol02:175:2:bot | bot | c | 0 | clean | trim | none
漏削(残框) | vol02:182:8:top | top | c | 0 | none | trim | none
漏削(残框) | vol02:32:1:bot | bot | c | 0 | none | trim | none
漏削(残框) | vol02:56:1:top | top | c | 0 | none | trim | none
漏削(残框) | vol02:59:2:top | top | c | 0 | none | trim | none
漏削(残框) | vol02:59:4:top | top | c | 0 | none | trim | none
漏削(残框) | vol02:68:3:top | top | c | 0 | none | trim | none
漏削(残框) | vol02:80:7:top | top | c | 0 | none | trim | none
漏削(残框) | vol02:81:1:bot | bot | c | 0 | none | double | none

共 66/231 端不一致。

### 错例类型计数

- 多削内框(trim↔double 边界,人眼也可能难分): 28
- ★漏判粘字(会伤字): 16
- 漏削(残框): 12
- 漏内框(少削一道): 7
- 无框被当有框: 3

## 6 glued / none 清单(不报精度)

- **glued**(18): vol02:105:4:bot[bi→double], vol02:106:5:bot[b→glued], vol02:109:2:bot[d3→double], vol02:113:8:bot[a3i→double], vol02:114:6:bot[ei→double], vol02:114:7:bot[bi→double], vol02:123:1:bot[b→glued], vol02:123:3:bot[d3→double], vol02:131:2:bot[ci→double], vol02:133:1:bot[ci→double], vol02:134:1:bot[bi→double], vol02:134:2:bot[ci→double], vol02:136:4:top[e→trim], vol02:137:2:bot[bi→double], vol02:137:3:bot[bi→double], vol02:137:5:bot[bi→double], vol02:138:3:bot[e→trim], vol02:138:8:bot[ci→double]
- **none**(3): vol02:3:2:top[e→trim], vol02:3:7:top[e→trim], vol02:15:7:top[a→trim]