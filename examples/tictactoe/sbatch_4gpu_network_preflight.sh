#!/bin/bash
#SBATCH --job-name=marshal-4g-preflight
#SBATCH --partition=gpu-long
#SBATCH --nodes=4
#SBATCH --gres=gpu:a100-80:1
#SBATCH --constraint=xgph
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:10:00
#SBATCH --output=slurm-%x-%j.out

set -euo pipefail

REPO_DIR="${REPO_DIR:-${SLURM_SUBMIT_DIR}}"
CONDA_HOME="${CONDA_HOME:-/home/e/e1300530/miniconda3}"
TASK_CONDA_ENV_DIR="${TASK_CONDA_ENV_DIR:-${CONDA_HOME}/envs/marshal}"

cd "${REPO_DIR}"
export PATH="${TASK_CONDA_ENV_DIR}/bin:${PATH}"
export PYTHONPATH="${REPO_DIR}:${PYTHONPATH:-}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"

MASTER_NODE="$(scontrol show hostnames "${SLURM_JOB_NODELIST}" | sed -n '1p')"
PEER_NODE="$(scontrol show hostnames "${SLURM_JOB_NODELIST}" | sed -n '2p')"
MASTER_IP="$(getent ahostsv4 "${MASTER_NODE}.comp.nus.edu.sg" | awk '$1 !~ /^127[.]/ {print $1; exit}')"
PEER_IP="$(getent ahostsv4 "${PEER_NODE}.comp.nus.edu.sg" | awk '$1 !~ /^127[.]/ {print $1; exit}')"
MASTER_ADDR="${MASTER_IP}"
MASTER_PORT="$((30000 + SLURM_JOB_ID % 20000))"
test -n "${MASTER_IP}" && test -n "${PEER_IP}"
export MASTER_NODE PEER_NODE MASTER_ADDR MASTER_IP PEER_IP MASTER_PORT

echo "=== Routes and interfaces ==="
srun --cpu-bind=none --ntasks="${SLURM_NNODES}" --ntasks-per-node=1 \
  bash -c '
    set -euo pipefail
    route_target="${MASTER_IP}"
    [[ "$(hostname -s)" == "${MASTER_NODE}" ]] && route_target="${PEER_IP}"
    iface="$(ip route get "${route_target}" | awk '"'"'{for (i=1; i<=NF; i++) if ($i == "dev") {print $(i+1); exit}}'"'"')"
    test -n "${iface}"
    printf "rank=%s host=%s master=%s(%s) iface=%s addresses=%s\n" \
      "${SLURM_PROCID}" "$(hostname)" "${MASTER_ADDR}" "${MASTER_IP}" "${iface}" \
      "$(ip -o -4 addr show dev "${iface}" | tr "\n" ";")"
  '

echo "=== Ray cluster ==="
export RAY_TMPDIR="/dev/shm/marshal-ray-preflight-${SLURM_JOB_ID}"
srun --cpu-bind=none --ntasks="${SLURM_NNODES}" --ntasks-per-node=1 ray stop --force || true
srun --cpu-bind=none --ntasks="${SLURM_NNODES}" --ntasks-per-node=1 \
  bash -c '
    if [[ "${SLURM_PROCID}" == "0" ]]; then
      ray start --head --port="${MASTER_PORT}" --node-name="${SLURMD_NODENAME}"
    else
      sleep 4
      ray start --address="${MASTER_ADDR}:${MASTER_PORT}" --node-name="${SLURMD_NODENAME}"
    fi
    sleep 15
    if [[ "${SLURM_PROCID}" == "0" ]]; then
      python -c '"'"'import ray; ray.init(address="auto"); r=ray.cluster_resources(); print("ray_resources", r); assert r.get("GPU", 0) == 4'"'"'
    fi
    sleep 5
  '
srun --cpu-bind=none --ntasks="${SLURM_NNODES}" --ntasks-per-node=1 ray stop --force || true

echo "=== Gloo and NCCL collectives ==="
srun --cpu-bind=none --ntasks="${SLURM_NNODES}" --ntasks-per-node=1 \
  bash -c '
    set -euo pipefail
    route_target="${MASTER_IP}"
    [[ "$(hostname -s)" == "${MASTER_NODE}" ]] && route_target="${PEER_IP}"
    iface="$(ip route get "${route_target}" | awk '"'"'{for (i=1; i<=NF; i++) if ($i == "dev") {print $(i+1); exit}}'"'"')"
    export GLOO_SOCKET_IFNAME="${iface}"
    export NCCL_SOCKET_IFNAME="${iface}"
    export RANK="${SLURM_PROCID}"
    export WORLD_SIZE="${SLURM_NTASKS}"
    python -c '"'"'
import os
import torch
import torch.distributed as dist

rank = int(os.environ["RANK"])
world = int(os.environ["WORLD_SIZE"])
for backend in ("gloo", "nccl"):
    dist.init_process_group(backend, rank=rank, world_size=world)
    device = torch.device("cuda", 0) if backend == "nccl" else torch.device("cpu")
    value = torch.tensor([rank + 1.0], device=device)
    dist.all_reduce(value)
    expected = world * (world + 1) / 2
    assert value.item() == expected, (backend, rank, value.item(), expected)
    print(f"{backend} rank={rank}/{world} all_reduce={value.item()} PASS", flush=True)
    dist.destroy_process_group()
'"'"'
  '

echo "PREFLIGHT PASS"
