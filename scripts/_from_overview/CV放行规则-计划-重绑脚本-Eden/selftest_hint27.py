# -*- coding: utf-8 -*-
"""hint_remap_27.py 的合成自测（GUJI-208jd 件二）：一对一链式补行、主导候选（竞争者数=1）、
一对多但 A 侧有竞争者（不进主导）、0.5≤iou<0.6 低置信（不进 remap 也不进主导）。
用法：python3 -I selftest_hint27.py     纯标准库＋同目录脚本，不碰任何真实产物。"""
import json, subprocess, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def write_root(root, cells):
    d = Path(root, "vol05", "cell_shrink"); d.mkdir(parents=True)
    chars = [{"id": i, "bbox": b} for i, b in cells.items()]
    (d / "p0001.json").write_text(json.dumps({"x": {"columns": [{"chars": chars}]}}), encoding="utf-8")


B = {"vol05:1:1:10": [0, 0, 10, 10], "vol05:1:1:11": [0, 20, 10, 30],            # 链：B10→A11，B11 被挤占→A12
     "vol05:1:2:5": [100, 0, 110, 10], "vol05:1:2:6": [100, 10, 110, 20],        # 主导候选（竞争者 1）
     "vol05:1:3:7": [200, 0, 210, 10], "vol05:1:3:8": [200, 10, 210, 20],        # 一对多但 A 侧有竞争者
     "vol05:1:4:1": [300, 0, 310, 16.8]}                                          # 低置信 iou≈0.595
A = {"vol05:1:1:11": [0, 0, 10, 10], "vol05:1:1:12": [0, 20, 10, 30],
     "vol05:1:2:5": [100, 0, 110, 15],
     "vol05:1:3:6": [200, -12, 210, 5], "vol05:1:3:7": [200, 0, 210, 15],
     "vol05:1:4:1": [300, 0, 310, 10]}
cells = ["vol05:1:1:11", "vol05:1:1:12", "vol05:1:2:5", "vol05:1:3:7", "vol05:1:4:1"]

with tempfile.TemporaryDirectory() as td:
    td = Path(td); write_root(td / "A", A); write_root(td / "B", B)
    (td / "cells.txt").write_text("\n".join(cells), encoding="utf-8")
    r = subprocess.run([sys.executable, "-I", str(HERE / "hint_remap_27.py"), "--a", str(td / "A"), "--b", str(td / "B"),
                        "--cells", str(td / "cells.txt"), "--out-dir", str(td / "out")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    remap = dict(l.split("\t") for l in (td / "out/remap.tsv").read_text(encoding="utf-8").splitlines()
                 if l and not l.startswith("#"))
    dom = [l.split("\t") for l in (td / "out/主导候选.tsv").read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
    rows = {l.split("\t")[0]: l.split("\t") for l in (td / "out/对位.tsv").read_text(encoding="utf-8").splitlines()[1:]}
    assert remap.get("vol05:1:1:10") == "vol05:1:1:11", remap                 # 改号
    assert remap.get("vol05:1:1:11") == "vol05:1:1:12", remap                 # 被挤占的 B 号自动补行
    assert dom == [["vol05:1:2:5", "vol05:1:2:5"]], dom                        # 只有竞争者数=1 的进主导候选
    assert rows["vol05:1:2:5"][8] == "1", rows["vol05:1:2:5"]                  # 输出竞争者数
    assert int(rows["vol05:1:3:7"][8]) >= 2 and rows["vol05:1:3:7"][9] == "", rows["vol05:1:3:7"]
    assert rows["vol05:1:4:1"][1] == "低置信配对" and "vol05:1:4:1" not in remap, rows["vol05:1:4:1"]
    assert not any(d[0] == "vol05:1:4:1" for d in dom)
    print("hint_remap_27 自测通过：链式补行、主导候选(竞争者=1)、竞争者>1 不进主导、低置信不进 remap／主导")
