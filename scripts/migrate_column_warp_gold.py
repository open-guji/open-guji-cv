# -*- coding: utf-8 -*-
"""上游改了 Step1 之后，把 column-warp 金标**能迁的自动迁、不能迁的挑出来**。

    python scripts/migrate_column_warp_gold.py \\
        ../open-guji-dataset/char-segmentation/column-warp [--apply]

不带 `--apply` 只报告，带上才写盘。幂等。

## 为什么要有这个脚本

Step1 还在改，每改一次列图就变，这批金标已经因此作废过三轮（`head_raise`
列号归属、`verticals_inner` 按真墨重拟、输入换成算法边线+逐列窗口）。前三轮
是**手工**逐条复核的，费时且容易漏——第三轮差点只复核"还留在金标里的"那些，
那样会永久丢掉 2 条"上一轮失效、这一轮又有效"的标注。这个脚本把那套复核
固化下来，让**变化不大的自动留用、只有真变了的才回去重标**。

## 两条判据（都**不用算法自己的输出**当基准，避免循环论证）

**文字带** —— 判据就是金标自己的定义：「边界处墨量接近 0」。把人标的
`human_left/right` 放到新列图上，重算那两个 x 处的墨占比：

  * ≤ `KEEP_EPS`(0.01) —— 标注**仍然成立**，原样留用；`canonical_*` 按新图
    重新往外推（走廊的激进端本来就是派生量，不是人标的）。
  * 否则 —— 边界落进墨里了，标注失效，列进 `pending_relabel`。

**上下版框类别** —— 类别取决于"窗口裁到哪"，不能用墨量判。改用**图像指纹**：
导出时把人当时看的那两张端裁剪图各存一份 32×24 的缩略（`end_fingerprint`）；
迁移时重算裁剪图、跟指纹比平均绝对差：

  * ≤ `FP_TOL`(6 灰阶) —— 人看的还是同一张图，裁决留用；
  * 否则 —— 图变了，类别得重判。

指纹法的好处是**跟算法无关**：它只问"人当时看的那张图还在不在"，不问算法
现在怎么判。拿算法的一致性当留用判据会让金标永远测不出算法错——那是循环。

没有 `end_fingerprint` 的老样本（指纹是这一轮才加的）一律判为"需重看"，
不猜。
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from open_guji_cv.utils.column_projection import (  # noqa: E402
    column_profile,
    column_text_band,
    denoise_column,
    strip_column_rules,
)

KEEP_EPS = 0.01      # 人标点处的墨占比 <= 这个就算"还在零区"（实测人标处均值 0.0010）
ZERO_EPS = 0.005     # 往外推 canonical 用的门槛，跟导出脚本一致
FP_TOL = 6.0         # 端裁剪图指纹的平均绝对差容差（灰阶）
FP_SIZE = (32, 24)   # 指纹尺寸 (w, h)
CROP_ROWS = 220      # 跟标注页一致


def fingerprint(crop: np.ndarray) -> str:
    small = cv2.resize(crop, FP_SIZE, interpolation=cv2.INTER_AREA)
    return base64.b64encode(small.astype(np.uint8).tobytes()).decode()


def unpack_fp(s: str) -> np.ndarray:
    return np.frombuffer(base64.b64decode(s), dtype=np.uint8).reshape(FP_SIZE[1], FP_SIZE[0])


def end_crops(warped: np.ndarray) -> dict[str, np.ndarray]:
    """按定版顺序做端裁剪图：定带 -> 抹侧界行 -> 取两端。跟标注页一致。"""
    band = column_text_band(warped)
    core = strip_column_rules(warped)[:, band[0]:band[1]]
    return {"top": core[:CROP_ROWS], "bottom": core[-CROP_ROWS:][::-1]}


def current_column(sample: dict) -> np.ndarray | None:
    wf = ROOT / "output" / sample["book"] / "step2_columns" / sample["page"] / "windows.json"
    if not wf.exists():
        return None
    cols = json.loads(wf.read_text(encoding="utf-8"))["columns"]
    win = next((c for c in cols if c["col"] == sample["col"]), None)
    if win is None:
        return None
    img = cv2.imread(str(wf.parent / win["file"]), cv2.IMREAD_GRAYSCALE)
    return None if img is None else denoise_column(img)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", help="column-warp 子集目录")
    ap.add_argument("--apply", action="store_true", help="写盘（默认只报告）")
    args = ap.parse_args()

    samples_dir = Path(args.dataset) / "samples"
    files = sorted(samples_dir.glob("*.json"))
    if not files:
        raise SystemExit(f"{samples_dir} 里没有样本")

    band_keep, band_drop, band_none = [], [], []
    cls_keep, cls_recheck, cls_nofp = [], [], []
    for f in files:
        s = json.loads(f.read_text(encoding="utf-8"))
        key = f.stem
        warped = current_column(s)
        if warped is None:
            print(f"  ! {key} 读不到当前列图，跳过（先跑 regen_step2_columns.py）")
            continue
        changed = False

        tb = s.get("text_band")
        if not tb:
            band_none.append(key)
        else:
            prof = column_profile(warped)
            hl, hr = tb["human_left"], tb["human_right"]
            if hl >= len(prof) or hr > len(prof):
                band_drop.append((key, "越界"))
            elif max(float(prof[hl]), float(prof[hr - 1])) > KEEP_EPS:
                band_drop.append((key, "墨 %.4f" % max(float(prof[hl]), float(prof[hr - 1]))))
            else:
                cl, cr = hl, hr
                while cl - 1 >= 0 and prof[cl - 1] <= ZERO_EPS:
                    cl -= 1
                while cr < len(prof) and prof[cr] <= ZERO_EPS:
                    cr += 1
                if (cl, cr) != (tb["canonical_left"], tb["canonical_right"]):
                    tb["canonical_left"], tb["canonical_right"] = cl, cr
                    changed = True
                band_keep.append(key)

        bc = s.get("border_class")
        if bc:
            fps = s.get("end_fingerprint") or {}
            crops = end_crops(warped)
            for end in ("top", "bottom"):
                if end not in bc:
                    continue
                cid = f"{key}:{end}"
                if end not in fps:
                    cls_nofp.append(cid)
                    continue
                d = float(np.abs(unpack_fp(fps[end]).astype(int)
                                  - cv2.resize(crops[end], FP_SIZE,
                                                interpolation=cv2.INTER_AREA).astype(int)).mean())
                (cls_keep if d <= FP_TOL else cls_recheck).append((cid, round(d, 1)))

        if changed and args.apply:
            f.write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"文字带：留用 {len(band_keep)}，失效需重标 {len(band_drop)}"
          f"，本来就没有 {len(band_none)}")
    for k, why in band_drop:
        print(f"  ✗ {k}  {why}")
    print(f"\n上下版框类别：留用 {len(cls_keep)}，需重看 {len(cls_recheck)}"
          f"，没有指纹判不了 {len(cls_nofp)}")
    for k, d in sorted(cls_recheck, key=lambda x: -x[1]):
        print(f"  ✗ {k}  端裁剪图变了（平均差 {d} 灰阶）")
    if cls_nofp:
        print(f"  ? 没指纹（导出时还没加这个字段）：{len(cls_nofp)} 条，一律当需重看")
    if not args.apply:
        print("\n（只报告，没写盘。加 --apply 才更新 canonical_*）")


if __name__ == "__main__":
    main()
