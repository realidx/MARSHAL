#!/usr/bin/env bash
# Two independent TP=2 reasoning arms in one four-slice H100-47 allocation.
#SBATCH --job-name=social-sp-o-gate
#SBATCH --partition=gpu-long
#SBATCH --nodes=1
#SBATCH --gres=gpu:h100-47:4
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=96
#SBATCH --mem=0
#SBATCH --time=10:00:00
#SBATCH --signal=B:USR1@900
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?Submit from the clean social-training checkout}"
export SOCIAL_SOURCE_COMMIT="${SOCIAL_SOURCE_COMMIT:-$(git rev-parse HEAD)}"
[[ "$(git rev-parse HEAD)" == "$SOCIAL_SOURCE_COMMIT" ]]
git diff --quiet
git diff --cached --quiet

topology_log="runs/social_mixed/sp-o-gate-${SLURM_JOB_ID}-topology.log"
mkdir -p "$(dirname "$topology_log")"
topology=$(nvidia-smi -L)
mapfile -t parent_rows < <(
  printf '%s\n' "$topology" | awk '
    /^GPU [0-9]+:/ { parent=$0; next }
    /MIG .*UUID: MIG-/ {
      uuid=$0
      sub(/^.*UUID: /, "", uuid)
      sub(/\).*/, "", uuid)
      if (parent != "") print parent "\t" uuid
    }
  '
)

parent0=""
parent1=""
parent0_uuids=()
parent1_uuids=()
for row in "${parent_rows[@]}"; do
  parent="${row%%$'\t'*}"
  uuid="${row##*$'\t'}"
  if [[ -z "$parent0" || "$parent" == "$parent0" ]]; then
    parent0="$parent"
    parent0_uuids+=("$uuid")
  elif [[ -z "$parent1" || "$parent" == "$parent1" ]]; then
    parent1="$parent"
    parent1_uuids+=("$uuid")
  else
    echo "Unexpected third physical parent in four-slice allocation: $parent" >&2
    exit 43
  fi
done
if [[ -z "$parent0" || -z "$parent1" || "$parent0" == "$parent1" ||
      ${#parent0_uuids[@]} -ne 2 || ${#parent1_uuids[@]} -ne 2 ]]; then
  echo 'Expected exactly two allocated MIG slices on each of two physical parents' >&2
  printf 'PARENT_ROW=%s\n' "${parent_rows[@]}" >&2
  exit 43
fi

o_devices="${parent0_uuids[0]},${parent1_uuids[0]}"
sp_devices="${parent0_uuids[1]},${parent1_uuids[1]}"
{
  echo "SLURM_JOB_ID=$SLURM_JOB_ID"
  echo "SLURM_NODELIST=${SLURM_NODELIST:-}"
  echo "SOURCE_COMMIT=$SOCIAL_SOURCE_COMMIT"
  echo "O_PAIR=$o_devices"
  echo "SP_PAIR=$sp_devices"
  echo "PARENT0=$parent0"
  echo "PARENT1=$parent1"
  printf '%s\n' "$topology"
} > "$topology_log"

launch_arm() {
  local arm="$1" devices="$2"
  local ray_root="/tmp/social-${SLURM_JOB_ID}-${arm}"
  mkdir -p "$ray_root"
  setsid env -u SOCIAL_RESUME -u MASTER_PORT \
    SOCIAL_ARM="$arm" \
    SOCIAL_RECIPE=reasoning \
    SOCIAL_GPU_PROFILE=h100-47 \
    SOCIAL_KEEP_CHECKPOINTS=1 \
    SOCIAL_PAUSE_AFTER_UPDATES=8 \
    SOCIAL_TOTAL_TOKENS=6553600 \
    SOCIAL_TOKENS_PER_UPDATE=65536 \
    SOCIAL_RAY_ROOT="$ray_root" \
    CUDA_VISIBLE_DEVICES="$devices" \
    ROLL_ASSIGNED_CUDA_DEVICES="$devices" \
    SLURM_CPUS_PER_TASK=48 \
    bash examples/social_mixed/sbatch_train.sh &
  LAUNCHED_PID=$!
}

launch_arm outcome "$o_devices"
o_pid=$LAUNCHED_PID
sp_pid=""

forward_signal() {
  local pgid
  for pgid in "$o_pid" "$sp_pid"; do
    if [[ -n "$pgid" ]]; then kill -USR1 -- "-$pgid" 2>/dev/null || true; fi
  done
}
trap forward_signal USR1 TERM

# Both jobs previously hung while creating NCCL model-update groups together.
# Complete O's initial sync before starting SP; training then runs concurrently.
o_phases="runs/social_mixed/outcome-seed42-${SLURM_JOB_ID}/phases.jsonl"
startup_deadline=$((SECONDS + 900))
while ! grep -q '"phase": "initial_weight_sync", "event": "end"' "$o_phases" 2>/dev/null; do
  if ! kill -0 "$o_pid" 2>/dev/null; then
    echo 'O exited before initial weight sync; refusing to launch SP' >&2
    wait "$o_pid" || true
    exit 45
  fi
  if (( SECONDS >= startup_deadline )); then
    echo 'O startup exceeded 15 minutes at collective/initial sync' >&2
    forward_signal
    exit 46
  fi
  sleep 5
done
launch_arm selfplay "$sp_devices"
sp_pid=$LAUNCHED_PID

wait_for_child() {
  local pid="$1" result_name="$2" status
  while true; do
    set +e
    wait "$pid"
    status=$?
    set -e
    if (( status > 128 )) && kill -0 "$pid" 2>/dev/null; then
      continue
    fi
    printf -v "$result_name" '%s' "$status"
    return 0
  done
}

wait_for_child "$o_pid" o_status
wait_for_child "$sp_pid" sp_status
printf 'O_EXIT_CODE=%s\nSP_EXIT_CODE=%s\n' "$o_status" "$sp_status" | tee -a "$topology_log"
(( o_status == 0 && sp_status == 0 ))
