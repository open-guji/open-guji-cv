"""`guji corpus build|verify|list`：语料库（corpus-vN）的清单与校验（设计见 doc/design/语料库版本化方案.md）。

P0 只做清单：把流程里读的语料类文件（仓内手写／脚本产物、工作区里按书而异的字频表、答案表、整理本参考文本）
登记进 `<工作区>/corpus-pack/vN/manifest.json`，记每个文件的 sha256。**不搬文件、不改任何 Step、不动指纹**——
Step 仍读原位置，`code_hash` 不变。`verify` 用来发现「清单之后文件又被改了」，那就该出 vN+1。

版本号是递增整数；已存在的 vN 不覆盖。不自动运行，定期手动跑。人裁累积（crop_exclusions）、字形库、
图像模型不属于语料库，不登记。
"""
from __future__ import annotations

import datetime
import hashlib
import json
import subprocess
from pathlib import Path

PACK_DIR = "corpus-pack"
REPO_ROOT = Path(__file__).resolve().parents[2]

#: (分组, 根, 相对根的通配)。根："repo" = 本仓，"ws" = 工作区。通配按 `Path.glob`，目录递归用 `**/*`。
ITEMS: tuple[tuple[str, str, str], ...] = (
    ("reference", "ws", "corpus/**/*.txt"),
    ("reference", "repo", "corpus/external/*.txt"),
    ("freq", "ws", "config/groups/freq.json"),
    ("l2", "ws", "config/groups/l2/*.json"),
    ("rules", "repo", "config/groups/*/*"),
    ("ids", "repo", "config/ids/*"),
    ("variants", "repo", "config/dicts/variants*.tsv"),
    ("variants", "repo", "config/variants/*.json"),
    ("variants", "repo", "config/variants/books/*.json"),
    ("variants", "ws", "config/variants/**/*.json"),
    ("notes", "repo", "config/jiazhu/*.json"),
    ("confusable", "repo", "config/confusable_*.json"),
    ("confusable", "repo", "config/iron_extra_confusable.json"),
    ("charset", "repo", "config/charset/*"),
    ("charset", "repo", "config/kangxi/*"),
)

_SKIP_NAMES = {"README.md", ".gitkeep"}


def _sha256(p: Path) -> str:
    from ..products.store import sha256_file
    return sha256_file(p)


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


def collect(ws: Path) -> list[dict]:
    """按 ITEMS 扫出当前所有语料文件，返回 manifest 的 items（按 (root, path) 排序，输出稳定）。"""
    roots = {"repo": REPO_ROOT, "ws": ws}
    seen: dict[tuple[str, str], dict] = {}
    for group, root, pat in ITEMS:
        base = roots[root]
        for p in sorted(base.glob(pat)):
            if not p.is_file() or p.name in _SKIP_NAMES:
                continue
            rel = p.relative_to(base).as_posix()
            key = (root, rel)
            if key in seen:
                continue
            seen[key] = {"group": group, "root": root, "path": rel,
                         "size": p.stat().st_size, "sha256": _sha256(p)}
    return [seen[k] for k in sorted(seen)]


def pack_root(ws: Path) -> Path:
    return ws / PACK_DIR


def versions(ws: Path) -> list[int]:
    d = pack_root(ws)
    if not d.is_dir():
        return []
    return sorted(int(p.name[1:]) for p in d.iterdir()
                  if p.is_dir() and p.name.startswith("v") and p.name[1:].isdigit()
                  and (p / "manifest.json").exists())


def manifest_path(ws: Path, version: int) -> Path:
    return pack_root(ws) / f"v{version}" / "manifest.json"


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
    roots = {"repo": REPO_ROOT, "ws": ws}
    changed, missing = [], []
    listed = set()
    for it in man["items"]:
        listed.add((it["root"], it["path"]))
        p = roots[it["root"]] / it["path"]
        if not p.is_file():
            missing.append(f'{it["root"]}:{it["path"]}')
        elif _sha256(p) != it["sha256"]:
            changed.append(f'{it["root"]}:{it["path"]}')
    extra = [f'{i["root"]}:{i["path"]}' for i in collect(ws) if (i["root"], i["path"]) not in listed]
    code_ok = man.get("code_tables", {}).get("NEVER_MATCH_FAMILIES") == _never_match_hash()
    return {"version": version, "changed": changed, "missing": missing, "extra": extra,
            "never_match_families_same": code_ok,
            "clean": not (changed or missing or extra) and code_ok}


def summary(ws: Path) -> list[dict]:
    out = []
    for v in versions(ws):
        m = json.loads(manifest_path(ws, v).read_text(encoding="utf-8"))
        out.append({"version": v, "created": m.get("created"), "files": len(m["items"]),
                    "built_with": m.get("built_with"), "note": m.get("note", "")})
    return out
