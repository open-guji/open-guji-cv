"""按刻形拆判的异体对（2026-10-24，sheldon「尙尚、盖蓋葢…按 IDS 拆判」）：产物里已放行格（放行字当标签）＋人裁 → 整字 HOG 模板库，按册留出评测。

用法：python build_shape_pair.py <组 id> <原图根（<册>/<页>.png）> <数据目录（含 output/glyph_store，取人裁）> <产物根…> [--write] [--char-patch]
      [--dataset=<dataset>/char-groups/variant --by=claude-<线程> --date=YYYY-MM-DD]（训练集落 dataset）
      [--labels=<labels.jsonl>]（全部标签来自这份人裁表 `{id, form, src}`，不收放行格与中心库人裁：放行字被码位归一过的组用，如 變𠮓）
产物根下是 `<册>/seed_admit/p*.json` 与 `<册>/cell_shrink/p*.json`（`guji products pack fetch` 的布局）。

标签：已放行格的放行字（人裁格与印章通道不收），每册每字最多 `PER_VOL` 格；人裁刻形；`EXTRA` 是看图补的格（如送审格里的 盖）。
放行字是跟整理本或台账走的，混着码位错的格：先做一轮按册留出，与标签不一致的格逐格看过图（`DROP` 里的是看图确认标签错或看不清的），
不进模板，再按册留出评一遍，0 错门槛 ×1.1 进 `ids_online.SPECS`。
`--char-patch`：字块改用线上同款 char_patch（工作区 GUJI_WORKSPACE 要有该册产物与原图；kou 起用，早先的组是原图按框裁）。
"""
from __future__ import annotations

import glob
import json
import random
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from open_guji_cv.core.anchor import crop_patch
from open_guji_cv.groups import freq, ids_online as O, ids_whole
from open_guji_cv.groups.flow import is_provisional

