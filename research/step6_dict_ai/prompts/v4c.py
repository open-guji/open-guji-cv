"""v4c = v4 + 其他待判位填图像首选（E4）：▢ 改成〔X?〕。p20 宴饮菜单一天 88 格待判，▢ 把句子挖得读不成句。"""
from . import v4, v1
VERSION = 'v4c-2026-09-26'
SYSTEM = v4.SYSTEM
def build(*a, **kw):
    v1.FILL['mode'] = 'guess'
    return v4.build(*a, **kw)
