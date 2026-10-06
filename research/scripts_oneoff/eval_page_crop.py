"""上游裁切吃掉最外列：列窗越出页图多少（char-segmentation/page-crop）。

「中间的文字被错误截断」这句话里，切分层修不了的那一半就在这儿：s3 把
页面裁窄了，最外一列的字**根本不在页图里**（vol01/18 col1 的墨一路顶到
页图右缘 x=1607、页宽 1608）。网格照书级列距把列窗算到 1629，越出页图
21px —— 越出多少，就是那一列被吃掉多少。

这个量**不需要人工标注**：越界是网格模型与页图尺寸的直接比较。金标只
记「当前哪些页越界、越了多少」，回归看的是别越界的页不许新越界、已越界
的页不许越得更多。

用法：PYTHONPATH=. python research/scripts_oneoff/eval_page_crop.py <数据集目录> [--update] [--source v2|v1]

## 2026-09-30（M1·A 道）：默认改读现行 v2 链

`--source v1`（旧）读 `./output/<册>/phase3_char_grid`（退役的 v1 链，云端没有；不存在时
旧脚本静默扫 0 页 → 假通过）。`--source v2`（默认）读 `products/<册>/border_detect`
（Step1 `borders`）：直接拿**最外两条竖直线**跟页图宽比——

    over_right = max(0, -min_y verticals[0].x_at(y))            # 最右一条越出页图右缘
    over_left  = max(0, max_y verticals[-1].x_at(y) - width)    # 最左一条越出页图左缘

口径与旧版同构（网格模型 vs 页图尺寸的直接比较，`over_threshold_px`=8 不变、指标名不变：
「越界页」「新越界」「越得更多」），但**量的对象从 v1 的 cell_left_x/cell_right_x
换成了 v2 的最外界行**——v2 的列窗就是由这些线围出来的。**金标是算法快照不是人裁**：
v2 基线写 `page-crop/expected_v2.json`（`--update` 重冻；v1 的 `expected.json` 6 页留档不动，
它对应的是退役链，不能拿来当 v2 的回归基线）。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

OVER_T = 8.0        # 越出页图这么多像素才算（<8px 是网格拟合的正常毛刺）


def scan(out_root: str = "output") -> dict[str, dict]:
    res: dict[str, dict] = {}
    for book_dir in sorted(Path(out_root).glob("vol*")):
        for gp in sorted((book_dir / "phase3_char_grid").glob("*_char_grid.json")):
            page = gp.stem.replace("_char_grid", "")
            grid = json.loads(gp.read_text(encoding="utf-8"))
            cols = [c for c in grid.get("columns") or []
                    if c.get("cell_left_x") is not None
                    and any(x.get("type") == "char" for x in c.get("cells", []))]
            width = (grid.get("image_size") or {}).get("width")
            if not cols or not width:
                continue
            over_l = max(0.0, -min(c["cell_left_x"] for c in cols))
            over_r = max(0.0, max(c["cell_right_x"] for c in cols) - width)
            if max(over_l, over_r) >= OVER_T:
                res[f"{book_dir.name}/{page}"] = {"left": round(over_l, 1),
                                                  "right": round(over_r, 1)}
    return res


MARGINS: dict[str, tuple[float, float]] = {}     # scan_v2 顺手记：页 → (右缘余量, 左缘余量) px，正数=线在页图内


def scan_v2() -> tuple[dict[str, dict], int]:
    """读 v2 产物 `border_detect`（borders）；返回 (越界页, 扫描页数)。"""
    import open_guji_cv.products.kinds  # noqa: F401  注册产物种类
    from open_guji_cv.products.store import ProductStore
    st = ProductStore()
    res: dict[str, dict] = {}
    n = 0
    root = st.root
    for book_dir in sorted(Path(root).glob("vol*")) + sorted(Path(root).glob("bxgb")):
        book = book_dir.name
        for key in st.keys(book, "border_detect"):
            b = st.read(book, "border_detect", key, "borders")
            if b is None or not b.verticals:
                continue
            n += 1
            H, W = float(b.height), float(b.width)
            ys = (0.0, H)
            right = min(b.verticals[0].to_vline().x_at(y) for y in ys)
            left = max(b.verticals[-1].to_vline().x_at(y) for y in ys)
            over_r, over_l = max(0.0, -float(right)), max(0.0, float(left) - W)
            MARGINS[f"{book}/{int(key[1:])}"] = (round(float(right), 1), round(W - float(left), 1))
            if max(over_l, over_r) >= OVER_T:
                res[f"{book}/{int(key[1:])}"] = {"left": round(over_l, 1),
                                                 "right": round(over_r, 1)}
    return res, n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset")
    ap.add_argument("--out", default="output")
    ap.add_argument("--source", choices=("v2", "v1"), default="v2")
    ap.add_argument("--update", action="store_true",
                    help="把当前实测写回金标（只在确认是改进时用）")
    args = ap.parse_args()
    if args.source == "v2":
        return main_v2(args)
    shard = Path(args.dataset) / "page-crop" / "expected.json"
    got = scan(args.out)
    if args.update or not shard.exists():
        shard.parent.mkdir(parents=True, exist_ok=True)
        shard.write_text(json.dumps({"over_threshold_px": OVER_T, "pages": got},
                                    ensure_ascii=False, indent=1),
                         encoding="utf-8")
        print(f"写入金标 {len(got)} 页 → {shard}")
        return
    gold = json.loads(shard.read_text(encoding="utf-8"))["pages"]
    new = sorted(set(got) - set(gold))
    gone = sorted(set(gold) - set(got))
    worse = [(k, gold[k], got[k]) for k in sorted(set(got) & set(gold))
             if max(got[k].values()) > max(gold[k].values()) + 0.5]
    print(f"越界页：金标 {len(gold)} → 实测 {len(got)}")
    for k in gone:
        print(f"  ✔ 修好 {k} （金标 {gold[k]}）")
    for k in new:
        print(f"  ✗ 新越界 {k} {got[k]}")
    for k, a, b in worse:
        print(f"  ✗ 越得更多 {k} {a} → {b}")
    ok = not new and not worse
    print("回归门：通过" if ok else "回归门：**失败**")
    raise SystemExit(0 if ok else 1)


def main_v2(args) -> None:
    shard = Path(args.dataset) / "page-crop" / "expected_v2.json"
    got, n_pages = scan_v2()
    if n_pages == 0:
        raise SystemExit("v2 产物里没有 border_detect（products/<册>/border_detect 为空）——"
                         "先跑 guji pipeline / eval --from-raw；不是「0 页越界」")
    if args.update:
        shard.write_text(json.dumps({"over_threshold_px": OVER_T, "source": "v2:borders",
                                     "n_pages_scanned": n_pages, "pages": got},
                                    ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"写入 v2 基线：扫描 {n_pages} 页、越界 {len(got)} 页 → {shard}")
        return
    print(f"扫描 v2 产物 {n_pages} 页，越界 {len(got)} 页：{got}")
    if MARGINS:
        mr = min(MARGINS.items(), key=lambda kv: kv[1][0])
        ml = min(MARGINS.items(), key=lambda kv: kv[1][1])
        print(f"最外界行离页图边缘的最小余量（正=在页内；不计入回归）：右缘 {mr[1][0]}px（{mr[0]}）"
              f"，左缘 {ml[1][1]}px（{ml[0]}）")
    v1 = Path(args.dataset) / "page-crop" / "expected.json"
    if v1.exists():
        old = json.loads(v1.read_text(encoding="utf-8"))["pages"]
        print(f"（对照 v1 旧基线 {len(old)} 页：" + "、".join(
            f"{k}→v2 {got.get(k, '未越界' if k in MARGINS else '未扫描(产物缺)')}" for k in sorted(old)) + "）")
    if not shard.exists():
        print("还没有 v2 基线（expected_v2.json）——不做回归判定；确认后用 --update 冻结")
        return
    bl = json.loads(shard.read_text(encoding="utf-8"))
    gold = bl["pages"]
    # 「修好」只对本次真扫到的页成立；没扫到的页不能算修好（云端没全书产物时尤其）
    gone = sorted(k for k in set(gold) - set(got) if k in MARGINS)
    new = sorted(set(got) - set(gold))
    worse = [(k, gold[k], got[k]) for k in sorted(set(got) & set(gold))
             if max(got[k].values()) > max(gold[k].values()) + 0.5]
    print(f"[v2 链] 基线扫 {bl.get('n_pages_scanned')} 页、越界 {len(gold)} 页；本次扫 {n_pages} 页、越界 {len(got)} 页"
          + ("" if n_pages >= (bl.get("n_pages_scanned") or 0) else "（覆盖不全）"))
    for k in gone:
        print(f"  ✔ 修好 {k} （金标 {gold[k]}）")
    for k in new:
        print(f"  ✗ 新越界 {k} {got[k]}")
    for k, a, b in worse:
        print(f"  ✗ 越得更多 {k} {a} → {b}")
    ok = not new and not worse
    print("回归门：通过" if ok else "回归门：**失败**")
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
