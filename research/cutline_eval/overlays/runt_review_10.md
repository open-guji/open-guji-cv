# 矮格复核 10 格(overview#554)

问每格:**线是否切进了字/多切了一格**(绿线=该格上下沿,红线=本列各格上沿)。回:对/切错/拿不准。

| cell_id | 类别 | h/period | 说明 | 图 |
|---|---|---|---|---|
| `vol02:113:1:4` | A 批已确认伤字 | 41/113=0.36 | 老|莊,线切进「莊」上部;该格 41px=0.36 period | `overlays/runt_review/vol02_p113_c1_s4.png` |
| `vol02:15:9:20` | 矮格(中段) | 37/114=0.32 | 线从「元」下半穿过;37px | `overlays/runt_review/vol02_p15_c9_s20.png` |
| `vol02:188:4:20` | 矮格(中段) | 39/113=0.35 | 线从「足」下半穿过;39px | `overlays/runt_review/vol02_p188_c4_s20.png` |
| `vol04:196:2:21` | 末格矮(slot21) | 66/113=0.58 | 66px=0.58 period,有墨 | `overlays/runt_review/vol04_p196_c2_s21.png` |
| `vol04:196:8:21` | 末格矮(slot21) | 66/113=0.58 | 66px=0.58 period,有墨 | `overlays/runt_review/vol04_p196_c8_s21.png` |
| `vol05:3:5:21` | 末格矮(slot21) | 59/114=0.52 | 59px=0.52 | `overlays/runt_review/vol05_p3_c5_s21.png` |
| `vol05:46:8:21` | 末格矮(slot21) | 63/113=0.56 | 63px=0.56 | `overlays/runt_review/vol05_p46_c8_s21.png` |
| `vol05:108:2:21` | 末格矮(slot21) | 49/114=0.43 | 49px=0.43 | `overlays/runt_review/vol05_p108_c2_s21.png` |
| `vol05:154:8:21` | 末格矮(slot21) | 67/114=0.59 | 67px=0.59 | `overlays/runt_review/vol05_p154_c8_s21.png` |
| `vol07:87:8:21` | 末格矮(slot21) | 65/112=0.58 | 65px=0.58 | `overlays/runt_review/vol07_p87_c8_s21.png` |

未入包:`vol04:14:5:21`(空列末格,ink 0.02、前一格 ink 0,不是字格切错)。
cell_id 格式 = `册:页:列:slot`(同 touching-cuts 的 id 口径)。