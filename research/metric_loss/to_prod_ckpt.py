# -*- coding: utf-8 -*-
"""把实验 checkpoint 转成生产 `CnnCandidates` 能加载的形状，以便跑
`scripts/eval_oov.py` 这类官方评测。

为什么需要转：生产 `cnn_candidates._build_net` 里写死了
`self.cls = nn.Linear(d, n_cls)`（带 bias），而余弦头档存的是
`W`（归一化权重、无 bias）。backbone 与 `emb` 两边完全一致，
所以只需把 `W` 搬到 `cls.weight`、`cls.bias` 置 0：

    cos(θ) · s  ==  (W_norm @ e_norm) · s

生产 forward 算的是 `cls(e)`，其中 `e = normalize(emb)*16`。
若令 `cls.weight = W_norm`、`bias = 0`，则
`cls(e) = W_norm @ normalize(emb) * 16 = cos(θ) * 16`——
与训练时 `cos * scale` 完全一致（scale=16 时）。

⚠️ **`emb` 一路不受影响**，转换只为让 `cls` 能算出来。
OOV 集上 `cls` 恒为 0（类外字不在输出空间），所以转换正确性
对本实验的主指标无影响；但转了才能一条命令跑完官方评测。
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="实验 checkpoint（best.pt）")
    ap.add_argument("--dst", required=True, help="输出生产形状 checkpoint")
    a = ap.parse_args()
    import torch
    import torch.nn.functional as F

    ck = torch.load(a.src, map_location="cpu", weights_only=False)
    st = dict(ck["state"])
    cfg = ck.get("cfg", {})
    scale = float(cfg.get("scale", 16.0))
    if "W" in st:
        W = st.pop("W")
        # 生产 forward 里 e 已经乘过 16，而训练时 cos 是对 normalize(e) 算的，
        # 再乘 scale。两边要对上：cls.weight = W_norm * (scale/16)
        st["cls.weight"] = F.normalize(W, dim=1) * (scale / 16.0)
        st["cls.bias"] = torch.zeros(W.shape[0])
        print(f"余弦头 → 线性头：W {tuple(W.shape)}，scale={scale}")
    else:
        print("已是线性头，直接拷贝")
    out = {"state": st, "classes": ck["classes"], "comps": ck["comps"]}
    Path(a.dst).parent.mkdir(parents=True, exist_ok=True)
    torch.save(out, a.dst)
    print("写出", a.dst)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
