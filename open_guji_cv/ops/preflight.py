"""`guji pipeline`／`guji step` 开跑前的依赖自检（GUJI-654）。

缺 torch、缺权重、缺 joblib 在引擎里都是**悄悄退回旧办法或整页失败**：产物照出，只打一条警告
（10-21 重跑 vol08：册配置开了 `shadow_veto`，没装 joblib，seed_admit 69 页全失败，pipeline 照样返回 0）。
这里在起跑前就把「这次要跑的步骤，本机缺什么」查出来，缺了直接拒跑（退出码 2）。
`--allow-missing-deps` 或环境变量 `GUJI_ALLOW_MISSING_DEPS=1` 放行（只提醒）。

只查**这次要跑的步骤用得上的**东西：只跑 Step1 的人不需要 torch。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

INSTALL_HINT = 'uv pip install -e ".[console,torch,dev,datastore,shadow,pdf]"'


def _have(mod: str) -> bool:
    return importlib.util.find_spec(mod) is not None


def check(eng, steps: list[str]) -> list[str]:
    """返回缺的东西，一条一句人话；空表＝齐了。"""
    from ..clustering import cnn_candidates as CNN
    from ..utils.cut_select import DEFAULT_CKPT as JUDGE_CKPT
    out: list[str] = []
    if "row_segment" in steps and _params(eng, "row_segment", "cut_judge") == "unet":
        if not _have("torch"):
            out.append("没装 torch：Step3 row_segment 的切点裁判（cut_judge=unet）会悄悄退回旧规则，产物和装了 torch 的不一样")
        elif not Path(JUDGE_CKPT).is_file():
            out.append(f"缺切点裁判权重 {JUDGE_CKPT}：Step3 会悄悄退回旧规则")
    if "rare_candidates" in steps:
        if not _have("torch"):
            out.append("没装 torch：Step5-b rare_candidates 没有 embedding 候选")
        elif not Path(CNN.DEFAULT_CKPT).is_file():
            out.append(f"缺识别权重 {CNN.DEFAULT_CKPT}：Step5-b 没有 embedding 候选")
    if "seed_admit" in steps and _params(eng, "seed_admit", "shadow_veto"):
        gone = [m for m in ("joblib", "sklearn") if not _have(m)]
        if gone:
            out.append(f"册配置开了 shadow_veto，但没装 {'、'.join(gone)}：Step7 seed_admit 会整页失败（装 `.[shadow]`）")
    return out


def _params(eng, step_id: str, field: str):
    """某一步解析后的参数值（册 yaml、管线 yaml、`--params` 都算进去）；这一步不在管线里返回 None。"""
    from .. import steps as _s  # noqa: F401 —— 确保 Step 已注册
    from ..core.step import STEPS
    step = STEPS.get(step_id)
    if step is None:
        return None
    return getattr(eng._params(step), field, None)
