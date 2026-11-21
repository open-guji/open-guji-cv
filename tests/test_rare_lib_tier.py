"""5-b 库字档（册配置 `font.charset.lib_chars`，缺省关）：本书字形库里人裁过、基集里没有的字另开一档进候选。
库和检索都自己造，不读模型文件。"""
from __future__ import annotations

import json

import numpy as np

from helpers import make_book
from open_guji_cv.clustering import charset_spec as CS
from open_guji_cv.clustering import cnn_candidates as CC
from open_guji_cv.clustering import rare_panel as RP
from open_guji_cv.core import engine as E
from open_guji_cv.steps.rare_candidates import RareCandidatesStep


def _store(tmp_path, rows):
    """造一个 glyph_store：rows = [(实例号, 字, label_status)]，每例一张小图。"""
    import cv2
    d = tmp_path / "glyph_store"
    (d / "instances").mkdir(parents=True)
    (d / "patches").mkdir()
    with open(d / "instances" / "v2.jsonl", "w", encoding="utf-8") as f:
        for iid, ch, st in rows:
            f.write(json.dumps({"instance_id": iid, "label": ch, "label_status": st}, ensure_ascii=False) + "\n")
            cv2.imwrite(str(d / "patches" / (iid.replace(":", "_") + ".png")), np.full((8, 8), 255, np.uint8))
    return d


def test_spec_defaults_off():
    assert CS.spec_for_book(None)["lib_chars"] is False


def test_real_chars_takes_human_single_chars_only(tmp_path):
    d = _store(tmp_path, [("v2:001:1:1:1", "𠋫", "human"), ("v2:001:1:1:2", "候", "human"),
                          ("v2:001:1:1:3", "𥳑", "auto"), ("v2:001:1:1:4", "左王", "human")])
    assert CC.real_chars((f"store:{d}",)) == frozenset("𠋫候")


def test_real_chars_follows_store_content(tmp_path):
    d = _store(tmp_path, [("v2:001:1:1:1", "𠋫", "human")])
    spec = (f"store:{d}",)
    assert CC.real_chars(spec) == frozenset("𠋫")
    with open(d / "instances" / "v2.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"instance_id": "v2:001:1:1:9", "label": "𥳑", "label_status": "human"},
                           ensure_ascii=False) + "\n")
    import cv2
    cv2.imwrite(str(d / "patches" / "v2_001_1_1_9.png"), np.full((8, 8), 255, np.uint8))
    assert CC.real_chars(spec) == frozenset("𠋫𥳑")


def test_lib_tier_is_library_minus_base(tmp_path):
    d = _store(tmp_path, [("v2:001:1:1:1", "𠋫", "human"), ("v2:001:1:1:2", "候", "human"),
                          ("v2:001:1:1:3", "内", "human"), ("v2:001:1:1:4", "○", "human")])
    base = ("候", "內", "簡")
    got = RP.lib_tier(base, (False, (f"store:{d}",)))
    assert got == tuple(sorted("𠋫内"))          # 基集已有的、不是汉字的都不进
    assert RP.lib_tier(base, (False, (f"store:{d}",))) is got      # 元组身份稳定
    assert RP.lib_tier(base, None) == ()


def test_lib_tier_takes_base_chars_the_veto_would_drop(tmp_path):
    d = _store(tmp_path, [("v2:001:1:1:1", "无", "human"), ("v2:001:1:1:2", "候", "human")])
    base = ("候", "无", "無")
    rp = (False, (f"store:{d}",))
    assert RP.lib_tier(base, rp, None, "none") == ()
    assert RP.lib_tier(base, rp, None, "no-simplified") == ("无",)


