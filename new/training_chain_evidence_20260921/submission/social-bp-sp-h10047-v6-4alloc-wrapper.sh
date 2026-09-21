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

bp_devices="${parent0_uuids[0]},${parent1_uuids[0]}"
selfplay_devices="${parent0_uuids[1]},${parent1_uuids[1]}"
{
  echo "BP_CUDA_VISIBLE_DEVICES=$bp_devices"
  echo "SELFPLAY_CUDA_VISIBLE_DEVICES=$selfplay_devices"
  echo "PARENT0=$parent0"
  echo "PARENT1=$parent1"
} | tee -a "$topology_log"

launch_arm() {
  local arm="$1"
  local devices="$2"
  local resume="$3"
  local ray_root="/tmp/social-${SLURM_JOB_ID}-${arm}"
  mkdir -p "$ray_root"
  # The returned PID is also the session/process-group ID. Broadcasting the
  # warning signal reaches sbatch_train.sh and its Python driver rather than
  # killing an intermediate background subshell.
  setsid env \
    SOCIAL_ARM="$arm" \
    SOCIAL_GPU_PROFILE=h100-47 \
    CUDA_VISIBLE_DEVICES="$devices" \
    ROLL_ASSIGNED_CUDA_DEVICES="$devices" \
    SOCIAL_RAY_ROOT="$ray_root" \
    SLURM_CPUS_PER_TASK=48 \
    SOCIAL_RESUME="$resume" \
    MASTER_PORT= \
    bash examples/social_mixed/sbatch_train.sh &
  LAUNCHED_PID=$!
}

: "${BP_RESUME:?Missing BP_RESUME checkpoint}"
: "${SELFPLAY_RESUME:?Missing SELFPLAY_RESUME checkpoint}"
[[ -f "$BP_RESUME/COMPLETE.json" ]] || { echo 'Incomplete B/P resume checkpoint' >&2; exit 44; }
[[ -f "$SELFPLAY_RESUME/COMPLETE.json" ]] || { echo 'Incomplete SP resume checkpoint' >&2; exit 44; }

launch_arm bp "$bp_devices" "$BP_RESUME"
bp_pid=$LAUNCHED_PID
launch_arm selfplay "$selfplay_devices" "$SELFPLAY_RESUME"
selfplay_pid=$LAUNCHED_PID

forward_signal() {
  local pgid
  for pgid in "$bp_pid" "$selfplay_pid"; do
    kill -USR1 -- "-$pgid" 2>/dev/null || true
  done
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

wait_for_child "$bp_pid" bp_status
wait_for_child "$selfplay_pid" selfplay_status

printf 'BP_EXIT_CODE=%s\nSELFPLAY_EXIT_CODE=%s\n' \
  "$bp_status" "$selfplay_status" | tee -a "$topology_log"
(( bp_status == 0 && selfplay_status == 0 ))
