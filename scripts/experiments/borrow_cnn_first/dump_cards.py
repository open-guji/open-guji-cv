"""把一本书的审卡装配结果落成规范 JSON（逐格卡片 / 按字种 / 按形聚类三种），
改前改后各跑一次比 sha256——验收「四庫、北行审卡数据改前改后一致」用。只读产物。

  GUJI_WORKSPACE=<ws> GUJI_CACHE_DIR=<沙箱> python dump_cards.py <book> <pages> <out.json>
"""
import hashlib
import json
import sys

from open_guji_cv.console.routers.review import cards_by_char, cards_by_shape
from open_guji_cv.products.store import ProductStore
from open_guji_cv.review.cards import cards

book, pages, out = sys.argv[1:4]
st = ProductStore()
res = {
    "cards": cards(book, pages, 10 ** 9, "review", st),
    "cards_auto": cards(book, pages, 300, "auto", st),
    "group_char": cards_by_char(book, pages, "review", st, gate_cut=True, skip_decided=True, sample_limit=60),
    "group_shape": cards_by_shape(book, pages, "review", st, gate_cut=True, skip_decided=True, sample_limit=60),
}
s = json.dumps(res, ensure_ascii=False, sort_keys=True, default=str)
open(out, "w", encoding="utf-8").write(s)
print(book, pages, {k: len(v.get("cards") or v.get("groups") or []) for k, v in res.items()},
      "sha256", hashlib.sha256(s.encode()).hexdigest()[:16])