PER_VOL = 12      # 每册每字最多收几格（模板库 <1MB）
#: 组 → 放行格每字总共最多收几格（人裁与看图补的格不限）：口框族 國圖固 放行格多、64×64 模板大，不封顶模板库 4MB
CAP = {"kou": 30, "fa": 60, "qi": 160, "xiang": 80, "weim": 80, "bie": 80, "zhen": 80, "li": 110, "xuan": 300}   # qi：陪衬 司音 放行格多
#: 组 → (字, 看图补的格 {id: 字}, 看图剔出的格)
PLAN = {
    # 尙／尚：上部 小（左撇外撇）对 ⺌（两点内收）。首轮按册留出与放行字不一致的 12 格看图：10 格是放行字码位错（按刻形改标签不如直接剔），
    # vol08:67:9:3（顶上压黑框）、vol14:3:9:12（印章底纹）看不清。
    "shang": ("尙尚", {}, {"vol16:48:2:12", "vol16:28:7:9", "vol13:188:8:8", "vol04:98:5:6", "vol17:72:9:19", "vol10:114:7:11",
                          "vol10:104:6:9", "vol05:115:6:7b", "vol09:116:3:11", "vol08:67:1:1", "vol08:67:9:3", "vol14:3:9:12"}),
    # 盖／蓋／葢：盖 无草头；蓋 草头下 去皿；葢 草头下 大皿（殿本多作葢）。盖 放行只 5 格，补 vol16–20 送审里看图确认是 盖 的 6 格。
    "gai": ("蓋葢", {}, {"vol16:30:2:12", "vol05:181:1:6"}),
    # 䟦／跋：右边 叐（横下作又、无点）对 犮（撇上带点）。䟦 放行少（15），补 vol11–20 送审里看图确认整理本作 䟦、刻形是 䟦 的 31 格。
    "ba": ("䟦跋", dict.fromkeys([
        "vol12:25:2:12", "vol12:92:5:21", "vol12:94:3:20", "vol12:151:8:17", "vol13:149:5:7", "vol13:152:6:20", "vol13:169:8:18",
        "vol13:185:7:17", "vol13:198:9:13", "vol13:199:7:10", "vol13:199:8:20", "vol13:225:3:11", "vol14:49:4:13", "vol15:5:3:10",
        "vol15:94:1:20", "vol15:103:3:14", "vol15:123:6:6", "vol16:128:3:10", "vol16:145:3:8", "vol17:73:5:14", "vol17:83:8:11",
        "vol17:110:3:16", "vol17:110:7:4", "vol17:110:8:20", "vol18:66:1:5", "vol19:5:6:19", "vol19:5:8:9", "vol19:5:8:20",
        "vol19:162:8:14", "vol20:98:1:15", "vol20:120:1:6",
    ], "䟦"), {"vol06:106:1:17", "vol09:239:1:18", "vol10:65:4:4", "vol14:48:8:19"}),   # 放行成 跋、刻形是 叐（无点、下作又）
    # 凖／準（长尾异体对，2026-10-24）：左旁 冫（点＋一长提斜穿）对 氵（三笔竖排）。放行成 準、刻形是 冫 的 2 格剔出（vol20:100:1:6 是送审格本身），
    # vol17:92:1:8 中间一笔看不清，剔出。
    "zhun": ("凖準", {}, {"vol05:177:6:17", "vol20:100:1:6", "vol17:92:1:8"}),
    # 宻／密：中部 㐅 交叉（无点）对 必（两侧带点）。放行成 密、刻形是 㐅 的 2 格（vol17:139:4:15、vol17:70:4:21）剔出，vol20:104:3:6 墨团看不清剔出。
    "mi": ("宻密", {}, {"vol17:139:4:15", "vol17:70:4:21", "vol20:104:3:6"}),
    # 䘮／喪（2026-10-25）：中部 从（两人）对 吅（两口）。首轮按册留出的 2 个错例看图是放行成 喪、刻 䘮（vol12:147:2:8、145:6:12），改标；
    # 补 vol11–20 送审格看图 6 格（5 格 䘮、vol16:82:3:7 喪）。
    "sang": ("䘮喪", {"vol12:147:2:8": "䘮", "vol12:145:6:12": "䘮", "vol11:11:4:10": "䘮", "vol13:18:9:11": "䘮", "vol13:19:2:19": "䘮",
                     "vol17:91:1:9": "䘮", "vol16:82:3:7": "喪"}, set()),
    # 變／𠮓（2026-10-25）：下部 攵（左上多一短撇）对 又。工作区码位归一 變→𠮓 把放行字全改成 𠮓，放行字不能当标签；
    # 标签全走 sheldon 的人裁表（dataset variant/bian/sheldon_labels.jsonl，`--labels`）。
    "bian": ("變𠮓", {}, set()),
    # 象／𧰼（2026-10-26，A24 全册任务 08）：⺈ 下 带一竖的框（象）对 空框（𧰼）。标签全走人裁表（`--labels`：dataset 人裁刻形＋
    # sheldon 10-26 标注页 173 格）；已放行 象 里混着 𧰼（标注页 14 格高分反对里 10 格是 𧰼），放行字不当标签。
    "xz": ("象𧰼", {}, set()),
    # 口框族 國圖圍園固圓圜（形近不同义，框内部件不同）；圃 圈 囿 进库当陪衬。團 殿本没有放行格，不进库。
    # 首轮按册留出与标签不一致的格看图：vol12:41:9:14 放行 圃、刻形是 園（标签错）；vol19:65:2:12、vol13:223:6:21、vol11:86:2:21、
    # vol20:224:1:21 字块切坏（连进邻字或缺半边）。其余不一致的是真判错（圜↔園、圓↔圖），留着定门槛。
    "kou": ("國圖圍園固圓圜圃圈囿", {}, {"vol12:41:9:14", "vol19:65:2:12", "vol13:223:6:21", "vol11:86:2:21", "vol20:224:1:21"}),
    # 撰／𢰅（3–4 格异体对，2026-10-24）：撰 ⿰扌巽（巳巳 下 共：两短竖＋小八）对 𢰅 ⿰扌㢲（巳巳 下 丌，殿本刻作长撇长捺大开）。
    # 𢰅 放行 33 格（vol19–20 为主）。用首轮库把 vol04–20 全部 1,633 格 撰／𢰅 判一遍，放行成 撰、判成 𢰅 的格逐格看图：22 格刻形是 𢰅
    # （vol05 p128–150 一批「某某撰」、vol17:83:8:7、vol19:100:2:6、vol19:107:3:6，后者是按册留出唯一的错例），改标 𢰅 补进；
    # vol08:5:4:6 下部看不清，剔出；印章格、人裁格各 1 与 vol16:65:8:7（0.09）是 撰，不动。
    "zhuan": ("撰𢰅", dict.fromkeys([
        "vol05:128:2:7", "vol05:128:8:7", "vol05:130:4:6", "vol05:133:2:6", "vol05:134:1:7", "vol05:134:9:7", "vol05:135:6:7",
        "vol05:135:9:7", "vol05:136:6:7", "vol05:138:9:7", "vol05:139:5:7", "vol05:140:1:6", "vol05:141:1:7", "vol05:142:1:7",
        "vol05:143:1:7", "vol05:144:1:7", "vol05:144:8:7", "vol05:146:3:7", "vol05:150:1:7", "vol17:83:8:7", "vol19:100:2:6",
        "vol19:107:3:6",
    ], "𢰅"), {"vol08:5:4:6"}),
    # 瑣／𤨏（2026-10-25，GUJI-719）：右上 ⺌（瑣）对 巛（𤨏）。𤨏 放行 8 格全是坐标兜底通道，补送审格 vol16:142:2:10（看图 巛）。
    "suo": ("瑣𤨏", {"vol16:142:2:10": "𤨏"}, set()),
    # 隱／𨼆（2026-10-25，A24「压低 vol21–50 形近字组送审」，首跑 V 类）：右上 爫工（隱）对 平顶 丅⺊、无 工（𨼆 ⿰阝⿳⿸丅⺊⺕心）。
    # 字形库没有 𨼆，库排成 隱。𨼆 放行只 1 格，补 vol21–50 送审里看图确认整理本作 𨼆、刻形是 𨼆 的 33 格；首轮按册留出的错例看图：
    # 放行成 隱、刻 𨼆 的 3 格改标；vol44:37:6:20（墨糊）、vol46:47:3:19（放行 𨼆、顶上像 爫）看不清，剔出。
    # 整理本作 隠 的（放行 28 格、送审 19 格）放大看与 𨼆 同一刻形，记成 𨼆（`ALIAS`）；其中 vol22:85:1:8 放行成 隠、刻 隱（爫工），改标。
    # 按册留出：门槛 0.5 错 2（标 𨼆 判 隱，margin 0.83／0.67），0.85 起 0 错（给 192：隱 130、𨼆 62），门槛取 0.85。
    "yin": ("隱𨼆隙臆匱應隔", dict.fromkeys([
        "vol32:63:5:10", "vol32:64:9:15", "vol32:82:2:5", "vol34:137:8:7", "vol34:36:4:10", "vol41:164:2:11", "vol41:86:1:15",
        "vol44:144:9:7", "vol44:201:8:9", "vol44:58:5:11", "vol44:77:9:8", "vol44:79:8:12", "vol44:87:5:18", "vol45:94:8:3",
        "vol46:24:8:10", "vol47:31:2:5", "vol48:245:7:16", "vol49:110:4:7", "vol49:141:1:20", "vol49:141:4:9", "vol49:151:2:16",
        "vol49:156:5:9", "vol49:163:3:21", "vol49:181:7:11", "vol49:21:8:9", "vol49:28:4:11", "vol49:9:6:9", "vol50:10:5:18",
        "vol50:33:6:13", "vol50:40:7:10", "vol50:44:7:20", "vol50:4:7:12", "vol50:9:5:11",
    ], "𨼆") | dict.fromkeys([                                   # 整理本作 隠、同刻形
        "vol31:140:6:8", "vol31:154:2:13", "vol31:154:2:15", "vol31:154:2:17", "vol31:154:2:21", "vol31:154:3:4",
        "vol31:154:4:11", "vol31:154:5:21", "vol31:154:7:15", "vol31:157:8:18", "vol41:135:8:9", "vol44:100:8:20",
        "vol44:214:5:19", "vol48:66:1:17", "vol48:67:4:19", "vol50:100:6:13", "vol50:120:9:19", "vol50:196:7:8", "vol50:69:7:6",
    ], "𨼆") | dict.fromkeys(["vol49:138:4:12", "vol44:227:7:20", "vol45:109:6:8"], "𨼆") | {"vol22:85:1:8": "隱"}, {"vol44:37:6:20", "vol46:47:3:19"}),
    # 算／𮅕（同上）：下部 廾（两竖）对 大（长撇长捺，𮅕 ⿱𥫗狊）。字形库没有 𮅕，库多排成 莫。补送审看图确认的 40 格；
    # vol49:191:4:1（「算學八卷」）上部墨重像 冖，剔出。
    "suan": ("算𮅕莫㝠箕集篇", dict.fromkeys([
        "vol49:105:2:9", "vol49:111:7:9", "vol49:119:5:5", "vol49:119:6:9", "vol49:125:7:19", "vol49:132:1:11", "vol49:136:2:3",
        "vol49:139:7:5", "vol49:148:8:18", "vol49:151:1:20", "vol49:151:9:6", "vol49:152:8:13", "vol49:154:9:11",
        "vol49:156:8:8", "vol49:175:4:5", "vol49:176:1:12", "vol49:176:7:21", "vol49:177:3:4", "vol49:178:3:4", "vol49:178:6:16",
        "vol49:180:8:13", "vol49:180:9:20", "vol49:180:9:6", "vol49:183:1:20", "vol49:185:1:11", "vol49:185:3:11",
        "vol49:188:3:6", "vol49:190:4:17", "vol49:191:6:6", "vol49:193:2:14", "vol49:195:1:10", "vol49:195:2:17",
        "vol49:195:6:5", "vol49:196:3:15", "vol49:196:4:18", "vol49:98:1:21", "vol49:98:2:12", "vol49:98:8:9", "vol50:198:5:14",
        "vol50:218:8:21",
    ], "𮅕"), {"vol49:191:4:1"}),
    # 闗／關（同上）：門内下部 灬（闗）对 丱（關，两腿长垂）。闗 放行 19 格，补送审看图确认的 17 格（库多排成 闡間）；
    # 首轮按册留出错例看图：放行成 關、刻 闗（下部四点）的 6 格改标。
    # 这几组的第一项里成员后面的字是陪衬（库形紧咬的组外字，registry `_SHAPE_PAIR_FLOW`），也进模板库，判成它们＝弃权。
    # 勢／𫝑、發／𤼵（2026-10-25，sheldon 定按刻形分拆）：放行格里两形混放（放行字跟整理本走），放行字不能当标签；
    # 标签全走 sheldon 的标注表（dataset variant/{shi,fa}/sheldon_labels.jsonl，`--labels`）：标注页预填机器判的刻形，
    # sheldon 逐格过了一遍、改了有疑问的格，没点的＝按预填（src「其余」，每册每字 ≤PER_VOL 进模板）。
    # 勢／𫝑：左上 坴（勢）对 幸（𫝑 ⿱執力，左上横画多、叠得高）。
    # vol51–99（2026-10-26）：首跑包回放的 144 格上标注页，sheldon 改 1 格；按册留出错例 vol53:2:7:4 墨断看不清，标注表里置空剔出。
    "shi": ("勢𫝑", {}, set()),
    # 發／𤼵：右下 殳（發）对 矢（𤼵 ⿱癶矤）。字形库没有 𤼵，库排成 發登務條；登務條 当陪衬进库（`--labels` 时照收放行格）。
    # vol51–99（2026-10-26）：回放没把握的 60 格上标注页（sheldon 改 3 格），高把握改判 𤼵 的 99 格 A24 右下放大逐张看过，一并进表。
    "fa": ("發𤼵登務條", {}, set()),
    # 派／𣲖（2026-10-26，A24「压低 vol51–99 形近字组送审」，首跑 V 类）：右边 𠂢 上有横（派）对 无横、三竖并列（𣲖）。
    # 字形库没有 𣲖，库排成 泒。首轮按册留出唯一错例 vol62:140:5:16 放行成 泒、刻形是 𣲖，改标。
    # 選𨕖（2026-10-26，全册任务 03）：𨕖 放行 0 格；补 整理本作 𨕖、看图是丌形的送审 35 格，和放行 選 里看图是丌形的 7 格（整理本作 選）。
    "xuan": ("選𨕖", dict.fromkeys([
        "vol20:228:6:19", "vol29:90:4:4", "vol31:135:4:16", "vol37:122:8:14", "vol39:5:6:14", "vol39:90:9:8", "vol39:92:2:3",
        "vol39:94:4:21", "vol39:96:8:17", "vol42:3:6:13", "vol42:7:3:13", "vol66:116:2:20", "vol66:118:6:15", "vol66:121:6:5",
        "vol66:122:7:17", "vol66:138:6:20", "vol66:191:9:13", "vol83:139:8:4", "vol86:22:6:11", "vol86:30:6:3", "vol86:38:5:12",
        "vol86:38:5:17", "vol86:38:6:3", "vol86:38:6:7", "vol86:38:6:12", "vol86:39:7:3", "vol86:55:9:5", "vol86:55:9:7",
        "vol86:56:2:6", "vol86:74:1:9", "vol86:76:3:7", "vol86:104:5:3", "vol96:165:8:12", "vol39:94:8:16", "vol86:38:7:9",
        "vol94:128:5:18", "vol86:5:5:17", "vol31:40:2:7", "vol14:45:4:17", "vol86:7:7:4", "vol28:53:6:9", "vol20:240:7:11",
    ], "𨕖"), set()),
    "pai": ("派𣲖", {"vol62:140:5:16": "𣲖"}, set()),
    # 隸／𨽾（2026-10-26，A24 全册任务 07）：左上 木（柰，隸）对 士（士示）。士示 一种刻法整理本作 隷／𨽻、字形库标 𨽾（`ALIAS` 并成 𨽾）。
    # 蒙／𫎇（2026-10-26，A24 全册任务 07）：头部 艹（蒙）对 〢丷（两竖带点，𫎇）。整理本作 䝉 的与 𫎇 同一刻法（`ALIAS` 并成 𫎇）。
    # 放行字与整理本一个 艹 一个 〢丷 的 20 格（多是 mn 组旧判法「库形最近」放的）不进模板，由复核重判。
    # 放行成 蒙 的 31 格放大看，5 格头部是 〢丷（两竖外带点、上面没有 艹 的横），改标 𫎇。
    "mn": ("蒙𫎇", dict.fromkeys(["vol39:14:8:10", "vol53:15:9:13", "vol89:180:6:9", "vol94:106:7:15", "vol21:121:2:5"], "𫎇"), {
        "vol13:76:1:19", "vol20:199:5:3", "vol20:241:6:20", "vol20:32:9:7", "vol38:206:5:10", "vol39:22:9:20", "vol39:48:5:9",
        "vol39:49:3:4", "vol42:23:5:3", "vol45:121:1:11", "vol53:12:4:9", "vol53:14:3:11", "vol53:15:8:8", "vol88:102:6:7",
        "vol89:180:6:9", "vol94:106:4:2", "vol94:106:6:9", "vol94:20:7:3", "vol94:43:1:21", "vol94:69:1:19",
    }),
    # 整理本作 隸、放行成 𨽾（或反过来）的 45 格是码位放错（看图多是 柰 旁放成 𨽾），不进模板，由复核改回。
    # 首轮按册留出 margin ≥0.29 的 5 个错例看图都是 柰 旁、整理本缺位放成 𨽾，也剔出（首 5 个）。
    "li": ("隸𨽾", {}, {
        "vol64:132:3:13", "vol58:84:1:9", "vol64:30:4:16", "vol18:59:1:10a", "vol40:116:8:8",
        "vol21:107:8:4", "vol21:59:3:7", "vol24:45:6:15", "vol24:61:8:14", "vol31:123:6:8a", "vol31:134:1:10", "vol31:173:8:10a",
        "vol31:202:9:9a", "vol34:140:9:13", "vol35:51:8:9a", "vol38:174:3:8", "vol38:77:9:16", "vol38:86:1:17", "vol38:92:8:16",
        "vol39:13:3:19", "vol39:27:7:14", "vol42:27:3:21", "vol44:4:4:17", "vol46:104:5:9a", "vol46:30:1:9a", "vol46:91:8:6a",
        "vol47:143:3:8a", "vol50:16:3:4", "vol50:79:8:14", "vol58:121:9:12a", "vol59:173:9:16a", "vol63:15:6:8a",
        "vol63:32:6:10a", "vol63:8:8:8a", "vol63:9:4:7a", "vol63:9:9:8a", "vol64:10:9:12a", "vol64:186:9:6", "vol64:28:2:8",
        "vol75:111:2:9", "vol82:7:8:15", "vol86:114:4:7a", "vol89:10:5:10a", "vol89:129:3:9a", "vol89:48:3:9a", "vol89:49:6:9a",
        "vol89:82:5:9a", "vol90:76:6:8a", "vol95:92:5:3", "vol95:94:5:16",
    }),
    # 奇／竒（同上）：上部 大（撇向左下出头）对 立（点横、平顶）。放行字跟整理本走，混放：首轮按册留出错例看图，
    # 放行成 奇、刻 竒 的 11 格改标；放行成 苛、刻 竒 的 vol92:5:4:6 改标；放行成 竒、刻 奇 的 3 格改标；
    # vol67:11:9:17、vol70:37:6:15（字块切掉上半）、vol87:94:6:8 看不清，剔出。
    # 音苛司 是库形紧咬的陪衬（送审格库首位多是 音）。苛 放行只 14 格，按册留出 苛 判成 竒 最高 0.91，门槛取 1.0。
    "qi": ("奇竒音苛司", dict.fromkeys(["vol55:11:8:3", "vol88:143:5:3", "vol88:155:2:9", "vol68:138:7:3", "vol88:148:9:17", "vol80:110:2:16",
                                      "vol64:152:8:7", "vol79:120:8:16", "vol64:71:8:6", "vol68:138:4:17", "vol64:198:7:2", "vol92:5:4:6"], "竒")
           | dict.fromkeys(["vol67:74:5:11", "vol63:34:5:9", "vol83:60:8:3"], "奇"), {"vol67:11:9:17", "vol70:37:6:15", "vol87:94:6:8"}),
    # 歲／嵗（同上）：上部 止（歲）对 山（嵗）。嚴巖熾 是陪衬（送审格库首位多是 歲，其次 熾嚴巖）。
    # 首轮按册留出成员错例只 vol56:48:2:5（放行 歲、判 嵗 0.93），上部墨糊，剔出。
    "sui": ("歲嵗熾嚴巖", {}, {"vol56:48:2:5"}),
    # 码位已定仍送审的形近族（2026-10-26，A24 全册任务 04）：整理本作 鄉鄕／㣲微／別别／鎭鎮，库首位却是形近的另一个字（卿、徵徴、刖則所、鍾愼…），
    # 字形库在两三个字间分不开（cov 差 0.01 内）。码位已定（鄉→鄕 㣲→微 别→別 鎮→鎭），两码位并成一类（`ALIAS`），形近字当陪衬进库（判成它们＝弃权）。
    # 首轮按册留出与标签不一致、判成本组字的格看图：vol10:11:4:9 放行成 徴、字块是 所（剔出）；vol62:108:8:14、108:8:10 放行成 刖、刻形是 別
    # （左 口力，放行错，剔出；殿本 刖 放行只这 2 格）。
    "xiang": ("鄕卿鄭鄒郡", {}, set()),
    "weim": ("微徵徴徹", {}, {"vol10:11:4:9"}),
    "bie": ("別刖則所冊册", {}, {"vol62:108:8:14", "vol62:108:8:10"}),
    "zhen": ("鎭鍾愼慎鏡鏤銷續錢鈿鑽錄鉤鉞銀鍵", {}, set()),
    "guanm": ("闗關闡間閱閣聞開", dict.fromkeys([
        "vol31:181:3:13", "vol32:102:1:10", "vol34:102:8:8", "vol34:12:9:14", "vol34:93:6:5", "vol36:66:9:20", "vol36:71:3:15",
        "vol38:56:6:11", "vol38:69:7:19", "vol40:168:8:21", "vol41:128:4:8", "vol41:135:5:19", "vol45:118:4:5", "vol46:84:8:16",
        "vol49:74:7:19", "vol50:173:4:11", "vol50:180:6:13",
    ], "闗") | dict.fromkeys(["vol48:37:6:6", "vol45:66:1:7", "vol45:32:8:15", "vol50:248:7:11", "vol40:172:1:10", "vol36:94:6:21"], "闗"),
     set()),
    # 组外异体对 11 对（2026-10-26，A24 全册任务 01）：标签走 `--labels`（HOG 聚类＋看图），见 dataset variant/<组>/。
    "yinv": ("陰隂", {}, set()),
    "xian": ("陷䧟", {}, set()),
    "shu": ("䟽疏", {}, set()),
    "ning": ("寧寜", {}, set()),
    "yao": ("謠謡", {}, set()),
    "jim": ("覊羈", {}, set()),
    "xun": ("巡廵", {}, set()),
    "jian": ("劍劔", {}, set()),
    "chi": ("勅敕", {}, set()),
    "bi": ("𡚁弊", {}, set()),
    "huiq": ("囘回", {}, set()),
}


