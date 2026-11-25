"""scripts/char_cov_profile.py 字表聚合（原 tests/test_seed_admit_solo_adapt.py；solo_adapt 通道 2026-11-24 搬进全唐文书仓，字表脚本留 cv）。"""


def test_builder_aggregate():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("ccp", Path(__file__).resolve().parents[1] / "scripts" / "char_cov_profile.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    recs = [{"c": "治", "cands": [["治", 0.98], ["洽", 0.99]]}] + [{"c": "治", "cands": [["治", 0.97 + i / 1000]]} for i in range(5)]
    out = mod.aggregate(recs)
    assert out["schema"] == "char_cov_profile/1" and out["prof"]["治"]["n"] == 6
    assert ["治", "洽"] in out["risk"] and out["cross"]["治|洽"] == 0.99
