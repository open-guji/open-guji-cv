# -*- coding: utf-8 -*-
"""冻结集 id → 当前管线 id 的重键映射，**按图块内容配对**。

    PYTHONPATH=. python scripts/build_rekey_map.py \
        --old-root /tmp/guji-old-502fa04d0c/output --new-root output \
        --out config/rekey_502fa04d0c_to_current.json

## 为什么不能按几何重叠

上游 `rekey_instances.py` 的协议是「旧格位矩形 → 新网格里重叠最大的格位」。
在**同一套页图坐标**下这是对的；跨到当前管线就不对了——页裁切本身变了
（上游新建过 `page-crop` 分片，「最外列被上游裁掉」），旧坐标系里的矩形落到
新坐标系是**平移过的**。实测：几何映射给出 0.88~0.94 的重叠，看图却是
學→藝、通→家、輯→者，整整错开一列一格，而且重叠分数高得很有说服力。
**几何法在这里会安静地给出高置信度的错答案**，这是最危险的一种错。

所以改成按内容配对：同一页内，把旧图块与新图块两两算归一化后的 IoU，
匈牙利算法做全局最优指派，低于阈值的不配。这条路与坐标系无关，而且
**自带验证**——配对成功的 IoU 应该扎堆在高位，随机配对在 0.17 附近，
两堆分得开才说明映射可信。

## 读法

- `moved` / `same`：配上了（IoU ≥ 阈值），照映射改键；
- `unmatched`：这一页里没有像它的新图块——多半是这一格被重切没了，
  **留给人工**，别硬迁。
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from scipy.optimize import linear_sum_assignment  # noqa: E402

from open_guji_cv.clustering.normalize import normalize_patch  # noqa: E402


MIN_IOU = 0.55          # 配上/配不上的分界；归一化后配上的中位在 0.79，随机在 0.17


def page_patches(root: Path, book: str, page: str) -> dict[tuple[int, int], np.ndarray]:
    """一页里所有图块，过一遍 `normalize_patch` 再二值化。

    **必须归一化**：两版的裁切松紧不一样，直接 resize 比 IoU，同一个字也只有
    0.5 上下，跟随机配对（0.17）分不开；归一化（Sauvola + 质心居中）之后同字
    中位 0.79，才真正分得开。这一步只为配对，不参与任何判据。
    """
    d = root / book / "phase4_chars" / "patches" / page
    out = {}
    for f in sorted(d.glob("*.png")):
        col, idx = f.stem.split("_")
        im = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
        if im is None:
            continue
        out[(int(col), int(idx))] = normalize_patch(im).astype(bool)
    return out


def match_page(old: dict, new: dict) -> dict[tuple[int, int], tuple[tuple[int, int], float]]:
    if not old or not new:
        return {}
    ok, nk = list(old), list(new)
    A = np.array([old[k].ravel() for k in ok])
    B = np.array([new[k].ravel() for k in nk])
    inter = A.astype(np.uint16) @ B.T.astype(np.uint16)
    union = A.sum(1)[:, None] + B.sum(1)[None, :] - inter
    iou = inter / np.maximum(union, 1)
    ri, ci = linear_sum_assignment(-iou)
    return {ok[i]: (nk[j], float(iou[i, j])) for i, j in zip(ri, ci)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-root", required=True)
    ap.add_argument("--new-root", default="output")
    ap.add_argument("--ids", nargs="*", default=[
        "../open-guji-dataset/char-clustering/samples/001-vol01-body/expected.json",
        "../open-guji-dataset/char-clustering/samples/002-vol02-body/expected.json",
        "../open-guji-dataset/glyph-match/pairs/expected.json",
        "../open-guji-dataset/glyph-match/triplets/expected.json",
        "config/crop_exclusions.jsonl",
        "config/crop_exclusions_released.jsonl"],
        help="要迁移的每一个集都列进来（少列一个，那个集里独有的实例会被当成"
             "配不上而白白剔掉）")
    ap.add_argument("--out", default="config/rekey_502fa04d0c_to_current.json")
    a = ap.parse_args()

    def collect(path: str) -> list[str]:
        """从各种集里抠出实例 id：instances[].instance_id、三元组的三个端、
        排除名单的 instance_id。**要迁的每一个集都得喂进来**——只按其中一个集
        建表，别的集里多出来的实例会被当成「配不上」白白剔掉（第一版就是这么
        丢了 97/197 条三元组）。"""
        t = Path(path)
        if t.suffix == ".jsonl":
            return [json.loads(l)["instance_id"]
                    for l in t.read_text(encoding="utf-8").splitlines() if l.strip()]
        d = json.loads(t.read_text(encoding="utf-8"))
        rows = d["instances"] if isinstance(d, dict) and "instances" in d else d
        out = []
        for r in rows:
            if "instance_id" in r:
                out.append(r["instance_id"])
            else:
                out += [r[k] for k in ("anchor", "same", "other") if k in r]
        return out

    ids: list[str] = []
    for src in a.ids:
        if Path(src).exists():
            ids += collect(src)
    ids = sorted(set(ids))

    old_root, new_root = Path(a.old_root), Path(a.new_root)
    by_page: dict[tuple[str, str], list[str]] = {}
    for iid in ids:
        book, page, _, _ = iid.split(":")
        by_page.setdefault((book, page), []).append(iid)

    out: dict[str, dict] = {}
    tally = Counter()
    ious: list[float] = []
    for (book, page), page_ids in sorted(by_page.items()):
        old = page_patches(old_root, book, page)
        new = page_patches(new_root, book, page)
        pair = match_page(old, new)
        for iid in page_ids:
            _, _, col, idx = iid.split(":")
            hit = pair.get((int(col), int(idx)))
            if hit is None or hit[1] < MIN_IOU:
                tally["unmatched"] += 1
                out[iid] = {"status": "unmatched",
                            "iou": round(hit[1], 3) if hit else 0.0}
                continue
            (nc, ni), iou = hit
            new_id = f"{book}:{page}:{nc}:{ni}"
            ious.append(iou)
            tally["same" if new_id == iid else "moved"] += 1
            out[iid] = {"status": "same" if new_id == iid else "moved",
                        "new_id": new_id, "iou": round(iou, 3)}

    # 多对一是可能的（旧两格并成新一格）——迁移时必须察觉，否则金标会互相覆盖
    hit = Counter(v["new_id"] for v in out.values() if v.get("new_id"))
    collide = sum(1 for n in hit.values() if n > 1)
    print(f"{len(ids)} 条：" + "　".join(f"{k} {v}" for k, v in tally.most_common()))
    print(f"  新键被多条旧键指到（并格）：{collide} 个新键")
    if ious:
        q = np.percentile(ious, [5, 25, 50])
        print(f"  配上的 IoU 分位 5%/25%/50% = {q[0]:.2f}/{q[1]:.2f}/{q[2]:.2f}"
              f"（随机配对约 0.17，分得开才说明映射可信）")
    Path(a.out).write_text(json.dumps(
        {"_doc": "冻结集 502fa04d0c → 当前管线的重键映射，**按图块内容配对**"
                 "（同页内 IoU + 匈牙利指派）；status: same/moved/unmatched。"
                 "几何重叠法在这里会给出高置信度的错答案，别用。"
                 "生成：scripts/build_rekey_map.py",
         "min_iou": MIN_IOU, "n": len(ids),
         "tally": dict(tally), "n_collide": collide, "map": out},
        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"→ {a.out}")


if __name__ == "__main__":
    main()
