"""扫一册书，找可能的反色带（Step0 预清理的候选页）。

**这是辅助工具，不是自动化**：它给候选，人工看图确认，再把位置写进
`$GUJI_WORKSPACE/books/<book>.yaml` 的 `preclean:` 段。位置是参数，不猜。

判据
----
竖排页里列与列之间有贯通的空白窄条（栏线之间的纸）。正常页这些列几乎全白；
反色带经过时它们成段变黑 —— `find_bands` 就是找这种「纸列成段变黑」的横条。

坑：不能用「整页墨占比低」来找纸列 —— 被带穿过的列正因为带而变黑，会被排除掉
（循环论证，实测就是这么漏掉 p151 的）。改成先按行墨量挑出**干净行**
（多数行都是干净的），只在干净行上判定哪些列是纸列。

粗筛出来的候选里绝大多数不是反色带，`looks_inverted` 按下面两条判据滤：

1. **上下都夹着正文**（`ctx` 行内、带上下两侧的字列墨占比都 ≥ `--min-ctx-ink`）。
   反色带是扫描故障，落在字堆中间；上下版框只有内侧有字，外侧是页边空白
   （实测版框空白侧 0.00-0.08，反色带两侧都有 0.20-0.45）。
2. **带内纸列是纯黑的一整段**（实黑度 ≥ `--min-solid`）。
   这是「极性反了」的正面证据：纸被翻成黑，黑得干净、没有笔画混进来。
   职名页/目录页整列重复同一个字（vol01 p98 的「翰」、p117 的「編」）也会让
   纸列判定失真，但那是有笔画的墨，实黑度只有 0.6-0.7，过不了这一条。

两条都是**按页自量的相对判据**，不含固定像素。早先的版本靠一对写死的
`--body 450,2600` 把版框区切掉，跨版式不成立 —— vol02 p136 的版面整体下沉
约 110px，上版框落到 y402，既不在预期版框位置、又掉在正文区下界之外：
那次是运气好滤掉了误报，反过来版框沉到 y>450 的页就会冒充正文区反色带报出来
（同类毛病见 Step3 抬头 HR_DIST 绝对像素跨版式失效）。

界行救援：带落在「抬头空栏」里，判据 1 量不到墨
------------------------------------------------
判据 1 假定带的上下都有字，但有一类带不满足：**落在版框内侧的抬头空栏里**。
vol02 p136 就是——那页版面整体下沉约 110px（真上版框在 y≈328，别页在 y≈290），
带落在 y402-417，上下都是空栏，量到上 0.08 / 下 0.05，与版框无异，被判为版框。
两次误判都栽在这里。

**分辨它们的是界行**（用户指出）：界行（列间竖线）在 x=325/875/1069/1268 处
**穿过这条粗线继续往上**，一直到 y≈328 才收 —— 说明 328 那条才是上版框，
402-417 这条在**版框以内**；版框以内不会横贯一条粗线，只能是缺陷。
所以判据 1 不过时再看一眼：带上下各 `RULE_CTX` 行里都数得出 ≥ `MIN_RULES` 条界行，
就放行（`count_rules`）。版框外侧是页边，一条界行都没有，捞不进来。

代价：抬头页的抬头列本身向上突出，看着也像「界行穿过版框」，会被捞进来
（vol04 p11/p30/p44、vol06 p40/p41、vol09 p109 都是这种，看图即可排除）。
十册合计多出 26 页候选，换来 **3 页此前完全扫不到的真带**：
vol02 p136、vol07 p46、p78 —— 其中 vol07 此前是「零候选册」。这笔买卖是划算的。

已知盲区：贴着版框的带，默认滤法会漏
------------------------------------
判据 1 要求两侧都有字，所以**压在上/下版框上的反色带扫不出来** —— 已知 vol01 p48
就是这种（抬头字顶部一条带，上 0.06 / 下 0.31，yaml 里早已登记修复）。

改成「取两侧大者」能捞回 p48，但那样上下版框会全数涌进来（版框内侧本来就有字），
vol01 从 38 页涨到 120+ 页，等于没滤。实测还比过「到页边的墨」「横跨比」
「带内字列白占比」「band_boundary 量到的列数」四个量，都无法把 p48 与上版框分开 ——
**贴边的带在这些页级统计量上与版框同形**，这条盲区是判据本身的，不是阈值没调好。

所以贴边的带靠 `--edge` 单独扫：它把判据 1 换成「大者过线」，专门用来复查版框一带，
输出会多、要人工看图。**换新书时两种都跑一遍**，别只跑默认的。

实测（2026-09-12，十册全扫）：
  默认滤法 vol02 188 页 → 3 页（151/152/153），正是 yaml 登记的那三页，零误报零漏报；
  vol03/06/07 零候选；vol04 4、vol05 2、vol08 1、vol09 2、vol10 1。
  其中**新发现九页真反色带**，八页已登记修复：vol02 p136、vol04 p17、
  vol05 p22/p178、vol07 p78、vol08 p13、vol09 p174/p175、vol10 p135
  （vol07 p46 也是真带，几何还没量准，见 vol07.yaml 的 notes；
  vol04 另外 3 页是墨污不是反色带，本工具只管反色带）。

  vol01 206 页 → 38 页，**已人工确认全是误报**（旧 `--body` 滤法 62 页）：
  vol01 是卷首，職名頁/目錄頁密集，整版九列重复同一个字且横向严格对齐
  （「翰翰翰翰翰」/「林林林林林」），正好骗过「列间纸列成段变黑」这条粗筛判据；
  38 页里 22 页集中在 p98–p128 的職名頁区间。**vol01 全册真带只有 p48 一条**
  （贴着抬头框，默认滤法反而扫不到，见上面「已知盲区」）。
  判据 2 本来就是拦这个的，但重复字笔画粗、个别行实黑度冲到 0.85 以上就漏过来了；
  **不值得为这一册把判据拧紧**（会误伤真带），留给人工扫一眼即可——职名页一看就认得出。

拿到候选之后：量横向范围别用固定阈值切
--------------------------------------
这个脚本只报 y 范围，`segments`（横向范围）要另外量，办法是看「带内哪些纸列变黑了」。
**坑：带薄的一端会被固定阈值切掉。** vol05 p178 的带横跨全部 9 列，但右端 1-2 列
只有 13px 高（中段是 38px），拿「纸列黑占比 > 0.5」当判据就够不到，端点停在 x=1657，
漏掉两列——**修完图上那两列还是黑的，可墨占比数字看着是正常的**。

办法：阈值从 0.5 往下放到 0.35 / 0.25 各量一遍，看端点**收敛**在哪
（p178 在 0.35 和 0.25 都收敛到 1843，那才是真端点；0.15 漂到 2071 是书口另一块污）。
只有一两根孤立列的漂移是噪声，不是带（vol10 p135 在 0.25 下多出的 x=2064 就是，
它和带之间隔着七百多像素的空白纸列）。

用法
----
    python scripts/scan_inverted_bands.py data_full/zongmu/vol02
    python scripts/scan_inverted_bands.py data_full/zongmu/vol01 --edge  # 复查贴版框的带
    python scripts/scan_inverted_bands.py data_full/zongmu/vol01 --raw   # 看粗筛全量
"""
import argparse
from pathlib import Path

