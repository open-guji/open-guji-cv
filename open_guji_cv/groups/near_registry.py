"""形近字组登记表 `near_groups/2` 的读口（2026-11-28，第三步重构 W1 第一期）。

表是 `config/near_groups/v2.json`，由 `scripts/build_near_groups_v2.py` 从六处现有来源确定性生成；schema、来源与
「谁还在读旧表」见 `doc/3-识字/形近字组登记表.md`。**这一期只加读口，现役代码一处都不改读它**（第二期再迁，要 code_equiv）。

    from open_guji_cv.groups import near_registry as NR
    reg = NR.load()                     # 缺省读仓里的表；书级版本给 path
    reg.get("guan").chars               # ('官', '宫', '宮')
    reg.groups_of("宫")                 # 这个字在哪些组（注册组在前、单立字对在后）
    reg.by_type("near")                 # 按类型过滤：near（形近异义）／variant（异体，同义异码）；2026-11-28 起没有 fold
    reg.glyph_near_spec("guan", book="<书>")   # 转成 3b 书配置 groups.<组> 那种 dict
    reg.handling_of("jys")              # 本组处理方式 {methods, context, aspect, action, threshold}（2026-11-28）

## 书配置引用登记表（`ref`）

    params:
      glyph_near:
        groups:
          gong: {ref: guan, methods: {cnn_small: models/glyph_near_gong}}   # ref 之外写的键盖过登记表

`expand_refs(groups, book)` 把带 `ref` 的组展开成 3b 认的 `{chars, fold, methods, trigger, delta, topk}`（`ref` 键本身不留，
参数指纹只跟内容走）；**一个 `ref` 都没写时原样返回同一个对象**，接进 `GlyphNearParams` 后没写 `ref` 的书参数哈希逐位不变。
3b 已接线（2026-11-28）：`GlyphNearStep.book_params` 按本册 id 调 `resolve`（＝`expand_refs`＋守 `handling.methods`），
展开后重算 `methods_sha`。

## 处理方式 `handling`（2026-11-28，Sheldon 定「每组自定」）

`handling_of(组)` → `{methods, context, aspect, action, threshold}`（字段见 `doc/3-识字/形近字组登记表.md` 第三节）：
`methods` 是本组**允许**用的 3b 看图方法（[]＝不做字形区分，如 日曰、己已巳），`context`／`aspect`／`action`／`threshold`
给收尾与 4d 读。表里这组没写 `handling`（旧版书级表）→ `DEFAULT_HANDLING`（不配看图方法、不走文意、宽高比关、只出证据、门槛未定）。
**书配置优先、handling 是缺省**（Sheldon 11-28）：`handling_of(组, over=书级覆盖)`，覆盖只认 context／aspect／action／threshold，
`methods` 不许书级放宽。书级覆盖写在哪个书配置键由读它的步定（4d／收尾归 CV4），取值一律经这个函数合。

**3b 守 `handling.methods`**（`resolve`）：书配置 `glyph_near.groups` 里某组挂了不在登记表那组 `handling.methods` 里的方法——
- 哪个登记表组：写了 `ref` 就是 `ref` 指的组；没写 `ref`、写了 `chars` 的，取登记表里**包含这几个字的成员最少的组**
  （同 `scripts/build_near_groups_v2.py` 把书配置挂到组上的规则，id 序破平；殿本 `gong`＝宫宮官 → `guan`）；哪组都不包含 → 不守；
  保留伪组（`_guard`，near_knn 用）不对应登记表组，不守。
- 过渡期（`STRICT_METHODS = False`，CV4 11-28 定）：**警告、跳过这个方法并计数**（一组的方法全被跳过就整组不跑；`resolve` 返回的 skipped 列表；3b 产物
  `PageNear.skipped_methods` 记「组:方法」，日志 warning 一次）。各书配置清干净后改 `STRICT_METHODS = True`：配置载入时就报错，
  信息里写清书配置组、登记表组、方法与允许的方法。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
import logging
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[2]
DEFAULT_PATH = REPO / "config" / "near_groups" / "v2.json"
FORMAT = "near_groups/2"
TYPES = ("near", "variant")
#: 旧类型名 → 现类型（2026-11-28 Sheldon：只分 near／variant 两类；旧版书级表里的 fold 读成 near，组内异体归并在 `fold` 字段）
LEGACY_TYPES = {"fold": "near"}
#: 表里没写 `handling` 的组（旧版书级表）用这个：不配看图方法、不走文意、宽高比关、只出证据、门槛未定
DEFAULT_HANDLING = {"methods": [], "context": False, "aspect": False, "action": "evidence", "threshold": None}
#: 书配置挂了 `handling.methods` 以外的方法：False＝警告、跳过、计数（过渡期，CV4 11-28 定）；True＝载入时报错
STRICT_METHODS = False
ACTIONS = ("admit", "evidence")
#: 书级可以覆盖的 handling 键（`handling_of(组, over)`）；methods 不在内
BOOK_OVERRIDE_KEYS = ("context", "aspect", "action", "threshold")
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
    handling: dict = field(default_factory=lambda: dict(DEFAULT_HANDLING))
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
            typ = LEGACY_TYPES.get(typ, typ)
            if typ not in TYPES:
                raise ValueError(f"组 {gid} 的 type 不认识：{typ!r}（应为 {TYPES}）")
            ng = NearGroup(id=gid, chars=tuple(g.get("chars") or ()), type=typ, methods=tuple(g.get("methods") or ()),
                           fold=dict(g.get("fold") or {}), src=tuple(g.get("src") or ()), books=dict(g.get("books") or {}),
                           handling=_handling(g.get("handling")), raw=g)
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
            raise ValueError(f"不认识的类型 {sorted(bad)}（应为 {TYPES}；fold 2026-11-28 已取消，归 near）")
        return [g for g in self.groups.values() if g.type in types]

    def handling_of(self, gid: str, over: dict | None = None) -> dict:
        """本组处理方式 `{methods, context, aspect, action, threshold}`（新 dict，`methods` 是 list；人定表写了 note 的另带 `note`）。
        组不在表里报 KeyError。

        `over`：书级覆盖（**书配置优先、登记表 handling 是缺省**，Sheldon 11-28）：只认 `BOOK_OVERRIDE_KEYS`
        （context／aspect／action／threshold），写了的键盖过登记表；`methods` 不许书级放宽（3b 守的就是它），写了报错。"""
        h = self.get(gid).handling
        out = {**h, "methods": list(h["methods"])}
        for k, v in (over or {}).items():
            if k not in BOOK_OVERRIDE_KEYS:
                raise ValueError(f"组 {gid} 的书级 handling 覆盖不认识的键 {k!r}（可写 {BOOK_OVERRIDE_KEYS}；methods 只能改登记表）")
            if k in ("context", "aspect") and not isinstance(v, bool):
                raise ValueError(f"组 {gid} 的书级 handling 覆盖 {k} 要写 true／false：{v!r}")
            if k == "action" and v not in ACTIONS:
                raise ValueError(f"组 {gid} 的书级 handling 覆盖 action {v!r} 不认识（应为 {ACTIONS}）")
            if k == "threshold" and v is not None and (isinstance(v, bool) or not isinstance(v, (int, float))):
                raise ValueError(f"组 {gid} 的书级 handling 覆盖 threshold 要写数或 null：{v!r}")
            out[k] = v
        return out

    def match_chars(self, chars) -> str | None:
        """书配置里没写 `ref` 的组按 `chars` 对到登记表组：包含这几个字的成员最少的组（id 序破平）；哪组都不包含 → None。"""
        want = set(chars or ())
        if not want:
            return None
        hit = set(self._by_char.get(next(iter(want)), ()))
        for c in want:
            hit &= set(self._by_char.get(c, ()))
        return min(hit, key=lambda x: (len(self.groups[x].chars), x)) if hit else None

    def registry_group_of(self, name: str, spec) -> str | None:
        """书配置 `glyph_near.groups.<name>` 守哪个登记表组的 `handling`：`ref` 指的组；没 `ref` 按 `chars` 对；伪组 → None。"""
        if name.startswith("_") or not isinstance(spec, dict):
            return None
        if "ref" in spec:
            return str(spec["ref"])
        return self.match_chars(spec.get("chars"))

    def check_methods(self, groups: dict, strict: bool | None = None) -> list[tuple[str, str, str]]:
        """书配置（展开 `ref` 之前的）`glyph_near.groups` 里挂了登记表组 `handling.methods` 以外的方法 → [(书配置组, 登记表组, 方法)]，
        按书配置组、方法排序。`strict`（缺省 `STRICT_METHODS`）为真时有一条就报 ValueError。"""
        bad: list[tuple[str, str, str]] = []
        for name, spec in sorted((groups or {}).items()):
            gid = self.registry_group_of(name, spec)
            if gid is None:
                continue
            allowed = set(self.get(gid).handling["methods"])
            for m in sorted((spec.get("methods") or {})):
                if m not in allowed:
                    bad.append((name, gid, m))
        if bad and (STRICT_METHODS if strict is None else strict):
            raise ValueError("glyph_near：书配置给形近字组挂了登记表 handling.methods 以外的方法（config/near_groups/handling.json）："
                             + "；".join(f"组 {n}（登记表 {g}，允许 {sorted(self.get(g).handling['methods'])}）挂了 {m}"
                                        for n, g, m in bad))
        return bad

    def resolve(self, groups: dict, book: str | None = None, strict: bool | None = None) -> tuple[dict, list]:
        """书配置 `glyph_near.groups` → (展开 `ref`、去掉 `handling.methods` 以外方法后的 dict, 跳过的 [(书配置组, 登记表组, 方法)])。
        一组挂的方法全被跳过时整组去掉。没有要跳过的方法时等于 `expand`（一个 `ref` 都没有就原样返回同一个对象）。"""
        bad = self.check_methods(groups, strict)
        if bad:
            drop: dict[str, set] = {}
            for n, _, m in bad:
                drop.setdefault(n, set()).add(m)
            out = {}
            for n, s in groups.items():
                if n in drop:
                    left = {k: v for k, v in (s.get("methods") or {}).items() if k not in drop[n]}
                    if not left:
                        continue                 # 这组挂的方法全被跳过：整组不跑（不出只有触发、没有方法的空记录）
                    s = {**s, "methods": left}
                out[n] = s
            groups = out
            log.warning("glyph_near%s：跳过 %d 个登记表 handling.methods 以外的方法：%s", f"（{book}）" if book else "",
                        len(bad), "、".join(f"{n}:{m}（登记表 {g}）" for n, g, m in bad))
        return self.expand(groups, book), bad

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
            if name.startswith("_") and isinstance(spec, dict) and "ref" in spec:
                raise ValueError(f"glyph_near 组 {name!r} 是保留伪组（如 `_guard`），不引用登记表，不写 ref")
            if isinstance(spec, dict) and "ref" in spec:
                out[name] = self.glyph_near_spec(str(spec["ref"]), book, **{k: v for k, v in spec.items() if k != "ref"})
            else:
                out[name] = spec
        return out


def _handling(h) -> dict:
    """表里一组的 `handling` → 补齐键的 dict（缺键取 `DEFAULT_HANDLING`；`methods` 存成 tuple）。"""
    out = {**DEFAULT_HANDLING, **dict(h or {})}
    out["methods"] = tuple(out.get("methods") or ())
    return out


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> NearRegistry:
    return NearRegistry(json.loads(Path(path).read_text(encoding="utf-8")), path)


def load(path: str | Path | None = None) -> NearRegistry:
    """读登记表（按文件修改时间缓存）。缺省读仓里的 `config/near_groups/v2.json`。"""
    p = Path(path) if path else DEFAULT_PATH
    return _load(str(p), p.stat().st_mtime)


def resolve(groups: dict, book: str | None = None, path: str | Path | None = None,
            strict: bool | None = None) -> tuple[dict, list]:
    """同 `NearRegistry.resolve`；`groups` 空时不读表、原样返回。"""
    if not groups:
        return groups, []
    return load(path).resolve(groups, book, strict)


def handling_of(gid: str, over: dict | None = None, path: str | Path | None = None) -> dict:
    """同 `NearRegistry.handling_of`（`over`＝书级覆盖），读缺省（或 `path`）的表。"""
    return load(path).handling_of(gid, over)


def expand_refs(groups: dict, book: str | None = None, path: str | Path | None = None) -> dict:
    """同 `NearRegistry.expand`；没写 `ref` 时不读表、原样返回。"""
    if not any(isinstance(s, dict) and "ref" in s for s in (groups or {}).values()):
        return groups
    return load(path).expand(groups, book)
