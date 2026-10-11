# colend_eval:B 批列端标签 × 现行 Step2 列端规则评测(#534,C5 Esme)

**状态:中间结果(洛杉矶 10-11)。** 只评测,不改 `open_guji_cv/steps/*`,本目录不入 `code_deps`。

## 复现
```
python3 -I research/colend_eval/eval_matrix.py <dataset>/char-segmentation/column-end-class/items.jsonl research/colend_eval
```
数据:open-guji-dataset main `7b9c559`(L3-batch 231 端带引擎出卡时档位快照;另 9 条覆盖在旧占位条上、无引擎字段,不进本矩阵)。


## 更正(叠图后,10-11)
中间结果里把"人判 glued、规则结论 trim/double 的 16 条"标成"★漏判粘字(会伤字)"是**过度推断**。叠图(`overlays/glued_xi_sheet1.png`、`sheet2.png`,红线=规则削线,图为削版框前的列端、下端已翻转)看这 16 条:
削线都落在框条的**下沿**,框条整条被削掉,首字的笔画紧贴红线之下;**没有看到整字被削**。个别笔画贴线(如 113:8:bot、114:6:bot、136:4:top)是否被啃掉几个像素,肉眼定不了,需做像素级核对(削线以上的墨里是否含字身)。
所以 `bi/ci/ei/a3i` 这类"下端按 Step1 内框线补削"的档位对"框粘字"并不伤字,**人判 glued ≠ 规则必须不削**;glued 在这套规则里应理解为"框与首字之间没有间隙(要靠内框线位置精确切)",不是"不可切"。轴一/轴二里把这类按 double 算也只是口径问题,待 Mila 定。

## 口径与限制(先读)
1. 规则"结论"由 `engine_trim_case` 映射:a/d/e→trim;层数≥2 或带 `i`→double;b→glued;c→none。**映射是我的假设**,尤其 `bi/ci/ei`(下端按 Step1 内框线位置补削)是否算"判有内框"需 Mila/Elena 确认。
2. 用的是**出卡时快照**(`fp_match` 全真=点卡时产物指纹与出卡一致),没有重跑引擎;**未叠图**,"伤字""漏框"都是由人判与规则结论的差推出,待叠图证实。
3. `stratum_weight` 缺省,按等权数;样本为分层超采样,**比例不是全书率**。glued(18)/none(3)只列清单。
4. "人眼也难分"没有逐条标签;trim↔double 的互错单列为"边界带",待人眼复核(下一步出叠图)。


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
## 叠图覆核结果(10-11 晚)
- `overlays/c_miss_sheet*.png`(c 档 12 端,人判 trim 11):多数端图里**看不到框墨**(只有侧线),规则"不削"看上去是对的 → 这 11 条"人判 trim"更像是**标签口径/裁法问题**(版框在文字带外?),列入标签复核。
- `overlays/trim_overcut_sheet*.png`(28 条人判 trim、规则判多层):图上确有"粗条+细线"两道,规则的削线落在**第二道的下沿**、字未被削 → 规则对**削位**判对了,"trim vs double"在这批上只是**类别口径**问题(用户说的边界模糊),不是削错。
- `cut_probe.py`(探针,K=3 行 T=0.10):削线两侧都有连续墨的端 11/231;叠图确认**像是削进字的 3 条**:`47:2:bot`(a3,cut=76,人判 double)、`70:8:bot`(d2,cut=82,人判 trim)、`106:5:bot`(b,cut=66,人判 glued);其余(20:9、21:3、21:6、108:7、109:2、114:6、136:4)削线在框下沿、字笔画贴线,3:2:top 是印章/污渍页。图见 `overlays/cut_cross_sheet*.png`。
- 结论:现行规则**削位基本是对的**(231 端里可见伤字 3 条),分类标签(trim/double)与规则层数的出入大多是口径;真正的问题是 ①多层累计削得过深的少数(a3/d2 76–82 行)②c 档与标签的分歧 ③阈值膨胀(33 个阈值)带来的可维护性。
