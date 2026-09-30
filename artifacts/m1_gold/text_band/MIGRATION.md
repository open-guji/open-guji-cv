# text_band「金标」迁移（M1·A 道）
不是人裁：`expected.json` 是 v1 链（phase2 inner_frame）的算法快照（294 页 / 47431 格 / 偏短 vol01/50=0.863、vol01/88=0.898）。v1 链退役，**不迁，重冻 v2 基线**：
`expected_v2.json`（本目录，来源 `eval_text_band.py --update`，读 `borders` + `row_segment`，口径对应见脚本头注）。当前基线 = vol01 108 页（+vol02 沙箱里恰有 1 页）/ 17231 格 / 偏短 0 页；
vol02 的 row_segment 产物沙箱里没跑完，未入基线（回归只比页交集，补齐后 `--update` 重冻）。v1 的 `expected.json` 原样留档。
