# -*- coding: utf-8 -*-
"""发版前核对：引擎仓里属于语料底库的文件，与中心库最新底库 ``b<M>`` 登记的是否一致（规矩见 `doc/版本号规矩.md` 第三节）。

底库（``corpus-base`` 工作区 ``config/corpus-base/b<M>/manifest.json``）登记引擎仓的字表、IDS、异体、形近、规则……
（`core/corpus_pin.py` 的 ``ITEMS`` 里 root=repo 的那些）每个文件的 sha256。钉了语料总号的册起跑前会硬校验
（`require_pin_clean`）：装的 cv 里这些文件和钉的 ``b<M>`` 不符就拒跑。所以**一个版本改了底库文件，就要配一个新底库**：

    python scripts/check_base_corpus.py                       # 拉中心库最新底库清单比（要读令牌 GUJI_DATA_TOKEN／_READ）
    python scripts/check_base_corpus.py --manifest <b<M> 的 manifest.json>   # 离线比本机一份清单

退出码：0 = 一致；1 = 有改动／缺／新增（按提示 ``guji corpus build-base`` 出 ``b<M+1>``，并告诉各执行线程改钉）；
2 = 拿不到清单。只读：不写库、不改文件。
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def repo_items(repo: Path) -> dict[str, str]:
    """引擎仓里登记进底库的文件：相对路径 → sha256（同 `build_base` 的口径）。"""
    from open_guji_cv.core.corpus_pin import ITEMS, _not_corpus, _sha256
    out: dict[str, str] = {}
    for _group, root, pat in ITEMS:
        if root != "repo":
            continue
        for p in sorted(repo.glob(pat)):
            if not p.is_file():
                continue
            rel = p.relative_to(repo).as_posix()
            if _not_corpus(root, rel) or rel in out:
                continue
            out[rel] = _sha256(p)
    return out


def compare(man: dict, have: dict[str, str], never_match: str | None = None) -> dict:
    """清单 vs 本仓：changed／missing（清单有、仓里没了）／extra（仓里新出现）／code_tables。"""
    from open_guji_cv.core.corpus_pin import _not_corpus
    listed = {i["path"]: i["sha256"] for i in man.get("items") or []
              if i.get("root") == "repo" and not _not_corpus("repo", i["path"])}
    changed = sorted(p for p in listed if p in have and have[p] != listed[p])
    missing = sorted(p for p in listed if p not in have)
    extra = sorted(p for p in have if p not in listed)
    tables = []
    want = (man.get("code_tables") or {}).get("NEVER_MATCH_FAMILIES")
    if never_match is not None and want and want != never_match:
        tables.append("NEVER_MATCH_FAMILIES")
    return {"changed": changed, "missing": missing, "extra": extra, "code_tables": tables}


def latest_central_manifest() -> tuple[int, dict]:
    """从中心库拉 ``corpus-base`` 的底库清单（只读），返回 (最新号, 清单)。"""
    import os
    if not os.environ.get("GUJI_DATA_TOKEN") and os.environ.get("GUJI_DATA_TOKEN_READ"):
        os.environ["GUJI_DATA_TOKEN"] = os.environ["GUJI_DATA_TOKEN_READ"]
    from open_guji_cv.core.corpus_pin import BASE_DIR, BASE_WS
    from open_guji_cv.datastore.client import WorkerSource
    from open_guji_cv.datastore.materialize import materialize
    with tempfile.TemporaryDirectory() as td:
        materialize(WorkerSource(), BASE_WS, Path(td), (BASE_DIR + "/",), cache=None, bucket="main")
        d = Path(td) / BASE_DIR
        vs = sorted(int(x.name[1:]) for x in d.iterdir()
                    if x.name.startswith("b") and x.name[1:].isdigit() and (x / "manifest.json").exists())
        if not vs:
            raise FileNotFoundError(f"中心库 {BASE_WS} 里没有底库清单")
        return vs[-1], json.loads((d / f"b{vs[-1]}" / "manifest.json").read_text(encoding="utf-8"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--manifest", help="本机一份底库清单（不给就拉中心库最新的）")
    ap.add_argument("--repo", default=str(ROOT), help="引擎仓根（缺省本仓）")
    a = ap.parse_args(argv)
    try:
        if a.manifest:
            man = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
            b = man.get("base_version", "?")
        else:
            b, man = latest_central_manifest()
    except Exception as e:                       # noqa: BLE001
        print(f"✗ 拿不到底库清单：{e}", file=sys.stderr)
        return 2
    try:
        from open_guji_cv.ops.corpus_pack import _never_match_hash
        nm = _never_match_hash()
    except Exception:                            # noqa: BLE001 —— 缺依赖时只比文件
        nm = None
    r = compare(man, repo_items(Path(a.repo)), nm)
    bad = r["changed"] + r["missing"] + r["extra"] + r["code_tables"]
    if not bad:
        print(f"✓ 引擎仓的底库文件与 b{b} 一致（{len(man.get('items') or [])} 个文件）")
        return 0
    print(f"✗ 引擎仓的底库文件与最新底库 b{b}（repo_commit {man.get('repo_commit', '?')}）不符：")
    for k, name in (("changed", "改了"), ("missing", "缺了"), ("extra", "新增"), ("code_tables", "代码常量变了")):
        if r[k]:
            print(f"  {name} {len(r[k])}：{r[k][:8]}")
    print(f"  发版前（在要发的提交上、文件都已提交）跑 guji corpus build-base 出 b{b + 1 if isinstance(b, int) else 'M+1'}；"
          f"钉了老底库的册在新版 cv 上会拒跑，要请各执行线程改钉（guji corpus pin）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
