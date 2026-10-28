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
source /home/e/e1300530/tmp/oracle_cpu_20261021/game_oracle_remote_v1/.venv/bin/activate
export PYTHONPATH="$PWD:$PWD/third_party/negotiation_benchmark/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1
oracle_output=new/structure_pool_v1_20261026/remote_remaining18_20261029
oracle_audit=new/structure_pool_v1_20261026/remote_reload18_20261029
oracle_resources=/home/e/e1300530/tmp/structure_pool_remote_20261029/resources
mkdir -p "$oracle_resources"
lscpu > "$oracle_resources/lscpu.txt"
scontrol show job "$SLURM_JOB_ID" > "$oracle_resources/slurm_job.txt"
python -m new.structure_pool_20261026 doctor > "$oracle_resources/doctor.json"
srun --cpu-bind=cores python /home/e/e1300530/MARSHAL/new/structure_pool_remote_remaining18_20261029/physical_exec.py /home/e/e1300530/MARSHAL/new/structure_pool_remote_remaining18_20261029/monitor.py "$oracle_resources/solve" python -u -m new.structure_pool_20261026 run --jobs new/structure_pool_v1_20261026/raw_v1/parents.jsonl --output "$oracle_output" --indices 6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23 --workers 18 --memory-gb 16 --max-nodes 600000 --construct-seconds 180 --solve-seconds 120 --audit-seconds 180 --metric-seconds 300 --case-seconds 900 --max-sweeps 512 --joint-evaluations 400 --repair-passes 8 --backend inertia_then_joint
srun --cpu-bind=cores python /home/e/e1300530/MARSHAL/new/structure_pool_remote_remaining18_20261029/physical_exec.py /home/e/e1300530/MARSHAL/new/structure_pool_remote_remaining18_20261029/monitor.py "$oracle_resources/reload" python -u -m new.structure_pool_20261026 audit --run "$oracle_output" --output "$oracle_audit" --workers 18 --seconds 180 --case-seconds 900 --memory-gb 16