import numpy as np
from PIL import Image

# 判据阈值。都是按页自量的相对量，不是像素常数，所以换书一般不用动。
MIN_SOLID = 0.85    # 带内纸列的「实黑度」：反色带 0.92-1.00，重复字/表格线 0.60-0.74
MIN_CTX_INK = 0.15  # 带上下两侧字列的墨占比：反色带两侧都 0.20-0.45，版框空白侧 0.00-0.08
CTX = 120           # 往带上下各看多少行
MIN_RULES = 2       # 界行救援：带上下各自要有几条界行穿过来（版框外侧是页边，一条都没有）
RULE_CTX = 70       # 数界行时往带上下各看多少行（要小于「带到真版框」的距离）


def find_bands(path, min_rows=8, frac=0.20, min_paper=40, ink=128):
    """粗筛：找「列间纸列成段变黑」的横条，返回 [(y0, y1, 纸列墨占比), ...]。"""
    g = np.array(Image.open(path).convert("L"))
    b = g < ink
    h, w = b.shape

    rowink = b.mean(axis=1)
    clean = rowink < np.median(rowink) * 1.5
    if clean.sum() < h * 0.3:
        return []
    paper = b[clean].mean(axis=0) < 0.02
    if paper.sum() < min_paper:
        return []

    rows = b[:, paper].mean(axis=1)
    hot = np.flatnonzero(rows > frac)
    if len(hot) < min_rows:
        return []
    brk = np.flatnonzero(np.diff(hot) > 8)
    segs = [s for s in np.split(hot, brk + 1) if len(s) >= min_rows]
    return [(int(s[0]), int(s[-1]), round(float(rows[s].mean()), 3)) for s in segs]


def count_rules(b, y_from, y_to, min_frac=0.8):
    """这一段里有几条**界行**（列间竖线）。用来判断带是不是落在版框以内。"""
    seg = b[y_from:y_to]
    if seg.shape[0] < 12:
        return 0
    cand = np.flatnonzero(seg.mean(axis=0) > min_frac)
    if not len(cand):
        return 0
    return 1 + int((np.diff(cand) > 3).sum())   # 相邻列聚成一条


