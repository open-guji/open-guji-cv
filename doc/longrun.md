# 长跑任务的断点续跑（longrun）——一页用法

**解决什么**：云端容器空闲会被回收——**磁盘保留、后台进程全死**。会话被叫醒后，一条命令让没跑完的长任务从断点接着跑；已完成的步骤不重算，已完成的页由 `guji` 自己的指纹跳过。
**不做什么**：不改引擎、不写事件、不碰正式 `products/`（产物走沙箱）；不是调度器，只在你（或被叫醒的会话）敲 `resume` 时才续。

## 0. 前提（一次）
```bash
# 已在 cv main：在 main 的检出里直接用 scripts/（bootstrap_cloud.sh、longrun.sh、longrun_fresh_check.py、longrun_sandbox_ws.sh、jobs/），不需要任何分支
bash scripts/bootstrap_cloud.sh        # 环境（装好后重跑秒过）；runner 每次起来也会自检，缺件自己补
```

## 1. 三条命令
```bash
bash scripts/longrun.sh start  <job文件> [名字] --env VAR1,VAR2   # 起（后台）。--env 列出 job 要用的环境变量，会存下来，续跑时自动带上
bash scripts/longrun.sh status [名字]                              # 看：运行中／完成／失败／已中断；已完成几步；当前步；最后一行进度
bash scripts/longrun.sh resume [名字|--all]                        # ★被叫醒后只敲这一条：没完成且 runner 不在的任务从断点续
```
另有 `stop <名字>`、`compare <目录A> <目录B>`（逐文件 sha256；rc 0＝一致）。任务状态与日志在 `$GUJI_LONGRUN_DIR`（默认 `~/guji-longrun/<名字>/`：`logs/<步骤>.log`、`done/`、`runner.log`）。

**被叫醒的第一件事**：`bash scripts/longrun.sh resume`。它先打印 `uptime`（回收过会是 `up 0 min`），再对每个任务判断：已完成→不动；runner 还在→不重起；否则续跑。runner 是否在跑看 `flock`，不看 pid 文件，所以回收后不会误判「还在跑」。

## 2. 写一个 job 文件（bash，用 `step` 声明步骤，按序执行）
```bash
step <步骤名> '<命令>' ['<验证命令>']
```
- **命令必须幂等**（原样重跑安全）。`guji pipeline`／`guji step` 满足：只重算过期或缺失的页。
- **验证命令**写了就必须 rc 0 才算这步完成。`guji pipeline` 即便有页失败也可能 rc 0，所以要验：
  `guji status <册> -w $WS --pages all --json 2>/dev/null | python3 -I scripts/longrun_fresh_check.py <步骤,步骤>`（要求每页都 fresh）。
- 步骤名＋命令＋验证命令的哈希进完成戳：改了命令，这一步重跑，别的步不动。
- 一步失败：runner 停在那里（状态 `失败`，日志在 `logs/<步骤>.log`），不会往下跑；排除原因后再 `resume`。
- 完成戳只在「命令 rc 0 且验证过」才原子写入；被杀在半路没有戳，重跑该步（页级进度靠命令自己跳过）。

## 3. 首个用例：GUJI-208ex 2b（vol01–07 全册字节对比：main 代码 vs 窄对合并分支）
```bash
WSREAL=<guji-workspace 里 96mid1ogzk-… 目录>          # 真工作区，只读用
git worktree add --detach $HOME/lr/cvA 4eed859         # main 代码
git worktree add --detach $HOME/lr/cvB 75d5187         # claude/narrow-pair-merge-1014（先 git fetch 该分支）
bash scripts/longrun_sandbox_ws.sh "$WSREAL" $HOME/lr/ws
export CVA=$HOME/lr/cvA CVB=$HOME/lr/cvB WS=$HOME/lr/ws SBX=$HOME/lr/run1 JOBS=4
bash scripts/longrun.sh start scripts/jobs/narrow_pair_2b.job.sh narrow2b --env CVA,CVB,SBX,WS,JOBS
bash scripts/longrun.sh status narrow2b
# 容器被回收后：
bash scripts/longrun.sh resume
# 全部完成后：对比结果在 $SBX/compare_A_vs_B.txt（A＝main 代码，B＝分支代码；「manifest 语义不同 0、逐字节不同 0」即 2b 的「不同页数＝0」）
```
一个 job 一对 A／B 两份产物（`$SBX/prodA`、`prodB`）与缓存；两个 job 同时跑要用不同的 `SBX`，也别共用 `$GUJI_LONGRUN_DIR` 里同名任务。

## 4. 对比口径与坑
- `compare` 默认排除 `_manifest.jsonl`（带 `ts`／`elapsed`／`code_rev`，两次运行必不同）和 `_raw_index.json`（图片索引，按需增长），**但**另按「页键→产物 sha256＋状态」比 manifest 语义，所以「页文件逐字节一致」和「manifest 里记的产物 sha 一致」都被查。
- 别用 `pkill -f <脚本名>` 杀 runner：会连自己所在的 shell 一起杀。用 `longrun.sh stop <名字>`。
- 别在 runner 还活着时 `rm -rf` 任务状态目录：锁文件被换掉，会出现两个 runner。
- `--env` 只存路径之类的变量到 `env.sh`（权限 600），**别放密码**。
- 起任务的机器要能访问 job 里写的路径；换容器后路径不存在，`resume` 会在第一步就失败并写明原因。
- job 文件在 `start` 时被存档到任务目录；之后改源文件，`resume` 读不到（Ethan GUJI-520 踩到）。要让改动生效：对同一名字再 `start <改好的job文件> <名字> --env …`（runner 不在时会刷新存档，命令改过的步骤重跑，其余已完成的步骤不动），或换个名字重起。
