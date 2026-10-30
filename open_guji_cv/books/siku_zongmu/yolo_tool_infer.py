"""yolo-tool（open-guji/yolo_tool）两段 YOLOv8 的 ONNX 推理：版面 → 裁条 → 单字。

只用 onnxruntime + numpy + cv2，不装 torch/ultralytics。流程逐条对照 yolo_tool `core/workers.py`
BatchInferWorker.run（L95-186）：
- 版面模型整页喂，conf 0.25 / NMS IoU 0.45，宽 <10 或高 <15 的框丢掉；
- 每个版面框裁原图（不加边、不缩放）喂单字模型，同阈值，宽或高 <6 的丢掉，坐标加回整页。
差别只在前处理：导出的 ONNX 是定长 1024×1024，这里做**方形** letterbox（灰 114 补边）；
ultralytics 用 .pt 时是按 stride 的矩形 letterbox。两者框位差在一两个像素（见 doc/design/19 D 块实测）。

模型文件不进本仓（版面 104 MB、单字 12 MB），由调用方给路径；`model_fingerprint()` 给两份文件的 sha。
坐标一律**左上原点**的原图像素。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

TYPE_NAMES = ("text", "subText", "midText", "ear", "subText2", "midSubText")
IMGSZ = 1024


@dataclass
class Box:
    x0: float
    y0: float
    x1: float
    y1: float
    conf: float
    cls: str


def model_fingerprint(model_dir: str | Path) -> str:
    d = Path(model_dir)
    h = hashlib.sha256()
    for k in ("type", "slide"):
        h.update((d / k / "best.onnx").read_bytes())
    return h.hexdigest()[:16]


class YoloTool:
    def __init__(self, model_dir: str | Path):
        import onnxruntime as ort
        d = Path(model_dir)
        opts = ort.SessionOptions()
        opts.log_severity_level = 3
        self.type_sess = ort.InferenceSession(str(d / "type" / "best.onnx"), opts, providers=["CPUExecutionProvider"])
        self.slide_sess = ort.InferenceSession(str(d / "slide" / "best.onnx"), opts, providers=["CPUExecutionProvider"])

    @staticmethod
    def _detect(sess, img_bgr: np.ndarray, conf: float, iou: float, names: tuple[str, ...] | None) -> list[Box]:
        h, w = img_bgr.shape[:2]
        r = min(IMGSZ / h, IMGSZ / w)
        nh, nw = int(round(h * r)), int(round(w * r))
        top, left = (IMGSZ - nh) // 2, (IMGSZ - nw) // 2
        canvas = np.full((IMGSZ, IMGSZ, 3), 114, np.uint8)
        canvas[top:top + nh, left:left + nw] = cv2.resize(img_bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
        x = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        out = sess.run(None, {sess.get_inputs()[0].name: x})[0][0]     # (4+nc, N)
        scores = out[4:]
        cls = scores.argmax(0)
        sc = scores[cls, np.arange(scores.shape[1])]
        keep = sc >= conf
        if not keep.any():
            return []
        cx, cy, bw, bh = out[0, keep], out[1, keep], out[2, keep], out[3, keep]
        sc, cls = sc[keep], cls[keep]
        x0 = (cx - bw / 2 - left) / r
        y0 = (cy - bh / 2 - top) / r
        x1 = (cx + bw / 2 - left) / r
        y1 = (cy + bh / 2 - top) / r
        boxes = []
        for c in np.unique(cls):                      # 按类 NMS（同 ultralytics agnostic=False）
            m = np.where(cls == c)[0]
            rects = [[float(x0[i]), float(y0[i]), float(x1[i] - x0[i]), float(y1[i] - y0[i])] for i in m]
            idx = cv2.dnn.NMSBoxes(rects, [float(sc[i]) for i in m], conf, iou)
            for k in np.array(idx).reshape(-1):
                i = m[int(k)]
                boxes.append(Box(float(np.clip(x0[i], 0, w)), float(np.clip(y0[i], 0, h)),
                                 float(np.clip(x1[i], 0, w)), float(np.clip(y1[i], 0, h)),
                                 float(sc[i]), names[int(c)] if names else "ch"))
        boxes.sort(key=lambda b: -b.conf)
        return boxes[:300]

    def infer(self, img_bgr: np.ndarray, type_conf: float = 0.25, slide_conf: float = 0.25,
              iou: float = 0.45) -> tuple[list[Box], list[Box]]:
        """→ (版面框, 单字框)；单字框的 `cls` 是它所在版面框的类名。"""
        H, W = img_bgr.shape[:2]
        layouts = [b for b in self._detect(self.type_sess, img_bgr, type_conf, iou, TYPE_NAMES)
                   if b.x1 - b.x0 >= 10 and b.y1 - b.y0 >= 15]
        chars: list[Box] = []
        for t in layouts:
            lx0, ly0 = max(0, int(t.x0)), max(0, int(t.y0))
            lx1, ly1 = min(W, int(t.x1)), min(H, int(t.y1))
            crop = img_bgr[ly0:ly1, lx0:lx1]
            if crop.size == 0:
                continue
            for b in self._detect(self.slide_sess, crop, slide_conf, iou, None):
                if b.x1 - b.x0 < 6 or b.y1 - b.y0 < 6:
                    continue
                chars.append(Box(b.x0 + lx0, b.y0 + ly0, b.x1 + lx0, b.y1 + ly0, b.conf, t.cls))
        return layouts, chars
