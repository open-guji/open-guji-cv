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

## 判据：**主判据是「图变没变」**，不是「算法现在怎么判」

一条人裁只对**它当时看的那张图**成立。所以导出时给每条标注存一份图像指纹
（文字带存整列图的 `column_fingerprint`，上下版框存两张端裁剪图的
`end_fingerprint`，都是灰度缩略）；迁移时重算、比平均绝对差 ≤ `FP_TOL`
（6 灰阶）就**原样留用**。

指纹法的好处是**跟算法无关**：它只问"人当时看的那张图还在不在"。
**拿算法的一致性当留用判据会让金标永远测不出算法错——那是循环论证。**

图**真的变了**之后，还有一条自动补救通道，只对 `clean` 列开：把人标的
`human_left/right` 放到新图上，如果那两个 x 处的墨占比仍 ≤ `KEEP_EPS`(0.01)，
说明"边界处墨量接近 0"这个**金标自己的定义**依旧满足，可以免人工留用
（`canonical_*` 按新图重推——走廊的激进端本来就是派生量）。

**这条通道对 `mixed`/`idk` 列不适用**，别拿它去查：`mixed` 的含义就是"这一列
压根找不到墨量归零的边界"，用零墨判据去查必然报警。实测 vol01/47 c2/c7 的
左侧从头到尾在 0.04~0.09 之间、没有任何零区——那正是人判 `mixed` 的原因，
不是标注错了。早先版本没分这个情况，把它们误报成"失效"。

没有指纹的老样本（指纹是后加的）一律判"需重看"，不猜。
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
FP_TOL = 6.0         # 指纹的平均绝对差容差（灰阶）；标定见下面的注释
FP_SIZE = (32, 24)   # 端裁剪图指纹尺寸 (w, h)
COL_FP_SIZE = (24, 96)   # 整列图指纹尺寸——列又高又窄，纵向多给点
# FP_TOL 标定：列图横向平移 1~3px 时指纹差 ≈0（带跟着移、图其实没变，正是
# "变化不大就不用重标"该有的行为），平移 8px 才开始报警。
CROP_ROWS = 220      # 跟标注页一致


def fingerprint(crop: np.ndarray, size: tuple[int, int] = FP_SIZE) -> str:
    small = cv2.resize(crop, size, interpolation=cv2.INTER_AREA)
    return base64.b64encode(small.astype(np.uint8).tobytes()).decode()


def fp_diff(stored: str, img: np.ndarray, size: tuple[int, int] = FP_SIZE) -> float:
    a = np.frombuffer(base64.b64decode(stored), dtype=np.uint8).reshape(size[1], size[0])
    b = cv2.resize(img, size, interpolation=cv2.INTER_AREA)
    return float(np.abs(a.astype(int) - b.astype(int)).mean())


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
            col_fp = s.get("column_fingerprint")
            same_img = (col_fp is not None
                         and fp_diff(col_fp, warped, COL_FP_SIZE) <= FP_TOL)
            ink = (max(float(prof[hl]), float(prof[hr - 1]))
                   if hl < len(prof) and hr <= len(prof) else None)
            if same_img:
                band_keep.append(key)        # 图没变，人裁照旧成立
            elif ink is None:
                band_drop.append((key, "越界"))
            elif s.get("verdict") != "clean":
                # mixed/idk 没有"墨量归零的边界"可言，零墨判据用不上——图变了
                # 就只能回去重看
                band_drop.append((key, "图变了且判为 %s，零墨判据不适用"
                                   % s.get("verdict")))
            elif ink > KEEP_EPS:
                band_drop.append((key, "图变了、人标点处墨 %.4f" % ink))
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
                d = fp_diff(fps[end], crops[end])
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
