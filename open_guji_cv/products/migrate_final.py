"""收尾步产物原地改名迁移：`seed_admit/` → `char_decide/`（CV4 P3a-1，2026-11-28；命令 `guji-cv decide migrate-name`）。

给各册**不重跑**用：改名那一版发出后，旧产物用本命令原地改名，close-check、看板、冻结比对不报坏账。纪律：

- **只改名不删**：目录 `os.rename`；每页 JSON 只把顶层键 `seed_admit` 换成 `char_decide`（内层数据逐字不动，迁移时核对
  解析后相等）；`_prev/` 里上一代同样处理；原 `_manifest.jsonl` 留一份 `_manifest.jsonl.pre-rename`；
- **指纹按新名换算**：manifest 每条的 `sha256` 换成新文件的 sha，`fingerprint`／`self_hash`／`params_hash`／`upstream` 由调用方给的
  `convert(step_id, key, entry)` 算（命令行默认用引擎对新名 Step 重算，只有「上游与参数都没变」的页才换，别的页保持原样、照常过期）；
  下游各步 manifest 里 `upstream` 的 `seed_admit` 键也一起换名换 sha；
- **留 sha 清单存档**：`<产物根>/<册>/_migrate_char_decide.json`，记迁移前后每个文件的 sha256（页、`_prev` 页、manifest）与核对结果；
- 新旧目录并存（`char_decide/` 里已有页）→ 拒绝，不猜；已经迁完 → 空操作。

本模块不在任何 Step 的 `code_deps` 里。
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict
from pathlib import Path
from typing import Callable

from ..core.decide_names import LEGACY_ADMIT_STEP, NEW_ADMIT_STEP
from .manifest import Manifest, ManifestEntry
from .store import sha256_file

ARCHIVE_NAME = "_migrate_char_decide.json"
PRE_MANIFEST = "_manifest.jsonl.pre-rename"

#: `convert(step_id, key, entry) -> {字段: 新值}`：算这一条 manifest 换名后该有的 fingerprint／self_hash／params_hash／upstream。
#: 返回空 dict ＝ 这条只换 sha／upstream 键名，指纹不动。
Convert = Callable[[str, str, ManifestEntry], dict]


def _dumps(payload: dict) -> bytes:
    """同 `ProductStore.write` 的确定性序列化。"""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _inventory(step_dir: Path) -> dict[str, str]:
    inv: dict[str, str] = {}
    for p in sorted(step_dir.glob("p*.json")):
        inv[p.name] = sha256_file(p)
    prev = step_dir / "_prev"
    if prev.is_dir():
        for p in sorted(prev.glob("p*.json")):
            inv[f"_prev/{p.name}"] = sha256_file(p)
    m = step_dir / "_manifest.jsonl"
    if m.exists():
        inv["_manifest.jsonl"] = sha256_file(m)
    return inv


def _rename_page(path: Path) -> tuple[bool, bool]:
    """改一个页 JSON 的顶层键。返回 (改了, 迁移前就是确定性序列化)。已是新键 → (False, True)。"""
    raw = path.read_bytes()
    doc = json.loads(raw.decode("utf-8"))
    if NEW_ADMIT_STEP in doc and LEGACY_ADMIT_STEP not in doc:
        return False, True
    if LEGACY_ADMIT_STEP not in doc or NEW_ADMIT_STEP in doc:
        raise ValueError(f"{path}：顶层键不是 {LEGACY_ADMIT_STEP}（{sorted(doc)}），不迁")
    new = {(NEW_ADMIT_STEP if k == LEGACY_ADMIT_STEP else k): v for k, v in doc.items()}
    if json.loads(_dumps(new).decode("utf-8"))[NEW_ADMIT_STEP] != doc[LEGACY_ADMIT_STEP]:
        raise ValueError(f"{path}：改键后内层数据对不上，停")
    canonical = _dumps(doc) == raw
    tmp = path.with_suffix(".json.tmp")
    tmp.write_bytes(_dumps(new))
    tmp.replace(path)
    return True, canonical


def plan(root: str | Path, book: str) -> dict:
    """迁移前的状态：`state` = nothing（没有 seed_admit/）｜ready｜conflict（两个目录并存）｜done（只有 char_decide/）。"""
    base = Path(root) / book
    old, new = base / LEGACY_ADMIT_STEP, base / NEW_ADMIT_STEP
    has_old, has_new = old.is_dir(), new.is_dir()
    if has_old and has_new and any(new.glob("p*.json")):
        state = "conflict"
    elif has_old:
        state = "ready"
    elif has_new:
        state = "done"
    else:
        state = "nothing"
    out = {"book": book, "state": state, "pages": len(list(old.glob("p*.json"))) if has_old else 0}
    if has_old:
        out["sha_before"] = _inventory(old)
    downstream = []
    if base.is_dir():
        for d in sorted(p for p in base.iterdir() if p.is_dir() and p.name not in (LEGACY_ADMIT_STEP, NEW_ADMIT_STEP)):
            m = d / "_manifest.jsonl"
            if m.exists() and any(LEGACY_ADMIT_STEP in (e.upstream or {}) for e in Manifest(m).all().values()):
                downstream.append(d.name)
    out["downstream"] = downstream
    return out


def migrate(root: str | Path, book: str, convert: Convert | None = None, dry_run: bool = False,
            now: Callable[[], float] = time.time) -> dict:
    """做迁移，返回报告（同时落 `ARCHIVE_NAME`；`dry_run` 只返回计划、什么都不动）。"""
    base = Path(root) / book
    p = plan(root, book)
    if p["state"] == "conflict":
        raise RuntimeError(f"{book}：{LEGACY_ADMIT_STEP}/ 与 {NEW_ADMIT_STEP}/ 并存（{NEW_ADMIT_STEP}/ 里已有页），不自动迁；先查清哪边是对的")
    if p["state"] != "ready" or dry_run:
        return p
    old, new = base / LEGACY_ADMIT_STEP, base / NEW_ADMIT_STEP
    before = p["sha_before"]
    if new.is_dir():                                  # 只剩空壳（没有页）：让位
        for f in new.iterdir():
            raise RuntimeError(f"{new} 非空（{f.name}），不迁")
        new.rmdir()
    os.rename(old, new)
    pages_changed = 0
    non_canonical = []
    for pg in sorted([*new.glob("p*.json"), *((new / "_prev").glob("p*.json") if (new / "_prev").is_dir() else [])]):
        changed, canon = _rename_page(pg)
        pages_changed += changed
        if not canon:
            non_canonical.append(str(pg.relative_to(new)))
    page_sha = {p_.name: sha256_file(p_) for p_ in new.glob("p*.json")}
    n_conv = _migrate_manifest(new, base, book, convert, page_sha)
    n_down = {}
    for d in p["downstream"]:
        n_down[d] = _migrate_downstream(base / d, convert, page_sha)
    after = _inventory(new)
    report = {"book": book, "state": "migrated", "ts": now(), "pages": p["pages"], "pages_changed": pages_changed,
              "fingerprint_converted": n_conv, "downstream": n_down, "non_canonical_pages": non_canonical,
              "sha_before": before, "sha_after": after}
    (base / ARCHIVE_NAME).write_text(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    return report


def _apply(entry: ManifestEntry, sha: str | None, upstream_rename: bool, fields: dict) -> ManifestEntry:
    d = asdict(entry)
    if sha is not None:
        d["sha256"] = sha
    if upstream_rename:
        d["upstream"] = {(NEW_ADMIT_STEP if k == LEGACY_ADMIT_STEP else k): v for k, v in (entry.upstream or {}).items()}
    d.update({k: v for k, v in fields.items() if k in ManifestEntry.__dataclass_fields__})
    return ManifestEntry(**d)


def _migrate_manifest(new_dir: Path, base: Path, book: str, convert: Convert | None, page_sha: dict[str, str]) -> int:
    path = new_dir / "_manifest.jsonl"
    if not path.exists():
        return 0
    (new_dir / PRE_MANIFEST).write_bytes(path.read_bytes())
    entries = Manifest(path).all()
    n = 0
    out = Manifest(path)
    for key, e in entries.items():
        fields = convert(NEW_ADMIT_STEP, key, e) if convert else {}
        n += bool(fields)
        # 新页 sha 取实际文件；没产物文件的条目（failed／skipped）sha256 本来就是 None，保持
        sha = page_sha.get(f"{key}.json") if e.sha256 else None
        out.put(_apply(e, sha, True, fields))
    out.compact()
    return n


def _migrate_downstream(step_dir: Path, convert: Convert | None, page_sha: dict[str, str]) -> int:
    """下游某步的 manifest：`upstream` 里的 `seed_admit` 键换名、值换成新页 sha；指纹同样交给 convert。"""
    m = Manifest(step_dir / "_manifest.jsonl")
    n = 0
    for key, e in m.all().items():
        if LEGACY_ADMIT_STEP not in (e.upstream or {}):
            continue
        fields = convert(step_dir.name, key, e) if convert else {}
        ent = _apply(e, None, True, fields)
        up = dict(ent.upstream)
        sha = page_sha.get(f"{key}.json")
        if sha:
            up[NEW_ADMIT_STEP] = sha
        ent.upstream = up
        m.put(ent)
        n += 1
    m.compact()
    return n