#: `--labels` 表里 src 以这些字开头的行（人只说了「其余都是 X」、没逐格点的），每册每字也只收 PER_VOL 格
BULK_SRC = ("其余",)


def labels_extra(path: Path) -> dict:
    """人裁表 → {格: 刻形}；form 为空（别的字）的不收；BULK_SRC 的行每册每字 ≤PER_VOL（按格号定序取前几格）。"""
    out, per = {}, Counter()
    for r in sorted((json.loads(l) for l in open(path, encoding="utf-8") if l.strip()), key=lambda r: r["id"]):
        if not r.get("form"):
            continue
        if r.get("src", "").startswith(BULK_SRC):
            k = (r["id"].split(":")[0], r["form"])
            if per[k] >= PER_VOL:
                continue
            per[k] += 1
        out[r["id"]] = r["form"]
    return out


#: 剔出模板的格里看图有结论的（只进数据集当记录，不进模板）：组 → {格: (刻形, 说明)}
LOOKED = {
    "zhun": {"vol05:177:6:17": ("凖", "放行成 準，刻形左旁是 冫"), "vol20:100:1:6": ("凖", "放行成 準（文意通道），刻形左旁是 冫；整理本作 凖")},
    "mi": {"vol17:139:4:15": ("宻", "放行成 密，中部是 㐅 交叉、无点"), "vol17:70:4:21": ("宻", "放行成 密，中部是 㐅 交叉、无点"),
           "vol20:104:3:6": ("宻", "放行成 密，墨重，中部偏 㐅；不进模板")},
}


