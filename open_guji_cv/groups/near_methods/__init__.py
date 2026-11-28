"""3b `glyph_near` 的字形方法登记表（2026-11-27，第三步重构）。

一个字组可以挂几个方法，写在书配置 `params.glyph_near.groups.<组>.methods` 里：`{方法名: 模型目录}`，或
`{方法名: {path: 模型文件, pair: [字, 字]}}`（一份模型文件挂多对的方法，如 part_shape，2026-11-28；`pair` 选其中一对），
或 `{方法名: {path: 模型文件, group: 模型组名}}`（一份模型文件挂几组的方法，如 stroke_veto；`group` 选其中一组）。
方法只回答「这张字块图在组内各字里更像哪个」，给组内每个字一个分，外加证据；**不定字、不放行**。
校准（分 → p）也由方法自己带的校准表做，但只在收尾 `glyph_analyzer` 里调，3b 产物里存的是原始分。

接口（以后的方法照这个写，第四步那些看图判字的方法迁过来也照这个）：

    m = load_method(name, spec)               # name 如 "cnn_small"；spec 是模型目录、单个模型文件，或 {path, pair}／{path, group}
    outs = score(m, patches, book_id, ctx=ctx, cells=cells)
                                              # 即 m.score(patches, book_id[, ctx=…, cells=…])
                                              # patches: 字块图（uint8，白底黑字，任意尺寸），哪种图见 m.patch
                                              # → [{"sims": {字: 分}, "evidence": {...}}, …]，与 patches 一一对应
    p = m.calibrate(sims)                     # {字: 校准后的 p} 或 None（没有校准表）
    m.fingerprint()                           # 模型目录（或文件）的 sha256 短哈希，进参数指纹；{path, pair} 时再并上 pair，{path, group} 时并上组名
    method_fingerprint(name, spec)            # "<方法>=<指纹>"，进 `methods_sha`；4d 拿同一个函数比对（spec 是字符串时与之前逐位相同）
    lib_fingerprint(库文件)                    # 书级刻例库（book_knn／near_knn）钉版指纹＝文件 sha256 前 16 位；这类方法（`lib = True`）
                                              # 的 method_fingerprint 就是它，与第四步参数指纹 bk／nk 段同值
    m.model_sha                               # 模型版本，写进 3b 产物 `PageNear.models` 与收尾 `near.methods.*.model`

- `m.patch`（类属性，可缺）：方法吃哪种字块图。`"raw"`（缺省）＝原图灰度按 `bbox_page` 裁块；`"char_patch"`＝第二步
  切字缓存里的字块图（`ctx.image("char_patch", patch_key)`，第四步 seed_admit 各判官读的就是这个）。
  3b 按它给图，方法自己不读图。
- **可选 ctx**（2026-11-28 加）：方法的 `score` 声明了 `ctx`／`cells` 参数（或 `**kwargs`）才传，老方法不认也照用（`score()` 用
  `inspect` 判）。`ctx` 是 `RunContext`（要读本书库、3a 候选的方法用，如以后的 book_knn／near_knn）；`cells` 与 patches
  一一对应，每格 `{id, page, col, slot, sub, patch_key, char, candidates, punct}`（`char`／`candidates` 是 3a 的首位与候选，`punct`＝标点格）。
  **方法不许改 ctx 里的东西**，只读。

## 各方法

一个方法一个模块（结构拆分 C5，2026-11-28）：`cnn_small`、`rr_shape`、`wu_shape`、`hou_shape`、`part_shape`、`pair_shape`、`book_knn`、`near_knn`、`stroke_veto`、`flow_shape`、`pair_clf`；各自的判法、sims、证据、指纹、校准写在该模块头。公用的路径解析、指纹、`score` 在 `_base`。本包对外的名字一律从包根导入。

"""
from __future__ import annotations

import json
from pathlib import Path

