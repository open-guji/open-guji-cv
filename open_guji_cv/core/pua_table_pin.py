"""PUA 码表共享层的钉住与读取（读取侧；写入在 guji-manager `ops/pua_table.py`，两边布局约定一致）。

中心库只读工作区 `pua-wyg`（四库文渊阁本 PUA 码表），按版本出：`config/pua-wyg/v<N>/{pua_table.jsonl,manifest.json}`。
书在 `book_defaults.yaml`（或册 yaml）写 `pua_table_pin: N`（或 `v<N>`）→ 读共享层 `v<N>`；**没钉**仍读本书
`config/pua/pua_table.jsonl`（向后兼容）。副本由 `guji db pull` 拉到 `borrowed_root('pua-wyg')`；钉了而副本缺／sha 不符就报错，
不悄悄读空表。码表内容经 `digest`（清单里的 sha256）进 seed_admit 的指纹（`SeedAdmitParams.pua_table_digest`）。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

PUA_WS = "pua-wyg"
PUA_DIR = "config/pua-wyg"
TABLE_FILE = "pua_table.jsonl"
MANIFEST_FILE = "manifest.json"
_PIN_RE = re.compile(r"^v?(\d+)$", re.IGNORECASE)


def parse_pin(v) -> int | None:
    """`3` / `"v3"` → 3；空 → None；别的报错（不猜）。"""
    if v is None or v == "" or v is False:
        return None
    m = _PIN_RE.match(str(v).strip())
    if not m or int(m.group(1)) < 1:
        raise ValueError(f"pua_table_pin 要写版本号（如 1 或 v1），收到 {v!r}")
    return int(m.group(1))


def version_dir(pin: int, root: Path | None = None) -> Path:
    if root is None:
        from .workspace import active_branch, borrowed_root
        root = borrowed_root(PUA_WS, active_branch())
    return Path(root) / PUA_DIR / f"v{pin}"


def _manifest(pin: int, root: Path | None = None) -> dict:
    d = version_dir(pin, root)
    try:
        return json.loads((d / MANIFEST_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise FileNotFoundError(f"PUA 码表共享层没有 v{pin}（{d}）：先 guji db pull 拉共享层，或确认 pua_table_pin（{e}）") from e


def digest(pin: int, root: Path | None = None) -> str:
    """`pua-v<N>-<sha256 前 16 位>`：进指纹用。清单缺报 FileNotFoundError。"""
    return f"pua-v{pin}-{str(_manifest(pin, root).get('sha256') or '')[:16]}"


def read_lines(pin: int, root: Path | None = None) -> list[str]:
    """共享层 `v<pin>` 码表的各行文本；清单缺、文件缺、sha 不符都报错。"""
    man = _manifest(pin, root)
    d = version_dir(pin, root)
    try:
        raw = (d / TABLE_FILE).read_bytes()
    except OSError as e:
        raise FileNotFoundError(f"PUA 码表 v{pin} 缺 {TABLE_FILE}（{d}）：重新 guji db pull") from e
    if man.get("sha256") != hashlib.sha256(raw).hexdigest():
        raise ValueError(f"PUA 码表 v{pin} 的 sha256 与清单不符（{d}），副本损坏：重新 guji db pull")
    return raw.decode("utf-8").splitlines()


def with_pua_table_pin(p, book):
    """册钉了 `pua_table_pin` 且这步开了码表（`pua_code_table`）时，参数里写入码表内容指纹；没钉原样返回。"""
    v = getattr(book, "pua_table_pin", None)
    if not v or not getattr(p, "pua_code_table", False) or not hasattr(p, "pua_table_digest"):
        return p
    return type(p)(**{**p.model_dump(), "pua_table_digest": digest(v)})
