"""殿本换图源后文本层的私用码表（`siku-qiefen-v2` 的 U+F1xxx）→ 字，给 `seed_admit.pua_code_table` 用（A24 2026-11-06，A31 X01 派单）。

两处来源，后者盖前者（数据目录由调用方传 `config_dir=ws_config_dir()`）：
1. 仓内 `config/pua/siku_qiefen_v2_codes.json`：`codes`＝码→字（只收人裁一致的码），`families`＝一码多字的码→族内字（如 F1001 乖垂埀）；
2. 工作区数据目录 `config/pua/pua_table.jsonl`（中心库同步）：`siku-qiefen-v2:U+` 起头的行、以及 daizhige 行 `same_as` 里的 v2 码；`verdict=char` → 码→字，`verdict=multi`（一码多字，字在 `chars`）→ 族。

码写法统一成 `F1001`（U+ 之后的十六进制，大写）。
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_FILE = Path(__file__).resolve().parents[2] / "config" / "pua" / "siku_qiefen_v2_codes.json"
_PREFIX = "siku-qiefen-v2:U+"
_MULTI = {"multi", "多字"}   # pua_table.verdict：一码多字（私用码线程 sheldon 逐格看图）


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
            code = str(r.get("code", ""))
            keys = [norm_code(code)] if code.startswith(_PREFIX) else []
            keys += [norm_code(c) for c in (r.get("same_as") or []) if str(c).startswith(_PREFIX)]   # 殆知阁码指到的新图源码
            if not keys:
                continue
            fam = r.get("family") or r.get("chars")          # 一码多字：族内字（字符串或列表）
            fam = frozenset("".join(fam) if not isinstance(fam, str) else fam) if fam else frozenset()
            if r.get("verdict") in _MULTI:                    # 多字码：只登族，不登单字（按码放字时族内都认、族外降审）
                for k in keys:
                    codes.pop(k, None)
                    if fam:
                        fams[k] = fam
                continue
            if r.get("verdict") == "char" and r.get("char"):     # 殆知阁行（审核页）的 char 也落到它 same_as 的 v2 码
                for k in keys:
                    codes[k] = r["char"]
                    if fam:
                        fams[k] = fam
    return codes, fams
