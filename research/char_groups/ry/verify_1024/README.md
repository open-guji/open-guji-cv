# 日曰（ry）＋日目（rm）送审压缩（A24 2026-10-24）

结论在 `doc/字组/ry.md`、`rm.md`；数据在 dataset `char-groups/variant/ry/`。

| 脚本 | 作用 |
|---|---|
| `replay.py` | 离线回放：撤回产物里组流程（和组流程留审后被 rare_ref／witness3／seal／coord_fallback 放回）的改动，按现行规则＋L2 表重跑 ry／rm／mz；ry_shape 用留痕里的宽高比，不取图 |
| `summ.py` | 回放前后各组放行／送审／后续补放计数 |
| `eval_truth.py` | 回放结论对真值（dataset labels；没细读的格＝放行字，1888 格逐格扫过） |
| `diff_replay.py` | 两次回放逐格比，列出变了的格 |
| `l1_check.py` | ry／rm L1 规则对全部日曰目格回测 |
| `build_tables.py` | 中心库现行表＋细读＋haiku 补票 → 新 L2 表 |

复现（产物用 `guji products pack fetch` 取到 `<prod>/<册>/`）：

```
python research/char_groups/ry/verify_1024/build_tables.py ~/.guji-data/main/siku-zongmu/config/groups/l2 labels.jsonl haiku_1024.json /tmp/t
cp ~/.guji-data/main/siku-zongmu/config/groups/l2/mz.json /tmp/t/      # 回放的表目录要有三组的表
python research/char_groups/ry/verify_1024/replay.py <prod> rp.jsonl --tables /tmp/t --vols vol11,...,vol20
python research/char_groups/ry/verify_1024/summ.py rp.jsonl
python research/char_groups/ry/verify_1024/eval_truth.py rp.jsonl labels.jsonl
```
