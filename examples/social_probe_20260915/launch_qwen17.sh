#!/usr/bin/env bash
set -euo pipefail
entry_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
probe_python="${PROBE_PYTHON:-/raid/chenjiahao/conda_envs/mas/bin/python}"
probe_model="${PROBE_MODEL:-/raid/chenjiahao/mas/models/Qwen3-1.7B}"
probe_job_dir="${1:?Supply a NEW absolute output directory}"
[[ "$probe_job_dir" = /* && ! -e "$probe_job_dir" ]] || { echo 'Output must be a new absolute directory'; exit 2; }
mkdir -p "$probe_job_dir"
exec > >(tee -a "$probe_job_dir/launcher.log") 2>&1
trap 'status=$?; echo "$status" > "$probe_job_dir/EXIT_CODE"' EXIT
export PYTHONDONTWRITEBYTECODE=1 TOKENIZERS_PARALLELISM=false
echo "PROBE_JOB_DIR=$probe_job_dir"
"$probe_python" "$entry_dir/run_remote.py" --check
"$probe_python" "$entry_dir/download_qwen17.py" "$probe_model"
bash "$entry_dir/run_remote.sh" --model "$probe_model" --output "$probe_job_dir/probe" \
  --execution graphs --workers-per-gpu 16 --gpu-memory 0.80 \
  --stages bp bridges l0 selfplay --sampling-seed 20260916 --capture-performance
