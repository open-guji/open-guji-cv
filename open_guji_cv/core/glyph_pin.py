"""册钉字形库（glyph_pin）：别处的人裁进库，不让本册 seed_admit 判过期。

册 yaml 写 `glyph_pin: 1`（或 `g1`）。钉了之后，`params_for` 把参数里**来自字形库内容**的指纹
（`PIN_FIELDS`：seed_admit 的人裁指纹、近似字指纹）换成 `glyph-g1`：指纹只认钉的号，不看库内容。
没钉的册一字不变，指纹逐位相同。

为什么要有：`human_shapes_fingerprint` 取的是整个工作区的人裁（各册、各对话都往同一个库里写）。
2026-10-19 重跑 vol04–10 时，每次 `guji db sync` 拉到别的对话的人裁，各册 seed_admit 全部判过期，
已过粗校的册（vol04、07、10）也要从 rare_candidates 起重跑、重做出口检查。钉住后：

- 新人裁不再让本册过期；`guji status` 在册名下提示本册钉着字形库；
- 要落地时把号加一（`glyph_pin: 2`），本册 seed_admit 全部过期一次，重跑时读的是当时的库；
- 因别的原因重跑的页（切分改了、`guji recheck` 点名的格）照常读**当前**的库：钉的是指纹，不是库内容。
  所以同一册里不同页用的人裁可能新旧不一，这是有意的；要整册一致就加号重跑。

与语料库钉子（`core/corpus_pin.py`）同一套写法，但不校验内容：字形库没有「版本清单」，
也不需要——人裁只增不改，晚落地不会让已放行的格变错。
"""
from __future__ import annotations

#: 来自字形库内容、钉住后换成钉号的参数字段（只换已经有值的）。
#: 不含 `rare_candidates.db_font_fingerprint`：字体域在不在是真差别（没导字体时 Step5-b 退化），不能钉掉。
#: 不含 `glyph_match.db_fingerprint`：它本来就是软参数，不进指纹。
PIN_FIELDS: tuple[str, ...] = ("human_fingerprint", "approx_fingerprint")


def parse_pin(v) -> int | None:
    """册 yaml 的 `glyph_pin:`：`1`／`"1"`／`"g1"` → 1；空 → None。"""
    if v is None or v == "":
        return None
    s = str(v).strip().lower()
    s = s[1:] if s.startswith("g") else s
    if not s.isdigit() or int(s) < 1:
        raise ValueError(f"册 yaml 的 glyph_pin: 应是正整数（如 1 或 g1），收到 {v!r}")
    return int(s)


def pin_token(v: int) -> str:
    return f"glyph-g{int(v)}"


def with_glyph_pin(p, book):
    """册钉了字形库时，把参数里的字形库内容指纹换成钉号；没钉原样返回。

    只换已经有值的字段（开关没开时这些字段是空的，保持为空：`approx_fingerprint` 空表示不用近似字表）。"""
    v = getattr(book, "glyph_pin", None)
    if not v:
        return p
    fields = [f for f in PIN_FIELDS if getattr(p, f, "")]
    if not fields:
        return p
    tok = pin_token(v)
    return type(p)(**{**p.model_dump(), **{f: tok for f in fields}})

