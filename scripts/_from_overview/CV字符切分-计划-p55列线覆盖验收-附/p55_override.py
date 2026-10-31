"""原型（不改 cv 仓）：对 vol05 p55 套「给定界线」覆盖——在 detect_borders 的结果上补右外内框线、去掉左缘窄条，
再跑真 Step1–4，量格数。仅沙箱。"""
import copy, sys
sys.path.insert(0, "/home/user/open-guji-cv")
import open_guji_cv.steps.border_detect as bd
from open_guji_cv.seg.frame_types import VLine
orig = bd.detect_borders
NEWX = float(sys.argv[1])          # 缺的右线 x_at_top（右起）
def patched(*a, **k):
    res = orig(*a, **k)
    vs = list(res.verticals)
    first = copy.copy(vs[0]); first.x_at_top = NEWX
    res.verticals = [first] + vs[:-1]           # 加右线、去最左窄条
    if getattr(res, "verticals_straight", None):
        s0 = copy.copy(res.verticals_straight[0]); s0.x_at_top = NEWX
        res.verticals_straight = [s0] + list(res.verticals_straight)[:-1]
    if getattr(res, "vline_filled", None):
        res.vline_filled = [False] + list(res.vline_filled)[:-1]
    return res
bd.detect_borders = patched
from open_guji_cv.cli_v2 import main
sys.argv = ["guji"] + sys.argv[2:]
main()
