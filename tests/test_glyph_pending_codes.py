"""待收字登记表（research/a24/pua_src/glyph_pending_codes.json）的格式守卫：每项都是「来源:U+XXXX」，
来源只能是已知的两套码，且不重复前缀（曾写成 daizhige:daizhige:U+…，和回查出的码永远对不上）。"""
import json
import re
from pathlib import Path

REG = Path(__file__).resolve().parents[1] / "research" / "a24" / "pua_src" / "glyph_pending_codes.json"
ITEM = re.compile(r"^(daizhige|siku-qiefen-v2):U\+[0-9A-F]{4,6}$")


def test_every_registry_item_parses_as_source_and_codepoint():
    codes = json.loads(REG.read_text(encoding="utf-8"))["codes"]
    assert codes and len(codes) == len(set(codes))
    bad = [c for c in codes if not ITEM.match(c)]
    assert not bad, bad


def test_daizhige_codes_match_resolver_format():
    """回查出的码写法是 `daizhige:U+XXXX`（utils.daizhige.pua_codes）：登记表里的殆知阁码得是同一写法。"""
    from open_guji_cv.utils.daizhige import PUA_SOURCE
    codes = json.loads(REG.read_text(encoding="utf-8"))["codes"]
    dz = [c for c in codes if c.startswith(PUA_SOURCE + ":")]
    assert dz and all(c.count(":") == 1 for c in dz)
