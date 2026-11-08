"""参校本属性 `reference_profile` 与书级 5b 字表 `rare_charset`（册配置，2026-11-08）。

设计：ai-team `domain/CV/设计/参校本属性/`（总设计 A31，A 块 A20）。Sheldon 11-07：「没有参校本是这整册书一个确定的属性，
要让大部分算法都能处理」——所以「这页有没有参照、什么形态」写成册配置里**由人写的确定属性**，各步按它分支，
不再从「对不上」反推。

册 yaml 写法：

    reference_profile:
      default: none            # 没点名的页；不写 default ＝ column
      segments:
        - pages: ["35-64"]     # 页号写法同 page_kinds（整数或 "10-380"）
          kind: text           # column（逐列本）| text（不分行全文）| none（无参照）
          ref: wiki            # references[] 里某项的 label 或 file；不写＝references[0]
          note: 职名、凡例
    reference_profile: none    # 简写：整册同一形态，等于 {default: none}

- 段上**不收 `quality`**：参校本质量只在 `references[].quality` 写一处，段用 `ref:` 指过去。
- **未声明**（三层都没写）：每页 `kind_of` 返回 `column`、`declared=False`。读它的步必须把 `column` 实现成
  「今天的行为，逐字节不变」，只给 `text`／`none` 加分支，所以旧书产物不变。
- **不要把 `reference_profile`／`rare_charset` 放进 `StepSpec.book_deps`**：`_self_payload` 把 book_deps 整份写进
  指纹，加一个键＝该步所有册指纹都变（值是 None 也变）。要进指纹就学 `bin_input`：只在声明了非 column 的页加键
  （`page_token`）。
- 分层：基础配置 `book_defaults.yaml` 只许写 `default`（或标量），不许写 `segments`（页号按册）；册 yaml、运行覆盖都可写。
  各层先 `normalize_layer` 把标量归一成 `{default: x}` 再合并，所以册 yaml 只写 `segments` 时继承基础配置的 `default`。

`rare_charset`（书级，字符串）：Step5-b 生僻字候选的语料字表文件（路径同 `references[].file`，按 `corpus_path` 解析），
与参校本脱钩——无参照的书／页也有一份按书的字表（如全书语料），不当参校本用。不写＝照旧取 `references[0].file`，
再退回总目语料（`align_ref.book_corpus`）。本模块只定键名、读取与解析；Step5-b 接线是 C 块的事。

本模块在 core，只放数据与纯函数，不 import steps；不在任何 Step 的 `code_deps` 里，改它不动指纹。
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: 参照形态。顺序即显示顺序。
KINDS = ("column", "text", "none")
#: 未声明时每页的形态（＝今天的行为）
DEFAULT_KIND = "column"
_TOP_KEYS = frozenset({"default", "segments"})
_SEG_KEYS = frozenset({"pages", "kind", "ref", "note"})


@dataclass(frozen=True)
class RefSegment:
    pages: tuple[int, ...]          # 已展开
    kind: str
    ref: int | None = None          # references[] 下标；none 段为 None
    note: str = ""
    expr: tuple = ()                # yaml 原样的页号表达式（显示用）


@dataclass(frozen=True)
class RefProfile:
    declared: bool = False
    default: str = DEFAULT_KIND
    segments: tuple[RefSegment, ...] = ()
    #: 未声明段、`default` 是 column／text 时用的参校本下标（references 为空时 None）
    default_ref: int | None = None
    _index: dict = field(default_factory=dict, compare=False, repr=False)

    def __post_init__(self) -> None:
        idx: dict[int, RefSegment] = {}
        for s in self.segments:
            for p in s.pages:
                idx[p] = s
        object.__setattr__(self, "_index", idx)

    def segment_of(self, page: int) -> RefSegment | None:
        return self._index.get(int(page))

    def kind_of(self, page: int) -> str:
        s = self._index.get(int(page))
        return s.kind if s else self.default

    def ref_index(self, page: int) -> int | None:
        """这页用 `references[]` 的第几份；无参照页 None。"""
        s = self._index.get(int(page))
        if s:
            return s.ref
        return None if self.default == "none" else self.default_ref

    def ref_of(self, page: int, references: list[dict]) -> dict | None:
        i = self.ref_index(page)
        return references[i] if i is not None and i < len(references) else None

    def pages_of(self, kind: str, all_pages) -> list[int]:
        if kind not in KINDS:
            raise ValueError(f"未知参照形态 {kind!r}，只认 {'、'.join(KINDS)}")
        return sorted(int(p) for p in all_pages if self.kind_of(p) == kind)

    def page_token(self, page: int) -> str | None:
        """进指纹用：声明了非 column 的页给 `"<kind>:<ref>"`，其余（含未声明）None——不写键，指纹逐位不变。"""
        if not self.declared:
            return None
        k = self.kind_of(page)
        if k == DEFAULT_KIND:
            return None
        return f"{k}:{self.ref_index(page)}"

    def summary(self, all_pages) -> dict:
        out = {"declared": self.declared, **{k: 0 for k in KINDS}}
        for p in all_pages:
            out[self.kind_of(p)] += 1
        return out


UNDECLARED = RefProfile()


def normalize_layer(raw):
    """一层配置里的 `reference_profile` 原样值 → 合并前的规范形（标量 → `{default: x}`）。None 原样返回（＝回到未声明）。
    只查形状，不查与 references 的关系（那要等各层合完）。"""
    if raw is None:
        return None
    if isinstance(raw, str):
        _check_kind(raw, "reference_profile")
        return {"default": raw}
    if not isinstance(raw, dict):
        raise ValueError("reference_profile: 要写成 column／text／none，或 {default: …, segments: [...]}")
    bad = sorted(set(map(str, raw)) - _TOP_KEYS)
    if bad:
        raise ValueError(f"reference_profile: 不认识 {', '.join(bad)}，只认 default、segments")
    return dict(raw)


def fold_layer(name: str, layer: dict, *, allow_segments: bool = True) -> dict:
    """一层配置里的 `reference_profile` 归一（返回新字典；这层没写就原样返回）。基础配置传 `allow_segments=False`。"""
    if "reference_profile" not in layer:
        return layer
    try:
        rp = normalize_layer(layer["reference_profile"])
    except ValueError as e:
        raise ValueError(f"{name}：{e}") from None
    if not allow_segments and rp and rp.get("segments"):
        raise ValueError(f"{name}：reference_profile.segments 不许写在基础配置里（页号按册），只能写 default")
    out = dict(layer)
    out["reference_profile"] = rp
    return out


def load_reference_profile(raw, references: list[dict] | None = None) -> RefProfile:
    """合并好的 `reference_profile`（`normalize_layer` 之后的形）＋`references` → `RefProfile`。写错就报，不猜。"""
    refs = list(references or [])
    raw = normalize_layer(raw)
    if not raw:
        return RefProfile(declared=False, default_ref=0 if refs else None)
    from .book import _expand_pages
    default = raw.get("default", DEFAULT_KIND)
    _check_kind(default, "reference_profile.default")
    default_ref = None
    if default != "none":
        default_ref = _resolve_ref(None, refs, f"reference_profile.default: {default}")
    segs_raw = raw.get("segments") or []
    if not isinstance(segs_raw, list):
        raise ValueError("reference_profile.segments: 要写成列表，每项 {pages, kind, ref?, note?}")
    segs: list[RefSegment] = []
    owner: dict[int, int] = {}
    for i, s in enumerate(segs_raw, 1):
        where = f"reference_profile.segments 第 {i} 段"
        if not isinstance(s, dict):
            raise ValueError(f"{where}: 要写成 {{pages, kind, ref?, note?}}")
        extra = sorted(set(map(str, s)) - _SEG_KEYS)
        if extra:
            why = "（参校本质量只写在 references[].quality，段上用 ref: 指过去）" if "quality" in extra else ""
            raise ValueError(f"{where}: 不认识 {', '.join(extra)}{why}，只认 pages、kind、ref、note")
        if "pages" not in s or "kind" not in s:
            raise ValueError(f"{where}: pages、kind 都要写")
        expr = s["pages"]
        if isinstance(expr, (int, str)) and not isinstance(expr, bool):
            expr = [expr]
        if not isinstance(expr, (list, tuple)) or not expr or any(
                isinstance(p, bool) or not isinstance(p, (int, str)) for p in expr):
            raise ValueError(f"{where}: pages 要写成页号列表（整数或 \"10-380\" 这样的字符串）")
        try:
            pages = tuple(_expand_pages(list(expr)))
        except ValueError as e:
            raise ValueError(f"{where}: 页号写错了：{e}") from None
        kind = s["kind"]
        _check_kind(kind, f"{where}.kind")
        if kind == "none":
            if s.get("ref") is not None:
                raise ValueError(f"{where}: kind: none 的段不能写 ref")
            ref = None
        else:
            ref = _resolve_ref(s.get("ref"), refs, f"{where}（kind: {kind}）")
            if kind == "column" and refs[ref].get("line_is_column") is False:
                raise ValueError(f"{where}: kind: column 指向的参校本 {_ref_name(refs[ref])} 写着 line_is_column: false，自相矛盾")
        for p in pages:
            if p in owner:
                raise ValueError(f"{where}: 第 {p} 页已在第 {owner[p]} 段里，段与段不能重叠")
            owner[p] = i
        segs.append(RefSegment(pages=pages, kind=kind, ref=ref, note=str(s.get("note") or ""), expr=tuple(expr)))
    if default == "column" and default_ref is not None and refs[default_ref].get("line_is_column") is False:
        raise ValueError(f"reference_profile.default: column 指向的参校本 {_ref_name(refs[default_ref])} "
                         f"写着 line_is_column: false，自相矛盾")
    return RefProfile(declared=True, default=default, segments=tuple(segs), default_ref=default_ref)


def lint(book, all_pages=None) -> list[str]:
    """体检提示（不拦跑）：`book show`、manager 的册体检用。"""
    prof: RefProfile = getattr(book, "reference_profile", UNDECLARED)
    refs = getattr(book, "references", None) or []
    pages = list(all_pages) if all_pages is not None else book.all_pages()
    out: list[str] = []
    if not prof.declared:
        if not refs:
            out.append("没写 reference_profile、references 也为空：对位与 5b 字表会退回四库总目语料；"
                       "无参照的册请写 reference_profile: none（或配 references）")
        return out
    if pages:
        pset = set(pages)
        for i, s in enumerate(prof.segments, 1):
            out_of = [p for p in s.pages if p not in pset]
            if out_of:
                out.append(f"reference_profile 第 {i} 段有 {len(out_of)} 页不在本册页集里（如 {out_of[0]}）")
    if refs and prof.default == "none" and all(s.kind == "none" for s in prof.segments):
        out.append("配了 references，但 reference_profile 没有一页用它")
    if len(refs) > 1 and prof.default != "none":
        out.append("references 有多份，default 用的是 references[0]：建议把有参照的页写成段并写明 ref:，别靠 references 的顺序")
    skip = set()
    pk = getattr(book, "page_kinds", None) or {}
    if pk.get("cover") or pk.get("table"):
        from .book import _expand_pages
        skip = set(_expand_pages(list(pk.get("cover") or []) + list(pk.get("table") or [])))
    hit = sorted(p for p in skip if prof.kind_of(p) != "none" and prof.segment_of(p) is not None)
    if hit:
        out.append(f"page_kinds 的 cover／table 页整页跳过，reference_profile 给它们写形态没有用（如第 {hit[0]} 页）")
    return out


# ── 给 B 块（align_ref／row_segment）用的翻译 ─────────────────────────
def _book_pages(book, pages):
    return list(pages) if pages is not None else book.all_pages()


def ref_none_pages(book, pages=None) -> list[int]:
    """本册声明为无参照（kind: none）的页；未声明的册返回空表（行为照旧）。`pages` 给了只在其中挑。"""
    prof: RefProfile = getattr(book, "reference_profile", UNDECLARED)
    if not prof.declared:
        return []
    return prof.pages_of("none", _book_pages(book, pages))


def ref_text_pages(book, pages=None) -> list[int]:
    """本册声明为不分行全文参照（kind: text）的页；未声明的册返回空表（行为照旧）。"""
    prof: RefProfile = getattr(book, "reference_profile", UNDECLARED)
    if not prof.declared:
        return []
    return prof.pages_of("text", _book_pages(book, pages))


# ── 书级 5b 字表 ─────────────────────────────────────────────────────
def load_rare_charset(raw) -> str | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str):
        raise ValueError("rare_charset: 要写成语料文件名（同 references[].file，如 qtw_kanripo.txt）")
    return raw.strip() or None


def rare_charset_path(book) -> str | None:
    """`rare_charset` 解析成的语料文件路径（`corpus_path`）；没写 None（调用方照旧走 `align_ref.book_corpus`）。"""
    name = getattr(book, "rare_charset", None)
    if not name:
        return None
    from .workspace import corpus_path
    return str(corpus_path(name))


# ── 内部 ─────────────────────────────────────────────────────────────
def _check_kind(v, where: str) -> None:
    if v not in KINDS:
        raise ValueError(f"{where}: 未知参照形态 {v!r}，只认 {'、'.join(KINDS)}")


def _ref_name(r: dict) -> str:
    return str(r.get("label") or r.get("file") or "?")


def _resolve_ref(ref, refs: list[dict], where: str) -> int:
    if not refs:
        raise ValueError(f"{where}: 有参照的页要先在 references 里配参校本（references 为空）")
    if ref is None:
        return 0
    ref = str(ref)
    hits = [i for i, r in enumerate(refs) if ref in (str(r.get("label") or ""), str(r.get("file") or ""))]
    if not hits:
        raise ValueError(f"{where}: ref {ref!r} 在 references 里按 label／file 都找不到")
    if len(hits) > 1:
        raise ValueError(f"{where}: ref {ref!r} 在 references 里对上 {len(hits)} 项，写个唯一的 label")
    return hits[0]
