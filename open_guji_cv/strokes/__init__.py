"""笔画识别（L1 纯算法，不依赖 groups）：给字块和模板，逐笔贴上，得到每一笔的位置与把握量。

- `register(gray, tpl, RegParams)` → `Fit`：逐笔模板配准（判别用这个）。
- `template`：通用模板（Make Me a Hanzi＋cnchar）、本书模板、模板库 `TemplateBank`。
- `features`：差一笔（`verify_extra` 固定门槛；`verify_learned` 按本书刻例学门槛）、量几何（`geometry`、`ClassStats`）。
- `plan.plan_pair`：给两个字建议判法。
- `skeleton.extract`：不认字的骨架法，诊断用，判别不用。

设计：ai-team domain/CV/字形领域/笔画识别模块-设计-2026-11-07.md；研究与数字：同目录 笔画识别-研究-2026-11-07/。
"""
from .features import ClassStats, bad_fit, extra_feats, geometry, stroke_feats, verify_extra, verify_learned
from .plan import PairPlan, plan_pair
from .register import Fit, FitStroke, RegParams, register
from .template import (StrokeTemplate, TemplateBank, TStroke, average, build_book_template, fit_to_unit,
                       from_polylines, load_generic)

__all__ = ["ClassStats", "bad_fit", "extra_feats", "geometry", "stroke_feats", "verify_extra", "verify_learned", "PairPlan", "plan_pair",
           "Fit", "FitStroke", "RegParams", "register", "StrokeTemplate", "TemplateBank", "TStroke",
           "average", "build_book_template", "fit_to_unit", "from_polylines", "load_generic"]