def export(g: str, cells, data: Path, out: Path, by: str, date: str, labsrc: dict | None = None):
    """训练集落 dataset `char-groups/variant/<组>/`：labels.jsonl（一格一行）、crops/（建库用的清洗后字块）、split.json（按册分折）。
    `labsrc`（`--labels` 模式）：{格: 人裁表里的 src}，来源照抄人裁表。"""
    human = set() if labsrc else {k for k, f in freq.human_shapes(data).items() if f in PLAN[g][0]}
    d = out / g
    (d / "crops").mkdir(parents=True, exist_ok=True)
    rows, split = [], {}
    for f, gray, b, k in sorted(cells, key=lambda c: c[3]):
        cv2.imwrite(str(d / "crops" / (k.replace(":", "_") + ".png")), np.asarray(gray))
        if labsrc and k in labsrc:                    # 陪衬（放行格）不在人裁表里，照下面放行格记
            rows.append({"id": k, "form": f, "by": "sheldon", "date": date, "src": labsrc[k], "in_bank": True})
            split.setdefault(b, []).append(k)
            continue
        src = "human" if k in human else ("look" if k in PLAN[g][1] else "admit")
        rows.append({"id": k, "form": f, "by": {"human": "sheldon", "look": by, "admit": "auto-admit"}[src], "date": date,
                     "src": {"human": "central:人裁刻形", "look": "看图补", "admit": "已放行格（放行字当标签）"}[src], "in_bank": True})
        split.setdefault(b, []).append(k)
    for k, (f, note) in sorted(LOOKED.get(g, {}).items()):
        rows.append({"id": k, "form": f, "by": by, "date": date, "src": "看图（剔出模板的格）", "note": note, "in_bank": False})
    with open(d / "labels.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    (d / "split.json").write_text(json.dumps({b: sorted(v) for b, v in sorted(split.items())}, ensure_ascii=False, indent=1) + "\n",
                                  encoding="utf-8")
    print("数据集", d, len(rows), "行")


