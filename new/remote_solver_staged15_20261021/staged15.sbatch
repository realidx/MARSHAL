#!/usr/bin/env bash
#SBATCH --job-name=oracle-staged15-v4
#SBATCH --partition=long
#SBATCH --constraint=xcnh
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=15
#SBATCH --hint=nomultithread
#SBATCH --mem=32G
#SBATCH --time=24:00:00
#SBATCH --output=/home/e/e1300530/tmp/oracle_cpu_20261021/staged15-v4-%j.out
set -euo pipefail
cd /home/e/e1300530/tmp/oracle_cpu_20261021/game_oracle_experiments_v4
source /home/e/e1300530/tmp/oracle_cpu_20261021/game_oracle_remote_v1/.venv/bin/activate
export PYTHONPATH="$PWD:$PWD/third_party/negotiation_benchmark/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export ORACLE_EXPERIMENT_MODE=staged
oracle_output="remote_runs/staged-remaining15"
mkdir -p "${oracle_output}_resources"
lscpu > "${oracle_output}_resources/lscpu.txt"
scontrol show job "$SLURM_JOB_ID" > "${oracle_output}_resources/slurm_job.txt"
srun --cpu-bind=cores python /home/e/e1300530/MARSHAL/new/remote_solver_slurm_20261021/physical_exec.py /home/e/e1300530/MARSHAL/new/remote_solver_slurm_20261021/monitor.py "${oracle_output}_resources" python -u -m new.strategic_game_v1_20261021.remote_solver run --output "$oracle_output" --profile extended --workers 15 --indices 6 8 9 25 29 31 34 46 50 51 58 73 74 90 95
python -m new.strategic_game_v1_20261021.remote_solver audit --output "$oracle_output" --hash-only
