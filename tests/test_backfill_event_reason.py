"""scripts/zhengli/backfill_event_reason.py：按事件字段推 pending_reason；按原行写法重写、别的字段不动。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "zhengli"))

import backfill_event_reason as b  # noqa: E402


def _e(kind, **payload):
    return {"id": "evt_x_000001", "kind": kind, "payload": payload, "target": {"key": "vol20:1:1:1"}}


def test_reason_of():
    assert b.reason_of(_e("ctx_ruling", group="rr")) == "group_abstain"
    assert b.reason_of(_e("ctx_ruling", group="O", route="code_conflict", subclass="PUA")) == "ruling_conflict"
    assert b.reason_of(_e("ctx_ruling", group="O", subclass="PUA", ref="")) == "ref_lacuna"
    assert b.reason_of(_e("ctx_ruling", group="O", ref="", machine="甲")) == "ref_gap"
    assert b.reason_of(_e("ctx_ruling", group="O", ref="乙", machine="甲")) == "ref_mismatch"
    assert b.reason_of(_e("ctx_ruling", group="O", ref="甲", machine="甲")) == "unknown"
    assert b.reason_of(_e("confirm", via="newchar_review")) == "lib_missing"
    assert b.reason_of(_e("confirm", source="sheldon 异体对第二批")) == "variant_pair"
    assert b.reason_of(_e("confirm", via="doubt:occluded")) == "unknown"
    assert b.reason_of(_e("vision_check", v="ok")) == "unknown"


def test_plan_file_keeps_format(tmp_path):
    a = _e("confirm", via="newchar_review", v="甲")
    c = _e("cutline", y=3)
    d = _e("confirm", v="乙", pending_reason="hard_pair")
    f = tmp_path / "x.jsonl"
    f.write_text("\n".join([json.dumps(a, ensure_ascii=False, sort_keys=True), json.dumps(c, ensure_ascii=False),
                            json.dumps(d, ensure_ascii=False)]) + "\n", encoding="utf-8")
    lines, n, why = b.plan_file(f)
    assert why is None and sum(n.values()) == 1
    assert json.loads(lines[0])["payload"]["pending_reason"] == "lib_missing"
    assert lines[0] == json.dumps(json.loads(lines[0]), ensure_ascii=False, sort_keys=True)
    assert lines[1:] == f.read_text(encoding="utf-8").splitlines()[1:]          # 别的事件、已有原因的不动
    f.write_text(json.dumps(a, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")   # 认不出写法：整个文件不动
    _, n, why = b.plan_file(f)
    assert why and not n
