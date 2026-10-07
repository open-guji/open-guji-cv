# -*- coding: utf-8 -*-
"""scripts/zhengli/zl.py 的机器化整理脚本：自造数据，不碰真书（Z1 #476 七条）。"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ZL_PATH = Path(__file__).resolve().parents[1] / "scripts" / "zhengli" / "zl.py"
spec = importlib.util.spec_from_file_location("zl_under_test", ZL_PATH)
zl = importlib.util.module_from_spec(spec)
sys.modules["zl_under_test"] = zl
spec.loader.exec_module(zl)


def make_ctx(tmp_path, monkeypatch, book="vol07"):
    monkeypatch.setenv("ZL_STATE", str(tmp_path / "state"))
    monkeypatch.setenv("ZL_NO_REEXEC", "1")
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    return zl.Ctx(SimpleNamespace(book=book, ws=str(ws), jobs=1, snap=None))


# ① st_ws 认仓内子目录 / 默认 URL
def test_ws_default_url_is_open_guji_org():
    assert zl.WS_URL == "https://github.com/open-guji/guji-workspace"


def test_in_git_repo_accepts_subdirectory(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path / "repo")], check=True)
    sub = tmp_path / "repo" / "a" / "b"
    sub.mkdir(parents=True)
    assert zl.in_git_repo(sub) and zl.in_git_repo(tmp_path / "repo")
    assert not zl.in_git_repo(tmp_path / "nope")
    plain = tmp_path / "plain"
    plain.mkdir()
    assert not zl.in_git_repo(plain)


def test_st_ws_skips_clone_inside_repo(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path / "repo")], check=True)
    subprocess.run(["git", "-C", str(tmp_path / "repo"), "-c", "user.email=a@b", "-c", "user.name=n",
                    "commit", "-q", "--allow-empty", "-m", "x"], check=True)
    ctx = make_ctx(tmp_path, monkeypatch)
    ctx.ws = tmp_path / "repo" / "ws_sub"
    ctx.ws.mkdir()
    ctx.reports = ctx.ws / "reports" / ctx.book
    calls = []
    real = zl.sh

    def spy(c, cmd, **kw):
        calls.append(list(map(str, cmd)))
        if cmd[:2] == ["git", "rev-parse"]:
            return 0, "deadbeef\n"
        return 0, ""
    monkeypatch.setattr(zl, "sh", spy)
    zl.st_ws(ctx)
    assert not any("clone" in c for c in calls)
    assert ctx.st["pins"]["ws"] == "deadbeef"


# ② sh 不截断 + status --json 解析 + 崩溃写 NEXT
def test_sh_tail_none_returns_full_output(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path, monkeypatch)
    big = "x" * 9000
    rc, out = zl.sh(ctx, [sys.executable, "-c", f"print('{big}')"], tail=None)
    assert rc == 0 and len(out) > 8000
    rc, out = zl.sh(ctx, [sys.executable, "-c", f"print('{big}')"])
    assert len(out) == 4000


def test_status_json_big_with_log_noise(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path, monkeypatch)
    payload = {"closure_gaps": 3, "pages": [{"p": i, "note": "字" * 50} for i in range(400)]}
    script = "import json;print('日志 {not json}');print(json.dumps(%r, ensure_ascii=False))" % payload
    monkeypatch.setattr(ctx, "guji", lambda *a: [sys.executable, "-c", script])
    js = zl.status_json(ctx)
    assert js["closure_gaps"] == 3 and len(js["pages"]) == 400


def test_status_json_unparsable_writes_next(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path, monkeypatch)
    monkeypatch.setattr(ctx, "guji", lambda *a: [sys.executable, "-c", "print('boom')"])
    with pytest.raises(zl.Stop):
        zl.status_json(ctx)
    assert "status --json 解析失败" in (ctx.reports / "NEXT.md").read_text(encoding="utf-8")


def test_run_crash_writes_next_and_returns_1(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path, monkeypatch)

    def boom(c):
        raise KeyError("意外")
    monkeypatch.setattr(zl, "STAGES", [("boom", boom, "x")])
    a = SimpleNamespace(book="vol07", ws=str(ctx.ws), jobs=1, snap=None, bg=False, only=None, from_=None, to=None, redo=None)
    assert zl.cmd_run(a) == 1
    nxt = (ctx.reports / "NEXT.md").read_text(encoding="utf-8")
    assert "崩溃" in nxt and "KeyError" in nxt


# ③ GUJI_PRODUCTS_DIR
def test_products_dir_env(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path, monkeypatch)
    monkeypatch.delenv("GUJI_PRODUCTS_DIR", raising=False)
    assert zl.products_dir(ctx) == ctx.ws / "products"
    monkeypatch.setenv("GUJI_PRODUCTS_DIR", str(tmp_path / "snap"))
    assert zl.products_dir(ctx) == tmp_path / "snap"


# ④ yaml 只补开关
YAML = """# 书说明
book: vol07   # 册号
page_split: true
params:
  # 注释留着
  seed_admit:
    rare_ref: false  # 旧值
    shadow_conf: 0.5
    custom_keep: 1
  other: 2
