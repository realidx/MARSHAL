# 新100父游戏：远端CPU完整终局求解操作说明

2026-10-21。协议`strategic-parents-remote-terminal-solver-v1`。
只求解已冻结的100个原始父游戏，不生成替代题、不改规则/prompt/reward、不测Q/S/D、不训练。

**远端能增加CPU并发、单局时间和内存；不能保证现有一般和solver一定收敛。**
只有完整终局单边偏离和响应平局审核通过才保存可用reference。
正常跑完但仍有未认证局是允许的结果，必须原样回传，不通过换题凑足100。

## 1. 上传独立运行包

本地已经提供：

```text
new/remote_solver_bundle_20261021/game_oracle_remote_v1.tar.gz
new/remote_solver_bundle_20261021/game_oracle_remote_v1.tar.gz.sha256
```

无需git pull或复制整个仓库。包包含当前未提交但已冻结的必要源码、100父游戏、
版本/参数记录、CPU测试、Slurm脚本和独立依赖文件；不含模型权重或GPU环境。

在本地仓库根目录执行，先把SSH目标替换为自己的地址：

```bash
ORACLE_REMOTE='你的用户名@服务器地址'
scp new/remote_solver_bundle_20261021/game_oracle_remote_v1.tar.gz "$ORACLE_REMOTE:~/"
scp new/remote_solver_bundle_20261021/game_oracle_remote_v1.tar.gz.sha256 "$ORACLE_REMOTE:~/"
ssh "$ORACLE_REMOTE"
```

## 2. 远端解压与环境

以下命令都在远端执行。解到独立目录，不叠加到旧训练仓库：

```bash
cd ~
sha256sum -c game_oracle_remote_v1.tar.gz.sha256
tar -xzf game_oracle_remote_v1.tar.gz
cd game_oracle_remote_v1
python3 --version
```

需要Python 3.10—3.12，推荐3.12。若`python3`不在此范围，换用服务器已有的
`python3.12`或`python3.11`执行下面的venv命令。也可以先用conda创建Python3.12环境。
无需安装MARSHAL、ROLL、torch、vLLM或CUDA。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-oracle.txt
export PYTHONPATH="$PWD:$PWD/third_party/negotiation_benchmark/src${PYTHONPATH:+:$PYTHONPATH}"
mkdir -p remote_runs
python -m pip freeze > remote_runs/environment-packages.txt
python -m new.strategic_game_v1_20261021.remote_solver doctor > remote_runs/doctor.json
python -m unittest new.strategic_game_v1_20261021.test_rules new.game_design_feasibility_20261021.test_design -v
```

依赖固定为NumPy1.26.4、SciPy1.12.0。doctor会验证包内所有文件和100父游戏hash。
输入`parents.jsonl`必须是SHA256：
`30fb0f7d012f33f5d175650258698e9ba46cd88cafc64da39f848a69c4bfd3ad`。
六项CPU测试应全部通过；若安装、doctor或测试失败，先回传错误，不直接开全量任务。

以后重新登录远端，先恢复工作目录与环境，再执行启动/恢复/审核命令：

```bash
cd ~/game_oracle_remote_v1
source .venv/bin/activate
```

## 3A. 普通SSH服务器：后台跑第一轮

仍在`game_oracle_remote_v1`根目录、`.venv`已激活时：

```bash
nohup python -u -m new.strategic_game_v1_20261021.remote_solver run \
  --output remote_runs/base --profile base --workers 0 \
  > remote_runs/base.launch.log 2>&1 < /dev/null &
echo $! > remote_runs/base.pid
```

`--workers 0`自动选择分配到的CPU数与4的较小值，最低1；没有GPU要求。
明确知道可用CPU/内存后可改成`--workers 8`等，每个worker的数值库线程数固定为1。
内存不足先降低workers，保持数据、规则和认证容差不变。

查看状态：

```bash
tail -n 30 remote_runs/base.launch.log
cat remote_runs/base/progress.json
```

第一轮每局：构树120秒、求解300秒、独立审核180秒；完整候选搜索参数在`PROTOCOL.json`。
实际耗时取决于机器和游戏；多核主要提高不同游戏的并发，不保证单个困难游戏更快。

## 3B. Slurm服务器：代替3A提交CPU任务

Slurm脚本默认申请8CPU、32GB内存、24小时，不申请GPU；可用sbatch参数覆盖。
如集群要求指定partition/account，在命令里加本站对应的参数，不改包内脚本。

```bash
ORACLE_OUTPUT=remote_runs/base ORACLE_PROFILE=base \
  sbatch examples/strategic_slices/solve_parents_100_cpu.sbatch
```

输出在`oracle-作业号.out`，状态仍在`remote_runs/base/progress.json`。
脚本默认用Slurm分配的CPU数作为workers；可显式设置`ORACLE_WORKERS=4`降低内存占用。
例如小资源任务：

```bash
ORACLE_OUTPUT=remote_runs/base ORACLE_PROFILE=base ORACLE_WORKERS=4 \
  sbatch --cpus-per-task=4 --mem=16G examples/strategic_slices/solve_parents_100_cpu.sbatch
