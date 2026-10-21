#!/usr/bin/env bash
#SBATCH --job-name=oracle-cpu-probe
#SBATCH --partition=normal
#SBATCH --constraint=xcnh
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --hint=nomultithread
#SBATCH --mem=64G
#SBATCH --time=00:30:00
#SBATCH --output=/home/e/e1300530/tmp/oracle_cpu_20261021/probe-%j.out
set -euo pipefail
cd /home/e/e1300530/tmp/oracle_cpu_20261021/game_oracle_remote_v1
source .venv/bin/activate
export PYTHONPATH="$PWD:$PWD/third_party/negotiation_benchmark/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1
mkdir -p remote_runs/probe_resources
lscpu > remote_runs/probe_resources/lscpu.txt
scontrol show job "$SLURM_JOB_ID" > remote_runs/probe_resources/slurm_job.txt
srun --cpu-bind=cores python /home/e/e1300530/MARSHAL/new/remote_solver_slurm_20261021/monitor.py remote_runs/probe_resources python -u -m new.strategic_game_v1_20261021.remote_solver run --output remote_runs/probe --profile base --workers 8 --indices 2 15 79 62 17 5 4 95
python -m new.strategic_game_v1_20261021.remote_solver audit --output remote_runs/probe --hash-only
