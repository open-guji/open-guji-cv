import sys, json, collections
from pathlib import Path
from open_guji_cv.utils import cut_select
cut_select.PROBE_DEV = -1.0   # 实验：所有切点都过 U-Net，信号全采；现行门槛离线模拟
from open_guji_cv.core.book import load_book
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
from open_guji_cv.utils.bootstrap import ensure_products
book, shard, nshard = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
pg=set()
for l in open('/home/user/open-guji-dataset/char-segmentation/touching-cuts/items.jsonl'):
    d=json.loads(l)
    if d['status']=='active' and d['anchor']['book']==book: pg.add(d['anchor']['page'])
pg=sorted(pg)[shard::nshard]
if len(sys.argv)>4: pg=pg[:int(sys.argv[4])]
import time;t=time.time()
ensure_products(load_book(book), pg, store=ProductStore(), cache=ImageCache())
print(book,shard,len(pg),'pages',time.time()-t,'s')
