# -*- coding: utf-8 -*-
"""scripts/harvest_shadow_review.py：裁决 → 事件，重复跑不重复写（全部自造数据）。"""
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "harvest_shadow_review.py"


def _run(html, cards, fb, *extra):
    return subprocess.run([sys.executable, str(SCRIPT), str(html), "--cards", str(cards),
                           "--feedback-dir", str(fb), "--batch", "t-shadow", *extra],
                          capture_output=True, text=True, encoding="utf-8", check=True).stdout


def test_idempotent_and_mapping(tmp_path):
    cards = tmp_path / "cards.jsonl"
    cards.write_text("\n".join(json.dumps({"id": f"vol03:{p}:1:2", "a": "即", "b": "卽"})
                               for p in (4, 5, 6, 7)), encoding="utf-8")
    fb = tmp_path / "fb"
    (fb / "events").mkdir(parents=True)
    (fb / "events" / "old.jsonl").write_text(json.dumps(
        {"target": {"book": "vol03", "anchor": {"product_key": {"step": "seed_admit", "key": "p0004",
                                                                "fingerprint": "abc"}}}}) + "\n")

    def page(vs):
        data = {"rows": [], "verdicts": vs}
        p = tmp_path / "page.html"
        p.write_text('<script type="application/json" id="data">' + json.dumps(data) + "</script>")
        return p

    v = {"vol03:4:1:2": {"v": "b", "t": 1790645246979}, "vol03:5:1:2": {"v": "neither", "t": 1790645247979},
         "vol03:6:1:2": {"v": "idk", "t": 1790645248979}}
    _run(page(v), cards, fb)
    out = fb / "events" / "t-shadow.jsonl"
    evs = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert [e["target"]["key"] for e in evs] == ["vol03:4:1:2", "vol03:5:1:2"]
    assert evs[0]["payload"]["v"] == "confirm" and evs[0]["payload"]["shape"] == "卽"
    assert evs[0]["target"]["anchor"]["product_key"]["fingerprint"] == "abc"
    assert evs[1]["payload"] == {"v": "seg_defect", "quality": "truncated", "shape": "",
                                 "via": "shadow-review", "client_ts": 1790645247979}
    assert (evs[0]["step" if "step" in evs[0] else "kind"], evs[0]["target"]["unit"]) == ("confirm", "cell")

    _run(page(v), cards, fb)                       # 原样重跑：不增
    assert len(out.read_text(encoding="utf-8").splitlines()) == 2
    v["vol03:7:1:2"] = {"v": "a", "t": 1790645249979}
    _run(page(v), cards, fb)                       # 用户接着裁：只追加新的
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3 and json.loads(lines[2])["payload"]["shape"] == "即"
