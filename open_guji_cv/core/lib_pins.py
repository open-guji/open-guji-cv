"""四个库的版本号写成一串（2026-11-09，Sheldon 定）：`cv0.7.0-c31-g19-m2-k3`。

| 字母 | 库 | 册配置的键 | 层 |
|---|---|---|---|
| `cv` | 识别引擎（global 代码，语义化版本） | `cv_version` | global |
| `c` | 语料库总号（每册钉子账，下分底库 b、书库 v、册层） | `corpus` | 册 |
| `g` | 字形库 | `glyph_pin` | 书 |
| `m` | 模型库 | `model` | 书 |
| `k` | 书级代码（书仓 `code/`，`core/book_code.py`） | `code` | 书 |

册配置可以分开写四个键，也可以写简写 `pin: c31-g19-m2-k3`（同一层里展开成那几个键；与同层分开写的键不一致就报错）。
版本号都不进指纹：指纹按内容算，这串只用来钉住与一眼看懂。
"""
from __future__ import annotations

import re

#: 字母 → 册配置的键；顺序就是版本串里的顺序
LETTERS: tuple[tuple[str, str], ...] = (("c", "corpus"), ("g", "glyph_pin"), ("m", "model"), ("k", "code"))
_PART = re.compile(r"^(cv)(\d+\.\d+\.\d+)$|^([cgmk])(\d+)$")


def parse(s: str) -> dict:
    """`[cv0.7.0-]c31-g19-m2-k3`（各段可缺、顺序不限）→ {键: 值}。"""
    out: dict = {}
    for part in str(s).strip().split("-"):
        m = _PART.match(part.strip().lower())
        if not m:
            raise ValueError(f"pin: 里的 {part!r} 看不懂（要写 cv0.7.0、c31、g19、m2、k3 这样的段，用 - 连）")
        if m.group(1):
            key, val = "cv_version", m.group(2)
        else:
            key, val = dict(LETTERS)[m.group(3)], int(m.group(4))
        if key in out:
            raise ValueError(f"pin: {s!r} 里 {key} 写了两次")
        out[key] = val
    return out


def expand_layer(layer: dict, where: str = "") -> dict:
    """一层册配置里的 `pin:` 展开成分开的键；同层分开写了且不一致 → ValueError。没写 pin 原样返回。"""
    if not isinstance(layer, dict) or "pin" not in layer:
        return layer
    pins = parse(layer["pin"])
    out = {k: v for k, v in layer.items() if k != "pin"}
    for k, v in pins.items():
        if k in out and str(out[k]).lstrip("cgmkv").lower() != str(v):
            raise ValueError(f"{where}pin: 写 {k}={v}，同一层又写了 {k}: {out[k]}，两处不一致")
        out[k] = v
    return out


def format_pins(*, cv: str | None = None, corpus=None, glyph=None, model=None, code=None) -> str:
    """拼版本串；没钉的段写调用方给的占位（如 `g-82293e`）或省掉（None）。"""
    parts = []
    if cv:
        parts.append(f"cv{cv.lstrip('v')}")
    for letter, v in (("c", corpus), ("g", glyph), ("m", model), ("k", code)):
        if v is None or v == "":
            continue
        parts.append(f"{letter}{v}" if isinstance(v, int) or str(v).isdigit() else str(v))
    return "-".join(parts)
