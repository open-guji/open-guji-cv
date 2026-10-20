"""`guji pipeline --isolate-steps`（GUJI-555）：每个 Step 一个子进程，步序与产物落点不变。

数据全是造的／冻结的：`ws` fixture（tests/fixtures/workspace 的可写副本）。
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from open_guji_cv import cli_v2


FIXTURE_WS = Path(__file__).parent / "fixtures" / "workspace"


def _copy_fixture_workspace(dst: Path) -> Path:
    """第二份可写工作区（`ws` fixture 只给一份）：册配置、语料复制，原图复制（几百 KB）。"""
    for name in ("books", "corpus", "raw"):
        shutil.copytree(FIXTURE_WS / name, dst / name)
    return dst


def _args(**kw):
    base = dict(book="keben", pipeline="p1", pages="all", force=True, stop_on_error=False,
                params=None, jobs=2, allow_sample_db=False)
    base.update(kw)
    return SimpleNamespace(**base)


def test_argv_translates_one_step_to_guji_step():
    argv = cli_v2.isolated_step_argv(_args(params='{"a": {"b": 1}}', allow_sample_db=True,
                                           stop_on_error=True), "row_segment", "/w")
    assert argv[:4] == [sys.executable, "-m", "open_guji_cv", "step"]
    assert argv[4:6] == ["row_segment", "keben"]
    assert argv[argv.index("--pipeline") + 1] == "p1"
    assert argv[argv.index("--pages") + 1] == "all"
    assert argv[argv.index("-w") + 1] == "/w"
    assert argv[argv.index("--jobs") + 1] == "2"
    assert argv[argv.index("--params") + 1] == '{"a": {"b": 1}}'
    assert {"--force", "--stop-on-error", "--allow-sample-db"} <= set(argv)
    assert "--json" not in argv and "--wait" not in argv
    assert "--no-isolate-steps" in argv           # 子进程只跑一步，不能再隔离（否则自己起自己）


def test_argv_omits_flags_that_are_off():
    argv = cli_v2.isolated_step_argv(_args(force=False, jobs=None), "a", "/w")
    assert not {"--force", "--stop-on-error", "--params", "--jobs", "--allow-sample-db"} & set(argv)


def _fake_run(calls, fail_on=None):
    """`subprocess.Popen` 的替身：记下跑了哪一步，`wait()` 返回预设的返回码。"""
    def popen(argv, env=None, **_):
        calls.append((argv[4], env))
        code = 7 if argv[4] == fail_on else 0
        return SimpleNamespace(wait=lambda: code, poll=lambda: code, returncode=code)
    return popen


def test_steps_run_in_order_one_process_each(monkeypatch):
    monkeypatch.setenv("GUJI_WORKSPACE", "/w")
    calls: list = []
    monkeypatch.setattr(subprocess, "Popen", _fake_run(calls))
    rc = cli_v2._run_steps_isolated(_args(), ["page_survey", "border_detect", "cell_shrink"])
    assert rc == 0
    assert [c[0] for c in calls] == ["page_survey", "border_detect", "cell_shrink"]
    for _sid, env in calls:                       # 父进程持锁，子进程不抢；不再进批处理切片
        assert env["GUJI_NO_RUN_LOCK"] == "1" and env["GUJI_NO_BATCH_SLICE"] == "1"


def test_any_nonzero_step_stops_and_propagates(monkeypatch):
    """子进程非零 = 带 --stop-on-error 的失败，或整步崩了：都不接着用缺了的上游跑下游（2026-10-20）。"""
    monkeypatch.setenv("GUJI_WORKSPACE", "/w")
    calls: list = []
    monkeypatch.setattr(subprocess, "Popen", _fake_run(calls, fail_on="b"))
    for stop in (False, True):
        calls.clear()
        assert cli_v2._run_steps_isolated(_args(stop_on_error=stop), ["a", "b", "c"]) == 7
        assert [c[0] for c in calls] == ["a", "b"]


def test_pipeline_isolates_by_default_but_not_single_step_or_json(ws, monkeypatch):
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.pipeline import default_pipeline_id
    pid = default_pipeline_id(load_book("keben"))
    seen: list = []
    monkeypatch.setattr(cli_v2, "_run_steps_isolated", lambda args, steps: seen.append(list(steps)) or 0)
    with pytest.raises(SystemExit) as e:
        cli_v2.main(["pipeline", pid, "keben", "-w", str(ws), "--pages", "1", "--to", "column_warp"])
    assert e.value.code == 0 and seen and len(seen[0]) > 1
    seen.clear()
    for argv in (["step", "page_survey", "keben", "--pipeline", pid],
                 ["pipeline", pid, "keben", "--to", "column_warp", "--json"],
                 ["pipeline", pid, "keben", "--to", "column_warp", "--no-isolate-steps"]):
        with pytest.raises(SystemExit):
            cli_v2.main([*argv, "-w", str(ws), "--pages", "1"])
    assert seen == []


def test_crashed_step_makes_pipeline_exit_nonzero(monkeypatch, ws):
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.pipeline import default_pipeline_id
    pid = default_pipeline_id(load_book("keben"))
    monkeypatch.setattr(cli_v2, "_run_steps_isolated", lambda args, steps: 1)
    with pytest.raises(SystemExit) as e:
        cli_v2.main(["pipeline", pid, "keben", "-w", str(ws), "--pages", "1", "--to", "column_warp"])
    assert e.value.code == 1


def test_json_is_rejected_with_isolate_steps(ws, capsys):
    from open_guji_cv.core.pipeline import default_pipeline_id
    from open_guji_cv.core.book import load_book
    pid = default_pipeline_id(load_book("keben"))
    with pytest.raises(SystemExit) as e:
        cli_v2.main(["pipeline", pid, "keben", "-w", str(ws), "--pages", "1", "--to", "page_survey",
                     "--isolate-steps", "--json"])
    assert e.value.code == 2


def _products(root):
    out = {}
    for p in sorted((root / "products").rglob("*.json")):
        if p.name.startswith("_"):                # _raw_index 记原图 mtime，两份工作区必然不同
            continue
        out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def test_isolated_run_gives_same_products_as_single_process(ws, tmp_path, monkeypatch):
    """真子进程：前三步（含闸）在两个独立工作区各跑一遍，产物文件集与内容逐字节相同。"""
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.pipeline import default_pipeline_id
    pid = default_pipeline_id(load_book("keben"))
    ws2 = _copy_fixture_workspace(tmp_path / "ws2")
    common = [pid, "keben", "--pages", "1", "--from", "page_survey", "--to", "column_warp", "--force"]

    monkeypatch.setenv("GUJI_WORKSPACE", str(ws))
    with pytest.raises(SystemExit) as e:
        cli_v2.main(["pipeline", *common, "-w", str(ws), "--no-isolate-steps"])
    assert e.value.code == 0
    monkeypatch.setenv("GUJI_WORKSPACE", str(ws2))
    with pytest.raises(SystemExit) as e:
        cli_v2.main(["pipeline", *common, "-w", str(ws2), "--isolate-steps"])
    assert e.value.code == 0

    single, isolated = _products(ws), _products(ws2)
    assert single, "单进程没产出产物，测试没测到东西"
    assert single == isolated


def test_sigterm_is_forwarded_to_the_running_step(ws, tmp_path, monkeypatch):
    """控制台取消工单只 terminate 父进程：正在跑的那一步要跟着停，不能留成孤儿接着写产物。"""
    import os
    import signal
    import time
    script = tmp_path / "parent.py"
    marker = tmp_path / "child.pid"
    script.write_text(f"""
import subprocess, sys
from types import SimpleNamespace
from open_guji_cv import cli_v2
cli_v2.isolated_step_argv = lambda args, sid, ws: [sys.executable, "-c",
    "import os, time; open(r'{marker}', 'w').write(str(os.getpid())); time.sleep(60)"]
sys.exit(cli_v2._run_steps_isolated(SimpleNamespace(), ["a", "b"]))
""", encoding="utf-8")
    env = {**os.environ, "GUJI_WORKSPACE": str(ws)}
    parent = subprocess.Popen([sys.executable, str(script)], env=env)
    for _ in range(200):
        if marker.exists() and marker.read_text():
            break
        time.sleep(0.05)
    child = int(marker.read_text())
    parent.send_signal(signal.SIGTERM)
    assert parent.wait(timeout=20) == 128 + signal.SIGTERM
    time.sleep(0.2)
    with pytest.raises(OSError):
        os.kill(child, 0)                          # 子进程已经不在了
