#!/usr/bin/env bash
#SBATCH --job-name=oracle-experiment-v4
#SBATCH --partition=normal
#SBATCH --constraint=xcnh
#SBATCH --array=0-2
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --hint=nomultithread
#SBATCH --mem=8G
#SBATCH --time=03:00:00
#SBATCH --output=/home/e/e1300530/tmp/oracle_cpu_20261021/experiment-v4-%A_%a.out
set -euo pipefail
cd /home/e/e1300530/tmp/oracle_cpu_20261021/game_oracle_experiments_v4
source /home/e/e1300530/tmp/oracle_cpu_20261021/game_oracle_remote_v1/.venv/bin/activate
export PYTHONPATH="$PWD:$PWD/third_party/negotiation_benchmark/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 VECLIB_MAXIMUM_THREADS=1 NUMEXPR_NUM_THREADS=1
case "$SLURM_ARRAY_TASK_ID" in
  0) export ORACLE_EXPERIMENT_MODE=backward; oracle_index=34 ;;
  1) export ORACLE_EXPERIMENT_MODE=sparse; oracle_index=6 ;;
  2) export ORACLE_EXPERIMENT_MODE=staged; oracle_index=24 ;;
esac
oracle_output="remote_runs/${ORACLE_EXPERIMENT_MODE}-${oracle_index}"
mkdir -p "${oracle_output}_resources"
lscpu > "${oracle_output}_resources/lscpu.txt"
scontrol show job "$SLURM_JOB_ID" > "${oracle_output}_resources/slurm_job.txt"
srun --cpu-bind=cores python /home/e/e1300530/MARSHAL/new/remote_solver_slurm_20261021/physical_exec.py /home/e/e1300530/MARSHAL/new/remote_solver_slurm_20261021/monitor.py "${oracle_output}_resources" python -u -m new.strategic_game_v1_20261021.remote_solver run --output "$oracle_output" --profile extended --workers 1 --indices "$oracle_index"
python -m new.strategic_game_v1_20261021.remote_solver audit --output "$oracle_output" --hash-only
