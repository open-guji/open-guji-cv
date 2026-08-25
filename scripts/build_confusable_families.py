# -*- coding: utf-8 -*-
"""从**字体字形**建形近家族全对表（1214 字 × 全对 = 736k 对，4 分钟）。

    PYTHONPATH=. python scripts/build_confusable_families.py clean
    PYTHONPATH=. python scripts/build_confusable_families.py degraded

## 这张表干什么用

库匹配的覆盖率天花板是**异字对分数的上尾**：硬约束 precision ≥ 0.999 逼着
闸站在 0.9985，于是只放行 5% 的真同字对。把「结构上就该当形近家族看待」的
字对**直接否决掉**，闸就能往下走。实测（pairs knn 层，留出口径）：

    现状                        闸 0.9985  recall 0.0532
    只加字体护栏                 闸 0.9955  recall 0.1288
    只修 20 个疑似错标            闸 0.9895  recall 0.3131
    修错标 + 字体护栏(clean)     闸 0.9845  recall 0.4553
    修错标 + 字体护栏(degraded)  闸 0.9785  recall 0.5974   ← 11 倍

**为什么用字体而不用书上的数据**：拿书上的高分异字对反过来当护栏，
等于拿测试集自己学自己，量出来的提升是假的。字体与书本数据完全独立，
所以这张表当护栏是干净的。

## degraded 是什么

干净字体上 目/自 只有 0.942、注/註 0.851，可刻本上它们高得多——刻+印+扫+
归一化把区分性的细节抹平了，干净字体系统性**低估**书上的混淆度。所以另出
一版：渲染后加模糊+膨胀，仿刻印扫的退化（思路来自 Contrastive Attention
那篇的合成退化，见 .claude/doc/glyph_match_research.md §二③）。修完错标之后
degraded 版明显更好（0.5974 vs 0.4553）——**退化那一步是对的，之前被错标掩盖了**。

## 为什么能从 40 分钟压到 4 分钟

（实测 3.05 ms/对 → 0.33 ms/对，9.2×）

1. **参数是照「库匹配」调的，对字体表是浪费。** 默认 3 档缩放 × max_shift=3
   是为了吃下刻本的切分抖动；而这里两个字形都是同一支字体、同一号字渲染出来、
   再过同一个 `normalize_patch`（等比填满 + 质心居中），**根本没有那么大的
   尺度和平移差**。降到 1 档缩放 + max_shift=1：
   - 单对 3.05 → 1.24 ms（2.5×）；
   - 分数会整体挪一点（|Δ| 中位 0.029），但**「越没越过 τ」的判断在
     τ=0.99/0.98 上 100% 一致**，τ=0.96 上 99.93%。家族表只关心越阈，
     所以这个裁剪是安全的；τ 本来也要在留出集上扫，绝对值挪动无所谓。
2. **只用了 1/4 的机器。** 4 核，按行轮转分给 4 个进程（三角形负载，
   轮转比切块均衡）。
3. 预处理缓存开到 4096——1214 个字形 × 1 档缩放放得下，不再颠簸。

留了 `--full` 开关跑原参数，用来复核裁剪有没有改变结论。
"""
import sys, json, time, os, numpy as np, cv2
from multiprocessing import Pool
sys.path.insert(0,'/home/user/open-guji-cv')
from PIL import Image, ImageDraw, ImageFont
from fontTools.ttLib import TTFont
from open_guji_cv.clustering import verify as _V
from open_guji_cv.clustering.normalize import normalize_patch
_V.ELASTIC_PREP_CACHE = 4096

SP='/tmp/claude-0/-home-user-open-guji-cv/d16c26fc-ffa9-59a2-b17f-40f4df687434/scratchpad'
FONT='/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf'
MODE = sys.argv[1] if len(sys.argv)>1 else 'clean'
FULL = '--full' in sys.argv
KW = {} if FULL else dict(scales=(1.0,), max_shift=1)
NPROC = min(4, os.cpu_count() or 1)


def render(ch, ft, size=256):
    im = Image.new('L',(size,size),255)
    ImageDraw.Draw(im).text((size//2,size//2), ch, font=ft, fill=0, anchor='mm')
    a = np.array(im)
    if MODE == 'degraded':
        # 仿刻+印+扫的退化：干净字体上 目/自 只有 0.971、注/註 0.915，
        # 可刻本上它们是 0.993——细节被抹平了，干净字体系统性低估混淆度。
        a = cv2.GaussianBlur(a,(9,9),3.0)
        a = cv2.erode(a, np.ones((3,3),np.uint8))      # 黑字：erode = 墨变粗
        a = cv2.GaussianBlur(a,(5,5),1.5)
    return a


_cm = set(TTFont(FONT).getBestCmap())
_all = {r['char'] for r in
        json.load(open('/home/user/open-guji-dataset/glyph-match/pairs/expected.json'))['instances']}
CHARS = sorted(c for c in _all if ord(c) in _cm)
_ft = ImageFont.truetype(FONT, 180)
REPS = [normalize_patch(render(c, _ft)) for c in CHARS]


def rows(args):
    lo, step = args
    n = len(CHARS); out = {}
    for i in range(lo, n, step):
        ri = REPS[i]
        for j in range(i+1, n):
            out[CHARS[i]+CHARS[j]] = round(
                float(_V.verify_pair_elastic(ri, REPS[j], **KW).f1), 4)
    return out


if __name__ == '__main__':
    n = len(CHARS)
    print(f'{MODE}{" full" if FULL else ""}: {n} 字，{n*(n-1)//2} 对，{NPROC} 进程', flush=True)
    t0 = time.time()
    with Pool(NPROC) as p:
        parts = p.map(rows, [(k, NPROC) for k in range(NPROC)])
    out = {}
    for d in parts: out.update(d)
    tag = MODE + ('_full' if FULL else '')
    json.dump(out, open(f'{SP}/fontfam_{tag}.json','w'), ensure_ascii=False)
    dt = time.time()-t0
    print(f'完成 {len(out)} 对 {dt:.0f}s（{dt/len(out)*1000:.2f} ms/对）')
    s = sorted(out.items(), key=lambda x:-x[1])
    for th in (0.99,0.985,0.98,0.97,0.96,0.95,0.93,0.90):
        print(f'  ≥{th}: {sum(1 for _,v in s if v>=th)}')
    for q in ('一七','七匕','目自','注註','日目','山由','未末','玉王'):
        print(f'  {q}: {out.get(q, out.get(q[::-1],"?"))}')
    print('最像 24 对:', ', '.join(f'{k}({v:.3f})' for k,v in s[:24]))