def _page(imgs: Path, book: str, page: int, _c={}):
    k = (book, page)
    if k not in _c:
        _c.clear()
        _c[k] = cv2.imread(str(imgs / book / f"{page}.png"), cv2.IMREAD_GRAYSCALE)
    return _c[k]


def char_patch_fn():
    """线上同款字块（`ctx.image("char_patch")`，列图＋折线缝）：要工作区（GUJI_WORKSPACE）里有该册产物与原图。→ fn(册, 格 id)。"""
    from open_guji_cv import steps as _s  # noqa: F401
    from open_guji_cv.core.book import load_book
    from open_guji_cv.core.step import RunContext
    from open_guji_cv.products.cache import ImageCache
    from open_guji_cv.products.store import ProductStore
    cache, ctxs = ImageCache(), {}

    def fn(book: str, cid: str):
        _, p, c, s = cid.split(":")
        sub = s[-1] if s[-1] in "ab" else ""
        if book not in ctxs:
            ctxs[book] = RunContext(load_book(book), ProductStore(), cache, log=lambda _: None)
        try:
            return ctxs[book].image("char_patch", f"p{int(p):04d}c{int(c):02d}s{s.rstrip('ab')}{sub}")
        except Exception:   # noqa: BLE001 —— 再生不出的格不进库
            return None
    return fn


