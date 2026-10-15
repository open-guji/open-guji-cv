# -*- coding: utf-8 -*-
"""rebind_lookups.py 的合成数据自测：造小表，覆盖 一对一（未变／改号）、拆分、合并、无对应、部分重合、低置信配对、id 串被复用、夹注 a/b。

    python selftest.py          # 在 ./自测/ 下写合成输入与输出，断言分类正确，失败会 AssertionError
"""
import csv
import gzip
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import rebind_lookups as R  # noqa: E402

D = HERE / "自测"
D.mkdir(exist_ok=True)


def cell(i, x0, y0, x1, y1, **kw):
    return {"id": i, "bbox_page": [x0, y0, x1, y1], **kw}


# 第 1 页：一对一（A 未变、B 改号：列内整列顺移）；第 2 页：拆分；第 3 页：合并；第 4 页：无对应；
# 第 5 页：id 串被复用（旧 5:1:1 的框变成别的字，新 5:1:1 是另一块）；第 6 页：夹注 a/b；第 7 页：部分重合
old = [
    cell("v:1:1:1", 100, 100, 160, 160), cell("v:1:1:2", 100, 170, 160, 230),            # 1
    cell("v:2:1:1", 100, 100, 160, 220),                                                  # 2 拆分
    cell("v:3:1:1", 100, 100, 160, 160), cell("v:3:1:2", 100, 165, 160, 225),            # 3 合并
    cell("v:4:1:1", 100, 100, 160, 160),                                                  # 4 无对应
    cell("v:5:1:1", 100, 100, 160, 160),                                                  # 5 复用
    cell("v:6:1:1", 100, 100, 160, 220),                                                  # 6 夹注
    cell("v:7:1:1", 100, 100, 160, 160),                                                  # 7 部分重合
    cell("v:9:1:1", 100, 100, 160, 160),                                                  # 9 低置信配对
    cell("v:10:1:10", 100, 1000, 160, 1100), cell("v:10:1:9", 100, 900, 160, 1000),       # 10 改号链：整列顺移 10→9、9→8
    cell("v:11:1:3", 100, 100, 160, 200), cell("v:11:1:5", 100, 500, 160, 600),           # 11 同号复用：旧 11:1:3 搬到 11:1:4，新 11:1:3 是另一块
]
new = [
    cell("v:1:1:1", 101, 101, 160, 160), cell("v:1:1:3", 100, 170, 160, 231),            # 1：原 :2 变 :3
    cell("v:2:1:1", 100, 100, 160, 158), cell("v:2:1:2", 100, 162, 160, 220),            # 2
    cell("v:3:1:1", 100, 100, 160, 225),                                                  # 3
    cell("v:4:1:9", 300, 300, 360, 360),                                                  # 4：别处有格，原处没有
    cell("v:5:1:1", 100, 300, 160, 360), cell("v:5:1:2", 100, 100, 160, 160),            # 5：原框现为 :2，:1 换了位置
    cell("v:6:1:1a", 100, 100, 130, 220), cell("v:6:1:1b", 135, 100, 160, 220),          # 6：夹注拆成 a/b
    cell("v:7:1:1", 100, 100, 160, 125),                                                  # 7：只剩 5/12（iou≈0.42<0.5）
    cell("v:9:1:1", 100, 100, 160, 133),                                                  # 9：iou≈0.55（0.5≤iou<0.6）
    cell("v:10:1:9", 100, 1000, 160, 1100), cell("v:10:1:8", 100, 900, 160, 1000), cell("v:10:1:7", 100, 800, 160, 900),
    cell("v:11:1:4", 100, 100, 160, 200), cell("v:11:1:3", 100, 300, 160, 400), cell("v:11:1:5", 100, 500, 160, 600),
    cell("v:8:1:1", 100, 100, 160, 133),                                                  # 8：iou≈0.55，低置信配对
]


def write(path, rows):
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(json.dumps({"header": True, "note": "合成"}) + "\n")
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


