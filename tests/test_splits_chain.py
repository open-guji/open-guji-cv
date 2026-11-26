"""`engine._collapse_splits`：前一条 SPLITS 合回的那一项按旧名记，后一条能把它当一块再合（CV4 2026-11-26，
全唐文书仓 k13 的 admit_lanes 先改名回 cv 缺省模块、再随 seed_admit 的拆分合回）。"""
import open_guji_cv.core.code_equiv as ce
import open_guji_cv.core.engine as eng


def test_rename_then_merge(monkeypatch):
    h = {"s": "hs", "p": "hp", "book.x": "hbx", "cv.x": "hcx"}
    monkeypatch.setattr(eng, "_module_source_hash", lambda m: h[m])
    monkeypatch.setattr(eng, "_fingerprint_name", lambda m: m)
    monkeypatch.setattr(ce, "SPLITS", {
        "cv.x": ("hcx", (("book.x", "hbx"),)),                         # 书仓这一版＝cv 缺省模块
        "s": ("OLD", (("s", "hs"), ("p", "hp"), ("cv.x", "hcx"))),       # 拆分合回
    })
    assert eng._collapse_splits(["s", "p", "book.x"]) == [("s", "OLD")]
    assert eng._collapse_splits(["s", "p", "cv.x"]) == [("s", "OLD")]
    h["book.x"] = "changed"                                             # 书仓改了：不合，照常过期
    assert eng._collapse_splits(["s", "p", "book.x"]) == [("s", "hs"), ("p", "hp"), ("book.x", "changed")]
