"""殿本换图源后文本层的私用码表（`siku-qiefen-v2` 的 U+F1xxx）→ 字，给 `seed_admit.pua_code_table` 用（A24 2026-11-06，A31 X01 派单）。

两处来源，后者盖前者（数据目录由调用方传 `config_dir=ws_config_dir()`）：
1. 仓内 `config/pua/siku_qiefen_v2_codes.json`：`codes`＝码→字（只收人裁一致的码），`families`＝一码多字的码→族内字（如 F1001 乖垂埀）；
2. 工作区数据目录 `config/pua/pua_table.jsonl`（中心库同步）里 `code` 以 `siku-qiefen-v2:U+` 起头、`verdict=char` 的行（可带 `family` 字符串）。

码写法统一成 `F1001`（U+ 之后的十六进制，大写）。
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_FILE = Path(__file__).resolve().parents[2] / "config" / "pua" / "siku_qiefen_v2_codes.json"
_PREFIX = "siku-qiefen-v2:U+"


def norm_code(code: str) -> str:
    c = (code or "").strip()
    if c.startswith(_PREFIX):
        c = c[len(_PREFIX):]
    if c.upper().startswith("U+"):
        c = c[2:]
    return c.upper()


def load_table(config_dir: Path | None = None) -> tuple[dict[str, str], dict[str, frozenset[str]]]:
    """→ (码→字, 码→族内字集合)。读不到的来源跳过；两处都没有 → 两个空表。"""
    codes: dict[str, str] = {}
    fams: dict[str, frozenset[str]] = {}
    try:
        d = json.loads(REPO_FILE.read_text(encoding="utf-8"))
        codes.update({norm_code(k): v for k, v in (d.get("codes") or {}).items() if v})
        fams.update({norm_code(k): frozenset(v) for k, v in (d.get("families") or {}).items() if v})
    except (OSError, ValueError):
        pass
    f = Path(config_dir) / "pua" / "pua_table.jsonl" if config_dir is not None else None
    if f is not None and f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not str(r.get("code", "")).startswith(_PREFIX) or r.get("verdict") != "char" or not r.get("char"):
                continue
            k = norm_code(r["code"])
            codes[k] = r["char"]
            if r.get("family"):
                fams[k] = frozenset(r["family"])
    return codes, fams
