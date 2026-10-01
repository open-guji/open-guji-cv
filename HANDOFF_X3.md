# HANDOFF X3：Step3 粘连切点「送不送人审」门槛 vs 学出来的闸

分支 `claude/X3-step3-cutgate-1001`（基于 origin/main 70ece04）。**没改任何生产代码、默认不变、不写事件、没碰正式 products。**
任务卡 overview #323（该仓不在本会话授权范围，评论未发，请代贴本文「结论」一节）。
代码与数字全在 `experiments/step3_cutgate/`：`gen_products.py` / `gen_extra.py`（沙箱出产物）、`build_dataset.py`（标签×产物→特征表 `out/table.csv`）、`eval_gate.py`（评测，原始输出 `out/eval_report.txt`）。

## 结论（先说）
1. **学出来的闸没有可靠地比现行门槛好，按「负结果」交。** 同一标签集、同一页分组折（5 折×3 次换分组）上：
   - 标签＝人裁判决（moved/overlap/cand）：HGB 同送审量 246 条漏放 147 vs 现行 149（Δ−2，页自助 95% 区间 [−13,+12]）；LR +3。**无差别**。
   - 标签＝现役选中线与金标差 >5px（含 overlap）：HGB −7 [−19,+6]，LR −4。**区间含 0**。
   - 标签＝同上但剔除 overlap（75 条，物理重叠、切哪都伤字，不是闸能管的）：HGB 漏放 28→22（Δ−6，[−12,−1]），同漏放所需送审 246→195（−21%）。**这是唯一区间不含 0 的格子，但只涉及 112 条阳性里的 6 条，且标签集与现行门槛的标定集重叠（见「口径与偏差」），不足以支持换。**
   - 可信的 page 档（金标锚在原图坐标）只剩 40 条（阳性 13～18），Δ 0～+3，**区间全含 0，没有信息量**。
2. **现行闸 ≈ 单特征 `dis_unet` 阈值曲线**：同送审量下 dis 阈值曲线漏放 159（verdict）/103（cur）/28（noov），与现行 149/103/28 基本重合。也就是现行 7 个手调门槛里真起作用的就是「探针 ∧ dis≥60」，学习闸只在这条曲线上挪一点。
3. **消融**（HGB，同量 246 条的漏放数；全特征 147 / noov 22）：只用 U-Net 一组 148 / 25；去掉 U-Net 一组 153 / 31（noov 下最痛）；只用候选组 153 / 27；只用格高与墨量 171 / 47；只用上下文或只用类别 ≥195 / ≥61（基本没用）。去掉「上下文」反而更好（140 / 25）——这组特征（夹注/抬头/列尾/位置）在这个样本量上只是噪声。**信息几乎全在 U-Net 分歧块与候选间一致率里，没有被现行门槛忽略的强信号。**
4. **PROBE_DEV 探针门槛**：用不含任何 U-Net 量的特征（候选/格高/墨量/上下文）预测「该不该探」，同探量 465 条下覆盖真错 97/112，现行规则 98/112——**持平**；覆盖「探后 dis≥60」229/319 vs 现行 246/319，略低。现行 PROBE_DEV 在这批上漏掉 73 个 dis≥60 的切点，其中 10 个是真错（noov）——这是它的实际代价（换来生产里约 83% 的探针省时）。

## 标签怎么对上、丢了多少
标签 = 测试集 `touching-cuts` active 1599（按 M1 分档：page 101 / legacy 1498）∪ guji-workspace `feedback/events` 里 cutline 事件中**金标没有的键**取最新一条（153，主要是 vol03 blocking/drift 批）。键 = book:page:col:slot_above。合计 1752。
对产物：沙箱重跑 Step1→3（`PROBE_DEV=-1`，让**每个**切点都过 U-Net，信号全采；现行「要不要探针」在评测里离线模拟，`probed_now`）；覆盖 321+58 页（vol01/vol02/vol03/bxgb，overlay 工作区）。
| 去向 | 条数 |
|---|---|
| 入表 | **825**（gold_legacy 679 / event_only 106 / gold_page 40） |
| 锚点漂移（老条目：原格线 y_old 到当前同一格线 >3px，`gold_anchor_shift`） | 783 |
| 当前产物该列没有这个切点 | 108 |
| 带干扰 tag（stain/border/residue） | 14 |
| verdict=idk | 22 |
| 缺产物 / 取不到 | 0（补跑后） |
- page 档按 `colgeom.gold_rows_now` 用页面坐标换算到当前列窗；换算不了的计入漂移。page 101 条里入表只有 40。
- 漂移比 09-16 的结论（666/706 没漂）高得多：云端这套 Step1 与金标所在的那次几何不同（vol03 legacy 74% 漂移、vol01 约 50%）。**这批 legacy 金标现在能用的只有一半。**
- 排除 `chosen_by=human` 的切点（会泄漏标签）：0 条，沙箱没读回流。

