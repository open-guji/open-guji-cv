"""放行字落册码位的例外（`seed_admit._codepoint_exempt`）：按刻形拆判的字对，人裁与字组判出的刻形不被码位归一改回。

vol04:197:7:3 人裁 變，工作区 `codepoints` 變→𠮓 把它改回 𠮓（A32 10-25 报）；bian 组判出的 變 也一样。"""
from types import SimpleNamespace

from open_guji_cv.products.kinds.recog import AdmitRec
from open_guji_cv.steps.seed_admit import _codepoint_exempt

BOOK = SimpleNamespace(canonical_char=lambda c: {"變": "𠮓", "宮": "宫", "內": "内"}.get(c, c))


def _rec(char, channel="match_replace", provenance="match", group=None):
    return AdmitRec(id="vol04:197:7:3", slot=3, admit=True, char=char, channel=channel, provenance=provenance,
                    evidence={"group": group} if group else {})


def test_human_shape_kept_when_pair_split_by_shape_group():
    assert _codepoint_exempt(_rec("變", "human", "human"), BOOK)


def test_group_pick_kept():
    assert _codepoint_exempt(_rec("變", group={"id": "bian", "pick": "變", "decision": "keep"}), BOOK)
    assert _codepoint_exempt(_rec("變", "group_flow", "context", {"id": "bian", "pick": "變", "decision": "fix"}), BOOK)


def test_group_abstain_falls_back_to_codepoint():
    assert not _codepoint_exempt(_rec("變", group={"id": "bian", "pick": None, "decision": "keep"}), BOOK)
    assert not _codepoint_exempt(_rec("變"), BOOK)


def test_pairs_without_shape_split_still_unified():
    # 內内 真归一，人裁也归一；宫宮 在 guan 组同一族（族内按库形最近），宮→宫 暂归一照旧
    assert not _codepoint_exempt(_rec("內", "human", "human"), BOOK)
    assert not _codepoint_exempt(_rec("宮", "human", "human"), BOOK)
    assert not _codepoint_exempt(_rec("宮", group={"id": "guan", "pick": "宮", "decision": "keep"}), BOOK)


def test_target_form_untouched():
    assert not _codepoint_exempt(_rec("𠮓", "human", "human"), BOOK)