class _FakeCnn:
    """只实现 `rare_for_batch` 用到的几个口：基集那次返回固定候选，库字档那次返回库里的字。"""
    available = True
    last_gw_prov: list = []
    last_real_prov: list = []

    def __init__(self, base_rows, lib_rows):
        self.base_rows, self.lib_rows, self.calls = base_rows, lib_rows, []

    def topk_batch(self, norms, cs, k=10):
        return [[] for _ in norms]

    def emb_topk_batch(self, norms, cs, k=10, real_proto=None, gw_enabled=None):
        self.calls.append(("base", real_proto))
        self.last_gw_prov = [{} for _ in norms]
        return [list(self.base_rows) for _ in norms]

    def emb_topk_batch_subset(self, norms, idx, cs, k=10, real_proto=None, gw_enabled=None, **_):
        self.calls.append(("subset", tuple(cs), real_proto, list(idx)))
        self.last_gw_prov = [{} for _ in idx]
        return [list(self.lib_rows) for _ in idx]


def _run(monkeypatch, tmp_path, lib_chars: bool, base_rows, lib_rows):
    d = _store(tmp_path, [("v2:001:1:1:1", "𠋫", "human"), ("v2:001:1:1:3", "内", "human")])
    fake = _FakeCnn(base_rows, lib_rows)
    monkeypatch.setattr(CC, "shared", lambda *a, **k: fake)
    monkeypatch.setattr(CC, "require_checkpoint", lambda cnn: None)
    spec = {"allow": "no-simplified", "escalate_threshold": 0.0, "lib_chars": lib_chars}
    monkeypatch.setattr(RP, "book_charsets", lambda book, corpus: (("候", "內", "倏"), (), spec))
    monkeypatch.setattr(RP, "book_font_editions", lambda book: [])
    img = np.full((64, 64), 255, np.uint8)
    img[20:40, 20:40] = 0
    hits = RP.rare_for_batch([img], 10, None, None, real_proto=(False, (f"store:{d}",)))
    return fake, [h["char"] for h in hits[0]]


def test_off_never_queries_library(monkeypatch, tmp_path):
    fake, chars = _run(monkeypatch, tmp_path, False, [("候", 0.95), ("倏", 0.90)], [("𠋫", 0.97)])
    assert [c[0] for c in fake.calls] == ["base"]
    assert chars[:2] == ["候", "倏"] and "𠋫" not in chars


def test_on_merges_library_chars_by_score(monkeypatch, tmp_path):
    fake, chars = _run(monkeypatch, tmp_path, True, [("候", 0.95), ("倏", 0.90)], [("𠋫", 0.93), ("内", 0.50)])
    kinds = [c[0] for c in fake.calls]
    assert kinds == ["base", "subset"]
    _, cs, real_proto, idx = fake.calls[1]
    assert cs == tuple(sorted("𠋫内")) and idx == [0]
    assert real_proto[0] is True                 # 刻例原型在这一档总是开着
    assert fake.calls[0][1][0] is False          # 基集那次仍照书的开关（这里是关）
    assert chars[:3] == ["候", "𠋫", "倏"]        # 按分数插在中间，基集内字的先后不变


def test_on_exempts_library_chars_from_simplified_veto(monkeypatch, tmp_path):
    _, chars = _run(monkeypatch, tmp_path, True, [("內", 0.95)], [("内", 0.96)])
    assert chars[:2] == ["内", "內"]


def test_fingerprint_key_only_when_on(tmp_path, monkeypatch):
    from open_guji_cv.core.engine import params_hash
    step = RareCandidatesStep()
    ph = params_hash(step.spec.params(), step.spec.soft_params, step.spec.path_params)
    base = E._self_payload(step, make_book(), ph)
    assert "lib_chars" not in base
    assert "lib_chars" not in E._self_payload(step, make_book(font={"charset": {"lib_chars": False}}), ph)

    d = _store(tmp_path, [("v2:001:1:1:1", "𠋫", "human")])
    font = {"charset": {"lib_chars": True}, "real_proto": {"stores": [str(d)]}}
    on = E._self_payload(step, make_book(font=font), ph)
    assert on["lib_chars"] not in ("", "none")
    with open(d / "instances" / "v2.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"instance_id": "v2:001:1:1:9", "label": "𥳑", "label_status": "human"},
                           ensure_ascii=False) + "\n")
    assert E._self_payload(step, make_book(font=font), ph)["lib_chars"] != on["lib_chars"]
