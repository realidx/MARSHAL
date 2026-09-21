#!/usr/bin/env bash
set -euo pipefail

cd "${SLURM_SUBMIT_DIR:?Submit from the clean social training checkout}"
: "${BP_RESUME:?Missing BP_RESUME checkpoint}"
[[ -f "$BP_RESUME/COMPLETE.json" ]] || { echo 'Incomplete B/P resume checkpoint' >&2; exit 44; }

topology_log="runs/social_mixed/bp-resume-h10047-${SLURM_JOB_ID}-topology.log"
mkdir -p "$(dirname "$topology_log")"
{
  echo "SLURM_JOB_ID=${SLURM_JOB_ID}"
  echo "SLURM_NODELIST=${SLURM_NODELIST:-}"
  echo "CUDA_VISIBLE_DEVICES(before)=${CUDA_VISIBLE_DEVICES:-}"
  nvidia-smi -L
} | tee "$topology_log"

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
device0=""
device1=""
for row in "${parent_rows[@]}"; do
  parent="${row%%$'\t'*}"
  uuid="${row##*$'\t'}"
  if [[ -z "$parent0" ]]; then
    parent0="$parent"
    device0="$uuid"
  elif [[ "$parent" != "$parent0" ]]; then
    parent1="$parent"
    device1="$uuid"
    break
  fi
done

if [[ -z "$device0" || -z "$device1" || "$parent0" == "$parent1" ]]; then
  echo 'ALLOCATED_H10047_CROSS_PARENT_SELECTION_FAILED' >&2
  printf 'PARENT_ROW=%s\n' "${parent_rows[@]}" >&2
  exit 43
fi

bp_devices="$device0,$device1"
{
  echo "BP_CUDA_VISIBLE_DEVICES=$bp_devices"
  echo "PARENT0=$parent0"
  echo "PARENT1=$parent1"
} | tee -a "$topology_log"

ray_root="/tmp/social-${SLURM_JOB_ID}-bp"
mkdir -p "$ray_root"
setsid env \
  SOCIAL_ARM=bp \
  SOCIAL_GPU_PROFILE=h100-47 \
  CUDA_VISIBLE_DEVICES="$bp_devices" \
  ROLL_ASSIGNED_CUDA_DEVICES="$bp_devices" \
  SOCIAL_RAY_ROOT="$ray_root" \
  SLURM_CPUS_PER_TASK=48 \
  SOCIAL_RESUME="$BP_RESUME" \
  MASTER_PORT= \
  bash /home/e/e1300530/tmp/sbatch_train_bp_keep1.sh &
bp_pid=$!

forward_signal() {
  kill -USR1 -- "-$bp_pid" 2>/dev/null || true
}
trap forward_signal USR1 TERM

while true; do
  set +e
  wait "$bp_pid"
  status=$?
  set -e
  if (( status > 128 )) && kill -0 "$bp_pid" 2>/dev/null; then
    continue
  fi
  break
done

printf 'BP_EXIT_CODE=%s\n' "$status" | tee -a "$topology_log"
exit "$status"
