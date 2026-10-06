"""v4n = v4 去掉专名线索（专名表来自整理本；v4 dev 上 12 个「否决图像且图像对」的错例里，
直父/元颜/杨州/史君 都是整理本写法经专名线索放大）。配 --no-ref 即「完全不看整理本」对照组。"""
import re
from . import v4, v2
VERSION = 'v4n-2026-09-26'
SYSTEM = re.sub(r'3\. 【專名線索】.*?\n', '', v4.SYSTEM).replace('4. 理由要具體', '3. 理由要具體').replace('5. confidence', '4. confidence').replace('6. 只能在候選中選', '5. 只能在候選中選')
def build(DAYS, d, ask, allpend, keys, txt, dictlib, MARK, with_ref=True, min_ctx=300):
    msgs, marks = v2.build(DAYS, d, ask, allpend, keys, txt, dictlib, MARK, with_ref=with_ref, min_ctx=min_ctx, strict=True)
    msgs[0] = {'role': 'system', 'content': SYSTEM}
    return msgs, marks