#: 同一刻形、整理本／字形库用了两个码位的，建库时并成一类（键码位的格记成值码位）。
#: 隠／𨼆（2026-10-25）：vol21–50 整理本作 隠 与作 𨼆 的格放大并排看是同一刻形（平顶 丅⺊、无 工），IDS 合 𨼆；码位待 sheldon 定。
ALIAS = {"yin": {"隠": "𨼆"}, "xiang": {"鄉": "鄕"}, "weim": {"㣲": "微"}, "bie": {"别": "別"}, "zhen": {"鎮": "鎭"}, "li": {"隷": "𨽾", "𨽻": "𨽾"}, "mn": {"䝉": "𫎇"}}


def gather(prods, imgs: Path, data: Path, chars: str, extra: dict, drop: set, group: str = "", patch_fn=None):
    """`patch_fn(册, 格 id)` 给了就用它取字块（线上同款 char_patch，见 `char_patch_fn`），否则按 cell_shrink 框从原图裁。"""
    random.seed(0)
    alias = ALIAS.get(group, {})
    chars = chars + "".join(alias)
    want: dict = {}                                   # id → (字, 来源)
    per: Counter = Counter()
    for root in prods:
        for vd in sorted(glob.glob(str(Path(root) / "vol*"))):
            book = Path(vd).name
            rs = []
            for f in sorted(glob.glob(f"{vd}/seed_admit/p*.json")):
                for col in json.load(open(f, encoding="utf-8"))["seed_admit"]["columns"]:
                    rs += [r for r in col["chars"] if r.get("admit") and r.get("char") in set(chars)
                           and r.get("channel") not in ("human", "seal") and not is_provisional(r)]   # 暂归一兜底的格写法没拆，不当模板
            random.shuffle(rs)
            for r in rs:
                if per[(book, r["char"])] < PER_VOL and r["id"] not in drop:
                    per[(book, r["char"])] += 1
                    want[r["id"]] = (alias.get(r["char"], r["char"]), r["channel"])
    cap = CAP.get(group)
    if cap:
        byc: dict = {}
        for k, (f, _) in sorted(want.items()):
            byc.setdefault(f, []).append(k)
        for f, ks in byc.items():
            if len(ks) > cap:
                for k in set(ks) - set(random.sample(ks, cap)):
                    del want[k]
    for k, f in freq.human_shapes(data).items():
        if f in chars and k not in drop:
            want[k] = (alias.get(f, f), "human")
    for k, f in extra.items():
        want[k] = (f, "look")
    cells = []
    by_page: dict = {}
    for k, v in want.items():
        b, p = k.split(":")[:2]
        by_page.setdefault((b, int(p)), []).append((k, v))
    for (b, p), ks in sorted(by_page.items()):
        sh = next((Path(r) / b / "cell_shrink" / f"p{p:04d}.json" for r in prods if (Path(r) / b / "cell_shrink" / f"p{p:04d}.json").exists()), None)
        img = _page(imgs, b, p)
        if sh is None or img is None:
            continue
        box = {c["id"]: c["bbox_page"] for col in json.load(open(sh, encoding="utf-8"))["char_index"]["columns"] for c in col["chars"]}
        for k, (f, src) in ks:
            if k not in box:
                continue
            g = patch_fn(b, k) if patch_fn is not None else crop_patch(img, tuple(box[k]))
            if g is not None:
                cells.append((f, ids_whole.clean_patch(g), b, k))
    return cells