```

3A和3B选择一种，不要同时写同一个output。

## 4. 如何判断第一轮完成

```bash
cat remote_runs/base/COMPLETE.json
python -m new.strategic_game_v1_20261021.remote_solver audit --output remote_runs/base --hash-only
```

- 没有`COMPLETE.json`：任务尚未结束或中断。
- `execution_complete=true`：该轮所有指定尝试已结束，**不代表100局都有标签**。
- `all_100_certified=true`：100局全部获得独立认证的reference。
- `unavailable>0`：有未认证局；`summary.json`列出ID，各attempt/result.json保留原因。

正常完成但有未认证局时，run退出码仍为0；基础设施错误非0并保留日志。
进度中的resolved包括成功和已用尽本轮初始化的失败，不等于认证数。

## 5. 第一轮有失败：只对缺失局做扩展搜索

不要覆盖base目录。下面的新run会保留并复制base中已认证的reference及其来源身份，
仅为其他父游戏运行扩展计划。接受容差、完整分支、终局目标和回应平局规范都不变。

```bash
nohup python -u -m new.strategic_game_v1_20261021.remote_solver run \
  --output remote_runs/extended --profile extended \
  --from-run remote_runs/base --workers 0 \
  > remote_runs/extended.launch.log 2>&1 < /dev/null &
echo $! > remote_runs/extended.pid
```

Slurm对应命令：

```bash
ORACLE_OUTPUT=remote_runs/extended ORACLE_PROFILE=extended ORACLE_FROM_RUN=remote_runs/base \
  sbatch examples/strategic_slices/solve_parents_100_cpu.sbatch
```

扩展计划按固定顺序：uniform → 信息集内Dirichlet初始化seed0 → seed1 → seed2。
每次初始化都重新完整求解，单次求解最多900秒；第一个通过独立认证的profile即接受，
后续初始化停止，**不根据调查收益、Q/S/D或模型表现挑profile**。
更改初始化仅改变数值搜索起点，不改变其他玩家的理性规范或信息可见性。

完整数值参数：

| 参数 | base | extended |
|---|---:|---:|
| 单次求解秒数 | 300 | 900 |
| 最大sweeps | 256 | 512 |
| 候选数量 | 8 | 12 |
| joint cells上限 | 65536 | 131072 |
| joint evaluations上限 | 640 | 2048 |
| large-tree ordered sweeps | 4 | 8 |
| 独立审核秒数 | 180 | 300 |

均为完整原生终局，max_nodes=100000、epsilon=1e-8、tie tolerance=1e-9。
底层未覆盖默认值也逐字段写入每次`pipeline_snapshot.json`。
CLI提供`--solve-seconds`、`--audit-seconds`、`--construct-seconds`、`--max-joint-cells`覆盖，
实际值完整记录；有意改变它们必须使用新的output，不能混续原run。

## 6. 中断、恢复和锁

已完成的局/初始化逐个保存。中断中的那次初始化重新计算，**不保存数值solver内部迭代状态**。
同一run恢复必须保持数据、源码、Python/NumPy/SciPy版本和数值参数一致。
workers可以调整，实际资源与启动环境分别记入`sessions/`。

普通SSH恢复base：

```bash
nohup python -u -m new.strategic_game_v1_20261021.remote_solver run \
  --output remote_runs/base --profile base --workers 0 --resume \
  > remote_runs/base.resume.log 2>&1 < /dev/null &
```

恢复extended时保留原来的`--from-run`：

```bash
nohup python -u -m new.strategic_game_v1_20261021.remote_solver run \
  --output remote_runs/extended --profile extended \
  --from-run remote_runs/base --workers 0 --resume \
  > remote_runs/extended.resume.log 2>&1 < /dev/null &
```

Slurm再次提交同样命令会自动加`--resume`。
正常SIGTERM/SIGINT会停止子进程、保留证据并释放锁；强制kill或节点故障可能留下`.run.lock`。
确认旧作业已停止后，给对应恢复命令加`--recover-lock`。
同机检测到记录的进程仍存活时会拒绝恢复；不同节点的恢复需要操作者先确认旧任务已停止。
不要删掉已有attempt目录，未完成的execution会保留，恢复另建execution。

## 7. 完成后重新加载reference做独立检查

若仅跑了base，将下方目录改为`remote_runs/base`：

```bash
python -m new.strategic_game_v1_20261021.remote_solver audit \
  --output remote_runs/extended --seconds 300
```

该命令逐个重新构树、载入保存的概率、核对policy hash，并再次做完整偏离/平局与原生转换审核。
审核报告写到`audits/`，不覆盖原reference。
如果希望命令在“仍有未认证局”时返回非0，添加`--require-all`：

```bash
python -m new.strategic_game_v1_20261021.remote_solver audit \
  --output remote_runs/extended --seconds 300 --require-all
```

仍有失败时也把全部结果回传；不要提高容差、删动作、改成短期收益或替换父游戏。
后续可能需要solver方法改进，增加CPU/时间本身不保证解决所有失败。

## 8. 打包回传

远端bundle根目录执行：

```bash
tar -czf oracle_results_20261021.tar.gz remote_runs BUNDLE_MANIFEST.json PROTOCOL.json
sha256sum oracle_results_20261021.tar.gz > oracle_results_20261021.tar.gz.sha256
```

在本地仓库根目录另开终端执行：

```bash
ORACLE_REMOTE='你的用户名@服务器地址'
mkdir -p new/remote_oracle_results_20261021
scp "$ORACLE_REMOTE:~/game_oracle_remote_v1/oracle_results_20261021.tar.gz" new/remote_oracle_results_20261021/
scp "$ORACLE_REMOTE:~/game_oracle_remote_v1/oracle_results_20261021.tar.gz.sha256" new/remote_oracle_results_20261021/
```

需要回传整个结果包，而非只有console日志。它包含所有未认证ID、完整运行快照、
已认证NPZ、证书、超时/失败原因及审计记录。我们拿到后再完成Q/S和新prompt设计，
之后才直接使用模型测D。100个父游戏reference齐备也不等于训练pipeline已就绪。
