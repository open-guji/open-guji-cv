"""scripts/check_fp_change.py 的纯函数部分（比指纹、书面放行口径）；起 worktree 算真指纹的部分由 CI 工作流自己跑。"""
import importlib.util
from pathlib import Path

_p = Path(__file__).resolve().parents[1] / "scripts" / "check_fp_change.py"
_spec = importlib.util.spec_from_file_location("check_fp_change", _p)
FC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(FC)


def test_diff_lists_changed_added_removed():
    base = {"a": "1", "b": "2", "c": "3"}
    head = {"a": "1", "b": "9", "d": "4"}
    assert FC.diff(base, head) == [("b", "2", "9"), ("d", None, "4"), ("c", "3", None)]
    assert FC.diff(base, dict(base)) == []


def test_allow_needs_explicit_note():
    assert FC.ALLOW.search("殿本 patch 线：v0.7.97＋…\n指纹变更：seed_admit 起过期，随统一重跑")
    assert FC.ALLOW.search("随 #1813 统一重跑，不与旧产物混批")
    assert not FC.ALLOW.search("殿本 patch 线：v0.7.97＋裁定键三件＋#1838 ruling_anchor_loose")
    assert not FC.ALLOW.search("PATCH（缺省关，产物逐字节不变，code_equiv 登记）")
