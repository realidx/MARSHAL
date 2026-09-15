#!/usr/bin/env bash
# One process per existing vLLM service; sequential sampling inside each arm.
set -euo pipefail
if [[ $# -ne 1 && $# -ne 4 ]]; then
  echo "Usage: bash $0 OUTPUT_DIR [FREE_PORT BP_PORT BRANCH_PORT]" >&2
  exit 2
fi
out=$1
ports=("${2:-8000}" "${3:-8001}" "${4:-8002}")
if [[ ${ports[0]} == "${ports[1]}" || ${ports[0]} == "${ports[2]}" || ${ports[1]} == "${ports[2]}" ]]; then
  echo "Use three distinct vLLM service ports." >&2
  exit 2
fi
for port in "${ports[@]}"; do
  if [[ ! $port =~ ^[0-9]+$ ]] || (( 10#$port < 1 || 10#$port > 65535 )); then
    echo "Invalid service port: $port" >&2
    exit 2
  fi
done
task_python=${SOCIAL_PYTHON:-/raid/chenjiahao/conda_envs/mas/bin/python}
task_tokenizer=${SOCIAL_TOKENIZER:-/raid/chenjiahao/mas/models/Qwen3-4B-Instruct-2507}
arms=(free_outcome bp_outcome bp_branch)
options=(--model social-base --blocks 1 --seed 7 --pack "${SOCIAL_PACK:-smoke}")
if [[ ${SOCIAL_SCRIPTED:-0} == 1 ]]; then
  options+=(--scripted)
else
  options+=(--tokenizer "$task_tokenizer")
fi
# mkdir without -p on the final directory refuses to mix with an earlier run.
mkdir -p "$(dirname "$out")"
mkdir "$out"
pids=()
stop_children() {
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  exit 130
}
trap stop_children INT TERM
for i in 0 1 2; do
  arm=${arms[$i]}
  "$task_python" -u -m training.b_sft.social_three_arm \
    "${options[@]}" --arm "$arm" \
    --endpoint "http://127.0.0.1:${ports[$i]}/v1" \
    --output "$out/$arm" > "$out/$arm.log" 2>&1 &
  pids+=("$!")
  printf '%s\t%s\t%s\n' "$arm" "${ports[$i]}" "$!" >> "$out/processes.tsv"
  echo "Started $arm on port ${ports[$i]} (PID $!)"
done
failed=0
for i in 0 1 2; do
  if wait "${pids[$i]}"; then
    echo "Finished ${arms[$i]}: $out/${arms[$i]}/summary.json"
  else
    echo "Failed ${arms[$i]}: inspect $out/${arms[$i]}.log" >&2
    failed=1
  fi
done
exit "$failed"
