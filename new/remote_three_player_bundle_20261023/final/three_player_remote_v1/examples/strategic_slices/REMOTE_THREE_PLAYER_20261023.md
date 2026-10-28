# 三人复杂度：远端完整终局求解与Q/S

本包采用修复后的惯性BR/平局安全缩减与完整原生认证，并直接计算Q/S。
**先跑H2的33局**：每人1个可承诺事项、全局两个隐藏偏好分属不同玩家，其他规则保持2RR/调查1/报价1。
H3（每人一个隐藏偏好）和A2H2（一位玩家多一个承诺选择）也已冻结在包内，作为后续候选，不必一开始全跑。
本轮小样有效性与第25局处理见[结果说明](THREE_PLAYER_COMPLEXITY_20261023.md)。

没有GPU/模型/训练依赖。此处提供启动指示，**尚未代用户连接服务器或执行远端整批计算**。

## 1. 上传独立包

本地仓库中的交付：

```text
new/remote_three_player_bundle_20261023/final/three_player_remote_v1.tar.gz
new/remote_three_player_bundle_20261023/final/three_player_remote_v1.tar.gz.sha256
```

用户在本地终端替换SSH地址后执行：

```bash
STUDY_REMOTE='用户名@服务器地址'
scp new/remote_three_player_bundle_20261023/final/three_player_remote_v1.tar.gz "$STUDY_REMOTE:~/"
scp new/remote_three_player_bundle_20261023/final/three_player_remote_v1.tar.gz.sha256 "$STUDY_REMOTE:~/"
ssh "$STUDY_REMOTE"
```

无需git pull整个仓库，不依赖本地未提交文件已上传；源码/数据/注册版本都在独立包内。

## 2. 解压、建立CPU环境

以下都在远端执行，解到独立目录，不叠加旧包：

```bash
cd ~
sha256sum -c three_player_remote_v1.tar.gz.sha256
tar -xzf three_player_remote_v1.tar.gz
cd three_player_remote_v1
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export PYTHONPATH="$PWD:$PWD/third_party/negotiation_benchmark/src"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1
mkdir -p remote_runs
python -m pip freeze > remote_runs/environment-packages.txt
python -m new.three_player_complexity_v1_20261023.remote doctor > remote_runs/doctor.json
cat remote_runs/doctor.json
python -m new.three_player_complexity_v1_20261023.validate --output remote_runs/cpu_tests
```

若没有`python3.12`，可用Python3.10/3.11的venv，或已有conda创建独立Python3.12环境，
然后执行pip/install/export/doctor/validate部分：

```bash
conda create -n three-player-oracle python=3.12 -y
conda activate three-player-oracle
```

依赖固定NumPy1.26.4/SciPy1.12.0；doctor应显示`numpy_scipy_match_pinned=true`，源码/包hash通过。
CPU测试应8项通过；失败时先处理环境或回传错误，不将失败跳过后当有效整批结果。
后续重新登录时回到该目录并激活同一环境。

## 3A. 普通SSH：后台启动H2

在包根目录、环境已激活时：

```bash
nohup bash RUN_REMOTE.sh > remote_runs/H2.launch.log 2>&1 < /dev/null &
echo $! > remote_runs/H2.pid
```

默认1个CPU worker，每个worker数值库1线程，Linux每case的虚拟内存上限8GiB。
知道服务器容量后可用`STUDY_WORKERS=2 nohup bash RUN_REMOTE.sh ...`；每个worker各有8GiB上限，需给父进程和系统留余量。
也可直接运行同一命令，所有CLI覆盖会写入snapshot：

```bash
python -u -m new.three_player_complexity_v1_20261023.remote run \
  --jobs data/H2.jsonl --output remote_runs/H2 --workers 1
```

3A和3B任选一种，不同时写同一output。

## 3B. Slurm：CPU作业

默认4CPU/32GB/24小时、不申请GPU，使用2个worker。环境先按上节激活：

```bash
STUDY_ARM=H2 STUDY_OUTPUT=remote_runs/H2 STUDY_WORKERS=2 \
  sbatch examples/strategic_slices/solve_three_player_complexity_cpu.sbatch
```

如需要partition/account，在sbatch命令加本集群参数。资源未知时也可只开1个worker：

```bash
STUDY_ARM=H2 STUDY_OUTPUT=remote_runs/H2 STUDY_WORKERS=1 \
  sbatch --cpus-per-task=2 --mem=16G examples/strategic_slices/solve_three_player_complexity_cpu.sbatch
```

## 4. 实际计算合同与预算

