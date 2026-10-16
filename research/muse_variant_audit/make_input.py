"""muse 批次 V1（overview 卡见 README）：异体关系表单来源边复核的输入生成。

输入：config/variants/variants.json + 书中出现过的字（charset.json：四庫 vol02–vol10 快照里
seed_admit 定字 ∪ align_ref 整理本字，CV 总管 10-02 统计，4,141 字）。
输出：input.jsonl —— 单来源、两字都在书中出现过的边（待审），外加三组对照：
  ctrl_strict   多来源（≥3 个独立来源）严格异体，应判「同字异形」
  ctrl_spoof    unihan:kSpoofingVariant 单源边，应判「形近不同字」
  ctrl_known_no 10-02 人裁确认「不是同一字」的表内边（规则 B 负例），应判非同字
固定种子，可重生。
"""
import json, random, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
P = json.load(open(ROOT / "config/variants/variants.json"))["pairs"]
chars = set(json.load(open(sys.argv[1]))["chars"]) if len(sys.argv) > 1 else None
rng = random.Random(20261002)

KNOWN_NO = [("大", "太"), ("增", "憎"), ("楊", "揚"), ("且", "旦"), ("規", "窺"), ("戊", "戌"),
            ("管", "菅"), ("簿", "薄"), ("惟", "唯"), ("距", "鉅"), ("倡", "唱"), ("秩", "佚"),
            ("揀", "練"), ("兩", "雨"), ("齋", "齊"), ("雙", "隻")]

seen, todo, strict, spoof = set(), [], [], []
for a, m in P.items():
    for b, s in m.items():
        k = tuple(sorted((a, b)))
        if k in seen:
            continue
        seen.add(k)
        ss = sorted(set(s))
        if len(ss) >= 3:
            strict.append((k, ss))
        if len(ss) == 1:
            if ss[0] == "unihan:kSpoofingVariant":
                spoof.append((k, ss))
            if chars is not None and k[0] in chars and k[1] in chars:
                todo.append((k, ss))

rows = [{"id": f"t{i:05d}", "a": k[0], "b": k[1], "sources": ss, "group": "todo"}
        for i, (k, ss) in enumerate(sorted(todo))]
for g, pool, n in (("ctrl_strict", strict, 60), ("ctrl_spoof", spoof, 40)):
    for i, (k, ss) in enumerate(rng.sample(pool, min(n, len(pool)))):
        rows.append({"id": f"{g}{i:03d}", "a": k[0], "b": k[1], "sources": ss, "group": g})
for i, (a, b) in enumerate(KNOWN_NO):
    rows.append({"id": f"ctrl_no{i:03d}", "a": a, "b": b, "sources": P.get(a, {}).get(b, []),
                 "group": "ctrl_known_no"})
rng.shuffle(rows)   # 对照混进待审里，不让模型看出分组
with open(Path(__file__).with_name("input.jsonl"), "w") as f:
    for r in rows:
        f.write(json.dumps({k: r[k] for k in ("id", "a", "b")}, ensure_ascii=False) + "\n")
with open(Path(__file__).with_name("key.jsonl"), "w") as f:   # 分组与来源：只给验收用，不喂 muse
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print(len(rows), sum(r["group"] == "todo" for r in rows))
