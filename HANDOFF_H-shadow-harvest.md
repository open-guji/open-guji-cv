# H 道交单：影子核对页人裁收回（overview#272）

分支 `claude/H-shadow-harvest-0929`（基于 cv main 9ad3aaa）。**没有重算任何产物，没有动 ws。**

## 收回结果
页 `https://claude.ai/artifact/AbZcW34aYjumsvN2V2Z6oU`（vol03 影子≠现字核对，97 张卡）读回 **33 / 97 已裁**：
a 11 + b 12 = **23 张给字**，neither **10 张**，idk 0，未裁 64。

| 项 | 路径 / 数 |
|---|---|
| 事件文件 | `handoff/H-shadow-harvest/vol03-shadow-review-0929.jsonl`，**33 条**（23 条 `v=confirm`＋`shape`，10 条 `v=seg_defect quality=truncated shape=""`） |
| 落点（总管拷贝） | ws `96mid1ogzk-*/feedback/events/vol03-shadow-review-0929.jsonl` |
| 页上原始裁决快照 | `artifacts/vol03_shadow_review_verdicts.jsonl`（33 行 id/verdict/t） |
| 收回脚本 | `scripts/harvest_shadow_review.py`（测试 `tests/test_harvest_shadow_review.py`） |

给字的分布：㫖4 彞3 刋3 㝠2 卽2 𠮓2 變2 厯1 宮1 喪1 奕1 兄1。

## 事件口径
batch=`vol03-shadow-review-0929`，step=seed_admit，unit=cell，kind=confirm，actor=user，seq 1..33（按裁决时间）。
`payload.via="shadow-review"`、`client_ts`＝页上裁决时间。写入走 `EventLog.append`（同写锁、同字形合法性校验）。

**anchor 的限制（请知悉）**：口径同控制台 `_product_anchor`：`target.anchor.product_key={step,key:pNNNN,fingerprint}`。
云端 ws 没有 products/ 清单，取不到 seed_admit 现值指纹，所以**取的是同页、同 step 已有事件（vol03-all-decide，09-28）里带的指纹**，
每条 `anchor.fp_source="sibling_event"`。**5 条没找到指纹**（p53/p65/p97/p103/p106 上的卡，无既有事件），anchor 里只有 `product_key{step,key}`，`fp_source="none"`。
现行事件本来就只有 product_key 没有 bbox，bbox 需要 Step3 产物，云端也没有。总管若在有产物的机器上想补，
可用 `open_guji_cv.feedback.anchor.cell_anchor` 补 bbox/content_sha（未做）。

## 码位口径检查（books/vol03.yaml）
`codepoints:` 只有两项：`內→内`、`別→别`。用户所选 12 种字（含 彞 卽 刋 㫖 厯 宮 𠮓 㝠）**没有一个是被统一项，
`canonical_char` 不会把它们改回去 —— 无冲突**（脚本用 `--ws` 自检，输出「无冲突」）。

值得列出的**非冲突但相关**项（未改任何规则）：`config/variants/books/wuyingdian_zongmu.json`（本书用字账，由 vol01/vol02 派生）里，
所选刻形有 canonical 分组：㫖→旨、㝠→冥、卽→即、厯→歷、𠮓→變（宮 canonical 就是宮；彞、刋、喪、奕、兄 无分组）。
它是用字账的「分组键」，分组/评测用，**不改写事件的 `shape`**；进库仍以 `shape` 为准。
是否影响重跑 seed_admit 时的异体护栏／用字账评分，我没有实测（未重算任何产物），交给总管判断；本单不改任何规则。

## 测试
`.venv/bin/python -m pytest tests/ -s -q -p no:cacheprovider`：**2373 passed / 27 skipped / 1 failed**。
失败的是 `tests/test_cut_select.py::test_ckpt_fingerprint_empty_for_missing_file`——**stash 掉本单改动后同样失败**，
原因是云端没有那份模型检查点（`ckpt_fingerprint()` 返回空），与本单无关。新增 `test_harvest_shadow_review.py` 通过。

## 以后接着裁
把页重新读到本地，再跑（对 ws 的 feedback 目录，已写过的格自动跳过，页上新裁的才追加）：
```
python scripts/harvest_shadow_review.py PAGE.html --feedback-dir <ws>/feedback --ws <ws> \
    --batch vol03-shadow-review-0929
```
`--dry-run` 只看不写。事件文件先在 ws 里有了这批 33 条之后再跑，才不会重复（脚本按 `target.key` 判重）。
