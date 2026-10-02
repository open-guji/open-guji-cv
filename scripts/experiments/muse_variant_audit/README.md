# muse 批次 V1：异体关系表单来源边复核（overview 卡见下）

**为什么做**：`config/variants/variants.json` 47,182 条边里 22,454 条只有一个来源；`variants.are_variants` 任一来源即算异体，
于是 大/太、戊/戌、增/憎 都被当成异体（CV 总管 10-02 调查，overview `进度/总览/17` 规则 B 负结果：库首位是整理本字的「异体」时取库形，75 格只对 11）。
Step7 有几处借这张表放行（`ref_lib` 变体边、`variant_form`、rare_ref 的「库首位是异体就不放」）。先把**两字都在书里出现过**的单来源边审一遍。

**输入**：`input.jsonl`（2,073 条，只有 `id/a/b`），其中待审 1,957 条（通假单源 1,347、hydzd 447、twedu 81、yitizi 52、其他 30），
混入三组对照 116 条（`key.jsonl` 里有分组，**不喂 muse**）：
- `ctrl_strict` 60：≥3 个独立来源的严格异体 → 应判 `same_char=是`
- `ctrl_spoof` 40：Unihan kSpoofingVariant 单源边 → 应判「否」（形近易混）
- `ctrl_known_no` 16：10-02 人裁确认不是同一字的表内边（大/太、戊/戌…）→ 应判「否」

重生：`python make_input.py charset.json`（固定种子；charset.json = 四庫 vol02–vol10 快照里出现过的 4,141 字）。

**调用**：每条一次，`prompt.txt` 后接一行 `A：<a>　B：<b>`；`--output-schema schema.json`，参数照 muse-batch skill §二。不喂整理本、不要出处。

**输出**：`muse_out.jsonl`，每行 `{id, a, b, relation, same_char, reason}`。只是候选，**不改 variants.json**。

**抽检口径（放量闸）**：
1. 先跑对照 116 条 + 待审随机 100 条（种子 20261002）作试点。
2. 对照：`ctrl_strict` 判「是」≥90%；`ctrl_spoof`、`ctrl_known_no` 判「是」≤5%。不过线就停，回卡报不一致样本。
3. 过线后放量跑完其余待审；驱动道再随机抽 50 条自己判一遍（先不看 muse 答案），报一致率。
4. 收工回报：条数、调用数、429 次数、对照命中、抽检一致率与不一致逐条。

**之后（CV 侧，不归 muse）**：muse 判「否」且原来只有单一来源的边，由 CV 道在 `variants.json` 里加降级标记（不删边），
再看 Step7 放行受不受影响；判「是」的不升级，保持现状。
