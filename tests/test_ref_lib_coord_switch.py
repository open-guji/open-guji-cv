"""`ref_lib_coord` 书级开关（A24 2026-11-03）：缺省关、不进 dump；开了只用自己的 cov／gap 门槛。"""
from open_guji_cv.steps.seed_admit import SeedAdmitParams, ref_lib_coord_decide


def test_default_off_and_not_dumped():
    d = SeedAdmitParams().model_dump()
    assert not any(k.startswith("ref_lib_coord") for k in d)
    on = SeedAdmitParams(ref_lib_coord=True).model_dump()
    assert on["ref_lib_coord"] is True and on["ref_lib_coord_cov"] == 0.96


def test_decide_strict_thresholds():
    p = SeedAdmitParams(ref_lib_coord=True)
    kw = dict(char="兼", ref="兼", verdict="unsure", guard=None, doubts=["库 unsure(cov=0.98)", "near_form"],
              evidence={}, semantic=lambda c: c, cov_min=p.ref_lib_coord_cov, gap_min=p.ref_lib_coord_gap)
    assert ref_lib_coord_decide(cands=[("兼", 0.983), ("末", 0.866)], **kw)
    assert not ref_lib_coord_decide(cands=[("兼", 0.95), ("末", 0.7)], **kw)           # cov 不够
    assert not ref_lib_coord_decide(cands=[("兼", 0.983), ("末", 0.978)], **kw)        # 对手紧咬
