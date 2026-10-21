#!/usr/bin/env bash
#SBATCH --job-name=oracle-extended35-cpu
#SBATCH --partition=long
#SBATCH --constraint=xcnh
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=35
#SBATCH --hint=nomultithread
#SBATCH --mem=64G
#SBATCH --time=24:00:00
#SBATCH --output=/home/e/e1300530/tmp/oracle_cpu_20261021/extended35-%j.out
set -euo pipefail
cd /home/e/e1300530/tmp/oracle_cpu_20261021/game_oracle_remote_v1
source .venv/bin/activate
export PYTHONPATH="$PWD:$PWD/third_party/negotiation_benchmark/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1
mkdir -p remote_runs/extended_resources
lscpu > remote_runs/extended_resources/lscpu.txt
scontrol show job "$SLURM_JOB_ID" > remote_runs/extended_resources/slurm_job.txt
srun --cpu-bind=cores python /home/e/e1300530/MARSHAL/new/remote_solver_slurm_20261021/physical_exec.py /home/e/e1300530/MARSHAL/new/remote_solver_slurm_20261021/monitor.py remote_runs/extended_resources python -u -m new.strategic_game_v1_20261021.remote_solver run --output remote_runs/extended --profile extended --from-run remote_runs/base --workers 35
python -m new.strategic_game_v1_20261021.remote_solver audit --output remote_runs/extended --hash-only
