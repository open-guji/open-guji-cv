"""补跑只在人裁事件里出现、金标里没有的页（extra_pages.json: {book:[页]}），口径同 gen_products.py。"""
import sys, json
from open_guji_cv.utils import cut_select
cut_select.PROBE_DEV = -1.0
from open_guji_cv.core.book import load_book
from open_guji_cv.products.cache import ImageCache
from open_guji_cv.products.store import ProductStore
from open_guji_cv.utils.bootstrap import ensure_products
book, i, n = sys.argv[1], int(sys.argv[3]), int(sys.argv[4])
pg = json.load(open(sys.argv[2]))[book][i::n]
ensure_products(load_book(book), pg, store=ProductStore(), cache=ImageCache())
print(book, i, len(pg), 'pages done')
