"""L1 文意规则的册外回测（A24 2026-10-24）：整理本挖出的搭配规则在 vol11–20 上冲突的已下线，这里钉住
几个在新册里真实出现、旧规则判反的搭配，免得以后重挖时又加回来。例句取自殿本 vol11–20 整理本。"""
import pytest

from open_guji_cv.groups.ctx_l1 import CtxL1Backend
from open_guji_cv.groups.flow import rules_path
from open_guji_cv.groups.registry import GROUPS


def _decide(g, text):
    left, right = text.split("◎")
    return CtxL1Backend(rules_path(g), GROUPS[g].members).decide(left, right)


@pytest.mark.parametrize("g, text, wrong", [
    ("yr", "此聖人敷治之原每一月分爲◎章其曰", "二"),          # vol11:21:8:13，刻「一」
    ("yr", "禮記之屬四十一部五百七十◎卷内無", "二"),          # vol12:154:3:17
    ("yr", "淺近蓋課𫎇之作也孝經集解◎卷江採", "二"),          # vol15:142:4:5
    ("yr", "釋避煬帝諱改名博雅故至今◎名並稱", "一"),          # vol20:25:8:4，刻「二」
    ("em", "今考雜記遣車疏布輤四◎有章注輤其", "而"),          # vol12:123:5:15，刻「面」，旧规则错放成而
    ("mz", "法也以首率一◎之又以四率八乘之", "目"),            # vol19:47:1:13，刻「自」
    ("wj", "亦奇齡之所最信也荀子三年◎篇明出", "間"),          # vol12:74:4:4，三年問（篇名）
    ("wj", "答門人李塨問南北郊分祀及◎有禘無祫", "間"),        # vol11:78:6:13
    ("wj", "重今輕古輕今重四目後爲雜◎篇凡三十", "間"),        # vol12:85:2:19
    ("wj", "子宗潢所編本名四書疑義有◎有答奇齡", "間"),        # vol18:73:6:14
])
def test_heldout_collocations_not_decided_wrong(g, text, wrong):
    ch, _why, _ids = _decide(g, text)
    assert ch != wrong


def test_wj_still_gives_nianjian():
    assert _decide("wj", "嘉靖年◎刻本")[0] == "間"


def test_yr_keeps_tianyige_rule():
    # 天一閣藏：没冲突的那条留着
    assert _decide("yr", "范氏天◎閣藏本")[0] == "一"
