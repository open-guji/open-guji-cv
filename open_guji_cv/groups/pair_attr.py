"""形近字对归属表的读取（第 7 步用）。格式、含义、校验命令见 guji-manager `doc/参考/形近字对归属表.md`（`guji-manager pair-attr`）。

文件 `config/groups/pair_attribution.yaml`：`pairs: {淸清: {attr: shape|context|merge, to?: 字}}`，没列的对缺省刻形；可加 `variant: true` 标同字异形（第 7 步 pair_form 只对它自动改字，异字对只记证据）。
本模块只读，不校验到 manager 那么细（格式不对直接抛 ValueError，不静默当没写）。"""
from __future__ import annotations

import hashlib
from pathlib import Path

SCHEMA = "pair_attribution/1"
ATTRS = ("shape", "context", "merge")


def pair_key(a: str, b: str) -> str:
    return "".join(sorted((a, b)))


def load(path: str | Path) -> dict[str, dict]:
    import yaml
    doc = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if doc.get("schema") != SCHEMA:
        raise ValueError(f"形近字对归属表要 schema: {SCHEMA}（{path}）")
    out: dict[str, dict] = {}
    for k, v in (doc.get("pairs") or {}).items():
        cs = list(str(k))
        if len(cs) != 2 or cs[0] == cs[1] or not isinstance(v, dict) or v.get("attr") not in ATTRS:
            raise ValueError(f"形近字对归属表 {k!r} 写得不对（{path}）")
        out[pair_key(*cs)] = dict(v)
    return out


def attr_of(table: dict[str, dict], a: str, b: str) -> str:
    return (table.get(pair_key(a, b)) or {}).get("attr", "shape")


def fingerprint(path: str | None) -> str:
    p = Path(path) if path else None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p and p.exists() else "missing"
