"""形近字组登记表 `near_groups/2` 的读口（2026-11-28，第三步重构 W1 第一期）。

表是 `config/near_groups/v2.json`，由 `scripts/build_near_groups_v2.py` 从六处现有来源确定性生成；schema、来源与
「谁还在读旧表」见 `doc/3-识字/形近字组登记表.md`。**这一期只加读口，现役代码一处都不改读它**（第二期再迁，要 code_equiv）。

    from open_guji_cv.groups import near_registry as NR
    reg = NR.load()                     # 缺省读仓里的表；书级版本给 path
    reg.get("guan").chars               # ('官', '宫', '宮')
    reg.groups_of("宫")                 # 这个字在哪些组（注册组在前、单立字对在后）
    reg.by_type("fold")                 # 按类型过滤：near／variant／fold
    reg.glyph_near_spec("guan", book="<书>")   # 转成 3b 书配置 groups.<组> 那种 dict

## 书配置引用登记表（`ref`）

    params:
      glyph_near:
        groups:
          gong: {ref: guan, methods: {cnn_small: models/glyph_near_gong}}   # ref 之外写的键盖过登记表

`expand_refs(groups, book)` 把带 `ref` 的组展开成 3b 认的 `{chars, fold, methods, trigger, delta, topk}`（`ref` 键本身不留，
参数指纹只跟内容走）；**一个 `ref` 都没写时原样返回同一个对象**，接进 `GlyphNearParams` 后没写 `ref` 的书参数哈希逐位不变。
3b 已接线（2026-11-28）：`GlyphNearStep.book_params` 按本册 id 调 `expand_refs`，展开后重算 `methods_sha`。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_PATH = REPO / "config" / "near_groups" / "v2.json"
FORMAT = "near_groups/2"
TYPES = ("near", "variant", "fold")
PAIR_PREFIX = "p:"
GLYPH_NEAR_KEYS = ("chars", "fold", "methods", "trigger", "delta", "topk")


@dataclass(frozen=True)
class NearGroup:
    id: str
    chars: tuple
    type: str
    methods: tuple = ()
    fold: dict = field(default_factory=dict)
    src: tuple = ()
    books: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def registered(self) -> bool:
        """在注册字组表里（第四步 group_flow 有判法）。"""
        return "registry" in self.src

    @property
    def pairs(self) -> dict:
        return dict(self.raw.get("pairs") or {})

    def canon(self, ch: str) -> str:
        return self.fold.get(ch, ch)


class NearRegistry:
    def __init__(self, data: dict, path: str = ""):
        if data.get("format") != FORMAT:
            raise ValueError(f"{path or '登记表'} 的 format 不是 {FORMAT}：{data.get('format')!r}")
        self.path = path
        self.meta = {k: v for k, v in data.items() if k != "groups"}
        self.groups: dict[str, NearGroup] = {}
        idx: dict[str, list[str]] = {}
        for gid, g in (data.get("groups") or {}).items():
            typ = str(g.get("type") or "")
            if typ not in TYPES:
                raise ValueError(f"组 {gid} 的 type 不认识：{typ!r}（应为 {TYPES}）")
            ng = NearGroup(id=gid, chars=tuple(g.get("chars") or ()), type=typ, methods=tuple(g.get("methods") or ()),
                           fold=dict(g.get("fold") or {}), src=tuple(g.get("src") or ()), books=dict(g.get("books") or {}),
                           raw=g)
            self.groups[gid] = ng
            for c in ng.chars:
                idx.setdefault(c, []).append(gid)
        self._by_char = {c: tuple(sorted(v, key=lambda x: (x.startswith(PAIR_PREFIX), x))) for c, v in idx.items()}

    def __contains__(self, gid: str) -> bool:
        return gid in self.groups

    def __len__(self) -> int:
        return len(self.groups)

    def get(self, gid: str) -> NearGroup:
        g = self.groups.get(gid)
        if g is None:
            raise KeyError(f"形近字组登记表里没有组 {gid!r}（{self.path}）")
        return g

    def groups_of(self, ch: str, types: tuple | str | None = None) -> list[NearGroup]:
        """一个字所在的组：注册组在前（按 id），单立字对在后。`types` 给了就只要这几类。"""
        want = (types,) if isinstance(types, str) else types
        return [self.groups[g] for g in self._by_char.get(ch, ()) if want is None or self.groups[g].type in want]

    def by_type(self, *types: str) -> list[NearGroup]:
        bad = set(types) - set(TYPES)
        if bad:
            raise ValueError(f"不认识的类型 {sorted(bad)}（应为 {TYPES}）")
        return [g for g in self.groups.values() if g.type in types]

    def glyph_near_spec(self, gid: str, book: str | None = None, **over) -> dict:
        """一组 → 3b `glyph_near` 书配置里 `groups.<组>` 那种 dict：`chars`、`fold`（折叠组才有）、`methods`
        （这本书在登记表里的 `books.<书>.glyph_near`，没有就空），再拿 `over` 盖（书配置里 `ref` 以外写的键）。
        只出写了值的键，缺的照 3b 的缺省（trigger=close、delta=0.03、topk=3）。"""
        g = self.get(gid)
        out: dict = {"chars": list(g.chars)}
        if g.fold:
            out["fold"] = dict(g.fold)
        bk = dict(((g.books.get(book) or {}).get("glyph_near") or {})) if book else {}
        out["methods"] = dict(bk.get("methods") or {})
        for k in ("trigger", "delta", "topk"):
            if k in bk:
                out[k] = bk[k]
        for k, v in over.items():
            if k == "ref":
                continue
            if k not in GLYPH_NEAR_KEYS:
                raise ValueError(f"glyph_near.groups 引用 {gid} 时不认识的键 {k!r}（可写 {GLYPH_NEAR_KEYS}）")
            out[k] = v
        return out

    def expand(self, groups: dict, book: str | None = None) -> dict:
        """书配置 `glyph_near.groups` → 展开 `ref` 后的 dict。一个 `ref` 都没有就原样返回同一个对象。"""
        if not any(isinstance(s, dict) and "ref" in s for s in (groups or {}).values()):
            return groups
        out = {}
        for name, spec in groups.items():
            if isinstance(spec, dict) and "ref" in spec:
                out[name] = self.glyph_near_spec(str(spec["ref"]), book, **{k: v for k, v in spec.items() if k != "ref"})
            else:
                out[name] = spec
        return out


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> NearRegistry:
    return NearRegistry(json.loads(Path(path).read_text(encoding="utf-8")), path)


def load(path: str | Path | None = None) -> NearRegistry:
    """读登记表（按文件修改时间缓存）。缺省读仓里的 `config/near_groups/v2.json`。"""
    p = Path(path) if path else DEFAULT_PATH
    return _load(str(p), p.stat().st_mtime)


def expand_refs(groups: dict, book: str | None = None, path: str | Path | None = None) -> dict:
    """同 `NearRegistry.expand`；没写 `ref` 时不读表、原样返回。"""
    if not any(isinstance(s, dict) and "ref" in s for s in (groups or {}).values()):
        return groups
    return load(path).expand(groups, book)
