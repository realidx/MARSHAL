#!/usr/bin/env bash
#SBATCH --job-name=structure-tail18
#SBATCH --partition=long
#SBATCH --constraint=xcnh
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=18
#SBATCH --hint=nomultithread
#SBATCH --mem=320G
#SBATCH --time=24:00:00
#SBATCH --output=/home/e/e1300530/tmp/structure_pool_remote_20261029/slurm-%j.out
set -euo pipefail
cd /home/e/e1300530/tmp/structure_pool_remote_20261029/runtime
export LD_LIBRARY_PATH="/home/e/e1300530/tmp/structure_pool_remote_20261029/python312/lib:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="$PWD:$PWD/third_party/negotiation_benchmark/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1
/home/e/e1300530/tmp/structure_pool_remote_20261029/python312/bin/python - <<'ENV_CHECK'
import sys,numpy,scipy,json
from pathlib import Path
assert Path(sys.executable).resolve().is_relative_to(Path('/home/e/e1300530/tmp/structure_pool_remote_20261029/python312')),sys.executable
assert sys.version_info[:2]==(3,12),sys.version
assert numpy.__version__=='1.26.4',numpy.__version__
assert scipy.__version__=='1.12.0',scipy.__version__
import new.three_player_complexity_v1_20261023.worker
print(json.dumps(dict(executable=sys.executable,python=sys.version,numpy=numpy.__version__,scipy=scipy.__version__,worker_import='PASS')),flush=True)
ENV_CHECK
oracle_output=new/structure_pool_v1_20261026/remote_remaining18_runtime_v4_20261029
oracle_audit=new/structure_pool_v1_20261026/remote_reload18_runtime_v4_20261029
oracle_resources=/home/e/e1300530/tmp/structure_pool_remote_20261029/resources_runtime_v4
mkdir -p "$oracle_resources"
lscpu > "$oracle_resources/lscpu.txt"
scontrol show job "$SLURM_JOB_ID" > "$oracle_resources/slurm_job.txt"
/home/e/e1300530/tmp/structure_pool_remote_20261029/python312/bin/python -m new.structure_pool_20261026 doctor > "$oracle_resources/doctor.json"
SLURM_CPUS_PER_TASK=18 SLURM_TRES_PER_TASK=cpu=18 srun --cpus-per-task=18 --cpu-bind=cores /home/e/e1300530/tmp/structure_pool_remote_20261029/python312/bin/python /home/e/e1300530/MARSHAL/new/structure_pool_remote_remaining18_20261029/physical_exec.py /home/e/e1300530/MARSHAL/new/structure_pool_remote_remaining18_20261029/monitor.py "$oracle_resources/solve" /home/e/e1300530/tmp/structure_pool_remote_20261029/python312/bin/python -u -m new.structure_pool_20261026 run --jobs new/structure_pool_v1_20261026/raw_v1/parents.jsonl --output "$oracle_output" --indices 6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23 --workers 18 --memory-gb 16 --max-nodes 600000 --construct-seconds 180 --solve-seconds 120 --audit-seconds 180 --metric-seconds 300 --case-seconds 900 --max-sweeps 512 --joint-evaluations 400 --repair-passes 8 --backend inertia_then_joint
SLURM_CPUS_PER_TASK=18 SLURM_TRES_PER_TASK=cpu=18 srun --cpus-per-task=18 --cpu-bind=cores /home/e/e1300530/tmp/structure_pool_remote_20261029/python312/bin/python /home/e/e1300530/MARSHAL/new/structure_pool_remote_remaining18_20261029/physical_exec.py /home/e/e1300530/MARSHAL/new/structure_pool_remote_remaining18_20261029/monitor.py "$oracle_resources/reload" /home/e/e1300530/tmp/structure_pool_remote_20261029/python312/bin/python -u -m new.structure_pool_20261026 audit --run "$oracle_output" --output "$oracle_audit" --workers 18 --seconds 180 --case-seconds 900 --memory-gb 16
