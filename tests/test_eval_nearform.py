"""eval_nearform 的报表口径（自造数据，不碰库与模型）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import eval_nearform as en  # noqa: E402


def _it(i, gold, split="dev", src="人裁"):
    return dict(pair="淸清", a="淸", b="清", id=i, gold=gold, split=split, label_src=src)


def test_report_counts_pair_confusion_and_splits():
    items = [_it("001:1:1:1", "淸"), _it("002:1:1:2", "淸", "test"), _it("003:1:1:3", "清"),
             _it("005:1:1:4", "千", src="文意")]
    top1 = ["淸", "清", "水", "干"]
    pair_ok = [True, False, True, None]
    res, pairs, flips = en.report(items, top1, pair_ok)
    a = res["全部|全部"]
    assert a["n"] == 3 and a["pair_confuse"] == 1 and a["top1"] == 33.33 and a["two_way"] == 66.67
    assert res["全部|test"]["pair_confuse"] == 1 and res["全部|dev"]["pair_confuse"] == 0
    assert flips["全部|对家误认"] == ["淸清|002:1:1:2"]
    assert res["文意三对|全部"]["n"] == 1
    assert pairs["淸清"]["n"] == 4