from ._base import REPO, SIZE, resolve_dir, prep_patch, vol_number, _dir_fingerprint, _sibling_calib, _accepts, score, _load_calib, _pair_fingerprint, lib_fingerprint, _group_fingerprint  # noqa: F401
from .cnn_small import _small_net, CnnSmall  # noqa: F401
from .rr_shape import RrShape  # noqa: F401
from .wu_shape import WuShape  # noqa: F401
from .hou_shape import HouShape  # noqa: F401
from .part_shape import PartShape  # noqa: F401
from .pair_shape import PairShape  # noqa: F401
from .book_knn import BOOK_KNN_KEYS, book_knn_measure, book_knn_settle, BookKnn  # noqa: F401
from .near_knn import NEAR_KNN_KEYS, near_knn_measure, near_knn_settle, NearKnn  # noqa: F401
from .stroke_veto import STROKE_VETO_KEYS, stroke_veto_trail, StrokeVeto  # noqa: F401
from .flow_shape import FlowShape  # noqa: F401
from .pair_clf import PairClf  # noqa: F401


METHODS = {"cnn_small": CnnSmall, "rr_shape": RrShape, "wu_shape": WuShape, "hou_shape": HouShape,
           "part_shape": PartShape, "pair_shape": PairShape, "book_knn": BookKnn, "near_knn": NearKnn,
           "stroke_veto": StrokeVeto, "flow_shape": FlowShape, "pair_clf": PairClf}


SPEC_KEYS = ("path", "pair", "group", "sim")


_CACHE: dict[tuple, object] = {}


def parse_spec(spec) -> tuple[str, dict]:
    """书配置里一个方法的写法 → (模型路径, 其余参数)。字符串＝模型目录或文件；dict＝`{path, pair}` 或 `{path, group}`（不能两个都写），
    pair_clf 写 `{path, pair, sim}`（`sim`＝相似度模型，同 glyph_match.sim_model 的 path）。"""
    if isinstance(spec, (str, Path)):
        return str(spec), {}
    if isinstance(spec, dict):
        bad = set(spec) - set(SPEC_KEYS)
        if bad or "path" not in spec or ("pair" in spec and "group" in spec):
            raise ValueError(f"glyph_near 方法写法 {spec!r} 不认识：要 {{path, pair}} 或 {{path, group}}（多了 {sorted(bad)}）")
        if "sim" in spec and "pair" not in spec:
            raise ValueError(f"glyph_near 方法写法 {spec!r} 不认识：`sim` 只配 {{path, pair, sim}}（pair_clf）")
        kw = {k: (list(v) if k == "pair" else str(v) if k in ("group", "sim") else v) for k, v in spec.items() if k != "path"}
        return str(spec["path"]), kw
    raise ValueError(f"glyph_near 方法写法 {spec!r} 不认识：写模型路径字符串或 {{path, pair}}")


def load_method(name: str, spec):
    """方法名＋模型目录（或单个模型文件，或 `{path, pair}`）→ 方法对象（按解析后的路径＋参数缓存）。"""
    cls = METHODS.get(name)
    if cls is None:
        raise ValueError(f"glyph_near：不认识的方法 {name!r}（已登记：{sorted(METHODS)}）")
    path, kw = parse_spec(spec)
    d = resolve_dir(path)
    key = (name, str(d), json.dumps(kw, ensure_ascii=False, sort_keys=True))
    m = _CACHE.get(key)
    if m is None:
        if not d.exists():
            raise FileNotFoundError(f"glyph_near 方法 {name} 的模型目录不存在：{d}")
        m = cls(d, **kw)
        _CACHE[key] = m
    return m


def method_fingerprint(name: str, spec) -> str:
    """`<方法>=<指纹>`，进 3b `methods_sha`；4d 比对模型版本也调它。spec 是字符串时＝模型目录（或文件）的指纹（与 11-28 之前逐位相同）；
    `{path, pair}` 时＝文件指纹并上这一对（按码位排，次序不论）；`{path, group}`（stroke_veto）时＝文件指纹并上组名；
    书级刻例库方法（`lib = True`，book_knn）＝`lib_fingerprint`。"""
    path, kw = parse_spec(spec)
    d = resolve_dir(path)
    if getattr(METHODS.get(name), "lib", False):
        return f"{name}={lib_fingerprint(d)}"
    if hasattr(METHODS.get(name), "spec_fingerprint"):
        return f"{name}={METHODS[name].spec_fingerprint(d, kw)}"
    if kw.get("pair") is not None:
        return f"{name}={_pair_fingerprint(d, kw['pair'])}"
    if kw.get("group") is not None:
        return f"{name}={_group_fingerprint(d, kw['group'])}"
    return f"{name}={_dir_fingerprint(d)}"
