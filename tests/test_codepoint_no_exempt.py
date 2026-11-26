"""书级 `codepoint_no_exempt`：史記 sui/guanm/yinv/can 统一归一（Sheldon 11-26），各出口放行字都落册码位。"""
from open_guji_cv.steps import seed_admit as sa
from open_guji_cv.steps.seed_admit import SeedAdmitParams


class _B:
    def canonical_char(self, c):
        return {"嵗": "歲", "隂": "陰"}.get(c, c)


class _R:
    def __init__(self, char, channel, prov="match", ev=None):
        self.char, self.channel, self.provenance, self.evidence = char, channel, prov, ev or {}


def test_default_keeps_shape_exempt_for_human():
    assert sa._codepoint_exempt(_R("嵗", "human", "human"), _B())


def test_no_exempt_all_channels_fold():
    off = ("sui", "yinv")
    assert not sa._codepoint_exempt(_R("嵗", "human", "human"), _B(), off)
    assert not sa._codepoint_exempt(_R("嵗", "group_flow", ev={"group": {"id": "sui", "pick": "嵗"}}), _B(), off)
    assert not sa._codepoint_exempt(_R("隂", "match_ref"), _B(), off)


def test_param_default_not_in_dump():
    assert SeedAdmitParams(db_path="x").codepoint_no_exempt == ()