def looks_inverted(gray, y0, y1, *, ink=128, ctx=CTX,
                   min_solid=MIN_SOLID, min_ctx_ink=MIN_CTX_INK, edge=False,
                   min_rules=MIN_RULES, rule_ctx=RULE_CTX):
    """这条横带像不像反色带。返回 (是否像, 实黑度, 上侧墨, 下侧墨)。

    两条判据见模块头：上下都夹着正文 + 带内纸列纯黑，都按页自量，无像素常数。
    另有**界行救援**：带上下各 `rule_ctx` 行里都有 ≥ `min_rules` 条界行穿过时，
    判据 1 可以不看墨（见模块头「界行救援」）。

    `edge=True` 把判据 1 放宽成「上下取大者」，用来复查压在版框上的带
    （如 vol01 p48）——代价是上下版框会大量涌入，见模块头「已知盲区」。
    """
    b = gray < ink
    h, _ = b.shape

    rowink = b.mean(axis=1)
    clean = rowink < np.median(rowink) * 1.5
    if clean.sum() < h * 0.3:
        return False, 0.0, 0.0, 0.0
    colink = b[clean].mean(axis=0)
    paper = np.flatnonzero(colink < 0.02)   # 列间纸列
    text = np.flatnonzero(colink > 0.15)    # 字列
    if len(paper) < 10 or len(text) < 10:
        return False, 0.0, 0.0, 0.0

    # 判据 2：带内那些确实变黑的纸列，黑得有多「实」
    band = b[y0:y1 + 1][:, paper].mean(axis=0)
    hit = band > 0.5
    solid = float(np.median(band[hit])) if hit.sum() >= 10 else 0.0

    # 判据 1：带上下各 ctx 行，字列上的墨——默认两侧都要过线（版框只有一侧有字）
    up = b[max(0, y0 - ctx):y0][:, text]
    dn = b[y1 + 1:min(h, y1 + 1 + ctx)][:, text]
    u = float(up.mean()) if up.size else 0.0
    d = float(dn.mean()) if dn.size else 0.0

    side = max(u, d) if edge else min(u, d)
    ok = side >= min_ctx_ink
    if not ok:
        # 界行救援：带上下都有界行穿过来 => 带在版框以内，不是版框线本身。
        # 专治「带落在抬头空栏里」——那一带本来没字，判据 1 量不到墨（vol02 p136）。
        ok = (count_rules(b, max(0, y0 - rule_ctx), y0) >= min_rules
              and count_rules(b, y1 + 1, min(h, y1 + 1 + rule_ctx)) >= min_rules)
    return ok and solid >= min_solid, solid, u, d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", help="原图目录，如 data_full/zongmu/vol02")
    ap.add_argument("--raw", action="store_true",
                    help="不滤，报粗筛全量（调阈值时看这个）")
    ap.add_argument("--edge", action="store_true",
                    help="复查压在版框上的带（判据放宽成上下取大者，输出会多很多）")
    ap.add_argument("--min-solid", type=float, default=MIN_SOLID,
                    help=f"带内纸列实黑度下限（默认 {MIN_SOLID}）")
    ap.add_argument("--min-ctx-ink", type=float, default=MIN_CTX_INK,
                    help=f"带上下两侧字列墨占比下限（默认 {MIN_CTX_INK}）")
    args = ap.parse_args()

    pages = sorted(Path(args.dir).glob("*.png"), key=lambda p: int(p.stem))
    n = 0
    for p in pages:
        segs = find_bands(str(p))
        if not segs:
            continue
        if args.raw:
            kept = [(a, b, f"墨{f}") for a, b, f in segs]
        else:
            gray = np.array(Image.open(p).convert("L"))
            kept = []
            for a, b, _ in segs:
                ok, solid, u, d = looks_inverted(
                    gray, a, b, min_solid=args.min_solid,
                    min_ctx_ink=args.min_ctx_ink, edge=args.edge)
                if ok:
                    kept.append((a, b, f"实黑{solid:.2f} 上{u:.2f} 下{d:.2f}"))
        if kept:
            n += 1
            print(f"p{int(p.stem):<4} " +
                  "  ".join(f"y{a}-{b}({tag})" for a, b, tag in kept))
    print(f"\n{len(pages)} 页里 {n} 页有候选"
          f"{'（粗筛全量，未滤）' if args.raw else
             '（已滤：贴版框模式，上下取大者 + 带内纸列纯黑）' if args.edge else
             '（已滤：上下夹正文 或 界行穿过，+ 带内纸列纯黑；贴版框的带看 --edge）'}")
    print("下一步：人工看图确认，再把位置写进 books/<book>.yaml 的 preclean 段")


if __name__ == "__main__":
    main()