两套标签：`lab_verdict`＝判决为 moved/overlap/cand（阳性 272/825＝33%）；`lab_cur`＝现役选中线（缝取均值）与金标 y（+锚点位移）差>5px 或 overlap（187＝22.7%）；`lab_cur_noov` 同上剔 overlap（112/750＝14.9%）。`lab_cur` 才是「**现在**这条线会不会被人改」，verdict 是当年那条线的判决，两者不同源，所以都报。

## 方法
信号（`build_dataset.py`）：dis_unet / agree / 与最优另一几何候选的 agree 差 / 候选里最小 dis / 直线的 dis；候选数、seam_ink、dev_max；上下格高/period、墨占比；是否夹注(sub)/抬头(raised)/疑似整宽正文；列尾、位置、本列切点数、宽度比；kind / origin / chosen_by。
**没有的**：U-Net 的逐像素置信分布（`assess` 只回 agree 与 dis）、图像侧量（直线处行墨占比——NOTES 已证伪为非单调信号、seal_region：页级产物不在本表路径上）。
模型：LR（标准化、class_weight 平衡）与 HGB（depth3、150 轮），按**页**分组 5 折，换 3 次分组顺序平均；比较口径＝同送审量漏放数 / 同漏放所需送审量；Δ 的 95% 区间是按页自助 400 次（比较对象＝现行闸在同重抽样下的送审量与漏放）。

## 口径与偏差（影响怎么读）
- 标签集是「曾经出过卡的切点」，不是全体切点：PENDING_BLOB=60（60 条）、ESCALATE_BLOB=100（673 条）、PROBE_DEV 都是在这批或其子集上标的，**对现行门槛是样本内**；学习闸是样本外（折外）。这对现行有利，所以「不比现行差」比「比现行好」更可信。
- 阳性率（33%/15%）高于生产全体切点，绝对漏放率不可外推，只看相对。
- overlap 75 条（vol01 为主）是天花板型，闸管不了；剔除与否结论方向不同，见上。
- 单次产物（一版 Step3、一版 U-Net 权重）；换权重要重跑。

## 对账：能不能替换 `_resolve_and_probe` / `cut_select.py` 里的手调门槛（用户 10-01 补充口径）
| 手调件 | 位置 | 学习闸替换后 |
|---|---|---|
| PENDING_BLOB=60 | cut_select.py:40 | 学习闸出一个分数 τ 取代它：同送审量 Δ 区间含 0（verdict/cur）；**不降但也不升** |
| ESCALATE_BLOB=100 | :69 | 实际阻塞门槛是 60（escalate⊂pending，cards.py 两者都挡）；100 只决定 `escalate` 标记与原因文案，学习闸替不掉「标记」这个语义 |
| PROBE_DEV=0.10 | :57 | 无 U-Net 特征的探针模型覆盖真错 97 vs 98（持平）、覆盖 dis≥60 低 17 条 |
| SPLIT_SHORT/TALL/MASS_MIN + `_split_suspect`（L0′） | row_boundaries.py:1224,1756–1771 | 本集只有 2 个 split_suspect 切点（1 个现役会被改），**无法评估，不动** |
| JUDGE_MARGIN / CC_MAX / MAJORITY / GUIDED_BAND | 选线类 | 任务边界：不换选线，没碰 |
**能删多少**：门槛常量 PENDING_BLOB、ESCALATE_BLOB、PROBE_DEV、SPLIT×3＝6 个，外加 `_split_suspect`＋探针分支约 35 行；**但学习闸要新增**：信号抽取模块（照 `shadow/signals.py`，约 100–150 行）、模型文件＋元数据/指纹/版本闸（照 `shadow/model.py`）、sklearn/pandas 依赖进 Step3 热路径、每个切点一次推理，并且 `escalate` 标记与探针省时的语义仍要保留规则。**净代码量上升、可审计性下降（黑箱 vs 一行 `dis>=60`）；不降这一点成立，但没有「明显简化」。结论：不替换。**
可以简化但与学习无关的一点：现行阻塞门槛等价于「探针 ∧ dis≥60」，若将来想少一个常量，可把 `ESCALATE_BLOB` 当纯标记保留、文档里直说「阻塞=60」，这不在本任务范围，未动。

## 没做 / 建议
- 没实现接入接口（学习闸不优于现行，按任务条件不接）。若用户仍要，接线应照 `shadow/` 做法：`cut_gate/signals.py`（`SIGNAL_VERSION`＋上表特征）、模型 `.joblib`＋元数据、`row_segment` 参数 `cut_gate: false` 默认关、关闭时不进指纹。
- 真正能动指标的是**标签与候选**而非闸：legacy 金标一半已漂移，重标一批 page 口径金标（M1 选项 c）比调闸有用；overlap 75 条是天花板。
- 复跑：`GUJI_WORKSPACE=<overlay> GUJI_PRODUCTS_DIR=<沙箱> python experiments/step3_cutgate/gen_products.py <册> <分片> <总片>`（四册）＋`gen_extra.py`，再 `build_dataset.py`、`eval_gate.py --repeats 3`。overlay 构造见 doc/cloud_eval.md。全程约 1.5 小时 4 核（vol02 个别噪点页 Step3 要 1–3 分钟）。
