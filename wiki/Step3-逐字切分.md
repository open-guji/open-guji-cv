# Step3 逐字切分（`row_segment`）

<img src="images/step3-cells.png" width="480" alt="vol04 第 9 页：字格">

*vol04 第 9 页的字格。绿框：字；灰框：空格（列头、列尾没字的格位也要占格，后面对位要用）。*

## 做什么

在 Step2 的列图上，把一列切成一格一格，每格标类型（字 `char`、空 `blank`、标点 `punct`），排好读序。殿本是**格位制**的：每列有固定的格数（正文 21 格），先按本页的行距建一张格位表，再在每个格位里找真正的切点。

- 切点不是简单的横线：字与字常常笔画相接，所以沿着「最省墨」的缝走（`seg/seam.py`），拿不准的切点交 U-Net 判官打分（`seg/cut_select.py`）。
- 职名页这种字距不定的列，参照整理本这一列的字数重切（`roster_ref`，史記职名页用得最多）。

## 夹注（双行小字）

正文里的小注是一格位里并排两行小字。切的时候整格先认出来，再左右劈开，读序是**先右行（a）后左行（b）**：

![vol16 第 6 页：右边几列是正文，左边几列夹注，紫色右行、橙色左行](images/step3-jiazhu-v16p6.png)

*vol16 第 6 页。紫框是夹注的右行（`sub=a`），橙框是左行（`sub=b`），绿框是正文大字。*

## 难例：大印下、小注挤在一起

<img src="images/step3-crowd-v46p106.png" width="320" alt="vol46 第 106 页：大印下的夹注列">

*vol46 第 106 页第 4 列，在大印底下：「聖學入門書」五个大字之后接双行小注「巡撫採進本／無卷數　江西」，两行字数不一样多，左行比右行短，空出的位置不切格。*

## 怎么验

切分代码按套书分目录（`books/<套书>/`），每套书有一份**样页单** `samples.yaml`，列着 10–30 页以前出过问题的页。改切分的 PR 要在样页上比改前改后，变了的页逐页看图：

```bash
python scripts/seg_samples.py affected --base origin/dev     # 这次改动牵动哪几套书
python scripts/seg_samples.py submit --set affected --base origin/dev --cv <分支> --why "…"
```

细节：[doc/切分代码结构.md](https://github.com/open-guji/open-guji-cv/blob/dev/doc/切分代码结构.md)、行切分设计 [doc/design/row_boundaries_design.md](https://github.com/open-guji/open-guji-cv/blob/dev/doc/design/row_boundaries_design.md)、粘连与夹注 [doc/design/step3_touching_and_jiazhu.md](https://github.com/open-guji/open-guji-cv/blob/dev/doc/design/step3_touching_and_jiazhu.md)。
