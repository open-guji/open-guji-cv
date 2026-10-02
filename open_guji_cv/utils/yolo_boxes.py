"""yolo_tool 单字 YOLO 模型的推理 + Step4 收框复核判据（Y1 道，overview#373）。

**可选依赖**：只要 `onnxruntime`（不要 torch；CPU 能跑，~14 MB wheel）。缺 onnxruntime、缺权重、
权重读不开——一律 `YoloUnavailable`，调用方当「弃权」，绝不报错。模型文件**不进本仓**：
路径由参数／环境变量 `GUJI_YOLO_WEIGHTS` 指向 yolo_tool 仓的 `model/slide/best.onnx`；
路径不进指纹，权重**内容**的指纹（`weights_fingerprint`）进指纹。

推理照 yolo_tool `BatchInferWorker` 与 `scripts/experiments/yolo_tool_probe/probe2.py`：
等比缩放到 1024、补 114 灰、conf 0.25、NMS IoU 0.45、丢宽/高 <6 的小框。

复核判据（`extra_ink_ratio`）：同一格里，YOLO 框比 CV 紧框**多包进来**的墨，占「两框并集里全部墨」
的比例。CV 只框到半个字、把版框线当字，都会让这个比例飙高；两框一致则 ≈0。
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np

ENV_WEIGHTS = "GUJI_YOLO_WEIGHTS"
INPUT = 1024


class YoloUnavailable(RuntimeError):
    """缺 onnxruntime／权重／读不开：调用方一律当弃权。"""


_FP: dict[tuple[str, int, int], str] = {}


def resolve_weights(path: str = "") -> str:
    """参数 > 环境变量；都空返回 ""。"""
    return str(path or os.environ.get(ENV_WEIGHTS, "") or "")


def weights_fingerprint(path: str) -> str:
    """权重内容的 sha256 前 16 位；读不到返回 ""（= 没有这个模型，闸弃权）。"""
    if not path:
        return ""
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return ""
    key = (str(p), st.st_size, int(st.st_mtime))
    if key not in _FP:
        h = hashlib.sha256()
        with p.open("rb") as f:
            for blk in iter(lambda: f.read(1 << 20), b""):
                h.update(blk)
        _FP[key] = h.hexdigest()[:16]
    return _FP[key]


_SESS: dict[str, object] = {}


def _session(path: str):
    if path in _SESS:
        return _SESS[path]
    try:
        import onnxruntime as ort
    except ImportError as e:            # 可选依赖缺席
        raise YoloUnavailable("onnxruntime 未安装") from e
    if not path or not Path(path).is_file():
        raise YoloUnavailable(f"YOLO 权重不存在: {path or '(未配置)'}")
    try:
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        _SESS[path] = ort.InferenceSession(path, opts, providers=["CPUExecutionProvider"])
    except Exception as e:              # noqa: BLE001 —— 权重坏了也是弃权
        raise YoloUnavailable(f"YOLO 权重读不开: {e}") from e
    return _SESS[path]


def _nms(xywh: np.ndarray, conf: np.ndarray, iou_thr: float) -> list[int]:
    x0, y0 = xywh[:, 0], xywh[:, 1]
    x1, y1 = x0 + xywh[:, 2], y0 + xywh[:, 3]
    area = xywh[:, 2] * xywh[:, 3]
    order = conf.argsort()[::-1]
    keep: list[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        r = order[1:]
        iw = np.clip(np.minimum(x1[i], x1[r]) - np.maximum(x0[i], x0[r]), 0, None)
        ih = np.clip(np.minimum(y1[i], y1[r]) - np.maximum(y0[i], y0[r]), 0, None)
        inter = iw * ih
        order = r[inter / (area[i] + area[r] - inter + 1e-9) <= iou_thr]
    return keep


def _infer(weights: str, img: np.ndarray, conf: float, iou: float, min_wh: float
           ) -> list[tuple[float, float, float, float, float, int]]:
    import cv2
    sess = _session(weights)
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    h, w = img.shape[:2]
    r = INPUT / max(h, w)
    nh, nw = max(1, int(round(h * r))), max(1, int(round(w * r)))
    pad = np.full((INPUT, INPUT, 3), 114, np.uint8)
    top, left = (INPUT - nh) // 2, (INPUT - nw) // 2
    pad[top:top + nh, left:left + nw] = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    x = np.ascontiguousarray(pad[:, :, ::-1].transpose(2, 0, 1)[None]).astype(np.float32) / 255.0
    try:
        out = sess.run(None, {"images": x})[0][0].T
    except Exception as e:              # noqa: BLE001
        raise YoloUnavailable(f"YOLO 推理失败: {e}") from e
    sc = out[:, 4:]
    cf, cls = sc.max(1), sc.argmax(1)
    k = cf >= conf
    if not k.any():
        return []
    b, cf, cls = out[k, :4], cf[k], cls[k]
    xywh = np.stack([(b[:, 0] - b[:, 2] / 2 - left) / r, (b[:, 1] - b[:, 3] / 2 - top) / r,
                     b[:, 2] / r, b[:, 3] / r], 1)
    res = []
    for i in _nms(xywh, cf, iou):
        bx, by, bw, bh = (float(v) for v in xywh[i])
        if bw >= min_wh and bh >= min_wh:
            res.append((bx, by, bw, bh, float(cf[i]), int(cls[i])))
    return res


def detect(weights: str, img: np.ndarray, conf: float = 0.25, iou: float = 0.45
           ) -> list[tuple[float, float, float, float, float]]:
    """单字检测（`model/slide`）：`[(x, y, w, h, conf), …]`，坐标落 `img` 自己的像素系。
    `img` 灰度或 BGR uint8。"""
    return [r[:5] for r in _infer(weights, img, conf, iou, 6)]


#: 版面模型（`model/type`）类别，顺序同 `type.yaml`
LAYOUT_CLASSES = ("text", "subText", "midText", "ear", "subText2", "midSubText")


def detect_layout(weights: str, img: np.ndarray, conf: float = 0.25, iou: float = 0.45
                  ) -> list[tuple[float, float, float, float, float, str]]:
    """版面检测（`model/type`，整页喂）：`[(x, y, w, h, conf, 类别名), …]`。"""
    return [(*r[:5], LAYOUT_CLASSES[r[5]] if r[5] < len(LAYOUT_CLASSES) else str(r[5]))
            for r in _infer(weights, img, conf, iou, 10)]


def sibling_layout(slide_weights: str) -> str:
    """yolo_tool 仓里两个模型并排放（`model/slide/best.onnx`、`model/type/best.onnx`）。"""
    return str(Path(slide_weights).parent.parent / "type" / "best.onnx") if slide_weights else ""


def detect_page(slide: str, layout: str, img: np.ndarray, conf: float = 0.25
                ) -> list[tuple[float, float, float, float, float, str]]:
    """yolo_tool 原生喂法（`BatchInferWorker`）：整页 → 版面模型出列条（正文/夹注）→ 每条原样裁出
    喂单字模型。返回页坐标（`img` 自己的像素系，左上原点）的 `[(x0, y0, x1, y1, conf, 版面类别), …]`。
    只收 text/subText/subText2 三类版面框；宽 <10 或高 <15 的版面框丢弃（同 yolo_tool）。"""
    H, W = img.shape[:2]
    out = []
    for x, y, w, h, _, cls in detect_layout(layout, img, conf):
        if cls not in ("text", "subText", "subText2"):
            continue
        x0, y0 = max(0, int(round(x))), max(0, int(round(y)))
        x1, y1 = min(W, int(round(x + w))), min(H, int(round(y + h)))
        if x1 - x0 < 10 or y1 - y0 < 15:
            continue
        for bx, by, bw, bh, bc in detect(slide, img[y0:y1, x0:x1], conf):
            out.append((bx + x0, by + y0, bx + x0 + bw, by + y0 + bh, bc, cls))
    return out


# ── 复核判据（纯函数，单测自造数据）──────────────────────────────────────

Box = tuple[float, float, float, float]      # x0, y0, x1, y1


def _iou(a: Box, b: Box) -> float:
    iw = min(a[2], b[2]) - max(a[0], b[0])
    ih = min(a[3], b[3]) - max(a[1], b[1])
    if iw <= 0 or ih <= 0:
        return 0.0
    inter = iw * ih
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def match_yolo(cv: Box, y_range: tuple[float, float], boxes: list[Box],
               x_range: tuple[float, float] | None = None) -> Box | None:
    """格内与 CV 框最对得上的 YOLO 框：中心 y 落在本格 `y_range`（整页喂法再加中心 x 落在本列
    `x_range`）内、与 CV 框有重叠，取 IoU 最大。没有 → None（弃权：YOLO 在这里没出字，或者
    出的是别的格的）。"""
    best, best_s = None, 0.0
    lo, hi = y_range
    for b in boxes:
        cy = (b[1] + b[3]) / 2
        if not (lo <= cy <= hi):
            continue
        if x_range is not None and not (x_range[0] <= (b[0] + b[2]) / 2 <= x_range[1]):
            continue
        s = _iou(cv, b)
        if s > best_s:
            best, best_s = b, s
    return best


def _count(ink: np.ndarray, x0: float, y0: float, x1: float, y1: float) -> int:
    H, W = ink.shape
    a, b = max(0, int(round(x0))), max(0, int(round(y0)))
    c, d = min(W, int(round(x1))), min(H, int(round(y1)))
    return int(ink[b:d, a:c].sum()) if c > a and d > b else 0


def extra_ink_ratio(ink: np.ndarray, cv: Box, yolo: Box, y_range: tuple[float, float],
                    skip_top: bool = False, skip_bottom: bool = False) -> float:
    """YOLO 框比 CV 框多包进来的墨 / 两框并集里的全部墨。

    只数本格竖向范围 `y_range`（Step3 的格线，上下各放 `PAD` 像素）里的墨——邻格探进来的笔画
    不算。`ink` 是 0/1 墨图（原图 <128）。并集 = 两框的外包矩形；多出的墨 = 并集墨 − CV 框墨。

    `skip_top`/`skip_bottom`：这一格贴着版框那一侧（列首格的上侧、列末格的下侧）。YOLO 单字框
    习惯连版框线的碎墨一起框进去，那一侧多出来的墨是版框不是字——不算（vol02/vol03 实测：不跳过时
    命中的 61 格几乎全是列末格 CV 紧框没错、YOLO 框吃了下版框碎墨）。真正要抓的「把版框线当末字」
    是版框线在 CV 框里、字在**上方**，那边不跳。
    """
    lo, hi = y_range[0] - PAD, y_range[1] + PAD
    ux0, uy0 = min(cv[0], yolo[0]), max(min(cv[1], yolo[1]), lo)
    ux1, uy1 = max(cv[2], yolo[2]), min(max(cv[3], yolo[3]), hi)
    if skip_top:
        uy0 = max(uy0, cv[1])
    if skip_bottom:
        uy1 = min(uy1, cv[3])
    total = _count(ink, ux0, uy0, ux1, uy1)
    if total <= 0:
        return 0.0
    inside = _count(ink, cv[0], max(cv[1], uy0), cv[2], min(cv[3], uy1))
    return max(0.0, (total - inside) / total)


PAD = 6.0
