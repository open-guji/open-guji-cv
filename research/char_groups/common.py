"""字组测试集公用定义（overview#437，G0，2026-10-06）。

字组登记表（与 dataset `char-groups/groups.json` 一致）、各册取哪几个快照、留出册的划分。
建集只读：guji-workspace 快照（`git archive <snap> | tar -x` 解到沙箱）、工作区事件与原图、overview 看图清单。
"""
from __future__ import annotations

GROUPS = {
    "jys": {"name": "己已巳", "members": "己已巳", "type": "near_form",
            "note": "殿本三字基本同形（封口与否刻工不守），按文意定：干支/时辰「巳」、虚词「已」、反身「己」。"},
    "ry": {"name": "日曰", "members": "日曰", "type": "near_form",
           "note": "宽高比中位数分得开（日≈0.70、曰≈0.80+），尾部大量重叠且随册漂（#352）；"
                   "现行主依据是整理本字。"},
    "rr": {"name": "入人八", "members": "入人八", "type": "near_form",
           "note": "入↔人、人↔八 两对（八↔入 未见混淆）。iron 曾把「八」放成「人」（#426）。"},
}
SETS = {k: set(v["members"]) for k, v in GROUPS.items()}

# 册 → (seed_admit 快照, 上游 glyph_match/align_ref/context_decide 快照, cell_shrink 快照)。
# 上游取「seed_admit 产物 _manifest.jsonl 的 upstream sha256 与之全部一致」的那个快照（build.py 会复核）。
SNAPS = {
    "vol02": ("vol02_20260930T0339", "vol02_20260929T1024", "vol02_20260929T1023"),
    "vol03": ("vol03_20260930T0457", "vol03_20260929T0451", "vol03_20260929T0450"),
    "vol04": ("vol04_20261006T1208", "vol04_20261006T1208", "vol04_20261006T1208"),
    "vol05": ("vol05_20260928T1508",) * 3,
    "vol06": ("vol06_20260928T1509",) * 3,
    "vol07": ("vol07_20260928T1509",) * 3,
    "vol08": ("vol08_20260928T1455-full",) * 3,
    "vol09": ("vol09_20260928T1511-full",) * 3,
    "vol10": ("vol10_20260928T1455-full",) * 3,
}

# 评测划分（按册，防止只在一册上调好）：
#   dev  = 调方法用（强真值最多：vol02/vol03 人裁 + vol03 muse 试点）
#   val  = 留出验证（vol04：现行代码最新的产物、看图结论；方法定型前不看它的错例）
#   pool = 只有现行产物与弱真值的册（vol05–10），量覆盖与人审率，不量错率
#   extra = 没有快照的题（vol01 confusable-context），只有文本上下文
SPLIT = {"vol02": "dev", "vol03": "dev", "vol04": "val",
         **{f"vol{i:02d}": "pool" for i in range(5, 11)}, "vol01": "extra"}

# 真值档
TIER_HUMAN, TIER_VISION, TIER_WEAK = "A_human", "B_vision", "C_weak"
STRONG = {TIER_HUMAN, TIER_VISION}
