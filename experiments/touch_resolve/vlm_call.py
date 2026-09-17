# -*- coding: utf-8 -*-
"""视觉大模型调用层（实验用）：复用 llm_context 的 key 查找与 OpenAI 兼容格式，加图片。

GLM 与千问的视觉模型都走同一个 chat/completions 端点，content 里放
{"type":"image_url","image_url":{"url":"data:image/png;base64,..."}} 即可。

    python vlm_call.py --smoke            # 各家发一张小图，看通不通
"""
import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request

import cv2
import numpy as np

sys.path.insert(0, r"D:/workspace/open-guji-cv")
from open_guji_cv.clustering.llm_context import ENDPOINTS, find_api_key  # noqa: E402

VISION_MODELS = {
    "qwen": "qwen-vl-plus",       # 便宜；qwen-vl-max 更强
    "glm": "glm-4v-plus",
}


def png_b64(img: np.ndarray) -> str:
    ok, buf = cv2.imencode(".png", img)
    return base64.b64encode(buf.tobytes()).decode()


def ask_vision(provider: str, prompt: str, images: list[np.ndarray],
               model: str | None = None, timeout: int = 60, max_tokens: int = 400) -> dict:
    """返回 {text, elapsed, usage, error}。图按顺序放在文字之前。"""
    cfg = ENDPOINTS[provider]
    key, _ = find_api_key(cfg["env"])
    if not key:
        return {"error": f"no key for {provider}"}
    model = model or VISION_MODELS[provider]
    content = [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + png_b64(im)}}
               for im in images]
    content.append({"type": "text", "text": prompt})
    body = {"model": model, "messages": [{"role": "user", "content": content}],
            "max_tokens": max_tokens, "temperature": 0}
    req = urllib.request.Request(
        cfg["url"], data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            j = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}",
                "elapsed": time.time() - t0}
    except Exception as e:                                   # noqa: BLE001
        return {"error": repr(e), "elapsed": time.time() - t0}
    text = (j.get("choices") or [{}])[0].get("message", {}).get("content", "")
    return {"text": text, "elapsed": time.time() - t0, "usage": j.get("usage"), "model": model}


def _smoke():
    img = np.full((96, 96), 255, np.uint8)
    cv2.putText(img, "7", (28, 72), cv2.FONT_HERSHEY_SIMPLEX, 2.2, 0, 6)
    for p in ("qwen", "glm"):
        r = ask_vision(p, "这张图里是什么？只回答一个字符。", [img], max_tokens=20)
        print(p, "->", json.dumps(r, ensure_ascii=False)[:300])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args()
    if a.smoke:
        _smoke()
