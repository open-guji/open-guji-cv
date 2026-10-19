# 批量跑 yolo_tool 原生流程：python run_yolo.py <list.json: [[img_path, key],...]> <out.jsonl>
import sys,json,os,time
sys.path.insert(0,os.path.dirname(__file__))
from yolo_headless import *
items=json.load(open(sys.argv[1])); out=sys.argv[2]
done=set()
if os.path.exists(out):
    for l in open(out): done.add(json.loads(l)['key'])
tm,sm=YOLO(TYPE_PT),YOLO(SLIDE_PT)
f=open(out,'a'); t0=time.time()
for i,(path,key) in enumerate(items):
    if key in done: continue
    img=load_page(path)
    t_list,s_list=infer_page(img,tm,sm)
    order=reading_order(t_list,s_list)
    f.write(json.dumps({"key":key,"hw":img.shape[:2],"type":t_list,
        "chars":[{"col":c,"k":k,"xywh":[round(v,1) for v in b[:4]],"conf":round(b[5],3)} for c,k,b in order]},ensure_ascii=False)+"\n"); f.flush()
    if i%10==0: print(i,len(items),round(time.time()-t0),flush=True)
print('done',round(time.time()-t0),flush=True)
