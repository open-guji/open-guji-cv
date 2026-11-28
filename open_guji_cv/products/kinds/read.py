"""第三步识字的新产物（2026-11-27，Sheldon 11-26 定的第三步重构）：3b `glyph_near`、3c `glyph_candidate`、
3d `cell_traits`、3e `glyph_vis`、收尾 `glyph_analyzer`。

设计见 ai-team 《第三步识字重构设计》（https://claude.ai/artifact/EdSn56RuC1viVHFpafy5Fz）：
- 3a `glyph_match` 出候选与相似度；
- 3b `glyph_near` 只处理触发了形近字组的格，按组登记的方法给组内每个字一个新的分（`sims`）＋证据，不定字；
- 收尾 `glyph_analyzer` 把各小步汇总成 `cands`（字＋p＋证据）与 `p_map`（切断、混边框等其他特征的概率），
  第三步不判断放不放行，第四步只读这里的 p。

单独放一个文件（不写进 `recog.py`）：`recog.py` 是现役几步的产物定义，动它会牵连那几步。都是 numeric。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_serializer

from ...core.spec import COLUMN_PX, ProductKindSpec
from ...core.step import register_kind


class NearMethodOut(BaseModel):
    """3b 一个方法对一格的输出：组内各字的分（这个方法自己的尺度，未校准），外加证据。"""
    method: str                                   # 「方法:组」，如 cnn_small:gong
    sims: dict[str, float] = Field(default_factory=dict)
    evidence: dict = Field(default_factory=dict)


class NearRec(BaseModel):
    """3b 一格在**一个**字组下的结果。一格触发几个组就有几条（同 `id`、不同 `group`，按组 id 排序紧挨着放；2026-11-28 起，
    之前一格只进按组 id 排第一个触发的组）。"""
    id: str
    slot: int
    sub: str | None = None
    group: str                                    # 触发的字组 id
    trigger: str = ""                             # 怎么触发的：member（首位在组里）／close（组内两字分差在 δ 内）
    methods: list[NearMethodOut] = Field(default_factory=list)


class ColumnNear(BaseModel):
    col: int
    chars: list[NearRec] = Field(default_factory=list)


class PageNear(BaseModel):
    page: int
    #: 各组各方法的模型目录指纹（`GlyphNearParams.methods_sha`）。写进产物，换校准表时 sims 不变、产物 sha 也会变，
    #: 收尾 `glyph_analyzer` 跟着过期
    methods_sha: str = ""
    columns: list[ColumnNear] = Field(default_factory=list)
    #: 本页跑过的方法用的模型版本 {"方法:组": 模型 sha}（方法的 `model_sha`；rr_shape 等从第四步搬来的判法与第四步
    #: 参数指纹里那一段同算法，如 rr_shape＝模型文件 sha256 前 16 位，4d 拿它对书配置 `group_flow_rr_shape`）。空的不落盘
    models: dict[str, str] = Field(default_factory=dict)
    #: 书配置挂了、但登记表该组 `handling.methods` 不允许、3b 过渡期跳过的方法「组:方法」（2026-11-28；见 `steps/glyph_near.py`
    #: 模块头「守登记表的 handling.methods」）。空的不落盘
    skipped_methods: list[str] = Field(default_factory=list)

    @model_serializer(mode="wrap")
    def _drop_empty_models(self, handler):
        d = handler(self)
        if isinstance(d, dict):
            for k in ("models", "skipped_methods"):
                if not d.get(k):
                    d.pop(k, None)
        return d

    def by_id_all(self) -> dict[str, list[NearRec]]:
        """{格 id: [NearRec…]}，一格触发的每个组一条，按组 id 排序。"""
        out: dict[str, list[NearRec]] = {}
        for c in self.columns:
            for r in c.chars:
                out.setdefault(r.id, []).append(r)
        return {k: sorted(v, key=lambda r: r.group) for k, v in out.items()}

    def get(self, cell_id: str, group: str) -> NearRec | None:
        """某格在某组下的 NearRec；这格没触发这个组 → None。"""
        for c in self.columns:
            for r in c.chars:
                if r.id == cell_id and r.group == group:
                    return r
        return None


class CandRec(BaseModel):
    """3c 一格的按图候选：[字, 余弦]，已按分降序；`fam_of` 记哪些字是按异体族并进来的（并进来的字→它所属的头名字）。"""
    id: str
    slot: int
    sub: str | None = None
    ran: bool = True
    cands: list[list] = Field(default_factory=list)        # [[字, 分], …]，最多 topk 个
    fam_of: dict[str, str] = Field(default_factory=dict)


class ColumnCand(BaseModel):
    col: int
    chars: list[CandRec] = Field(default_factory=list)


class PageCand(BaseModel):
    page: int
    #: 向量模型与字表包的版本，如 "r5@d2ce8bab+emb-807344bd"；写进产物，换模型或换字表包本步与收尾就过期
    model: str = ""
    columns: list[ColumnCand] = Field(default_factory=list)

    def by_id(self) -> dict[str, CandRec]:
        return {r.id: r for c in self.columns for r in c.chars}


class FinalCand(BaseModel):
    """收尾的一个候选：字、校准后的 p（还没有校准来源的为 None）、各小步的证据（a／b／c 键）。"""
    char: str
    p: float | None = None
    evidence: dict = Field(default_factory=dict)


class FinalRec(BaseModel):
    id: str
    slot: int
    sub: str | None = None
    cands: list[FinalCand] = Field(default_factory=list)
    #: 其他特征的概率：cut（字被切断）、border（混入边框）、residue（混入上下字残留）、stain（背景污染）…
    #: 只放有校准来源的键，没有就不写；以后加键不改格式。
    p_map: dict[str, float] = Field(default_factory=dict)
    #: p 从哪来，如 "near:cnn_small:gong"；没有任何校准来源时为空串
    p_src: str = ""
    #: 真字不在 `cands` 里的概率（「都不对」）。要通用打分器（设计第 5 期）才给得出，现在恒 None、不落盘；
    #: 不从 `p_map` 推，也不拿 1−Σp 顶（组内校准的 p 只在组内归一）
    p_other: float | None = None
    #: 3d `cell_traits` 的原始分 {键: 分}（cut、border、residue、stain、merged、blank…；未校准、**不是概率**，
    #: 标定以后才进 `p_map`）。3d 没跑为空，空的不落盘（没开 3d 的书收尾产物逐字节不变）。
    traits: dict[str, float] = Field(default_factory=dict)
    #: 3b 触发了的格，按组：`{组: {trigger, methods: {方法名: {method, …方法证据原样, model}}, [p, p_src]}}`（2026-11-28 一格多组起；
    #: 给 4d 取看图判法结果，rr_shape 的证据是 `{char, why, nn, score, geo}`，与第四步 `rr_shape.judge()` 同键同值）。
    #: 这组有方法出了校准 p 才有 `p`（{字: p}）与 `p_src`（`near:方法:组`，表写了 `version` 再接 `@版本`）；只有临时校准表
    #: （`temporary: true`，只给排序展示）出 p 的组改写 `p_tmp`／`p_tmp_src`，不写 `p`。没触发为空，空的不落盘。
    #: 读旧文件（之前是一格一组的 `{group, trigger, methods}`）用 `near_groups()`，两种都认
    near: dict = Field(default_factory=dict)
    #: 3e `glyph_vis`（看图大模型，只看图）这一格的结论：`{group, trigger, status, char, other, conf, why, model, prompt_sha,
    #: cache_hit, legacy, img_sha}`（几个组都触发时另有 `groups`）。**不是概率、不出 p**；答出字时那个候选另有
    #: `evidence.v = {conf, model, prompt_sha, cache_hit, legacy}`。没跑、没触发为空，空的不落盘（没开 3e 的书收尾产物逐字节不变）
    vis: dict = Field(default_factory=dict)

    def near_groups(self) -> dict[str, dict]:
        """`near` 按组 → `{组: {trigger, methods, …}}`；旧形状（`{group, trigger, methods}`，glyph_analyzer 0.1）也转成这样。"""
        n = self.near or {}
        if isinstance(n.get("group"), str) and isinstance(n.get("methods"), dict):
            return {n["group"]: {"trigger": n.get("trigger", ""), "methods": n["methods"]}}
        return n

    @model_serializer(mode="wrap")
    def _drop_empty_traits(self, handler):
        d = handler(self)
        if isinstance(d, dict):
            if not d.get("traits"):
                d.pop("traits", None)
            if not d.get("near"):
                d.pop("near", None)
            if not d.get("vis"):
                d.pop("vis", None)
            if d.get("p_other") is None:
                d.pop("p_other", None)
        return d


class TraitRec(BaseModel):
    """3d 一格的其他特征：每键一个原始分（0～1，0.5≈现行判法的门槛，未校准），`evidence` 按键放子判据的分与原始量。
    键与判法见 `clustering/cell_traits.py` 模块头。"""
    id: str
    slot: int
    sub: str | None = None
    scores: dict[str, float] = Field(default_factory=dict)
    evidence: dict = Field(default_factory=dict)


class ColumnTraits(BaseModel):
    col: int
    chars: list[TraitRec] = Field(default_factory=list)


class PageTraits(BaseModel):
    page: int
    model: str = ""                               # 判法口径版本，如 cell-traits/0
    columns: list[ColumnTraits] = Field(default_factory=list)

    def by_id(self) -> dict[str, TraitRec]:
        return {r.id: r for c in self.columns for r in c.chars}


class VisRec(BaseModel):
    """3e `glyph_vis` 一格：大模型只看字块图（不给前后文、不给整理本）在候选里判的「刻形像哪个」。只列触发了的格。"""
    id: str
    slot: int
    sub: str | None = None
    group: str                                    # 取候选的组（几个组都触发时按组 id 第一个）
    groups: list[str] = Field(default_factory=list)   # 触发的全部组（按组 id 排）
    trigger: list[str] = Field(default_factory=list)  # near_abstain／near_split／near_margin／a_margin／p_low
    cands: list[str] = Field(default_factory=list)    # 送给模型的候选（码位排序，不含「其他」）
    img_sha: str = ""
    status: str = ""                              # hit／asked／pending／error:<码>／skipped:<原因>
    char: str | None = None                       # 候选字；「其他」或没答为 None
    other: bool = False
    conf: str | None = None                       # high／mid／low（大模型自报，没校准，不当概率用）
    why: str = ""
    model: str = ""                               # 命中／调用的模型值（书配置值，或对话判的 session:<名>）
    prompt_sha: str = ""
    cache_hit: bool = False
    legacy: bool = False                          # 读的是 rekey 来的旧 vis1 答案（看过前后文；只在 accept_legacy 开时）
    ask: dict | None = None                       # pending 时给离线导出用：{img_sha, prompt, prompt_sha, cands, model}


class ColumnVis(BaseModel):
    col: int
    chars: list[VisRec] = Field(default_factory=list)


class PageVis(BaseModel):
    page: int
    model: str = ""                               # 判法口径版本，如 glyph-vis/0
    prompt: str = ""
    prompt_sha: str = ""
    #: 本书看图缓存（`<feedback>/vis_glyph/` 全部 vis_glyph 事件）的哈希：**只记录、不进指纹**，导了新答案要从 glyph_vis 起 force
    cache_pin: str = ""
    columns: list[ColumnVis] = Field(default_factory=list)
    usage: dict = Field(default_factory=dict)     # calls／hits／pending／errors／skipped／in／out

    def by_id(self) -> dict[str, VisRec]:
        return {r.id: r for c in self.columns for r in c.chars}


class ColumnFinal(BaseModel):
    col: int
    chars: list[FinalRec] = Field(default_factory=list)


class PageFinal(BaseModel):
    page: int
    model: str = ""                               # 收尾口径版本，如 glyph-analyzer/0
    columns: list[ColumnFinal] = Field(default_factory=list)

    def by_id(self) -> dict[str, FinalRec]:
        return {r.id: r for c in self.columns for r in c.chars}


GLYPH_CANDIDATE = register_kind(ProductKindSpec(
    id="glyph_candidate", title="3c 按图候选", storage="numeric", unit="cell",
    schema=PageCand, coord_space=COLUMN_PX))

GLYPH_NEAR = register_kind(ProductKindSpec(
    id="glyph_near", title="3b 形近字组分析", storage="numeric", unit="cell",
    schema=PageNear, coord_space=COLUMN_PX))

CELL_TRAITS = register_kind(ProductKindSpec(
    id="cell_traits", title="3d 字块图其他特征", storage="numeric", unit="cell",
    schema=PageTraits, coord_space=COLUMN_PX))

GLYPH_VIS = register_kind(ProductKindSpec(
    id="glyph_vis", title="3e 看图大模型（条件）", storage="numeric", unit="cell",
    schema=PageVis, coord_space=COLUMN_PX))

GLYPH_ANALYZER = register_kind(ProductKindSpec(
    id="glyph_analyzer", title="3 识字收尾（汇总）", storage="numeric", unit="cell",
    schema=PageFinal, coord_space=COLUMN_PX))
