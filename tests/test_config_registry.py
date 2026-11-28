"""X7 守卫：cv config/ 下每个进仓文件都要在 config/registry.yaml 登记；每条登记都要管到文件。"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
SCOPES = ("通用", "历史", "待查")
PREFIXED = ("来自书:", "应归组:")


def _files() -> list[str]:
    out = []
    for p in CONFIG.rglob("*"):
        if not p.is_file() or "__pycache__" in p.parts or p.name == ".DS_Store":
            continue
        rel = p.relative_to(CONFIG).as_posix()
        if rel != "registry.yaml":
            out.append(rel)
    return sorted(out)


def _entries() -> list[dict]:
    return yaml.safe_load((CONFIG / "registry.yaml").read_text(encoding="utf-8"))["entries"]


def _hits(path: str, files: list[str]) -> list[str]:
    return [f for f in files if (f.startswith(path) if path.endswith("/") else f == path)]


def test_every_config_file_registered():
    files, paths = _files(), [e["path"] for e in _entries()]
    missing = [f for f in files if not any(_hits(p, [f]) for p in paths)]
    assert not missing, f"config/ 下这些文件没在 config/registry.yaml 登记：{missing[:10]}"


def test_every_entry_matches_and_is_well_formed():
    files = _files()
    seen = set()
    for e in _entries():
        p = e["path"]
        assert p not in seen, f"重复登记 {p}"
        seen.add(p)
        assert _hits(p, files), f"登记了 {p} 但 config/ 下没有对应文件"
        s = e.get("scope", "")
        assert s in SCOPES or s.startswith(PREFIXED), f"{p} 的 scope 写法不对：{s!r}"
        assert e.get("owner"), f"{p} 没写负责线"
