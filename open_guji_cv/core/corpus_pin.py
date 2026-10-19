"""语料库（corpus-vN）的清单读取、册钉子与指纹替换（设计见 doc/design/语料库版本化方案.md）。

放在 core 是因为 `Engine.params_for` 要用它；`guji corpus build|verify|list`（`ops/corpus_pack.py`）
在它上面加「出新版」和代码常量校验。

**册钉子**：册 yaml 写 `corpus: 1`（或 `v1`）。钉了之后，`params_for` 把参数里**属于语料库的内容指纹**
（`PIN_FIELDS`）统一换成 `corpus-v1`：指纹只认版本号，不看内容；没钉的册一字不变。
钉住的版本必须有清单，否则报错；清单之后文件被改过只警告一次（该出新版本，或把文件改回去）。
"""
from __future__ import annotations

import sys
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



def _sha256(p: Path) -> str:
    from ..products.store import sha256_file
    return sha256_file(p)


def _base(root: str, pat: str, ws: Path) -> Path:
    """根目录。工作区里 ``config/`` 下的表迁到中心库数据目录后在 ``data_root``（GUJI-608）。"""
    if root == "repo":
        return REPO_ROOT
    if pat.startswith("config/"):
        from .workspace import data_root
        return data_root(ws) or ws
    return ws


def collect(ws: Path) -> list[dict]:
    """按 ITEMS 扫出当前所有语料文件，返回 manifest 的 items（按 (root, path) 排序，输出稳定）。"""
    seen: dict[tuple[str, str], dict] = {}
    for group, root, pat in ITEMS:
        base = _base(root, pat, ws)
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


def check_files(ws: Path, man: dict) -> dict:
    """拿清单对当前文件：changed／missing／extra（清单之外新出现的）。"""
    changed, missing, listed = [], [], set()
    for it in man["items"]:
        listed.add((it["root"], it["path"]))
        p = _base(it["root"], it["path"], ws) / it["path"]
        if not p.is_file():
            missing.append(f'{it["root"]}:{it["path"]}')
        elif _sha256(p) != it["sha256"]:
            changed.append(f'{it["root"]}:{it["path"]}')
    extra = [f'{i["root"]}:{i["path"]}' for i in collect(ws) if (i["root"], i["path"]) not in listed]
    return {"changed": changed, "missing": missing, "extra": extra}


# ── 册钉子 ─────────────────────────────────────────────────────────────────────

#: 属于语料库的内容指纹字段（各 Step 参数类里自动填的那些）。钉了版本就整体换成 `corpus-vN`。
#: 不含：`db_fingerprint`／`human_fingerprint`（字形库）、`exclusions_fingerprint`（人裁累积）、
#: `model_fingerprint`／`shadow_model_fingerprint`（模型）——它们不是语料。
PIN_FIELDS: tuple[str, ...] = (
    "corpus_fingerprint", "witness_fingerprint", "lane_witness_fingerprint",
    "ledger_fingerprint", "variants_fingerprint", "variant_graph_fingerprint",
    "note_fingerprint", "iron_config_fingerprint", "group_flow_fingerprint",
)


#: 读语料库的 Step。册钉了版本后，这些步的指纹**整步**多带一个 `corpus-vN`（`engine._self_payload`），
#: 补上没有内容指纹的输入：形近表、`NEVER_MATCH_FAMILIES`、异体表／异体图、`rare_candidates` 的字表与部件库。
#: 登记在这里而不是各 Step 的 `StepSpec`：改 Step 模块源码会让 `code_hash` 变，没钉的册也跟着过期。
CORPUS_STEPS: frozenset[str] = frozenset({
    "glyph_match", "rare_candidates", "context_decide", "align_ref", "seed_admit",
})


def step_pin_token(step_id: str, book) -> str | None:
    """这一步这册书该带的语料库版本串；没钉或这步不读语料 → None（指纹不变）。"""
    v = getattr(book, "corpus", None)
    return pin_token(v) if v and step_id in CORPUS_STEPS else None


def parse_pin(v) -> int | None:
    """册 yaml 的 `corpus:`：`1`／`"1"`／`"v1"` → 1；空 → None。"""
    if v is None or v == "":
        return None
    s = str(v).strip().lower()
    s = s[1:] if s.startswith("v") else s
    if not s.isdigit() or int(s) < 1:
        raise ValueError(f"册 yaml 的 corpus: 应是正整数版本号（如 1 或 v1），收到 {v!r}")
    return int(s)


def pin_token(version: int) -> str:
    return f"corpus-v{version}"


_CHECKED: dict[tuple[str, int], None] = {}


def _check_pin_once(ws: Path | None, version: int) -> None:
    """钉住的版本必须有清单；清单之后文件被改只警告一次。"""
    if ws is None:
        raise FileNotFoundError(f"册 yaml 钉了 corpus: {version}，但不知道工作区（设 GUJI_WORKSPACE 或给 -w）")
    key = (str(ws), version)
    if key in _CHECKED:
        return
    mp = manifest_path(ws, version)
    if not mp.exists():
        raise FileNotFoundError(f"册 yaml 钉了 corpus: {version}，但没有清单 {mp}"
                                f"（先跑 guji corpus build -w {ws}）")
    import json
    r = check_files(ws, json.loads(mp.read_text(encoding="utf-8")))
    _CHECKED[key] = None
    if r["changed"] or r["missing"]:
        print(f"  ⚠️  语料库 v{version} 的清单与当前文件不符（改了 {len(r['changed'])}，缺 {len(r['missing'])}）："
              f"{(r['changed'] + r['missing'])[:5]}——指纹只看版本号，这些改动不会让产物过期；"
              f"该出新版本就 guji corpus build，或把文件改回去", file=sys.stderr)


def with_corpus_pin(p, book):
    """册钉了语料库版本时，把参数里的语料内容指纹换成版本号；没钉原样返回。

    只换**已经有值**的字段（开关没开的步这些字段是空的，保持为空）。必须重新构造而不是
    `model_copy`——跟 `_with_book_corpus` 一样，参数类的派生指纹在 `model_post_init` 里填，
    非空就不再重填。"""
    v = getattr(book, "corpus", None)
    if not v:
        return p
    fields = [f for f in PIN_FIELDS if getattr(p, f, "")]
    if not fields:
        return p
    from .workspace import workspace_root
    _check_pin_once(workspace_root(), v)
    tok = pin_token(v)
    return type(p)(**{**p.model_dump(), **{f: tok for f in fields}})
