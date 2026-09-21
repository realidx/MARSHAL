#!/usr/bin/env bash
set -euo pipefail

cd "${SLURM_SUBMIT_DIR:?Submit from the clean social training checkout}"

topology_log="runs/social_mixed/dual-h10047-${SLURM_JOB_ID}-topology.log"
mkdir -p "$(dirname "$topology_log")"
{
  echo "SLURM_JOB_ID=${SLURM_JOB_ID}"
  echo "SLURM_NODELIST=${SLURM_NODELIST:-}"
  echo "CUDA_VISIBLE_DEVICES(before)=${CUDA_VISIBLE_DEVICES:-}"
  nvidia-smi -L
} | tee "$topology_log"

# H100-47 nodes expose two 47-GiB MIG slices from each physical H100.  Split
# the four allocated slices into two disjoint TP=2 pairs, each spanning both
# physical parents.
mapfile -t parent_rows < <(
  nvidia-smi -L | awk '
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
      ${#parent0_uuids[@]} -lt 2 || ${#parent1_uuids[@]} -lt 2 ]]; then
  echo "ALLOCATED_H10047_DUAL_PARENT_SELECTION_FAILED" >&2
  printf 'PARENT_ROW=%s\n' "${parent_rows[@]}" >&2
  exit 43
fi

mixed_devices="${parent0_uuids[0]},${parent1_uuids[0]}"
selfplay_devices="${parent0_uuids[1]},${parent1_uuids[1]}"
{
  echo "MIXED_CUDA_VISIBLE_DEVICES=$mixed_devices"
  echo "SELFPLAY_CUDA_VISIBLE_DEVICES=$selfplay_devices"
  echo "PARENT0=$parent0"
  echo "PARENT1=$parent1"
} | tee -a "$topology_log"

run_arm() {
  local arm="$1"
  local devices="$2"
  local resume="$3"
  (
    export SOCIAL_ARM="$arm"
    export SOCIAL_GPU_PROFILE=h100-47
    export CUDA_VISIBLE_DEVICES="$devices"
    export ROLL_ASSIGNED_CUDA_DEVICES="$devices"
    export SOCIAL_RAY_ROOT="/tmp/social-${SLURM_JOB_ID}-${arm}"
    export SLURM_CPUS_PER_TASK=48
    if [[ -n "$resume" ]]; then
      export SOCIAL_RESUME="$resume"
    else
      unset SOCIAL_RESUME
    fi
    unset MASTER_PORT
    mkdir -p "$SOCIAL_RAY_ROOT"
    bash examples/social_mixed/sbatch_train.sh
  )
}

run_arm mixed "$mixed_devices" "${MIXED_RESUME:-}" &
mixed_pid=$!
run_arm selfplay "$selfplay_devices" "${SELFPLAY_RESUME:-}" &
selfplay_pid=$!

forward_signal() {
  kill -USR1 "$mixed_pid" "$selfplay_pid" 2>/dev/null || true
}
trap forward_signal USR1 TERM

wait_for_child() {
  local pid="$1"
  local result_name="$2"
  local status
  while true; do
    set +e
    wait "$pid"
    status=$?
    set -e
    # A signal delivered to this wrapper interrupts bash wait with 128+signal
    # while the child is still completing its update and checkpoint.
    if (( status > 128 )) && kill -0 "$pid" 2>/dev/null; then
      continue
    fi
    printf -v "$result_name" "%s" "$status"
    return 0
  done
}

wait_for_child "$mixed_pid" mixed_status
wait_for_child "$selfplay_pid" selfplay_status

printf 'MIXED_EXIT_CODE=%s\nSELFPLAY_EXIT_CODE=%s\n' \
  "$mixed_status" "$selfplay_status" | tee -a "$topology_log"
(( mixed_status == 0 && selfplay_status == 0 ))
