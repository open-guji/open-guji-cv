"""IDS 路在线判别（字组统一流程 `group_flow` 的 `ids` 解法，方案 S7，2026-10-18 sheldon 定接进流水线）。

一格字块灰度图 → 自动缝切开 → 决定字的那一段在**冻结模板库**里最近邻 → margin 够、该类刻例够才给字，否则弃权。
算法就是离线评测用的 `ids_two.solve_two`（參㕘叅 ⿱厽X 一刀），本模块只做三件事：

1. **每组判法**（`SPECS`）：切向、缝先验、拼 IDS 的框、门槛（`min_margin`、每类至少 `min_class` 个刻例才许给该类）。
   门槛由人标池留一评测定（`python -m open_guji_cv.groups.ids_online loo <组> --dataset <dataset>`），目标给字格 0 错。
   没在这里登记的组（或登记了但没有模板库）→ 一律弃权 `abstain:no_bank`，流程照旧往下走。
2. **模板库冻结成文件**：从 dataset 人标池（`char-groups/variant/<组>/labels.jsonl` ＋ `crops/`）离线建，
   每个模板是归一化 32×32 墨迹图量化成 uint8，存 json（base64，键排序，可复现）。位置按顺序找：
   工作区 `config/groups/ids/<组>.json`（某书自己的池）→ 仓里 `config/groups/<组>/ids_bank.json`（殿本池）。
   建库是一次显式动作：`python -m open_guji_cv.groups.ids_online build <组> --dataset <dataset>`。
3. **指纹**：`fingerprint(组…)` ＝ 每组「判法参数＋模板库内容哈希＋`ids_override.tsv`＋`ids_lv1.txt`」的哈希，
   进 `seed_admit.group_flow_fingerprint`；扩池重建模板库 → 开了的册判过期，不开的册不受影响。

输入的字块与人标池同源：池里的 `crops/` 是二值页按 `bbox_page` 重裁，在线是 Step4 `char_patch`（灰度），
两边过 `ink_of`（<128）后墨迹几乎一致（vol04 同格实测 IoU 0.997–1.0），所以模板直接复用。
分层 L2：只依赖 numpy、PIL（经 `ids_parts`）与 `core.workspace`。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
from collections import Counter
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from .protocol import GroupVerdict

VERSION = 1
_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class IdsSpec:
    """一组的在线 IDS 判法（两段版，见 `ids_two`）。"""
    frame: str                  # 拼 IDS 的框，如 `⿱厽{}`
    orient: str                 # "h" 上下切／"v" 左右切
    prior: float                # 自动缝的先验位置（占图高／宽）
    which: int = 1              # 决定字的是第几段（1＝下／右）
    min_margin: float = 0.02    # 第一名减第二名不到这个数就弃权
    min_class: int = 8          # 某类模板（真实刻例）少于这个数，判成它也弃权
    by_form: bool = False       # True：模板按成员字分类（不经 IDS 拼字），切下的那一段直接和各字的同段比；
                                # 用于两字差别不落在同一 IDS 部件上的异体对（叙敘、冊册、教敎，2026-10-20）
    three: bool = False         # True：彝组三段版（`ids_solver.solve`）：自动缝切上／中／下三段、中段再竖切取右半，
                                # 每段二选一后拼 `⿳上⿰米X下` 交 IdsResolver；任一段 margin 不够整格弃权
    top_hog: float | None = None  # 三段版：给了数，上段（彑／彐）改用窗口 HOG＋岭回归（不依赖上／中缝），|判别值| 不到它弃权
    nearest_ok: bool = False      # 三段版：IDS 无对应码位只能归近似字（nearest_variant 旗）时照样给字（彝：彑米糸大 ≡ 𢑴，sheldon 10-20 定）
    bot_hog: float | None = None  # 三段版：同上，下段（廾／大）用下部窗口 HOG＋岭回归
    mid_hog: float | None = None  # 三段版：给了数，中段（糸／分）改用 HOG＋岭回归判别，|判别值| 不到它弃权（上下段仍用 min_margin）
    whole: str = ""             # "pix"|"hog"：整字二类岭回归（`ids_whole`，不切缝；差别不在缝两侧的两字异体：呂吕、徵徴），
                                # `min_margin` 当作判别值绝对值的门槛；非空时 frame/orient/prior/which 不用
    region: tuple = (0.0, 1.0, 0.0, 1.0)  # 整字版：取归一字块的哪一块（占宽高的 x0,x1,y0,y1）
    lam: float = 1.0            # 整字版：岭回归的 L2 系数
    size: int = 32              # 整字版：模板与在线字块归一后的边长（模板库里也写一份）


#: 已过离线评测、允许在线给字的组。每组的门槛与评测数字写在该行注释里（重评：`loo` 子命令）。
SPECS: dict[str, IdsSpec] = {
    # 參㕘叅：人标池 74 格（參 35／㕘 37／叅 2），自动缝。留一：margin 0.02 → 65 对／9 弃权／0 错，0.04 → 59／15／0；
    # 留一册（模板不含本册）：0.02 → 64／10／0，0.04 → 57／17／0；不设门槛时两格错（vol04 參→㕘），池图 margin 0.019、0.004，
    # 换成线上 char_patch 是 0.026、0.022（同格两种图 margin 差可到 ±0.018）。所以取 0.04（宁可弃权）。叅不足 8 例，永不给。
    "can": IdsSpec(frame="⿱厽{}", orient="h", prior=0.52, min_margin=0.04),
    # 以下三组（2026-10-20）：模板＝sheldon 合审裁过的殿本 vol04–10 格（中心库 confirm 事件），按字分类（by_form）。
    # 按册留一（判某册时模板不含该册，含 min_class 门槛）：叙敘 23 格 → 17 对／6 弃权／0 错；冊册 16 格 → 13／3／0（册 只 3 例，永不给）；
    # 教敎 28 格 → 24／4／0（margin 0.0 时 4 错，所以门槛 0.02）。厯歴 按册留一有错、啓啟 只一册有图，都未登记。
    "xu": IdsSpec(frame="", orient="h", prior=0.4, which=0, min_margin=0.02, by_form=True),
    "ce": IdsSpec(frame="", orient="h", prior=0.5, which=1, min_margin=0.02, by_form=True),
    "jiao": IdsSpec(frame="", orient="h", prior=0.5, which=0, min_margin=0.02, by_form=True),
    "qik": IdsSpec(frame="", orient="h", prior=0.5, which=1, min_margin=0.02, by_form=True),
    "lih": IdsSpec(frame="", orient="v", prior=0.4, which=1, min_margin=0.02, by_form=True),
    "jue": IdsSpec(frame="", orient="h", prior=0.4, which=0, min_margin=0.02, by_form=True),
    # 彝彛彜彞𢑱𢑴（2026-10-20，sheldon 定上线）：42 格人标三段读法（dataset yi_560/user_parts_labels），自动缝（band 0.08、pull 2.0）。
    # 留一：margin 0.04 → 23 对／19 弃权／0 错（覆盖 55%）；0.02 有 5 错、0.0 有 8 错，所以取 0.04。
    # 第二轮（sheldon 10-20 追问「剩下的为什么分不开」）：13 个弃权里 11 个三段其实读对了，只是 margin 不够——
    # 上段 彑／彐 只差左上一个小钩，自动缝常把上段笔画从中间切开（近邻 margin 0.00–0.04）；中段 糸／分 近邻留一 5/42 错。
    # 改法：三段都用 HOG＋岭回归（ids_parts.choose_hog，模板即训练集）；上段、下段不用缝，取墨迹外框的比例窗口
    # （ids_solver.TOP_WIN／BOT_WIN，bank 的 4|、5| 槽）。留一：34 对／8 弃权／0 错（覆盖 81%）；
    # 8 个弃权中 6 个是读对了但 Unicode 无此组合（彑米糸大，nearest 旗）；sheldon 10-20 定「彑米糸大 ≡ 𢑴，不用人审」→ nearest_ok：
    # 加上后 40 对／2 弃权／0 错（覆盖 95%）。
    # 阈值平台：top_hog 0.0–0.08、mid_hog 0.08–0.20、bot_hog 0.05–0.2 结果都一样。
    "yi_560": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.04, min_class=2, three=True,
                         top_hog=0.05, mid_hog=0.15, bot_hog=0.1, nearest_ok=True),
    # 呂吕、徵徴（2026-10-20，道 1 续）：按字分类（缝两侧无差别）改整字岭回归（`ids_whole`），模板＝殿本 vol01–10 人裁 confirm 事件格
    # （吕 48／呂 22、徵 34／徴 41；建库见 research/m7/lane1/build_whole_bank.py，评测同脚本，按册留一＝判某册时模板不含该册）：
    # 呂吕 pix 32×32、λ=1：|d|≥0.5 → 62 对／8 弃权／0 错（≥0.3 68 对 2 弃权 0 错，不设门槛也 0 错；取 0.5 留余量）。
    #   模板里 vol07:4:4:21 按 sheldon 复看改为呂（原人裁吕，墨浓两口被粗笔连上；更正写在建库脚本 CORRECTIONS）。
    # 徵徴 hog（取字块 x 0.28–0.78、y 0.15–0.65）80×80、λ=3：|d|≥0.6 → 38 对／37 弃权／0 错（≥0.5 46 对 0 错，≥0.4 55 对 0 错，≥0.3 1 错；
    #   换尺寸、λ、区域，0.6 处都是 0 错，所以取 0.6）。徵徴 不设门槛只有 87–92% 对，别放宽。
    "lv": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.5, min_class=8, whole="pix", lam=1.0, size=32),
    "zheng": IdsSpec(frame="", orient="h", prior=0.5, min_margin=0.6, min_class=8, whole="hog",
                     region=(0.28, 0.78, 0.15, 0.65), lam=3.0, size=80),
}


def bank_path(g: str) -> Path | None:
    """组 `g` 的模板库文件：工作区 `config/groups/ids/<g>.json` 优先，其次仓里 `<config_dir>/ids_bank.json`；都没有 → None。"""
    from ..core.workspace import ws_config_dir
    from .registry import GROUPS
    cfg = ws_config_dir()
    if cfg is not None and (cfg / "groups" / "ids" / f"{g}.json").exists():
        return cfg / "groups" / "ids" / f"{g}.json"
    spec = GROUPS.get(g)
    if spec is not None and spec.config_dir and (_ROOT / spec.config_dir / "ids_bank.json").exists():
        return _ROOT / spec.config_dir / "ids_bank.json"
    return None


def has_bank(g: str) -> bool:
    return g in SPECS and bank_path(g) is not None


# —— 模板库文件 ——

def _enc(t: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(t, dtype=np.uint8).tobytes()).decode("ascii")


def _dec(s: str, size: int) -> np.ndarray:
    a = np.frombuffer(base64.b64decode(s), dtype=np.uint8).reshape(size, size)
    return a.astype(np.float32) / 255.0


def quantize(t: np.ndarray) -> np.ndarray:
    """归一部件图（0–1 float）→ uint8；评测与建库同一量化，线上读回来与评测时一模一样。"""
    return np.clip(np.round(np.asarray(t, dtype=np.float32) * 255), 0, 255).astype(np.uint8)


def dump_bank(group: str, templates: dict, source: dict, size: int = 32) -> dict:
    """`templates = {部件名: [归一部件图,…]}` → 可写盘的 dict（部件名排序，模板保持输入顺序）。"""
    return {"version": VERSION, "group": group, "size": size, "source": source,
            "templates": {k: [_enc(quantize(t)) for t in templates[k]] for k in sorted(templates)}}


def write_bank(d: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(d, ensure_ascii=False, indent=0, sort_keys=True) + "\n", encoding="utf-8")


@lru_cache(maxsize=16)
def _load_cached(path: str, digest: str) -> dict:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    if d.get("version") != VERSION:
        raise ValueError(f"IDS 模板库 {path} 版本 {d.get('version')!r}，要的是 {VERSION}")
    size = int(d.get("size") or 32)
    return {k: [_dec(s, size) for s in v] for k, v in (d.get("templates") or {}).items()}


def load_bank(path: str | Path) -> dict:
    """→ `{部件名: [模板图(float 0–1),…]}`。按内容哈希缓存，文件换了自动重读。"""
    p = Path(path)
    return _load_cached(str(p), hashlib.sha256(p.read_bytes()).hexdigest())


@lru_cache(maxsize=16)
def _resolver(g: str):
    from .ids import IdsResolver
    from .registry import GROUPS
    spec = GROUPS[g]
    return IdsResolver(sorted(spec.members), _ROOT / (spec.config_dir or f"config/groups/{g}"))


# —— 指纹 ——

def _sha(p: Path | None) -> str:
    if p is None or not p.exists():
        return "missing"
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def fingerprint(groups) -> str:
    """点名组里登记了在线判法的，各取「判法参数＋模板库＋覆盖表＋IDS 总表」哈希；没有就空串（不改旧指纹）。"""
    from .ids import IDS_TABLE
    from .registry import GROUPS
    parts = []
    for g in sorted(set(groups)):
        if g not in SPECS or g not in GROUPS:
            continue
        sp = GROUPS[g]
        ov = _ROOT / (sp.config_dir or f"config/groups/{g}") / "ids_override.tsv"
        spec = hashlib.sha256(json.dumps(asdict(SPECS[g]), sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:8]
        parts.append(f"{g}={spec}.{_sha(bank_path(g))}.{_sha(ov)}")
    if not parts:
        return ""
    return "ids:" + ",".join(parts) + f",lv1={_sha(IDS_TABLE)}"


# —— 判 ——

def judge_with(g: str, gray: np.ndarray, bank: dict, spec: IdsSpec | None = None) -> GroupVerdict:
    """用给定模板库判一格（评测与线上共用）。给字条件：IDS 对上组内成员、margin ≥ `min_margin`、该类模板 ≥ `min_class`。"""
    from .ids_two import solve_two
    from .registry import GROUPS
    spec = spec or SPECS[g]
    members = GROUPS[g].members
    if spec.three:
        return _judge_three(g, gray, bank, spec)
    if spec.whole:
        return _judge_whole(gray, bank, spec, members)
    if spec.by_form:
        return _judge_by_form(gray, bank, spec, members)
    v = solve_two(np.asarray(gray), bank, _resolver(g), spec.frame, spec.orient, spec.prior,
                  which=spec.which, min_margin=0.0)
    m = float(v.margins[0]) if v.margins else 0.0
    slot = v.slots[0] if v.slots else None
    extra = {"ids": v.ids, "slot": slot, "margin": round(m, 4), "kind": v.kind,
             "scores": {k: round(float(s), 4) for k, s in (v.extra.get("scores") or {}).items()}}
    if v.kind == "abstain_blank":
        return GroupVerdict(None, why="abstain:blank", via="ids", extra=extra)
    if v.char is None or v.char not in members:
        return GroupVerdict(None, why="abstain:" + v.kind.removeprefix("abstain_"), via="ids", extra=extra)
    if m < spec.min_margin:
        return GroupVerdict(None, conf=m, why="abstain:low_margin", via="ids", extra=extra)
    n = len(bank.get(slot) or ())
    if n < spec.min_class:
        return GroupVerdict(None, conf=m, why="abstain:few_templates", via="ids", extra={**extra, "n_templates": n})
    return GroupVerdict(v.char, conf=m, why="agree", via="ids", extra=extra)


def _auto_three(gray):
    """彝组自动切：上／中、中／下两条缝（先取直线基线作先验）＋中段竖缝。无墨迹 → None。"""
    from .ids_segment import ink_of, polylines_to_mask, seam_polyline, straight_baseline, vertical_seam
    ink = ink_of(gray)
    if not ink.any():
        return None
    y1, y2 = straight_baseline(ink, 3)
    pl = (seam_polyline(ink, y1, band=0.08, pull=2.0), seam_polyline(ink, y2, band=0.08, pull=2.0))
    return pl, vertical_seam(ink, polylines_to_mask(ink.shape, *pl))


def _slot_bank(bank: dict) -> dict:
    """彝组模板库的键是 `位置|部件名`（如 `1|米糸`、`3|糸`＝中段竖切右半）→ `{位置: {部件名: [图,…]}}`。"""
    out: dict = {}
    for k, v in bank.items():
        slot, name = k.split("|", 1)
        out.setdefault(int(slot), {})[name] = v
    return out


def _judge_three(g: str, gray, bank: dict, spec: IdsSpec) -> GroupVerdict:
    from .ids_solver import solve
    arr = np.asarray(gray)
    cut = _auto_three(arr)
    if cut is None:
        return GroupVerdict(None, why="abstain:blank", via="ids")
    pl, vc = cut
    b = _slot_bank(bank)
    v = solve(arr, b, _resolver(g), pl, min_margin=spec.min_margin, vcut=vc, mid_hog=spec.mid_hog, top_hog=spec.top_hog, bot_hog=spec.bot_hog)
    ms = [float(x) for x in v.margins]
    extra = {"ids": v.ids, "slots": list(v.slots), "margins": [round(x, 4) for x in ms], "kind": v.kind, "flag": v.flag}
    if v.char is None or v.char not in _members(g):
        return GroupVerdict(None, conf=min(ms) if ms else 0.0, why="abstain:" + v.kind.removeprefix("abstain_"), via="ids", extra=extra)
    if v.flag and not spec.nearest_ok:      # nearest_variant：Unicode 没有这个组合，只能近似 → 缺省不放，送人审
        return GroupVerdict(None, conf=min(ms), why="abstain:nearest", via="ids", extra=extra)
    for k, name in enumerate(v.slots):
        key = 3 if (k == 1 and b.get(3)) else k
        tname = name[1:] if key == 3 and name.startswith("米") else name
        if len(b.get(key, {}).get(tname) or ()) < spec.min_class:
            return GroupVerdict(None, conf=min(ms), why="abstain:few_templates", via="ids", extra=extra)
    return GroupVerdict(v.char, conf=min(ms), why="agree", via="ids", extra=extra)


def _members(g: str):
    from .registry import GROUPS
    return GROUPS[g].members


def _judge_by_form(gray, bank: dict, spec: IdsSpec, members) -> GroupVerdict:
    """按字分类：自动缝切开，取第 `which` 段，与各成员字的同段模板比最近邻（`ids_two._choose_norm`）。"""
    from .ids_segment import ink_of
    from .ids_two import _choose_norm, auto_cut, part_of
    g = np.asarray(gray)
    if not ink_of(g).any():
        return GroupVerdict(None, why="abstain:blank", via="ids")
    pl = auto_cut(g, spec.orient, spec.prior)
    x = part_of(g, pl, spec.orient, spec.which) if pl is not None else None
    if x is None:
        return GroupVerdict(None, why="abstain:slot", via="ids")
    best, m, scores = _choose_norm(x, bank, 0.0)
    extra = {"form": best, "margin": round(float(m), 4), "scores": {k: round(float(v), 4) for k, v in scores.items()}}
    if best is None or best not in members:
        return GroupVerdict(None, why="abstain:slot", via="ids", extra=extra)
    if m < spec.min_margin:
        return GroupVerdict(None, conf=m, why="abstain:low_margin", via="ids", extra=extra)
    n = len(bank.get(best) or ())
    if n < spec.min_class:
        return GroupVerdict(None, conf=m, why="abstain:few_templates", via="ids", extra={**extra, "n_templates": n})
    return GroupVerdict(best, conf=m, why="agree", via="ids", extra=extra)


def _judge_whole(gray, bank: dict, spec: IdsSpec, members) -> GroupVerdict:
    """整字二类岭回归（`ids_whole`）：判别值绝对值 ≥ `min_margin`、判成的字模板 ≥ `min_class` 才给字。"""
    from . import ids_whole
    best, m, sc = ids_whole.score(np.asarray(gray), bank, spec.whole, tuple(spec.region), spec.lam, spec.size)
    extra = {"form": best, "margin": round(float(m), 4), "scores": {k: round(float(v), 4) for k, v in sc.items()}}
    if best is None:
        return GroupVerdict(None, why="abstain:blank", via="ids", extra=extra)
    if best not in members:
        return GroupVerdict(None, why="abstain:slot", via="ids", extra=extra)
    if m < spec.min_margin:
        return GroupVerdict(None, conf=m, why="abstain:low_margin", via="ids", extra=extra)
    n = len(bank.get(best) or ())
    if n < spec.min_class:
        return GroupVerdict(None, conf=m, why="abstain:few_templates", via="ids", extra={**extra, "n_templates": n})
    return GroupVerdict(best, conf=m, why="agree", via="ids", extra=extra)


_YI_NM = {"⺕": "彐", "彑": "彑", "糸": "米糸", "米+分": "米分", "廾": "廾", "大": "大"}


def _three_cells(g: str, dataset: Path):
    from PIL import Image
    d = Path(dataset) / "char-groups" / "variant" / g
    src = d / "user_parts_labels.jsonl"
    cells = []
    for line in src.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        gray = np.asarray(Image.open(d / "crops" / (r["id"].replace(":", "_") + ".png")).convert("L"))
        cut = _auto_three(gray)
        if cut is not None:
            cells.append((r["id"], tuple(_YI_NM[r[k]] for k in ("top", "mid", "bot")), gray, cut))
    return cells, src


def _three_bank(cells, skip: str | None = None) -> dict:
    from .ids_solver import add_real
    bank = {0: {}, 1: {}, 2: {}}
    for i, names, gray, (pl, vc) in cells:
        if i != skip:
            add_real(bank, gray, names, pl, vc)
    # 与线上同一量化
    return {f"{slot}|{name}": [quantize(t).astype(np.float32) / 255.0 for t in ts]
            for slot, names_ in bank.items() for name, ts in names_.items()}


def evaluate_three(g: str, dataset: Path, margins=(0.0, 0.02, 0.04, 0.06)) -> dict:
    """彝组留一：模板库只用其余格，切线用自动缝（同线上）。→ {margin: {right, abstain, wrong}}。"""
    cells, _ = _three_cells(g, dataset)
    out = {m: Counter() for m in margins}
    wrong = []
    for i, names, gray, _cut in cells:
        bank = _three_bank(cells, skip=i)
        for m in margins:
            v = _judge_three(g, gray, bank, IdsSpec(**{**asdict(SPECS[g]), "min_margin": m}))
            k = "abstain" if v.char is None else "right" if tuple(v.extra["slots"]) == names else "wrong"
            out[m][k] += 1
            if k == "wrong":
                wrong.append((m, i, names, v.char))
    return {"by_margin": {m: dict(c) for m, c in out.items()}, "wrong": wrong, "cells": len(cells)}


def build_three(g: str, dataset: Path) -> dict:
    """彝组：dataset `char-groups/variant/<g>/user_parts_labels.jsonl`（三段读法）＋ `crops/` → 模板库（自动缝，同线上）。"""
    cells, src = _three_cells(g, dataset)
    flat = _three_bank(cells)
    n = len(cells)
    out = dump_bank(g, flat, {"labels": f"char-groups/variant/{g}/user_parts_labels.jsonl",
                              "labels_sha256": hashlib.sha256(src.read_bytes()).hexdigest()[:16], "cells": n})
    return out


def form_templates(cells, spec: IdsSpec) -> dict:
    """`cells = [(成员字, 灰度图), …]`（人裁过的真实刻例）→ by_form 模板 `{字: [归一段图,…]}`，与线上同一量化。"""
    from .ids_two import auto_cut, part_of
    bank: dict = {}
    for form, gray in cells:
        g = np.asarray(gray)
        pl = auto_cut(g, spec.orient, spec.prior)
        x = part_of(g, pl, spec.orient, spec.which) if pl is not None else None
        if x is not None:
            bank.setdefault(form, []).append(quantize(x).astype(np.float32) / 255.0)
    return bank


def judge(g: str, gray) -> GroupVerdict:
    """线上入口：组 `g` 没登记判法或没有模板库 → `abstain:no_bank`；没图 → `abstain:no_patch`。"""
    if g not in SPECS:
        return GroupVerdict(None, why="abstain:no_spec", via="ids")
    p = bank_path(g)
    if p is None:
        return GroupVerdict(None, why="abstain:no_bank", via="ids")
    if gray is None:
        return GroupVerdict(None, why="abstain:no_patch", via="ids")
    return judge_with(g, gray, load_bank(p))


# —— 离线：建库与留一评测 ——

def _pool(g: str, dataset: Path):
    """dataset 人标池 → [(id, 字形, 灰度图, 切线)]。只收 `form` 在组内、切线 ≥2 点的行。"""
    from PIL import Image
    from .registry import GROUPS
    d = Path(dataset) / "char-groups" / "variant" / g
    mem = GROUPS[g].members
    rows = []
    for line in (d / "labels.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("form") in mem and len(r.get("cut") or ()) >= 2:
            img = np.asarray(Image.open(d / "crops" / (r["id"].replace(":", "_") + ".png")).convert("L"))
            rows.append((r["id"], r["form"], img, r["cut"]))
    return rows, d / "labels.jsonl"


def _templates(g: str, rows, skip: str | None = None) -> dict:
    from .ids_two import add_real, slot_name
    spec = SPECS[g]
    bank: dict = {}
    for i, form, img, cut in rows:
        if i != skip:
            add_real(bank, img, slot_name(_resolver(g), form, spec.which), cut, spec.orient, spec.which)
    return {k: [quantize(t).astype(np.float32) / 255.0 for t in v] for k, v in bank.items()}


def build(g: str, dataset: Path) -> dict:
    rows, src = _pool(g, dataset)
    return dump_bank(g, _templates(g, rows), {"labels": f"char-groups/variant/{g}/labels.jsonl",
                                              "labels_sha256": hashlib.sha256(src.read_bytes()).hexdigest()[:16],
                                              "cells": len(rows), "forms": dict(sorted(Counter(r[1] for r in rows).items()))})


def evaluate(g: str, dataset: Path, margins=(0.0, 0.01, 0.02, 0.03, 0.05)) -> dict:
    """留一：模板库只用其余格、切线用自动缝（同线上）。→ {margin: {right, abstain, wrong}}，另附错例。"""
    rows, _ = _pool(g, dataset)
    out = {m: Counter() for m in margins}
    wrong = []
    for i, form, img, _cut in rows:
        bank = _templates(g, rows, skip=i)
        for m in margins:
            v = judge_with(g, img, bank, IdsSpec(**{**asdict(SPECS[g]), "min_margin": m}))
            k = "abstain" if v.char is None else "right" if v.char == form else "wrong"
            out[m][k] += 1
            if k == "wrong":
                wrong.append((m, i, form, v.char, v.extra.get("margin")))
    return {"by_margin": {m: dict(c) for m, c in out.items()}, "wrong": wrong, "cells": len(rows)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="IDS 路模板库：建库／留一评测")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("group"); b.add_argument("--dataset", type=Path, required=True)
    b.add_argument("--out", type=Path, default=None, help="缺省 仓里 <config_dir>/ids_bank.json")
    e = sub.add_parser("loo"); e.add_argument("group"); e.add_argument("--dataset", type=Path, required=True)
    a = ap.parse_args(argv)
    if a.group not in SPECS:
        raise SystemExit(f"组 {a.group!r} 没有登记在线判法（ids_online.SPECS）")
    if a.cmd == "build":
        from .registry import GROUPS
        out = a.out or _ROOT / (GROUPS[a.group].config_dir or f"config/groups/{a.group}") / "ids_bank.json"
        d = build_three(a.group, a.dataset) if SPECS[a.group].three else build(a.group, a.dataset)
        write_bank(d, out)
        print(f"写入 {out}：{d['source']}，各类模板 { {k: len(v) for k, v in d['templates'].items()} }")
    else:
        r = (evaluate_three if SPECS[a.group].three else evaluate)(a.group, a.dataset)
        print(f"{a.group} 留一（自动缝）{r['cells']} 格")
        for m, c in r["by_margin"].items():
            print(f"  margin {m:.2f}: {c}")
        for w in r["wrong"]:
            print("  错", *w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
