# -*- coding: utf-8 -*-
"""PP-OCRv5 识别 worker：在**独立的 paddle 环境**里跑，主进程用 JSON 行协议调它。

## 为什么不装进主 venv

试了两次：paddlepaddle 3.3 与本 venv 的 numpy/torch 组合解不开，而且装的过程
要替换 numpy 的 DLL——控制台一开着就「拒绝访问」。paddle 的依赖树本来就重
（paddlex + 一整套模型注册表），塞进主 venv 只会让以后每次装东西都提心吊胆。

所以 paddle 留在它自己的环境（`D:/古籍整理/.venv`，用户为另一个项目装的，
paddleocr 3.4 + PP-OCRv5 模型都在），本模块作为 worker 被 `PaddleOcrSource`
用 subprocess 拉起，进程常驻、按行收发 JSON：

    → {"png": "<base64>", "k": 5}
    ← {"topk": [["字", 0.98], ...]}

单字块 CPU 推理约 50ms，常驻进程避免每次 2 秒的模型加载。

## 取 top-k 的办法

`TextRecognition.predict` 只给 top-1 文本。这里走 paddlex `TextRecPredictor`
的预处理链拿 (T, C) 概率矩阵，取非空白概率最大的时间步，在该步上排序——
与 `RapidOcrSource.rec_topk` 同一口径，候选层要的是分布不是一个字。
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys

import numpy as np


def main() -> int:
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace",
                                  line_buffering=True)
    sys.stdin = io.TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace")
    import cv2
    from paddleocr import TextRecognition

    model = sys.argv[1] if len(sys.argv) > 1 else "PP-OCRv5_server_rec"
    device = sys.argv[2] if len(sys.argv) > 2 else "cpu"
    pred = TextRecognition(model_name=model, device=device)
    # paddleocr 3.4 的 TextRecognition 是 PaddleXPredictorWrapper，
    # 真正的 TextRecPredictor 挂在 .paddlex_predictor 上
    inner = (getattr(pred, "paddlex_predictor", None)
             or getattr(pred, "_predictor", None) or pred)
    pre, infer, post = inner.pre_tfs, inner.infer, inner.post_op
    chars = post.character
    print(json.dumps({"ready": True, "model": model, "n_chars": len(chars)}), flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            buf = np.frombuffer(base64.b64decode(req["png"]), np.uint8)
            img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
            k = int(req.get("k", 5))
            h = img.shape[0]
            pad = max(4, h // 8)
            img = cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT,
                                     value=(255, 255, 255))
            raw = pre["Read"](imgs=[img])
            norm = pre["ReisizeNorm"](imgs=raw)
            x = pre["ToBatch"](imgs=norm)
            preds = infer(x=x)
            if isinstance(preds, (list, tuple)):
                preds = preds[-1]
            preds = np.asarray(preds)[0]                # (T, C)
            nb = preds[:, 1:]
            t = int(np.unravel_index(np.argmax(nb), nb.shape)[0])
            order = np.argsort(-preds[t])
            out = []
            for i in order:
                i = int(i)
                if i == 0:
                    continue
                ch = chars[i] if i < len(chars) else ""
                if ch and not ch.isascii():
                    out.append([ch, float(preds[t][i])])
                if len(out) >= k:
                    break
            print(json.dumps({"topk": out}, ensure_ascii=False), flush=True)
        except Exception as e:                      # 一条坏图不该杀掉 worker
            print(json.dumps({"error": str(e)[:200]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
