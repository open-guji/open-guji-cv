# page_crop「金标」迁移（M1·A 道）
同 text_band：`expected.json`（6 页 v1 越界快照）是退役链（s3 预处理裁窄）的算法快照，不迁；`expected_v2.json` = v2 基线（`eval_page_crop.py --update`，
读 `borders` 最外两条竖线对页宽）：扫 318 页（vol01 109 / vol02 186 / bxgb 23）、越界 0 页。v1 的 6 页里 vol01/18、vol02/136/64/70 在 v2 均未越界（最外线离边 ≥245px）；
vol01/167、178 不是正文页，v2 链没有其产物，未验。病根（预处理裁窄）在 v2 链里不存在。
