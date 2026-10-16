"""v5 = v4n（不给整理本）+ 专名线索，但专名表改从**本书自动文本**抽（data/names_auto.json）。
动机：v3 的专名表抽自整理本，把整理本写法（直父、元颜、杨州、史君）渗了进来；v4n 去掉后「否决图像且图像对」12→6。
这里专名来自图像共识/库首选/OCR首选拼成的文本（不含真值与人裁），只留出现 ≥2 次的。
另删掉 v3 的「本日整理本中出现的專名」一节（来自整理本）；线索措辞里的「整理本」换成「本書自動文本」。"""
import json, os, re
from . import v3, v4
H = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION = 'v5-2026-09-27'
SYSTEM = v4.SYSTEM.replace('【專名線索】是程序按本書專名表（從整理本抽出）機械匹配的結果（「精確」＝候選字與整理本專名用字相同；',
                           '【專名線索】是程序按本書專名表（從本書機器識別文本中抽出、出現至少兩次的專名）機械匹配的結果（「精確」＝候選字與專名表用字相同；') \
    .replace('但整理本的專名寫法可能是通行字，刻本可能刻異體；', '專名表本身來自機器識別，可能夾帶個別錯字；')
def build(DAYS, d, ask, allpend, keys, txt, dictlib, MARK, with_ref=False, **kw):
    v3._NAMES = json.load(open(H + '/data/names_auto.json'))['names']
    msgs, marks = v3.build(DAYS, d, ask, allpend, keys, txt, dictlib, MARK, with_ref=False, **kw)
    u = msgs[1]['content']
    u = re.sub(r'\n\n【本日整理本中出現的專名】[^\n]*', '', u)
    u = u.replace('（整理本出現 ', '（本書自動文本出現 ').replace('近似：整理本此位作「', '近似：專名表此位作「')
    return [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': u}], marks
