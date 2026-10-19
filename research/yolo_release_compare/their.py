import json,gzip,os
ROOT=os.environ.get('SIKU_RELEASE','siku/96mid1ogzk')  # release zip 解压后的 96mid1ogzk/
def load_ch(ch):
    rs=[json.loads(l) for l in gzip.open(f'{ROOT}/{ch}/text.jsonl.gz','rt')]
    return rs[0],{r['p']:r for r in rs[1:]}
def img_path(ch,p): return f'{ROOT}/{ch}/pages/{p:03d}.png'
def boxes(r, mode='tl'):
    out=[]
    small=set()
    for a,b in r['s']:
        small.update(range(a,a+b))
    for i,(x,y,w,h,c) in enumerate(zip(r['x'],r['y'],r['w'],r['hgt'],r['c'])):
        if mode=='center': x0,y0=x-w/2,y-h/2
        else: x0,y0=x,y
        out.append(dict(i=i,x0=x0,y0=y0,x1=x0+w,y1=y0+h,c=c,small=i in small))
    return out
FONT=os.environ.get('JIGMO_FONT','../yolo_tool/fonts/Jigmo.ttf')
def render(ch,p,out,crop=None,scale=1.0):
    from PIL import Image, ImageDraw, ImageFont
    h,P=load_ch(ch); r=P[p]
    im=Image.open(img_path(ch,p)).convert('RGB')
    d=ImageDraw.Draw(im); f=ImageFont.truetype(FONT,22)
    for b in boxes(r):
        col=(0,160,0) if b['small'] else (220,0,0)
        d.rectangle([b['x0'],b['y0'],b['x1'],b['y1']],outline=col,width=2)
        d.text((b['x1']-22,b['y0']+1),b['c'],font=f,fill=(0,0,255))
    if crop: im=im.crop(crop)
    if scale!=1: im=im.resize((int(im.width*scale),int(im.height*scale)))
    im.save(out)
def columns(r):
    """按 x 中心把大字分列（右→左）；小字按所在大列归并。返回 [[box,...],...]"""
    bs=boxes(r)
    if not bs: return []
    bs=sorted(bs,key=lambda b:-(b['x0']+b['x1'])/2)
    # 用 c 顺序自然分列：阅读顺序下 y 回跳即换列（夹注双行内部也会回跳，所以只看大字）
    cols=[];cur=[];lasty=-1;lastx=None
    for b in boxes(r):
        cx=(b['x0']+b['x1'])/2
        if cur and (b['y0']<lasty-20) and (lastx is None or abs(cx-lastx)>40 or not b['small']):
            # 换列（或夹注换小行）
            cols.append(cur);cur=[]
        cur.append(b);lasty=b['y0'];lastx=cx
    if cur: cols.append(cur)
    return cols
