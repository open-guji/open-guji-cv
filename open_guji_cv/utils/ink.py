# -*- coding: utf-8 -*-
"""册级「墨层」：原图（可能是彩图）→ 墨色灰度 → 二值，管线从 Step1 起读的就是它。

## 由来（用户 2026-11-17，起因是脉经彩图）

> 一般默认是彩图书的「墨层」转换，然后二值化（算法参数可选，给默认）。以后默认都二值化，
> 只有切分有问题，再考虑灰度化或者调整二值参数、算法。

两层：

1. **墨层转换** `color`：彩图只按亮度转灰（`luma`）时，朱印、朱批、红圈点、黄斑在亮度上都是中灰，
   二值化会把它们当成墨，正文就脏了。`max`（HSV 的 V，三通道取最大）把一切**有颜色**的记号抬成亮色，
   只留下三通道都暗的黑墨；`red`（只取红通道）只压红色。`auto`：这一页是彩图就用 `max`，灰度图用 `luma`。
2. **二值化** `binarize`：`otsu`（缺省）／`sauvola`／`none`（不二值＝灰度）。

## 为什么缺省是 Otsu 而不是 Sauvola 31/0.10

MJ 11-17 在脉经第 1 册（内阁文库彩图 JP2，6300×4600，纸纹重）8 页上实测（keben_body_v2，放行／送审）：

| 输入 | 放行／送审 |
|---|---|
| 原灰度 | 956／623 |
| Sauvola 31/0.10（`binarized_input`） | 849／775（纸纹成斑点，小字连通体被吃） |
| Otsu＋去小斑 | 932／646（格数与灰度完全一致） |

Sauvola 的窗口 31 是在 2400–2800 px 宽的扫描上定的，6300 px 的图上窗口相对太小，纸纹的局部起伏就被判成墨。
所以缺省 Otsu＋去小斑（`speck_area`，按页高缩放），Sauvola 留作可选（`window` 可写 `auto` 按页高放大）。
北行日錄那类**淡界行**的书 Otsu 会丢线（9-16 实测 10/13），那种书写 `binarize: sauvola`。

## 怎么写（册 yaml 或 `config/book_defaults.yaml`）

```yaml
ink: {}                       # 全用缺省：color auto，binarize otsu，speck_area auto
ink: {binarize: none}         # 只做墨层转换，不二值（切分有问题时的回退）
ink: {binarize: sauvola, window: auto, k: 0.10}
ink: {color: red, binarize: otsu, speck_area: 0}
```

**没写 `ink` 的册行为与指纹逐位不变**（读灰度；老开关 `binarized_input` 照旧）。写了的册，`ink` 的
规范化取值进所有读原图的步的指纹（`core/engine._self_payload` 的 `ink` 键）。

坐标：墨层与二值都与原图**同尺寸、逐像素对应**，不裁不拉直，所以彩图、灰度、二值三张图共用一套坐标。

⚠️ 本模块不在任何 Step 的 `code_deps` 里：改这里的算法不会让没写 `ink` 的册过期，但**会改写了 `ink` 的册的
产物而指纹不变**——改算法（不是加选项）时，同时把 `INK_ALGO` 加一，它进 `ink` 指纹键。
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

#: 墨层算法版本：本模块的转换／二值算法有实质改动时加一（进指纹，见模块头 ⚠️）。
INK_ALGO = 1

COLOR_MODES = ("auto", "luma", "max", "red")
BINARIZE_MODES = ("otsu", "sauvola", "none")

#: `speck_area: auto` 的基准：页高 3000 px 时去掉面积 < 6 px 的连通体，按 (页高/3000)² 缩放
#: （6300 px 高的图约 26 px）。小字连通体在脉经上是 200–600 px，句读点更大，留足余量。
SPECK_REF_H = 3000
SPECK_REF_AREA = 6
#: `window: auto` 的基准：页高 3000 px 时 Sauvola 窗口 31（与 `normalize.SAUVOLA_WINDOW` 同），按页高线性放大。
WINDOW_REF_H = 3000

#: 判「这一页是彩图」：缩略图上三通道最大差 > `COLOR_SPREAD` 的像素占比 ≥ `COLOR_FRAC`。
#: 灰度扫描存成 RGB（`pillow-rgb-png/1`）时三通道逐像素相同，差恒为 0。
COLOR_SPREAD = 12
COLOR_FRAC = 0.02


@dataclass(frozen=True)
class InkSpec:
    color: str = "auto"
    binarize: str = "otsu"
    #: Sauvola 窗口：整数或 "auto"（按页高放大）
    window: int | str = 31
    k: float = 0.10
    #: 二值后去掉面积小于它的墨连通体：整数（0＝不去）或 "auto"（按页高缩放）
    speck_area: int | str = "auto"
    #: 纸缘这么宽一圈强制判纸（同 `utils/binarized.EDGE_MARGIN` 的理由）
    edge_margin: int = 20

    def token(self) -> dict:
        """进指纹的规范化取值（键排好序、带算法版本）。"""
        d = {"algo": INK_ALGO, "color": self.color, "binarize": self.binarize,
             "edge_margin": self.edge_margin}
        if self.binarize != "none":
            d["speck_area"] = self.speck_area
        if self.binarize == "sauvola":
            d["window"] = self.window
            d["k"] = self.k
        return d

    @property
    def binary(self) -> bool:
        return self.binarize != "none"


def parse_ink(raw) -> InkSpec | None:
    """册配置 `ink:` → `InkSpec`。没写（None）→ None（老行为）。写错直接报错，不悄悄退回缺省。"""
    if raw is None:
        return None
    if raw is True:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError(f"ink 要写成映射（如 ink: {{}} 或 ink: {{binarize: otsu}}），收到 {raw!r}")
    unknown = set(raw) - {"color", "binarize", "window", "k", "speck_area", "edge_margin"}
    if unknown:
        raise ValueError(f"ink 里有不认识的键: {sorted(unknown)}")
    color = str(raw.get("color", "auto"))
    if color not in COLOR_MODES:
        raise ValueError(f"ink.color 只能是 {COLOR_MODES}，收到 {color!r}")
    binarize = str(raw.get("binarize", "otsu"))
    if binarize in ("false", "False", "off", "gray"):
        binarize = "none"
    if binarize not in BINARIZE_MODES:
        raise ValueError(f"ink.binarize 只能是 {BINARIZE_MODES}，收到 {binarize!r}")
    window = raw.get("window", 31)
    if window != "auto":
        window = int(window)
        if window < 3 or window % 2 == 0:
            raise ValueError(f"ink.window 要是 ≥3 的奇数或 auto，收到 {window}")
    speck = raw.get("speck_area", "auto")
    if speck != "auto":
        speck = int(speck)
        if speck < 0:
            raise ValueError("ink.speck_area 不能是负数")
    return InkSpec(color=color, binarize=binarize, window=window, k=float(raw.get("k", 0.10)),
                   speck_area=speck, edge_margin=int(raw.get("edge_margin", 20)))


def is_color(img: np.ndarray) -> bool:
    """这张图是不是彩图（三通道明显不同）。单通道一律 False。"""
    if img.ndim != 3 or img.shape[2] < 3:
        return False
    h, w = img.shape[:2]
    step = max(1, int(max(h, w) / 800))
    s = img[::step, ::step, :3].astype(np.int16)
    spread = s.max(axis=2) - s.min(axis=2)
    return float((spread > COLOR_SPREAD).mean()) >= COLOR_FRAC


def resolve_color_mode(img: np.ndarray, mode: str) -> str:
    """`auto` 落到具体做法：彩图 `max`，否则 `luma`。"""
    if mode != "auto":
        return mode
    return "max" if is_color(img) else "luma"


def to_ink_gray(img: np.ndarray, mode: str = "auto") -> np.ndarray:
    """原图（BGR 或灰度）→ 墨色灰度 uint8（暗＝墨）。灰度图原样返回。"""
    if img.ndim == 2:
        return img
    if img.shape[2] == 4:
        img = img[:, :, :3]
    m = resolve_color_mode(img, mode)
    if m == "luma":
        return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if m == "max":
        return img.max(axis=2).astype(np.uint8)
    if m == "red":
        return np.ascontiguousarray(img[:, :, 2])
    raise ValueError(f"未知墨层做法 {m!r}")


def _auto_window(h: int) -> int:
    w = int(round(31 * max(1.0, h / WINDOW_REF_H)))
    return w if w % 2 else w + 1


def speck_area_for(spec: InkSpec, h: int) -> int:
    if spec.speck_area == "auto":
        return int(round(SPECK_REF_AREA * (h / SPECK_REF_H) ** 2))
    return int(spec.speck_area)


def remove_specks(ink: np.ndarray, min_area: int) -> np.ndarray:
    """ink {0,1}（1＝墨）里面积 < min_area 的连通体抹掉。"""
    if min_area <= 1:
        return ink
    n, lab, stats, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    if n <= 1:
        return ink
    small = stats[:, cv2.CC_STAT_AREA] < min_area
    small[0] = False
    if not small.any():
        return ink
    out = ink.copy()
    out[small[lab]] = 0
    return out


def ink_mask(gray: np.ndarray, spec: InkSpec) -> np.ndarray:
    """墨色灰度 → {0,1} 墨掩码（1＝墨）。`binarize: none` 不该调这里。"""
    from .binarized import sauvola_binarize   # 经 binarized 借（分层守卫：utils 不直接 import clustering）
    h = gray.shape[0]
    if spec.binarize == "otsu":
        _, th = cv2.threshold(gray, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        ink = th.astype(np.uint8)
    elif spec.binarize == "sauvola":
        win = _auto_window(h) if spec.window == "auto" else int(spec.window)
        ink = sauvola_binarize(gray, window=win, k=spec.k)
    else:
        raise ValueError(f"binarize={spec.binarize!r} 不出掩码")
    m = int(spec.edge_margin)
    if m > 0 and ink.shape[0] > 2 * m and ink.shape[1] > 2 * m:
        ink[:m, :] = 0
        ink[-m:, :] = 0
        ink[:, :m] = 0
        ink[:, -m:] = 0
    return remove_specks(ink, speck_area_for(spec, h))


def ink_page(img: np.ndarray, spec: InkSpec) -> np.ndarray:
    """原图 → 管线读的那张：墨层灰度，二值时为白底黑字 {0,255}。与原图同尺寸。"""
    gray = to_ink_gray(img, spec.color)
    if not spec.binary:
        return gray
    return np.where(ink_mask(gray, spec) > 0, 0, 255).astype(np.uint8)
