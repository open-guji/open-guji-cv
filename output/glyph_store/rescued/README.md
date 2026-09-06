# 抢救出的人裁（不进 glyph.db 的那部分）

## phase9_seed_human_only.jsonl

v1 `output/vol01/phase9_seed/queue.jsonl` 里 `provenance=human` 共 1068 条，
其中 **48 条的 instance_id 在 `glyph.db` 的 admissions 里找不到**——它们只活在
那个 v1 队列文件里。2026-09-06 清理 v1 中间产物（`phase*` 目录体积占仓库
约 1.4 GB）之前把这 48 条抠出来存档。

为什么不能直接丢：`decided_char` 全部有值，20 条还带 `note`，记的是人裁时的
判断依据。例如

    vol01:7:5:20  已  ;corrected:modern_usage_over_shape(was 巳)

正是「己/已/巳 按字形读、按文意录，并记录这个转换」那条规矩的实际落点。

## id 口径注意

这里的 `instance_id` 是 **v1 键空间**（`book:page:col:idx`，idx 从 0 起、含
margin 格），与 v2 的 `book:page:col:slot`（slot 从 1 起、抬头负数、夹注 a/b）
**不是双射**——见 `open_guji_cv/steps/_v1_bridge.py` 的说明。要并回 v2 的
金标或 glyph.db，必须先按页/列重新定位，不能字符串直接套。

未做这一步，因为并库需要逐条核对格位，属于单独的活。
