# -*- coding: utf-8 -*-
"""形近字组登记表 `config/near_groups/v2.json`（格式 `near_groups/2`）的确定性生成。schema 与六处来源见
`doc/3-识字/形近字组登记表.md`，读口 `open_guji_cv/groups/near_registry.py`。

    python scripts/build_near_groups_v2.py                     # 重写 config/near_groups/v2.json（只读仓内来源）
    python scripts/build_near_groups_v2.py --check             # 只比对，与提交的不一致返回 1（tests/test_near_registry.py 同款守卫）

    # 书级版本：再并上一本书的 pair_clf 分类器文件、书配置里的 glyph_near 组（都在数据目录，不进仓），写到仓外
    python scripts/build_near_groups_v2.py --pair-clf <书>=<数据目录>/config/groups/pair_clf.json \\
        --glyph-near <书>=<册配置.yaml 或 groups 的 json> --out <数据目录>/config/near_groups/v2.json

仓内六处来源里五处在仓里（手工表 `config/near_groups/hand.json`、字体表、人裁表、`near_groups.json`、注册字组表），第六处 pair_clf 的对是书级文件，
只在带 `--pair-clf` 时并进来；提交的 v2.json 不带任何书级输入，所以 `books` 全空。

合并规则：
- 注册字组表（`groups/registry.py` 的 `FLOW_GROUPS`）每组一条，组 id 照旧；
- 字对来源（手工、人裁、字体 τ≥`confusable.FONT_TAU`、`near_groups.json`、书级 pair_clf）按无序对去重，`src` 记全部来源；
  两个字同在某个注册组里的对挂到那个组（同在几个组就挂几个）的 `pairs` 下，其余每对单立一组，id 为 `p:<两字按码位序>`；
- 剔除名单 `config/near_groups_drop.tsv` 里的对，没有手工／人裁／刻形（shape）来源的不收（同 `build_near_groups.py merge`）；
- 单立字对组的类型按规则定（`near_groups.json` 的 src 有 variant → variant，否则 near），`config/near_groups/type_override.json`
  人定覆盖（2026-11-28 Sheldon：pair_clf 来的 侣侶 记 variant、凊淸 保持 near）；
- 来源 7（2026-11-28）`config/near_groups/shape_pairs.json`：第四步书级刻形判法挂着、别处没登记的字对（史记 之矣），
  src＝`shape`，只为 3b `glyph_near` 的书配置能 `ref` 到一个组；现役读口按 src 取 hand／human／font，不读它。

本脚本只生成表。第二期（2026-11-28）起 `confusable.NEVER_MATCH_FAMILIES`／`partners()` 从本表派生，所以手工表不能再从
`confusable` 读（会读回自己），改读真源 `config/near_groups/hand.json`；改了任何来源都要重跑本脚本，否则现役护栏跟不上。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FORMAT = "near_groups/2"
OUT = ROOT / "config" / "near_groups" / "v2.json"
TYPES = {"near": "异字形近（组内是不同的字）", "variant": "同字异码（组内是同一个字的不同码位／写法）",
         "fold": "折叠组（组内既有不同的字，又有某字的异体；fold 把异体折到它归的字）"}
PAIR_PREFIX = "p:"
DOC = ("形近字组登记表（scripts/build_near_groups_v2.py 生成，勿手改；读口 open_guji_cv/groups/near_registry.py，"
       "schema 与来源见 doc/3-识字/形近字组登记表.md）。groups 的键是组 id：注册字组表的组 id 照旧，其余字对单立 p:<两字>。"
       "src：registry＝注册字组表、hand＝config/near_groups/hand.json（手工核过的形近否决对）、human＝config/confusable_human.json、"
       "font＝字体形近表 τ≥font_tau、near_groups＝config/near_groups.json、"
       "shape＝config/near_groups/shape_pairs.json（第四步书级刻形判法的字对，只给 3b ref，现役护栏与分流不读）、"
       "pair_clf:<书>＝该书的按对分类器文件。"
       "methods＝第四步 group_flow 的方法数组（按顺序）；books＝按书覆盖（哪本书开哪些方法、用哪个模型文件）。")


def pair_key(a: str, b: str) -> str:
    """无序字对的键：两字按码位序拼起来（同 `pair_clf.pair_key`）。"""
    return "".join(sorted((a, b)))


# ── 读仓内来源 ──────────────────────────────────────────────────────


def read_drop(path: Path) -> set[str]:
    out = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#"):
                k = line.split("\t", 1)[0].strip()
                if len(k) == 2:
                    out.add(pair_key(k[0], k[1]))
    return out


def repo_pair_sources(root: Path = ROOT) -> dict[str, dict]:
    """仓内字对来源（手工、人裁、字体、near_groups.json、刻形判法字对 shape）→ {对: {"src": {标签…}, …附带字段}}。"""
    from open_guji_cv.clustering.confusable import FONT_TAU, hand_pairs
    cfg = root / "config"
    acc: dict[str, dict] = {}

    def add(a: str, b: str, tag: str, **extra):
        if a == b:
            return
        e = acc.setdefault(pair_key(a, b), {"src": set()})
        e["src"].add(tag)
        e.update(extra)

    for a, b in hand_pairs(cfg / "near_groups" / "hand.json"):   # 手工表真源；confusable.NEVER_MATCH_FAMILIES 反过来从本表派生
        add(a, b, "hand")
    human = json.loads((cfg / "confusable_human.json").read_text(encoding="utf-8")).get("pairs", {})
    for k in human:
        if len(k) == 2:
            add(k[0], k[1], "human")
    font = json.loads((cfg / "confusable_font_degraded.json").read_text(encoding="utf-8"))
    for k, v in (font.get("pairs") or {}).items():
        if len(k) == 2 and float(v) >= FONT_TAU:
            add(k[0], k[1], "font", font=round(float(v), 4))
    ng = json.loads((cfg / "near_groups.json").read_text(encoding="utf-8"))
    for k, e in (ng.get("pairs") or {}).items():
        if len(k) == 2:
            extra = {"ng_src": sorted(e.get("src") or ()), "core": bool(e.get("core"))}
            if e.get("near"):
                extra["near"] = dict(sorted(e["near"].items()))
            add(k[0], k[1], "near_groups", **extra)
    shape = cfg / "near_groups" / "shape_pairs.json"            # 来源 7：第四步书级刻形判法的字对，只进登记表（2026-11-28）
    if shape.exists():
        for e in json.loads(shape.read_text(encoding="utf-8")).get("pairs") or ():
            add(str(e["a"]), str(e["b"]), "shape")
    drop = read_drop(cfg / "near_groups_drop.tsv")
    return {k: e for k, e in acc.items() if not (k in drop and not {"hand", "human", "shape"} & e["src"])}


def registry_groups() -> list[dict]:
    """注册字组表 `FLOW_GROUPS` → [{id, chars, type, name, fold, canon, methods…, registry}]，按组 id 排序。"""
    from open_guji_cv.groups import registry as R
    tables = {"GROUPS": R.GROUPS, "CODEPOINT_GROUPS": R.CODEPOINT_GROUPS, "SHAPE_GROUPS": R.SHAPE_GROUPS,
              "OPT_IN_GROUPS": R.OPT_IN_GROUPS}
    default = set(R.generic_flow_names())
    out = []
    for gid in sorted(R.FLOW_GROUPS):
        g = R.FLOW_GROUPS[gid]
        f = g.flow
        fams = tuple(f.families) if f and f.families else ()
        fold = {c: fam[0] for fam in fams for c in fam[1:]}
        if g.kind == "variant":
            typ = "variant"
        else:
            typ = "fold" if fold else "near"
        rec = {"id": gid, "chars": sorted(g.members), "type": typ, "name": g.name}
        if fold:
            rec["fold"] = dict(sorted(fold.items()))
            rec["families"] = list(fams)
        pv = R.PROVISIONAL.get(gid)
        if pv is not None:
            rec["canon"] = pv.to
        rec["methods"] = list(f.solvers) if f else []
        if f:
            rec["combine"] = f.combine
            if f.review_methods:
                rec["review_methods"] = list(f.review_solvers)
            if fams:
                rec["form_methods"] = list(f.form_solvers)
        rec["registry"] = {"table": next(t for t, d in tables.items() if gid in d), "kind": g.kind,
                           "config_dir": g.config_dir, "overlaps": list(g.overlaps), "default_flow": gid in default}
        out.append(rec)
    return out


# ── 书级来源（数据目录，不进仓）────────────────────────────────────────


def book_pair_clf(book: str, path: Path) -> tuple[dict[str, dict], dict[str, object]]:
    """书级 pair_clf 文件 → (字对来源, {对: 档})。档：0–3 或 "context"。"""
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    src: dict[str, dict] = {}
    tiers: dict[str, object] = {}
    for k, p in (d.get("pairs") or {}).items():
        a, b = str(p.get("a") or k[0]), str(p.get("b") or k[1:])
        key = pair_key(a, b)
        tiers[key] = p.get("tier")
        src[key] = {"src": {f"pair_clf:{book}"}}
    for s in d.get("context") or ():
        if len(s) >= 2:
            key = pair_key(s[0], s[1:])
            tiers.setdefault(key, "context")
            src.setdefault(key, {"src": {f"pair_clf:{book}"}})
    return src, tiers


def book_glyph_near(path: Path) -> dict:
    """册配置（yaml）或 groups 的 json → glyph_near 的 groups dict。"""
    text = Path(path).read_text(encoding="utf-8")
    if str(path).endswith((".yaml", ".yml")):
        import yaml
        d = yaml.safe_load(text) or {}
    else:
        d = json.loads(text)
    for k in ("params", "glyph_near", "groups"):
        if isinstance(d, dict) and k in d:
            d = d[k]
    return dict(d or {})


# ── 合表 ──────────────────────────────────────────────────────────────


def _merge_pair(dst: dict, e: dict) -> None:
    dst["src"] = sorted(set(dst.get("src") or ()) | set(e["src"]))
    for k, v in e.items():
        if k != "src":
            dst[k] = v


def read_type_override(path: Path) -> dict[str, str]:
    """单立字对组的类型人定覆盖 `config/near_groups/type_override.json` → {对: 类型}（键按码位序重排）。没有文件 → {}。"""
    if not Path(path).exists():
        return {}
    out = {}
    for k, e in (json.loads(Path(path).read_text(encoding="utf-8")).get("types") or {}).items():
        t = str(e["type"] if isinstance(e, dict) else e)
        if t not in TYPES:
            raise ValueError(f"{path}：{k} 的 type {t!r} 不认识（应为 {sorted(TYPES)}）")
        out[pair_key(k[0], k[1:])] = t
    return out


def build(reg: list[dict], pairs: dict[str, dict], book_pairs: dict[str, tuple[dict, dict]] | None = None,
          book_gn: dict[str, dict] | None = None, font_tau: float | None = None,
          type_override: dict[str, str] | None = None) -> dict:
    """纯函数：注册组 ＋ 字对来源 ＋ 书级输入 → `near_groups/2` 整张表（dict，键序确定）。

    - `reg`：`registry_groups()` 的形状；`pairs`：{对: {"src": {标签}, …}}；
    - `book_pairs`：{书: (字对来源, {对: 档})}；`book_gn`：{书: glyph_near 的 groups dict}；
    - `type_override`：{对: 类型}，单立字对组的类型人定覆盖（只管 `p:` 组；对没进表就不起作用）。"""
    book_pairs = book_pairs or {}
    book_gn = book_gn or {}
    type_override = type_override or {}
    allp: dict[str, dict] = {}
    for k, e in pairs.items():
        _merge_pair(allp.setdefault(k, {}), e)
    for _, (src, _) in sorted(book_pairs.items()):
        for k, e in src.items():
            _merge_pair(allp.setdefault(k, {}), e)

    groups: dict[str, dict] = {}
    by_char: dict[str, list[str]] = {}
    for r in reg:
        g = {k: v for k, v in r.items() if k != "id"}
        g["src"] = ["registry"]
        groups[r["id"]] = g
        for c in r["chars"]:
            by_char.setdefault(c, []).append(r["id"])

    def covering(key: str) -> list[str]:
        return sorted(set(by_char.get(key[0], ())) & set(by_char.get(key[1], ())))

    for key in sorted(allp):
        e = allp[key]
        gids = covering(key)
        if not gids:
            gid = PAIR_PREFIX + key
            ng = e.get("ng_src") or ()
            typ = type_override.get(key) or ("variant" if "variant" in ng else "near")
            groups[gid] = {"chars": [key[0], key[1]], "type": typ, "methods": [], "src": []}
            gids = [gid]
        for gid in gids:
            g = groups[gid]
            g.setdefault("pairs", {})[key] = dict(sorted(e.items()))
            g["src"] = sorted(set(g["src"]) | set(e["src"]))

    for book, (_, tiers) in sorted(book_pairs.items()):
        for key, tier in sorted(tiers.items()):
            gids = covering(key) or [PAIR_PREFIX + key]
            for gid in gids:
                b = groups[gid].setdefault("books", {}).setdefault(book, {})
                pc = b.setdefault("pair_clf", {"model": "config/groups/pair_clf.json", "pairs": {}})
                pc["pairs"][key] = tier

    for book, gn in sorted(book_gn.items()):
        for gn_id, spec in sorted(gn.items()):
            spec = dict(spec or {})
            chars = set(spec.get("chars") or ())
            hit = sorted(gid for gid, g in groups.items() if chars and chars <= set(g["chars"]))
            if not hit:
                continue
            # 最贴的组：成员最少的那个（gong 宫宮官 → guan，不挂到更大的组）
            gid = min(hit, key=lambda x: (len(groups[x]["chars"]), x))
            b = groups[gid].setdefault("books", {}).setdefault(book, {})
            b["glyph_near"] = {"id": gn_id, **{k: spec[k] for k in ("methods", "trigger", "delta", "topk") if k in spec}}

    order = sorted(groups, key=lambda g: (g.startswith(PAIR_PREFIX), g))
    groups = {gid: dict(sorted(groups[gid].items())) for gid in order}
    n_type: dict[str, int] = {}
    n_src: dict[str, int] = {}
    for g in groups.values():
        n_type[g["type"]] = n_type.get(g["type"], 0) + 1
        for s in g["src"]:
            n_src[s] = n_src.get(s, 0) + 1
    n_pair_src: dict[str, int] = {}
    for e in allp.values():
        for s in e["src"]:
            n_pair_src[s] = n_pair_src.get(s, 0) + 1
    return {
        "format": FORMAT,
        "_doc": DOC,
        "types": TYPES,
        "font_tau": font_tau,
        "n_groups": len(groups),
        "n_registry": sum(1 for g in groups.values() if "registry" in g["src"]),
        "n_pair_groups": sum(1 for gid in groups if gid.startswith(PAIR_PREFIX)),
        "n_pairs": len(allp),
        "n_by_type": dict(sorted(n_type.items())),
        "n_groups_by_src": dict(sorted(n_src.items())),
        "n_pairs_by_src": dict(sorted(n_pair_src.items())),
        "books": sorted(set(book_pairs) | set(book_gn)),
        "groups": groups,
    }


def build_from_repo(pair_clf: dict[str, Path] | None = None, glyph_near: dict[str, Path] | None = None) -> dict:
    from open_guji_cv.clustering.confusable import FONT_TAU
    bp = {b: book_pair_clf(b, p) for b, p in (pair_clf or {}).items()}
    bg = {b: book_glyph_near(p) for b, p in (glyph_near or {}).items()}
    return build(registry_groups(), repo_pair_sources(ROOT), bp, bg, font_tau=FONT_TAU,
                 type_override=read_type_override(ROOT / "config" / "near_groups" / "type_override.json"))


def dumps(table: dict) -> str:
    return json.dumps(table, ensure_ascii=False, indent=1) + "\n"


def _kv(items: list[str] | None, flag: str) -> dict[str, Path]:
    out = {}
    for s in items or ():
        if "=" not in s:
            raise SystemExit(f"{flag} 要写成 <书>=<文件>：{s!r}")
        b, p = s.split("=", 1)
        out[b] = Path(p)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--check", action="store_true", help="只比对 --out 与现生成的是否一致")
    ap.add_argument("--pair-clf", action="append", help="<书>=<pair_clf.json>（书级，结果别提交进仓）")
    ap.add_argument("--glyph-near", action="append", help="<书>=<册配置 yaml 或 glyph_near groups 的 json>（书级）")
    a = ap.parse_args(argv)
    bp, bg = _kv(a.pair_clf, "--pair-clf"), _kv(a.glyph_near, "--glyph-near")
    text = dumps(build_from_repo(bp, bg))
    out = Path(a.out)
    if a.check:
        same = out.exists() and out.read_text(encoding="utf-8") == text
        print("一致" if same else f"不一致：重跑 python scripts/build_near_groups_v2.py 再提交 {out}")
        return 0 if same else 1
    if (bp or bg) and out.resolve() == OUT.resolve():
        raise SystemExit("带书级输入生成的是书级版本，别写进仓里的 config/near_groups/v2.json；用 --out 指到数据目录")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    t = json.loads(text)
    print(f"{out}：{t['n_groups']} 组（注册 {t['n_registry']}、单立字对 {t['n_pair_groups']}），字对 {t['n_pairs']}；"
          f"按类型 {t['n_by_type']}；字对来源 {t['n_pairs_by_src']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