| 参数 | 默认 |
|---|---:|
| 完整公共树节点上限 | 600000 |
| 构树 / 缩减各自软预算 | 180秒 |
| 候选搜索总软预算 | 600秒 |
| 搜索分配 | 75%惯性BR，失败再25%联合数值候选 |
| 惯性BR最大sweeps | 512 |
| joint evaluations | 400；其内部BR前端最多256 sweeps/15秒 |
| 首次完整独立审核软预算 | 300秒 |
| 局部修复 | 最多8轮，沿用v6 helper每轮60秒诊断 |
| Q/S软预算 | 1200秒 |
| 每case外部硬wall上限 | 3600秒 |
| 每case Linux虚拟内存上限 | 8GiB |
| own偏离 / 平局容差 | 1e-8 / 1e-9 |

H2的33局预先计数约158234—170835个公共节点、9个world；H3为355625节点/27world；
A2H2约480795—522574节点/9world。更大计算不靠改近视对手、缩短到窗口或减少合法行动。
时间/内存不足是缺失结果，保留原因，不判零信号。

每case都在独立子进程，外部硬wall到期会停止其进程组。Linux会设置RLIMIT_AS；
本地macOS测试不应用该内存限制，实际flag记录于结果，不能据此声称测过Linux的内存上限。
配置中的epsilon/policy tie规则固定，不用CLI放宽。软预算仍可能被长数值调用跨过，最终由硬wall兜底。

## 5. 进度、完成与失败

```bash
tail -n 30 remote_runs/H2.launch.log
cat remote_runs/H2/progress.json
cat remote_runs/H2/COMPLETE.json
```

- `execution_complete=true`仅表示本轮所有case已结束。
- `all_certified=true`表示全部33局有完整终局reference。
- `all_measured=true`表示全部33局完成Q/S；认证成功但标签超时会分别记录。
- `unavailable`和`unmeasured`保留相应ID，不能将缺失当S=0。
- `cases/<index>/execution-0000/`保留worker.log、request、原始结果、reference和labels。

程序正常收集到失败/超时结果仍可退出0；看COMPLETE/逐case结果，不只看exit code。

中断恢复用同一个output、同一输入/source/Python/NumPy/SciPy和算法预算；workers可调整，另存session：

```bash
python -u -m new.three_player_complexity_v1_20261023.remote run \
  --jobs data/H2.jsonl --output remote_runs/H2 --workers 1 --resume
```

Slurm恢复加`STUDY_RESUME=1`。操作系统锁会随父进程退出释放；恢复前确认旧作业与子进程都已停止。
已结束的失败不会被resume自动重试；预算变化或重试用新output，并保留旧证据。例如仅重试index5、9：

```bash
python -u -m new.three_player_complexity_v1_20261023.remote run \
  --jobs data/H2.jsonl --output remote_runs/H2_retry --indices 5,9 --workers 1 \
  --solve-seconds 1200 --audit-seconds 600 --metric-seconds 2400 --case-seconds 7200 --memory-gb 12
```

index是扩展池索引，与`original_index`分别记录。不覆盖reference，不按S大小挑候选；重试结果回传后再审计整合。

## 6. 保存后独立重载审核与对照报告

```bash
python -m new.three_player_complexity_v1_20261023.remote audit \
  --run remote_runs/H2 --output remote_runs/H2_reload --workers 1
python -m new.three_player_complexity_v1_20261023.analyse \
  --run remote_runs/H2 --baseline data/baseline_three_player.json --output remote_runs/H2_analysis
```

独立审核重新构树/载入NPZ/完整偏离与响应平局检查，无搜索、修复。看`original_certified`与`independently_passed`，
以及`missing_original_indices`，不能把“已认证子集复核通过”写成33局全通过。
分析同时报告覆盖缺失和同一已测子集的新旧正S父游戏；不能仅挑成功题报改善比例。
不同world支持/均衡选择使该比较属于设计校准，不是隔离单因素的训练因果实验。

如果H2覆盖仍不足，再用`data/H3.jsonl`或`data/A2H2.jsonl`启动新output；无需重新上传包。
H3隐藏更多不保证优于H2，A2H2动作更多也不保证更多有效信息节点。

## 7. 回传完整证据

远端包根目录：

```bash
tar -czf three_player_results_20261023.tar.gz remote_runs BUNDLE_MANIFEST.json PROTOCOL.json data \
  examples/strategic_slices/versions/three_player_complexity_v1_20261023
sha256sum three_player_results_20261023.tar.gz > three_player_results_20261023.tar.gz.sha256
```

本地另开终端，替换同一SSH地址：

```bash
STUDY_REMOTE='用户名@服务器地址'
mkdir -p new/remote_three_player_results_20261023
scp "$STUDY_REMOTE:~/three_player_remote_v1/three_player_results_20261023.tar.gz" new/remote_three_player_results_20261023/
scp "$STUDY_REMOTE:~/three_player_remote_v1/three_player_results_20261023.tar.gz.sha256" new/remote_three_player_results_20261023/
```

即使失败也回传整个结果包。之后据真实Q/S覆盖判断最终33局设置，再改prompt、测模型D。
不把本包的99个研究候选直接当正式训练题库；第25局保留价值见证和挑战身份，完整父游戏仍待求解。
