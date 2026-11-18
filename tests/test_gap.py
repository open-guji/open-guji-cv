"""整理本缺字占位符：〓（私用码）与 ▣（以图代字）语义一致、可区分（A23 2026-11-16，utils/gap.py）。"""
import json
import sys
from pathlib import Path

import pytest

from open_guji_cv.groups import flow
from open_guji_cv.steps import seed_admit as sa
from open_guji_cv.steps.align_ref_coord import is_text_char
from open_guji_cv.utils.gap import GAP_CHARS, GAP_IMAGE, GAP_PUA, gap_kind, is_gap

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import dzg_placeholders as P  # noqa: E402


def test_gap_basics():
    assert GAP_CHARS == ("〓", "▣")
    assert is_gap("〓") and is_gap("▣")
    assert not is_gap("") and not is_gap(None) and not is_gap("字") and not is_gap("□") and not is_gap("〓〓")
    assert gap_kind("〓") == "pua" and gap_kind("▣") == "image" and gap_kind("字") is None


@pytest.mark.parametrize("g", ["〓", "▣"])
def test_gap_is_a_grid_slot(g):
    # 缺这条 ▣ 会被当标点丢掉，整列错一格（vol20 p133 列 5 同类问题）
    assert is_text_char(g)


@pytest.mark.parametrize("g", ["〓", "▣"])
def test_gap_not_a_witness_in_seed_admit(g):
    assert sa._ref_placeholder_norm(g) == g
    assert flow.GAPS == GAP_CHARS


def test_flow_gap_constant_still_pua():
    assert flow.GAP == GAP_PUA and GAP_IMAGE in flow.GAPS


def _col(no, *runs):
    return {"no": no, "runs": list(runs)}


def _write_ws(tmp_path, glyphs):
    ws = tmp_path / "ws"
    (ws / "corpus" / "daizhige").mkdir(parents=True)
    (ws / "config" / "pua").mkdir(parents=True)
    rec = {"id": "0001-0001", "page": "1-1a", "cover": False, "roll": {"name": "卷一"}, "book": {"id": 1},
           "pua_map": {}, "glyphs": glyphs,
           "cols": [_col(0, {"t": "text", "start": 0, "s": "古文作ခ又與"})]}
    (ws / "corpus" / "daizhige" / "0001.jsonl").write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    (ws / "corpus" / "siku_daizhige.txt").write_text(
        "# daizhige header 〓\n#@ 0001-0001 1-1a h0\n古文作〓又〓與〓\n", encoding="utf-8")
    (ws / "config" / "pua" / "pua_table.jsonl").write_text(
        json.dumps({"code": "daizhige:U+E001", "verdict": "char", "char": "字", "nearest": True}) + "\n", encoding="utf-8")
    return ws


def test_placeholders_split_kinds(tmp_path):
    ws = _write_ws(tmp_path, {"U+1001": ["img/glyphs/0001-1.png", 1, 2, 30, 40]})
    out = tmp_path / "out"
    st = P.run(ws, ws / "config" / "pua" / "pua_table.jsonl", out)
    txt = (out / "siku_daizhige.new.txt").read_text(encoding="utf-8").split("\n")
    # 以图代字→▣；码表定字的私用码→换字；无码表行的私用码仍 〓；行数、列字数不变
    assert txt[2] == "古文作▣又字與〓"
    assert st["新▣"] == 1 and st["新〓"] == 1 and st["pua:换字"] == 1 and st["pua:无码表行"] == 1
    assert st["行数相同"] and st["逐行字数相同"]
    slots = [json.loads(x) for x in (out / "slots.jsonl").read_text(encoding="utf-8").splitlines()]
    kinds = [s["kind"] for s in slots]
    assert kinds == ["image", "pua", "pua"]
    assert slots[0]["quote"] is True and slots[0]["img"]["src"] == "img/glyphs/0001-1.png"
    assert slots[1]["replaced"] and slots[1]["table"]["nearest"] and slots[1]["raw"] == "U+E001"
    assert slots[2]["action"] == "无码表行"


def test_placeholders_tolerates_source_glyph_edits(tmp_path):
    # 源文之后改了别的字面（蘊→蕴），只要 〓 位置一致就按位换，其余保持现网
    ws = _write_ws(tmp_path, {"U+1001": ["a.png", 0, 0, 1, 1]})
    rec = json.loads((ws / "corpus/daizhige/0001.jsonl").read_text(encoding="utf-8"))
    rec["cols"][0]["runs"][0]["s"] = "古文作ခ叉與"   # 又→叉
    (ws / "corpus/daizhige/0001.jsonl").write_text(json.dumps(rec, ensure_ascii=False) + "\n", encoding="utf-8")
    out = tmp_path / "out"
    st = P.run(ws, ws / "config/pua/pua_table.jsonl", out)
    assert st["源文改字但〓位一致"] == 1
    assert (out / "siku_daizhige.new.txt").read_text(encoding="utf-8").split("\n")[2] == "古文作▣又字與〓"
