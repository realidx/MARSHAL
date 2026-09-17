#!/usr/bin/env bash
set -euo pipefail
cd /raid/chenjiahao/mas
case "${1:-}" in
  marshal) model=MARSHAL-Generalist-Qwen3-4B; ports=(18115 18116) ;;
  socialr1) model=SocialR1-4B; ports=(18125 18126) ;;
  *) echo 'Usage: bash run_calbench_external_4096.sh marshal|socialr1' >&2; exit 2 ;;
esac
export CUDA_VISIBLE_DEVICES=6,7
export CUDA_HOME=/home/chenjiahao/cuda-11.8
export PATH="$CUDA_HOME/bin:$PATH"
export LD_LIBRARY_PATH="$CUDA_HOME/lib64:${LD_LIBRARY_PATH:-}"
export TRITON_PTXAS_PATH="$CUDA_HOME/bin/ptxas"
run_dir="runs/calbench-${1}-4096-$(date +%Y%m%d-%H%M%S)"
mkdir -p runs
printf '%s\n' "$run_dir" > "runs/calbench-${1}-4096.latest"
exec /raid/chenjiahao/conda_envs/mas/bin/python -u \
  -m examples.final_evaluation.launch_calbench_local \
  --suite formal --max-tokens 4096 \
  --model "/raid/chenjiahao/mas/models/$model" \
  --ports "${ports[@]}" --parallel-games 2 --output "$run_dir"
