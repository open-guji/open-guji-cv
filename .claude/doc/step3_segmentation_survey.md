# 粘连字切分 / 已知转写强制对齐：文献调研（2026-09-05）

## B 已知转写的强制对齐
- B1 ★★★ Yin, Wang, Liu, "Transcript mapping for handwritten Chinese documents by integrating character recognition model and geometric context", PR 2013. 过切分（连通域按宽/宽高比再切）→ 转写字符序列 × 原始段序列网格上 DTW/Viterbi 最大后验；代价 = 分类器置信 f0 + 几何 f1–f4（一元/二元×类相关/类无关，QDF/SVM），MCE+Nelder-Mead 学权重。CASIA-HWDB 1015 页/268,628 字：字级对齐 92.32%（含欠切分行）/ 99.04%（剔除）；只用分类器 91.47/98.37；几何模型在 2000 难行上 94.05→96.79。**过切分后仍 4.46% 字欠切分（真粘连），DTW 无法补救。** 可用性：把几何模型换成 21 格先验、候选换成"格线锚点 ±δ 内所有位置"绕开粘连无墨谷；单字分类器可用 1 万核对字位训；CPU 可跑。
- B2 ★★ Peer, Scius-Bertrand, Fischer, "CTC Transcription Alignment of the Bullinger Letters", VisionDocs@ICCV 2025, arXiv 2508.07904, 代码 nntp (CC BY 4.0). PyLaia CRNN 6.4M 参数；CTC 后验 + 带 ε 的 FSA token-passing DP；**只训 15 epoch 的弱模型对齐更准（88.5 vs 86.1；89.1 vs 77.3）**。CTC 峰给位置不给边界。
- B3 ★★ TCSeg (Tanaka, Osada, Furuhata, ICDAR 2021)：文本条件的字符切分——对每个文本假设分别预测一套边界；数字未确认。
- B4 ★ Fischer 2011 HIP 拉丁手稿 HMM 转写对齐（弱模型也可观）；Wilkinson & Nettelblad 2020 arXiv 2003.11087 只用 1–7% 全标注自举。
- B5 Moccia Code (J. Imaging 2023)：零学习，已知字数 + 均匀宽度先验 45–88%——投影+DP 方法的上界参考，必须加字形信息。
- B6 "A Transcription Is All You Need" ICDAR 2021：attention 图当切分弱标签。

## A 古籍/手写中文字符级切分与检测
- A1 ★★ Wang, Yin, Liu TPAMI 2012 过切分 + 候选格 + 贝叶斯路径搜索（AR 90.75/CR 91.39 转述）；CASIA-HWDB-T 粘连字库（ICFHR 2012）56,469 条粘连串标粘连点。drop-fall / water reservoir 只是候选生成器。
- A2 ★ Yang et al. IEEE Access 2018 TKH/MTH：TKH 1,000 页 32 万字；初始框由竖直投影 + beam search 生成再人工校；RGD 识别引导检测器；数字未确认。
- A3 ★ Ma et al. ICFHR 2020 MTHv2 (arXiv 2007.06890)：3,199 页 108 万字 6,762 类；ResNet-50-FPN Faster R-CNN 字符分支 + FCN 版面分支；**双行小注按字尺寸单独重新分组**；识别 CR/AR 96.07/95.52。
- A4 HRCenterNet (arXiv 2012.05739, IoU 0.81) / HRRegionNet (ICDAR 2021, IoU 0.862)：anchor-free 中心点，不依赖墨谷；边界靠回归，误差几像素以上；GPU。
- A5 KuroNet (arXiv 1910.09433) + Kaggle Kuzushiji 2019：1st/2nd 0.950（Cascade/Faster R-CNN），5th 0.940 CenterNet，8th 0.920 CenterNet-ResNet18+MobileNetV3（CPU 可）；类无关检测 F1≈0.99；"字几乎不重叠"。
- A6 ★ CRAFT (CVPR 2019) 亲和度热图 = 字间连接热图，弱监督按"切出字数 vs 转写长度"加权；KESAR (AAAI 2024, 代码 ABL-HD)：结构知识（近方形/同行同大小/相邻）修正伪框 + Abductive Matching（识别串与行标签 DP 对齐）+ **OSR 过切分-重组**（每框对半切再由识别器打分 DP 重组）；MTH 行分割 F 93.2（CRAFT 89.5）；8×V100 15 h。
- A7 ★ Peng et al. TMM 2022 (arXiv 2207.14801)：1D FCN 沿行每位置预测 p_loc/p_bbox/p_cls，**弱监督：预测串与转写编辑距离匹配上的字才更新伪框**；ICDAR2013 AR 97.70；DTLR (arXiv 2409.17095, 代码)：DINO-DETR + 改造 CTC 只用行转写微调，CASIA v2 AR 96.83，67 ms/行。
- A8：Wu et al. PR 2020 DRL 逐步精修框；Zheng 2016 arXiv 1611.01982 切点当 1D 语义分割；Bizais-Lillig 2024 清刻本 HTR 小数据 + GAN 增广 98.45%；Lee 2024 J. Cultural Heritage 夹注/正文相邻字关系 阅读顺序 98.6%；SCUT-CAB。

## 三条路线（小数据 + 已知转写 + CPU）
1. **网格锚候选 + 单字分类器 + 21 格先验的 DP 对齐**（Yin 2013 / KESAR-OSR 定制版）：候选 = 每条格线 ±δ 所有位置（粘连处照样有候选）；打分 = 分类器对"这块是不是标签字"的置信 + 格线偏差/字高一致性先验；DP 恰好 21 段。自举：97% 格线现法已对 → 干净训练样本。风险：分类器要对带邻字残笔的裁块鲁棒（±δ 随机偏移增广）。
2. **文本条件的 1D 切点热图**（Zheng 2016 / Peng 2022 / CRAFT 亲和度）：列图 → 长度 h 的切点概率；<1M 参数，CPU 每列几十 ms；DP 取恰好 20 个内部切点 + 网格先验；把标签字字形嵌入拼到位置特征（TCSeg 思想）。风险：1 万边界 ≈ 500 列偏小，粘连样本仅 2.6%，需过采样/人工再核 200–300 粘连格。
3. **列级 CRNN + CTC 强制对齐**（Peer 2025 / DTLR）：只需列级文本即可训；CTC 给字中心粗位置（±几到十几像素），需路线 1/2 细化；需较多列（合成/多册）。

## 双行小注：先检测再对齐——按字高（~32 vs 64px）+ 半宽投影切左右子列，各自作为已知文本序列跑同一 DP；子列字数由整理本给出。
## 数据：把粘连案例单独抽成 CASIA-HWDB-T 式小测试集（标粘连点），三条路线同尺比。
