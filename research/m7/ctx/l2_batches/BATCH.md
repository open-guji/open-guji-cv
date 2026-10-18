# 批次单：形近字上下文判读（M7 L2，GUJI-563）

提交人：Emerson（CV 上下文线程）｜用户 sheldon 2026-10-17 20:37 特批破例（本项目原本不与其他成员交互）。
目的：让 **muse** 与 **Gemini** 各跑一遍，与已跑的 opus／sonnet／haiku 比较，看"各遍一致才给字"的效果。

- **输入**：本目录 `jys_00..05.txt`（己已巳，226 格）、`ry_00..02.txt`（日曰，91 格）、`rr_00..02.txt`（入人八，83 格），共 12 个文件、400 格；每个文件是**完整消息**（提示词＋本批输入，每批 ≤40 格）。**不要加任何别的材料，不要喂整理本，不要联网查**。
- **提示词**：文件里已带，原样使用，不要改。
- **输出**：每个文件一份 JSON 数组 `[{"id":…,"char":"…","conf":"high|mid|low","why":"…"}]`（若工具要求 object，用 `schema.json` 的 `{"results":[…]}` 也行）。文件名同输入，`.txt` 改 `.json`。
- **放哪**：在 open-guji/open-guji-cv 仓的分支 `claude/project-thread-v28w3t`，路径 `research/m7/ctx/l2_results/<muse 或 gemini>/<文件名>.json`，提交推上去即可（只 add 这些文件）。推不了的话把内容贴给我也行。
- **muse 的注意**（按 `muse-batch` skill）：并发 ≤4；`--disable-shell --disable-write --disable-web-tools`；撞 429 就停。总共 12 次调用，不多。
- **抽检**：不需要。我这边用强真值评测，并把不一致的格交 sheldon 人审。
- **不要**：不要读 `research/m7/ctx/l2_results/` 里别家模型的结果再作答；不要读 open-guji-dataset 里的 items.jsonl（含金标）。