def loo(cells, sp):
    d = ids_whole.build("x", cells, sp.size)
    tpl = {k: [O._dec(s, sp.size) for s in v] for k, v in d["templates"].items()}
    books, keys = d["source"]["books"], d["source"]["keys"]
    res = []
    for bk in sorted({b for v in books.values() for b in v}):
        sub = {n: [t for j, t in enumerate(tpl[n]) if books[n][j] != bk] for n in tpl}
        for f in tpl:
            for i, x in enumerate(tpl[f]):
                if books[f][i] == bk:
                    ch, m, _ = ids_whole.score_norm(x, sub, sp.whole, tuple(sp.region), sp.lam)
                    ok = len(sub.get(ch, [])) >= sp.min_class
                    res.append((f, ch if ok else None, m, keys[f][i]))
    return res


if __name__ == "__main__":
    g, imgs, data = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    prods = [a for a in sys.argv[4:] if not a.startswith("--")]
    chars, extra, drop = PLAN[g]
    sp = O.SPECS[g]
    lab = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--labels=")), None)
    if lab:                                           # 全部标签走人裁表：不收放行格、不收中心库人裁
        extra = {**labels_extra(Path(lab)), **extra}
    if lab:                                           # 标签字只走人裁表；成员以外的陪衬照收放行格
        chars = "".join(ch for ch in chars if ch not in set(extra.values()))
    cells = gather(prods, imgs, data, chars, extra, drop, g, char_patch_fn() if "--char-patch" in sys.argv else None)
    print(g, "cells", Counter(c[0] for c in cells), "册", len({c[2] for c in cells}))
    res = loo(cells, sp)
    wrong = sorted(((m, f, ch, k) for f, ch, m, k in res if ch and ch != f), reverse=True)
    thr0 = wrong[0][0] if wrong else 0.0
    for t in sorted({0.3, 0.5, sp.min_margin, round(thr0 * 1.1, 2)}):
        give = [r for r in res if r[1] and r[2] >= t]
        print(f"  门槛 {t:.2f}: 给字 {len(give)}/{len(res)}，错 {sum(1 for r in give if r[1] != r[0])}",
              dict(Counter(r[0] for r in give if r[1] == r[0])))
    print("  错例（不设门槛）", [(k, f, "→", ch, round(m, 2)) for m, f, ch, k in wrong[:10]])
    if "--write" in sys.argv:
        d = ids_whole.build(g, cells, sp.size, {"labels": f"殿本已放行格（每册每字 ≤{PER_VOL}，放行字当标签，去掉看图确认码位错的格）＋人裁刻形＋看图补的格"})
        p = Path(__file__).resolve().parents[3] / "config" / "groups" / g / "ids_bank.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        O.write_bank(d, p)
        print("写", p, p.stat().st_size)
    ds = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--dataset=")), None)
    if ds:                                            # --dataset=<dataset>/char-groups/variant --by=claude-<线程> --date=YYYY-MM-DD
        kv = dict(a[2:].split("=", 1) for a in sys.argv if a.startswith("--") and "=" in a)
        labsrc = {r["id"]: r.get("src", "") for r in map(json.loads, open(lab, encoding="utf-8")) if r.get("form")} if lab else None
        export(g, cells, data, Path(ds), kv.get("by", "claude"), kv.get("date", ""), labsrc)
