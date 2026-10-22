"""open-guji-cv：古籍刻本图像 → 逐字转写的引擎。入口见 `guji` 命令（cli_v2）与 doc/runbook/整理一册书.md。"""

import os as _os

# 中心库令牌缺省用读令牌（sheldon 10-21）：云端 Default 环境只放 GUJI_DATA_TOKEN_READ/_PROD/_EXP 三把，
# 不设 GUJI_DATA_TOKEN。没设时退回读令牌，拉库、取 R2 预建件（字体包、产物包、语言模型）就不用每个会话手动 export。
# 推送仍要显式把 GUJI_DATA_TOKEN 设成正式／实验令牌；拿读令牌去推，Worker 按角色拒（与以前手动 export 读令牌时一样）。
if not _os.environ.get("GUJI_DATA_TOKEN") and _os.environ.get("GUJI_DATA_TOKEN_READ"):
    _os.environ["GUJI_DATA_TOKEN"] = _os.environ["GUJI_DATA_TOKEN_READ"]