write(D / "old_合成.jsonl.gz", old)
write(D / "new_合成.jsonl.gz", new)
lookups = [("v:1:1:1", "ok", "甲"), ("v:1:1:2", "wrong", "乙"), ("v:2:1:1", "ok", "丙"), ("v:3:1:1", "ok", "丁"),
           ("v:3:1:2", "wrong", "戊"), ("v:4:1:1", "ok", "己"), ("v:5:1:1", "ok", "庚"), ("v:6:1:1", "ok", "辛"),
           ("v:7:1:1", "unsure", "壬"), ("v:8:1:1", "ok", "癸"), ("v:9:1:1", "ok", "子"),
           ("v:10:1:10", "ok", "甲甲"), ("v:10:1:9", "wrong", "乙乙"), ("v:11:1:3", "ok", "丑")]
with open(D / "看图结论_合成.csv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.writer(f)
    w.writerow(["cell", "v", "shown", "judge", "note"])
    for c, v, s in lookups:
        w.writerow([c, v, s, "claude-opus-5-5", "合成"])

summ = R.main(["--old", str(D / "old_合成.jsonl.gz"), "--new", str(D / "new_合成.jsonl.gz"),
               "--lookups", str(D / "看图结论_合成.csv"), "--out-dir", str(D / "输出"), "--emit-vision-jsonl"])

want = {"v:1:1:1": "未变", "v:1:1:2": "一对一改号", "v:2:1:1": "一对多", "v:3:1:1": "多对一", "v:3:1:2": "多对一",
        "v:4:1:1": "无对应", "v:5:1:1": "一对一改号", "v:6:1:1": "一对多", "v:7:1:1": "部分重合", "v:8:1:1": "无对应", "v:9:1:1": "低置信配对",
        "v:10:1:10": "一对一改号", "v:10:1:9": "一对一改号", "v:11:1:3": "一对一改号"}
got = {}
for fn in ("看图结论_合成.新结论.csv", "看图结论_合成.要人看.csv"):
    with open(D / "输出" / fn, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            got[r["cell"]] = r["rebind_status"]
bad = {c: (want[c], got.get(c)) for c in want if got.get(c) != want[c]}
assert not bad, f"分类不符：{bad}"
# 复用 id 串：旧 5:1:1 的框在新表里是 5:1:2，不能因号相同判未变
assert got["v:5:1:1"] == "一对一改号"
js = [json.loads(l) for l in open(D / "输出" / "看图结论_合成.import-vision.jsonl", encoding="utf-8")]
# 导出顺序（208hj，Elena C2）：先全部退役行、后全部新号行
kinds = ["retire" if j["v"] == "unsure" and "退役" in j["note"] else "new" for j in js]
assert kinds == sorted(kinds, key=lambda k: 0 if k == "retire" else 1), kinds
# 旧号恰是别条新号目标时不写退役行：10:1:9 既是旧格（→10:1:8）又是新号目标（←10:1:10）
assert not any(j["cell"] == "v:10:1:9" and "退役" in j["note"] for j in js), js
# 模拟看图日志「同格按 (ts, 行号) 后到覆盖」
eff = {}
for i, j in enumerate(js):
    if j["cell"] not in eff or (j["ts"], i) >= eff[j["cell"]][:2]:
        eff[j["cell"]] = (j["ts"], i, j["v"])
v = {k: x[2] for k, x in eff.items()}
assert v["v:10:1:9"] == "ok" and v["v:10:1:8"] == "wrong" and v["v:10:1:10"] == "unsure", v   # 改号链
assert v["v:11:1:4"] == "ok" and v["v:11:1:3"] == "unsure", v                                   # 同号复用：旧号退役，新号落在新位置
assert v["v:1:1:3"] == "wrong" and v["v:1:1:2"] == "unsure" and v["v:5:1:2"] == "ok" and v["v:5:1:1"] == "unsure", v
assert summ["emit_selfcheck"] == "ok" and summ["retire_skipped_as_target"] == 1, summ
assert summ["by_status"] == {"未变": 1, "一对一改号": 5, "一对多": 2, "多对一": 2, "无对应": 2, "部分重合": 1, "低置信配对": 1}, summ["by_status"]
print("自测通过：", summ["by_status"])
