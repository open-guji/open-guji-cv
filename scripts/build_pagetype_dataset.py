"""生成页型数据集（page-type）。

金标为人工目视：把全书页面渲染成缩略图接触表，逐页判读。刻本页型在缩略图
尺度上就能认出来（封面是页中一个大框、书签是页侧窄长框、空白页只有界行、
牌记是一角一个小框），不需要看清字。

**不用转写文本定页型**：转写依赖切分，拿它判页型是循环论证；且非正文页的
转写质量最差（封面页基本是乱码），最需要判别的地方恰好最不可信。

标注表在下面的 LABELS，按**区间**记（刻本同类页成段出现）。改标注只改这里。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2

from open_guji_cv.clustering.page_type import (PageTypeLabel, page_features,
                                               save_labels)

# 人工目视标注（2026-08，vol01/vol02 全书 394 页）。
# 区间闭合，"页码: 页型"；未列出的页取 default。
#
# 判读依据（缩略图尺度可辨）：
#   cover    页中一个双线大框，框内大字书名，**无界行**
#   label    页侧一条窄长框（书签），其余整页留白，无界行
#   blank    有界行，字极少或完全没有
#   colophon 有界行，仅一角有一个小框、框内大字（牌记/刊记）
#   edict    有界行，字明显大、列数少于正文（上諭/表文）
#   body     九列密排正文（提要）
#   roster   九列，职名，字距拉开
#   toc      九列，目录，列上部有字下部空
#   uncertain 页型过渡处人工也判不准 —— 评测跳过，宁可少也不灌噪声
LABELS: dict[str, list[tuple[int, int, str]]] = {
    "vol01": [
        (1, 1, "cover"), (2, 2, "label"), (3, 3, "edict"),
        (4, 60, "body"),
        (61, 61, "toc"),            # 分卷目录，夹在正文段里
        (62, 62, "blank"),
        (63, 88, "body"),     # 87/88 是表文正文（88 卷尾稀疏，仍是 body）
        # 89-132 整段职名。原标（89-91 body / 92-95、127-133 uncertain /
        # 96-126 roster）是**错的**：逐页目视复核，89 是职名段首页
        # （勘閱繕校諸臣職名/總裁官職名），91-95 是歷任副總裁官/總纂官/
        # 提調官/日講起居注官/協勘總目官，127-132 是國子監學正/篆隸分校官/
        # 筆帖式/武英殿監造官——全是职名，没有一页「判不准」。发现途径：
        # 做正文/职名判别时 vol01/89、91 以 body 身份出现在弹性列比例
        # 0.33/0.67 处，与「body 弹性列应为 0」矛盾，追查即见段界标错。
        (89, 132, "roster"),
        (133, 133, "body"),   # 凡例二十则起，密排正文
        (134, 157, "body"),   # 157 是卷尾页：右 3 列有正文、左 6 列空，
                              # 结构上是正常正文页（曾误标 blank，特征复核时抓出）
        (158, 158, "blank"),
        (159, 204, "toc"),
        (205, 205, "colophon"),
        (206, 206, "blank"),
    ],
    "vol02": [
        (1, 1, "cover"), (2, 2, "label"),
        (3, 188, "body"),
    ],
}


def expand(book: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for a, b, t in LABELS[book]:
        for p in range(a, b + 1):
            out[str(p)] = t
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--with-features", action="store_true",
                    help="同时写出结构特征（供阈值标定/诊断，不是金标）")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    items: list[PageTypeLabel] = []
    feats: dict[str, dict] = {}
    counts: dict[str, int] = {}
    for book in LABELS:
        table = expand(book)
        for page, t in sorted(table.items(), key=lambda kv: int(kv[0])):
            p = Path("output") / book / f"{page}.png"
            if not p.exists():
                print(f"  跳过 {book}/{page}: 找不到页面图")
                continue
            items.append(PageTypeLabel(book=book, page=page, page_type=t))
            counts[t] = counts.get(t, 0) + 1
            if args.with_features:
                g = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
                feats[f"{book}/{page}"] = page_features(g)
    save_labels(items, out / "expected.json")
    if feats:
        (out / "features.json").write_text(
            json.dumps(feats, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"写出 {len(items)} 页 → {out}")
    print(f" 页型: {dict(sorted(counts.items(), key=lambda kv: -kv[1]))}")


if __name__ == "__main__":
    main()