tail: 9
"""


def test_patch_yaml_minimal_diff():
    new, ch = zl.patch_yaml_text(YAML, zl.STD_SEED_ADMIT)
    assert new is not None
    old_lines = YAML.splitlines()
    removed = [l for l in old_lines if l not in new.splitlines()]
    assert removed == ["    rare_ref: false  # 旧值", "    shadow_conf: 0.5"]   # 只有被改的两行
    assert "    rare_ref: true  # 旧值" in new and "    shadow_conf: 0.8" in new
    assert "# 书说明" in new and "    custom_keep: 1" in new and "tail: 9" in new
    assert "iron_gate: true" in new and ch["iron_gate"] == (None, True)
    import yaml
    d = yaml.safe_load(new)
    assert d["params"]["other"] == 2 and d["params"]["seed_admit"]["ji_yi_si_review"] is True
    assert all(d["params"]["seed_admit"][k] == v for k, v in zl.STD_SEED_ADMIT.items())
    # 幂等
    again, ch2 = zl.patch_yaml_text(new, zl.STD_SEED_ADMIT)
    assert again == new and ch2 == {}


def test_patch_yaml_no_params_and_flow_fallback():
    new, ch = zl.patch_yaml_text("book: v\n", zl.STD_SEED_ADMIT)
    assert new.startswith("book: v\n") and "params:\n  seed_admit:\n    ji_yi_si_review: true" in new
    bad, why = zl.patch_yaml_text("params: {seed_admit: {a: 1}}\n", zl.STD_SEED_ADMIT)
    assert bad is None and "流式" in why
    bad, why = zl.patch_yaml_text("params:\n  seed_admit: {a: 1}\n", zl.STD_SEED_ADMIT)
    assert bad is None


def test_st_yaml_writes_only_patch(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path, monkeypatch)
    (ctx.ws / "books").mkdir()
    f = ctx.ws / "books" / "vol07.yaml"
    f.write_bytes(YAML.encode("utf-8"))
    zl.st_yaml(ctx)
    assert "# 书说明" in f.read_text(encoding="utf-8") and "custom_keep: 1" in f.read_text(encoding="utf-8")


def test_ensure_venv_python_disabled_by_env(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path, monkeypatch)
    ctx.venv_py = "/nonexistent/python"
    zl.ensure_venv_python(ctx)       # ZL_NO_REEXEC=1 → 不 exec


# ⑤ snap-pack 跳过
def test_snap_pack_cloud_is_skipped_not_ok(tmp_path, monkeypatch):
    ctx = make_ctx(tmp_path, monkeypatch)
    monkeypatch.setenv("ZL_CLOUD", "1")
    with pytest.raises(zl.Skip):
        zl.st_snap_pack(ctx)
    monkeypatch.setattr(zl, "STAGES", [("snap-pack", zl.st_snap_pack, "x"), ("next", lambda c: None, "y")])
    a = SimpleNamespace(book="vol07", ws=str(ctx.ws), jobs=1, snap=None, bg=False, only=None, from_=None, to=None, redo=None)
    assert zl.cmd_run(a) == 0                      # 跳过不拦后面的步
    st = json.loads(ctx.state_f.read_text(encoding="utf-8"))["stages"]
    assert not st["snap-pack"].get("ok") and st["snap-pack"]["skipped"] and st["next"]["ok"]
    assert "已跳过" in ctx.log_f.read_text(encoding="utf-8")


# ⑥ 联系页
def test_parse_cell_id():
    assert zl.parse_cell_id("vol06:12:3:5") == (12, 3, 5, "")
    assert zl.parse_cell_id("vol06:12:3:5a") == (12, 3, 5, "a")
    assert zl.parse_cell_id("garbage") is None


def test_contact_window_one_cell_each_side():
    boxes = [(0, 10 + 40 * i, 30, 40 + 40 * i) for i in range(6)]
    y0, y1 = zl.contact_window(boxes, 2, 1, pad=0)
    assert (y0, y1) == (50, 160)                    # 第 1~3 格
    assert zl.contact_window(boxes, 0, 1, pad=0) == (10, 80)   # 首格上无邻
    assert zl.contact_window(boxes, 5, 1, pad=4, height=300)[1] == 244


def test_contact_rows_only_real_tier():
    rows = zl.contact_rows({"rows": [{"id": "a", "tier": "real"}, {"id": "b", "tier": "variant"}]})
    assert [r["id"] for r in rows] == ["a"]


def test_render_and_compose_tiles():
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    img = np.full((400, 60), 200, np.uint8)
    t = [zl.render_contact_tile(img, 20, 140, (5, 50, 55, 100), n, tile_h=120) for n in (1, 2, 3)]
    assert all(x.shape == (120, 60, 3) for x in t)
    sheet = zl.compose_contact(t, per_row=2)
    assert sheet.shape[0] == (120 + 6) * 2 + 6 and sheet.shape[2] == 3


def test_contact_md_marks_failed_and_sheet():
    md = zl.contact_md("v", [{"n": 1, "id": "v:1:1:1", "char": "未", "witness": {"W": "末"}, "ctx": "甲【未】乙", "ok": True, "sheet_idx": 0},
                             {"n": 2, "id": "v:1:1:2", "char": "", "ok": False, "why": "没有这一格的字框"}], ["v.联系页01.png"])
    assert "v.联系页01.png" in md and "⚠ 没有这一格的字框" in md
