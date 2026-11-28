"""decide-bench/cell-state 分片的构建脚本（CV4，2026-11-28）。

4c 格况（cell_state）的金标：每格 expected.state ∈ {char, non_char}（seal／occluded／seg_bad 的金标还没有，见分片 README 的缺口）。
来源只用已有人裁，不新增标注（Sheldon 11-28 标注暂停）：
- char：decide-bench/small 里人裁定了字（expected.char 非空）的格，护栏「有字判无字＝漏字，必须 0」；锚点沿用原图框 bbox。
- non_char：char-segmentation/instances 里人标 not_text（根本不是字）且 status=active 的格，锚点只有产物键（页／列／槽），无 bbox。

用法：python -m open_guji_cv.eval.decide_bench.build_cell_state --dataset <open-guji-dataset 根>
输出：<dataset>/decide-bench/cell-state/<工作区id>/items.jsonl（按书子目录）＋ metadata.json。重跑结果逐字节相同。
"""
import argparse
import collections
import json
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--dataset", required=True)
a = ap.parse_args()
ds = Path(a.dataset)
out = ds / "decide-bench" / "cell-state"
BOOKS = {"988g3f0wsu": "史記", "995ejelvk0": "全唐文", "siku-zongmu": "殿本（四库总目）"}
INST_WS = "siku-zongmu"          # instances 里的 vol01／vol02 是殿本

rows: dict[str, list[dict]] = collections.defaultdict(list)
for l in open(ds / "decide-bench/small/items.jsonl", encoding="utf-8"):
    d = json.loads(l)
    ch = (d.get("expected") or {}).get("char")
    if d.get("status") != "active" or not ch:
        continue
    ws = d["anchor"]["ws"]
    rows[ws].append({
        "id": "cs:" + d["id"], "anchor": d["anchor"], "input": {"from": "decide-bench/small", "small_id": d["id"]},
        "expected": {"state": "char"}, "label_origin": d["label_origin"], "stratum": "有字·人裁定字", "status": "active",
        "source_events": d.get("source_events", []),
        "history": [{"ts": "2026-11-28", "change": "created", "why": "4c 漏字护栏：人裁定了字的格不能判成无字"}]})
for l in open(ds / "char-segmentation/instances/items.jsonl", encoding="utf-8"):
    d = json.loads(l)
    e = d.get("expected") or {}
    if e.get("quality") != "not_text" or d.get("status") != "active":
        continue
    rows[INST_WS].append({
        "id": "cs:inst:" + d["id"], "anchor": {**d["anchor"], "ws": INST_WS, "key_kind": "product_key", "space": None},
        "input": {"from": "char-segmentation/instances", "instance_id": d["id"],
                  "note": "只有产物键（页、列、槽），切分改过后可能失效，用前核对"},
        "expected": {"state": "non_char"}, "label_origin": d.get("label_origin", "human"), "stratum": "无字·人标 not_text",
        "status": "active", "source_events": d.get("source_events", []),
        "history": [{"ts": "2026-11-28", "change": "created", "why": "从 instances 的 not_text 转入"}]})

counts = {}
for ws, rs in sorted(rows.items()):
    rs.sort(key=lambda r: r["id"])
    p = out / ws
    p.mkdir(parents=True, exist_ok=True)
    with open(p / "items.jsonl", "w", encoding="utf-8") as f:
        for r in rs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    counts[ws] = dict(collections.Counter(r["expected"]["state"] for r in rs))
meta = {
    "name": "decide-bench/cell-state", "version": "0.1.0", "schema_version": 1, "created": "2026-11-28", "status": "起步（只有 char 与 non_char）",
    "owner": "CV4", "sample_unit": "格", "books": {k: BOOKS.get(k, k) for k in sorted(rows)},
    "layout": "按书分子目录：<工作区id>/items.jsonl", "counts": counts,
    "label_origin_values": ["human", "human_audit"],
    "metrics": [
        {"name": "missed_char", "target": "0", "description": "金标 state=char 的格被 4c 判成 non_char／seal／occluded／seg_bad 且因此送审（漏字）"},
        {"name": "non_char_recall", "direction": "higher_is_better", "description": "金标 state=non_char 的格被 4c 判成 non_char 的比例"},
        {"name": "state_precision", "direction": "higher_is_better", "description": "4c 每种判定的精确率（金标有的状态才有）"}],
    "random_vs_hard": "char 层是人裁定字的格（易格偏多）；non_char 层是人标的难例；两者都不是随机样本，不能估全册率",
    "known_gaps": "无 seal／occluded／seg_bad／blank 金标；non_char 只有殿本 vol01、vol02，且无 bbox；史記、全唐文无 non_char。Sheldon 11-28 起标注暂停，补标等恢复后由 CV4 用 review-pages 做。",
}
(out / "metadata.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(counts, ensure_ascii=False))
