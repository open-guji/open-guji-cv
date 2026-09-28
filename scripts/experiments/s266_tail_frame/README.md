# S#266 列尾下版框线（vol03）复现台

overview#266 的改前/改后对照都是**内存重跑**（不读磁盘产物当「旧」，见 cv-segmentation §11）。
工作目录由 `S266_DIR` 指定（中间结果都落在那里），沙箱用 `GUJI_PRODUCTS_DIR` / `GUJI_CACHE_DIR`：

```bash
export GUJI_WORKSPACE=<…>/96mid1ogzk-欽定四庫全書總目武英殿刻本
export GUJI_PRODUCTS_DIR=$S266_DIR/products_base   # snap/96mid1ogzk/vol03/20260928T1708-full 的 products/
export GUJI_CACHE_DIR=$S266_DIR/cache
# 1. Step3 全书：旧代码（git stash 或 detect_bottom_bar=False）→ run_base，新代码 → run_new
python rs_harness.py $S266_DIR/run_base ; python rs_harness.py $S266_DIR/run_new
python cmp.py $S266_DIR/run_base $S266_DIR/run_new > $S266_DIR/cmp.txt     # 变化列
# 2. Step4 只跑变化页（两份缓存分开，column_image 软链共用）
GUJI_CACHE_DIR=$S266_DIR/cache_base python cs_harness.py $S266_DIR/run_base $S266_DIR/cs_base <页…>
GUJI_CACHE_DIR=$S266_DIR/cache_new  python cs_harness.py $S266_DIR/run_new  $S266_DIR/cs_new  <页…>
python cell_diff.py         # 字块级差异 → cell_diff.json
python regress.py           # 格类型计数 / 夹注金标 / 切线金标
python build_review.py out.html   # A/B 盲评页（左右随机，映射冻结在 s266_cards.jsonl）
```

`rs_harness.py` 同时核对与磁盘产物是否一致：snap 那份产物 110 页里 3 页（20/28/107）不一致，
原因是工作区里之后又落了人裁切线（裁决不进指纹），所以「旧」一律用内存重跑的 run_base。
