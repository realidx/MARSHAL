#!/usr/bin/env bash
#SBATCH --job-name=oracle-repair26-v3
#SBATCH --partition=long
#SBATCH --constraint=xcnh
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=26
#SBATCH --hint=nomultithread
#SBATCH --mem=64G
#SBATCH --time=24:00:00
#SBATCH --output=/home/e/e1300530/tmp/oracle_cpu_20261021/repair26-v3-%j.out
set -euo pipefail
cd /home/e/e1300530/tmp/oracle_cpu_20261021/game_oracle_repair_v3
source /home/e/e1300530/tmp/oracle_cpu_20261021/game_oracle_remote_v1/.venv/bin/activate
export PYTHONPATH="$PWD:$PWD/third_party/negotiation_benchmark/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1
mkdir -p remote_runs/repair_resources
lscpu > remote_runs/repair_resources/lscpu.txt
scontrol show job "$SLURM_JOB_ID" > remote_runs/repair_resources/slurm_job.txt
srun --cpu-bind=cores python /home/e/e1300530/MARSHAL/new/remote_solver_slurm_20261021/physical_exec.py /home/e/e1300530/MARSHAL/new/remote_solver_slurm_20261021/monitor.py remote_runs/repair_resources python -u -m new.strategic_game_v1_20261021.remote_solver run --output remote_runs/repair --profile extended --workers 26 --indices 1 6 8 9 20 24 25 28 29 31 34 46 47 50 51 53 58 59 62 63 69 73 74 75 90 95
python -m new.strategic_game_v1_20261021.remote_solver audit --output remote_runs/repair --hash-only
