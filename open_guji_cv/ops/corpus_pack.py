"""`guji corpus build|verify|list`：语料库（corpus-vN）的清单与校验（设计见 doc/design/语料库版本化方案.md）。

清单读取、文件扫描、册钉子在 `core/corpus_pin.py`；这里加「出新版」和代码常量（NEVER_MATCH_FAMILIES）校验。

P0 只做清单：把流程里读的语料类文件登记进 `<工作区>/corpus-pack/vN/manifest.json`，记每个文件的 sha256。
**不搬文件**——Step 仍读原位置；`verify` 用来发现「清单之后文件又被改了」，那就该出 vN+1。
P1 起册 yaml 可以 `corpus: N` 钉版本，指纹只认版本号（见 core/corpus_pin.py）。

版本号是递增整数；已存在的 vN 不覆盖。不自动运行，定期手动跑。人裁累积（crop_exclusions）、字形库、
图像模型不属于语料库，不登记。
"""
from __future__ import annotations

import datetime
import hashlib
import json
import subprocess
from pathlib import Path

from ..core.corpus_pin import (ITEMS, PACK_DIR, REPO_ROOT, check_files, collect, manifest_path,  # noqa: F401
                               pack_root, versions)


def _never_match_hash() -> str:
    """写死在 `clustering.match` 里的 NEVER_MATCH_FAMILIES：代码常量，也算语料。"""
    from ..clustering.match import NEVER_MATCH_FAMILIES
    items = sorted("".join(sorted(map(str, f))) if not isinstance(f, str) else f for f in NEVER_MATCH_FAMILIES)
    return hashlib.sha256(json.dumps(items, ensure_ascii=False).encode()).hexdigest()


def _git_head() -> str:
    try:
        r = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=30)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _cv_version() -> str:
    try:
        from importlib.metadata import version
        return version("open-guji-cv")
    except Exception:
        return ""


def build(ws: Path, version: int | None = None, note: str = "") -> Path:
    """出新版清单。已存在的版本号拒绝覆盖；缺省取现有最大号 + 1。"""
    have = versions(ws)
    v = version if version is not None else (have[-1] + 1 if have else 1)
    out = manifest_path(ws, v)
    if out.exists():
        raise FileExistsError(f"语料库 v{v} 已存在（{out}），不覆盖；要新版请不给 --version")
    items = collect(ws)
    man = {
        "corpus_version": v,
        "created": datetime.date.today().isoformat(),
        "built_with": {"cv_version": _cv_version(), "cv_commit": _git_head()},
        "note": note,
        "code_tables": {"NEVER_MATCH_FAMILIES": _never_match_hash()},
        "items": items,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(man, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return out


def verify(ws: Path, version: int) -> dict:
    """拿清单对当前文件：返回 changed／missing／extra（清单之外新出现的）。"""
    mp = manifest_path(ws, version)
    if not mp.exists():
        raise FileNotFoundError(f"没有语料库 v{version} 的清单：{mp}")
    man = json.loads(mp.read_text(encoding="utf-8"))
    r = check_files(ws, man)
    code_ok = man.get("code_tables", {}).get("NEVER_MATCH_FAMILIES") == _never_match_hash()
    return {"version": version, **r, "never_match_families_same": code_ok,
            "clean": not (r["changed"] or r["missing"] or r["extra"]) and code_ok}


def summary(ws: Path) -> list[dict]:
    out = []
    for v in versions(ws):
        m = json.loads(manifest_path(ws, v).read_text(encoding="utf-8"))
        out.append({"version": v, "created": m.get("created"), "files": len(m["items"]),
                    "built_with": m.get("built_with"), "note": m.get("note", "")})
    return out
